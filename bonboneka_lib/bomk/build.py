"""
bomk/build.py – Android build pipeline helpers.

Extracted from cli.py so that cli.py remains a thin argument-parsing
and dispatch layer only.

Public API
----------
run_build_pipeline(...)   – clone template, inject assets, build APK
cmd_create(...)           – handle `bomk create <folder>`
cmd_encased(...)          – handle `bomk create --encased <url>`
cmd_doctor(...)           – handle `bomk doctor <template>`
"""

import os
import re
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .lib    import (
    Logger, parse_groups, validate_groups, strip_shebang, SHEBANG_RE,
    parse_fluid_groups, validate_fluid_groups, detect_protocol,
)
from .inject import bundle_group, inject_assets
from .icon   import inject_icon
from .gitlink import commit_template, get_behaviour
from .config  import TEMPLATE_REPO, ASSETS_REL_PATH


# ── Public command handlers ───────────────────────────────────────────────────

def cmd_create(
    folder: str,
    output_dir: str,
    log: Logger,
    *,
    nobuild: bool = False,
    icon: str | None = None,
    appname: str | None = None,
    config: str | None = None,
) -> None:
    """Handle `bomk create <folder>`."""
    folder_path = Path(folder).resolve()
    if not folder_path.is_dir():
        log.error(f"Folder not found: {folder_path}")
        sys.exit(1)

    log.step(f"Scanning: {folder_path}")

    protocol = detect_protocol(str(folder_path))
    log.info(f"Protocol: {protocol}")

    # If --config is given, copy it into the folder so parse_fluid_groups
    # finds it at the expected location, or pass the path directly.
    if config:
        config_path = Path(config).resolve()
        if not config_path.exists():
            log.error(f"Config file not found: {config_path}")
            sys.exit(1)
        # Override protocol: an explicit --config always means Fluid
        protocol = "fluid"
        log.info(f"Using config: {config_path}")

    try:
        if protocol == "fluid":
            groups = parse_fluid_groups(str(folder_path), config_override=config)
            validate_fluid_groups(groups)
        else:
            groups = parse_groups(str(folder_path))
            validate_groups(groups)
    except ValueError as exc:
        log.error(str(exc))
        sys.exit(1)

    log.highlight(f"Found group(s): {sorted(groups.keys())}")

    bundled: dict[str, str] = {}
    for n in sorted(groups.keys()):
        log.step(f"Bundling group ${n} …")
        name, content = bundle_group(groups[n], n, log)
        bundled[name] = content
        log.info(f"  → {name}")

    # Resolve entry-point for informational logging
    html_file = next(f for f in groups[1] if f.suffix.lower() == ".html")
    entry_name = html_file.name if protocol == "fluid" else strip_shebang(html_file)
    log.highlight(f"Entry-point: {entry_name}")

    run_build_pipeline(
        bundled=bundled,
        output_dir=output_dir,
        log=log,
        nobuild=nobuild,
        icon=icon,
        appname=appname,
    )


def cmd_encased(
    url: str,
    output_dir: str,
    log: Logger,
    *,
    nobuild: bool = False,
    icon: str | None = None,
    appname: str | None = None,
) -> None:
    """Handle `bomk create --encased <url>`."""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        log.error(f"Invalid URL: {url!r}\n  Must start with http:// or https://")
        sys.exit(1)

    log.step(f"Encased mode → generating wrapper HTML for: {url}")

    # A minimal single-page app that loads the URL via JS (avoids iframe CSP issues)
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>App</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; overflow: hidden; }}
  </style>
</head>
<body>
  <script>
    // Use location.replace so the back-button exits the app instead of
    // looping back to this wrapper page.
    window.location.replace({url!r});
  </script>
</body>
</html>
"""

    with tempfile.TemporaryDirectory(prefix="bomk_encased_src_") as src_tmp:
        src_path = Path(src_tmp)
        html_file = src_path / "index_$1.html"
        html_file.write_text(html_content, encoding="utf-8")
        log.verbose(f"Generated wrapper HTML → {html_file.name}")

        try:
            groups = parse_groups(str(src_path))
            validate_groups(groups)
        except ValueError as exc:
            log.error(str(exc))
            sys.exit(1)

        bundled: dict[str, str] = {}
        for n in sorted(groups.keys()):
            log.info(f"Bundling group ${n} …")
            name, content = bundle_group(groups[n], n, log)
            bundled[name] = content
            log.info(f"  → {name}")

        run_build_pipeline(
            bundled=bundled,
            output_dir=output_dir,
            log=log,
            needs_internet=True,
            nobuild=nobuild,
            icon=icon,
            appname=appname,
        )


def cmd_doctor(template_path_str: str, log: Logger) -> None:
    """Handle `bomk doctor <template>`."""
    template_path = Path(template_path_str).resolve()

    if not template_path.is_dir():
        log.error(f"Template directory not found: {template_path}")
        sys.exit(1)

    log.step(f"Checking template: {template_path.name}")

    assets_dir = template_path / ASSETS_REL_PATH
    if not assets_dir.exists():
        log.error(f"Assets folder not found: {ASSETS_REL_PATH}")
        sys.exit(1)

    log.success(f"Assets folder found: {ASSETS_REL_PATH}")

    html_files = list(assets_dir.glob("*.html"))
    if not html_files:
        log.highlight("Assets folder is empty (no HTML files)")
        return

    log.success(f"Found {len(html_files)} HTML file(s)")

    protocol = detect_protocol(str(assets_dir))
    log.info(f"Protocol detected: {protocol}")

    if protocol == "fluid":
        _doctor_fluid(assets_dir, html_files, log)
    else:
        _doctor_shebang(html_files, log)


def _doctor_shebang(html_files: list[Path], log: Logger) -> None:
    files_with_shebang:    list[str] = []
    files_without_shebang: list[str] = []
    prime_shebang_found = False

    for html_file in html_files:
        m = SHEBANG_RE.match(html_file.name)
        if m:
            files_with_shebang.append(html_file.name)
            if int(m.group(2)) == 1:
                prime_shebang_found = True
                log.verbose(f"  {html_file.name} (prime shebang: _$1)")
            else:
                log.verbose(f"  {html_file.name}")
        else:
            files_without_shebang.append(html_file.name)
            log.verbose(f"  {html_file.name} (no shebang)")

    if files_without_shebang:
        log.error(f"{len(files_without_shebang)} file(s) missing shebang:")
        for fname in files_without_shebang:
            clean = fname.replace(".html", "")
            log.info(f"    {fname} → rename to {clean}_$<N>.html")
        sys.exit(1)

    log.success("All HTML files have shebangs")

    if not prime_shebang_found:
        log.error("No prime shebang detected: at least one HTML must have _$1 tag")
        sys.exit(1)

    log.success("Prime shebang (_$1) detected")
    log.highlight("Template is valid and ready to use!")


def _doctor_fluid(assets_dir: Path, html_files: list[Path], log: Logger) -> None:
    from .lib import FLUID_CONFIG_FILE, FLUID_MARKER_RE

    config_path = assets_dir / FLUID_CONFIG_FILE
    if not config_path.exists():
        log.error(
            f".bombundlefig not found in assets folder.\n"
            f"  Create one to declare your Fluid groups."
        )
        sys.exit(1)
    log.success(".bombundlefig found")

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error(f".bombundlefig is not valid JSON: {exc}")
        sys.exit(1)

    prime_found = False
    for key, filenames in raw.items():
        n = int(key)
        html_in_group = [f for f in filenames if f.endswith(".html")]
        for fname in html_in_group:
            fpath = assets_dir / fname
            if not fpath.exists():
                log.error(f"Group {n}: file not found: {fname}")
                sys.exit(1)
            src     = fpath.read_text(encoding="utf-8")
            markers = FLUID_MARKER_RE.findall(src)
            if any(int(m) == n for m in markers):
                log.verbose(f"  {fname} — id{n} marker found ✔")
                if n == 1:
                    prime_found = True
            else:
                log.error(
                    f"Group {n}: {fname} is missing "
                    f'<div class="id{n}"></div>'
                )
                sys.exit(1)

    if not prime_found:
        log.error('No prime group (id1) marker detected in any HTML file.')
        sys.exit(1)

    log.success('Prime marker (<div class="id1">) detected')
    log.highlight("Template is valid and ready to use!")


# ── Shared build pipeline ─────────────────────────────────────────────────────

def run_build_pipeline(
    bundled: dict[str, str],
    output_dir: str,
    log: Logger,
    *,
    needs_internet: bool = False,
    nobuild: bool = False,
    icon: str | None = None,
    appname: str | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="bomk_build_") as tmp:
        template_path = Path(tmp) / "template"

        _clone(template_path, log)
        _write_local_properties(template_path, log)
        _patch_gradle_properties(template_path, log)
        _patch_manifest(template_path, log, needs_internet=needs_internet)

        if appname:
            _patch_app_name(template_path, appname, log)

        if icon:
            try:
                inject_icon(template_path, icon, log)
            except (FileNotFoundError, ValueError) as exc:
                log.error(str(exc))
                sys.exit(1)

        if bundled:
            assets_dir = template_path / ASSETS_REL_PATH
            try:
                inject_assets(assets_dir, bundled, log)
            except FileNotFoundError as exc:
                log.error(str(exc))
                sys.exit(1)

        # Auto-commit if the template requests it
        behaviour = get_behaviour(template_path)
        if behaviour == "commit-per-build":
            log.step("Auto-committing template changes (commit-per-build)")
            try:
                commit_template(template_path, log)
            except ValueError as exc:
                log.error(str(exc))

        if nobuild:
            out  = Path(output_dir).resolve()
            out.mkdir(parents=True, exist_ok=True)
            dest = out / "template_output"
            shutil.copytree(str(template_path), str(dest), dirs_exist_ok=True)
            log.success(f"Done!  Template → {dest}")
            log.info(f"Assets injected into: {dest / ASSETS_REL_PATH}")
            return

        apk = _build(template_path, verbose=(log.level == Logger.VERBOSE), log=log)

        if apk and apk.exists():
            out  = Path(output_dir).resolve()
            out.mkdir(parents=True, exist_ok=True)
            dest = out / apk.name
            shutil.copy2(str(apk), str(dest))
            log.success(f"Done!  APK → {dest}")
            log.info(f"Output folder: {out}")
        else:
            log.error(
                "Build finished but APK was not found at the expected path.\n"
                f"  Check: {template_path / 'app' / 'build' / 'outputs' / 'apk' / 'debug'}"
            )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _patch_app_name(template_path: Path, appname: str, log: Logger) -> None:
    """Overwrite the app_name string resource in res/values/strings.xml."""
    # Escape XML special characters in the name
    safe = (appname
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "\\'"))          # Android requires escaped apostrophes

    candidates = list(template_path.rglob("res/values/strings.xml"))
    if not candidates:
        log.error("strings.xml not found — app name could not be set.")
        return

    strings_xml = candidates[0]
    content = strings_xml.read_text(encoding="utf-8")

    # Replace existing app_name value
    new_content, n = re.subn(
        r'(<string\s+name=["\']app_name["\']>)[^<]*(</string>)',
        rf'\g<1>{safe}\2',
        content,
    )
    if n == 0:
        # No existing app_name entry — inject one before </resources>
        new_content = content.replace(
            "</resources>",
            f'    <string name="app_name">{safe}</string>\n</resources>',
            1,
        )

    strings_xml.write_text(new_content, encoding="utf-8")
    log.verbose(f"strings.xml: app_name set to {appname!r}")
    log.success(f"App name set to: {appname!r}")


def _clone(dest: Path, log: Logger) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    log.step(f"Cloning template → {dest.name} …")
    r = subprocess.run(
        ["git", "clone", "--depth", "1", TEMPLATE_REPO, str(dest)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log.error(f"git clone failed:\n{r.stderr.strip()}")
        sys.exit(1)
    log.verbose(f"Cloned to {dest}")
    r2 = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(dest), capture_output=True, text=True,
    )
    commit = r2.stdout.strip() if r2.returncode == 0 else "unknown"
    log.info(f"Template commit: {commit}")


def _write_local_properties(template_path: Path, log: Logger) -> None:
    sdk_dir = (
        os.environ.get("ANDROID_HOME") or
        os.environ.get("ANDROID_SDK_ROOT") or
        os.path.expanduser("~/Android/Sdk")
    )
    if not sdk_dir or not Path(sdk_dir).exists():
        log.error(
            "Android SDK not found.\n"
            "Set ANDROID_HOME to your SDK path, e.g.:\n"
            "  export ANDROID_HOME=~/Android/Sdk"
        )
        sys.exit(1)
    sdk_path = str(sdk_dir).replace("\\", "/")
    (template_path / "local.properties").write_text(
        f"sdk.dir={sdk_path}\n", encoding="utf-8"
    )
    log.verbose(f"local.properties: sdk.dir={sdk_path}")


def _patch_gradle_properties(template_path: Path, log: Logger) -> None:
    props_path = template_path / "gradle.properties"
    content = props_path.read_text(encoding="utf-8") if props_path.exists() else ""
    required = {
        "android.useAndroidX":                   "true",
        "android.enableJetifier":                "true",
        "android.suppressUnsupportedCompileSdk": "34",
    }
    for key, val in required.items():
        if key not in content:
            content += f"\n{key}={val}"
            log.verbose(f"gradle.properties: added {key}={val}")
    props_path.write_text(content, encoding="utf-8")


def _patch_manifest(template_path: Path, log: Logger, *, needs_internet: bool = False) -> None:
    manifests = list(template_path.rglob("AndroidManifest.xml"))
    if not manifests:
        return
    manifest = manifests[0]
    content  = manifest.read_text(encoding="utf-8")

    def _add_exported(m: re.Match) -> str:
        tag = m.group(0)
        if "android:exported" in tag:
            return tag
        if tag.endswith("/>"):
            return tag[:-2].rstrip() + ' android:exported="true"/>'
        return tag.rstrip(">").rstrip() + '\n        android:exported="true">'

    content = re.sub(r"<activity\b[^>]*>", _add_exported, content, flags=re.DOTALL)

    if needs_internet and "INTERNET" not in content:
        content = content.replace(
            "<application",
            '<uses-permission android:name="android.permission.INTERNET"/>\n    <application',
            1,
        )
        log.verbose("AndroidManifest.xml: INTERNET permission added")

    manifest.write_text(content, encoding="utf-8")
    log.verbose("AndroidManifest.xml patched")


def _build(template_path: Path, verbose: bool, log: Logger) -> Path | None:
    gradlew = template_path / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not gradlew.exists():
        log.error("gradlew not found – is the template a valid Android project?")
        sys.exit(1)
    if os.name != "nt":
        gradlew.chmod(gradlew.stat().st_mode | 0o111)

    subprocess.run(
        [str(gradlew), "--stop"],
        cwd=str(template_path), capture_output=True, text=True,
    )

    log.highlight("Building APK (this may take a while) …")
    cmd = [
        str(gradlew), "assembleDebug",
        "--no-daemon", "--warning-mode", "none", "--stacktrace",
    ]
    r = subprocess.run(cmd, cwd=str(template_path), capture_output=not verbose, text=True)

    if r.returncode != 0:
        output = (r.stderr or r.stdout or "").strip()
        m = re.search(r"\* What went wrong:\n(.+?)(?=\n\* |\Z)", output, re.DOTALL)
        detail = m.group(1).strip() if m else output[-3000:]
        log.error(f"Gradle build failed:\n{detail}")
        sys.exit(1)

    apk = template_path / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if apk.exists():
        log.success(f"APK ready: {apk}")
    else:
        log.info("Build finished (APK not at expected path; check build/outputs/)")
    return apk if apk.exists() else None
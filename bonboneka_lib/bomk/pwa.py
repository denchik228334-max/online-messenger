"""
bomk/pwa.py – Build an Android APK from a PWA URL using Capacitor.
Replaces bubblewrap to avoid Node.js version conflicts and hanging prompts.

Requirements (checked at runtime):
  • Node.js (v18+)
  • Android SDK (ANDROID_HOME / ANDROID_SDK_ROOT)
  • Java JDK (for Gradle build)
"""

import os
import re
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .lib import Logger


# ── Preflight checks ──────────────────────────────────────────────────────────

def _require_node(log: Logger) -> int:
    """Checks for Node.js and returns the major version number."""
    node = shutil.which("node")
    if not node:
        log.error("Node.js is missing. Install it from https://nodejs.org/")
        sys.exit(1)
    
    r = subprocess.run([node, "-v"], capture_output=True, text=True)
    match = re.match(r"v(\d+)", r.stdout.strip())
    major_version = int(match.group(1)) if match else 20
    log.verbose(f"Detected Node.js v{major_version}")
    return major_version


def _require_npx(log: Logger) -> str:
    npx = shutil.which("npx")
    if not npx:
        log.error("npx CLI not found. Please ensure npm is installed correctly.")
        sys.exit(1)
    return npx


def _require_sdk(log: Logger) -> str:
    sdk = (
        os.environ.get("ANDROID_HOME") or
        os.environ.get("ANDROID_SDK_ROOT") or
        os.path.expanduser("~/Android/Sdk")
    )
    if not sdk or not Path(sdk).exists():
        log.error(
            "Android SDK not found.\n"
            "Set ANDROID_HOME to your SDK path, e.g.:\n"
            "  export ANDROID_HOME=~/Android/Sdk"
        )
        sys.exit(1)
    return sdk


# ── URL helpers ───────────────────────────────────────────────────────────────

def _validate_url(url: str, log: Logger) -> None:
    if not re.match(r"^https?://", url, re.IGNORECASE):
        log.error(f"Invalid URL: {url!r}\n  URL must start with http:// or https://")
        sys.exit(1)


def _derive_package_name(url: str) -> str:

    m = re.match(r"https?://([^/]+)", url, re.IGNORECASE)
    if not m:
        return "com.example.app"
    host = re.sub(r"^(www\d?|m|app|apps)\.", "", m.group(1).lower())
    parts = host.split(".")
    parts.reverse()
    sanitised = [re.sub(r"[^a-z0-9_]", "_", p) for p in parts if p]
    return ".".join(sanitised) + ".app"


# ── Capacitor build ───────────────────────────────────────────────────────────

def _capacitor_build(
    work_dir: Path,
    url: str,
    package: str,
    appname: str,
    npx: str,
    node_ver: int,
    log: Logger,
    ultra_verbose: bool = False,
) -> Path | None:
    # 1. Choose Capacitor version based on Node version
    # Capacitor 7+ requires Node 22. Capacitor 6 supports Node 18/20.
    cap_tag = "@6" if node_ver < 22 else ""
    
    try:
        # 2. Init and Install
        log.verbose("Initializing npm package...")
        subprocess.run(["npm", "init", "-y"], cwd=work_dir, capture_output=not ultra_verbose, check=True)

        log.info(f"Installing Capacitor {cap_tag or '(latest)'}...")
        subprocess.run(
            ["npm", "install", f"@capacitor/cli{cap_tag}", f"@capacitor/core{cap_tag}", f"@capacitor/android{cap_tag}"],
            cwd=work_dir, capture_output=not ultra_verbose, check=True
        )

        # 3. Project Config
        log.verbose("Initializing Capacitor project...")
        subprocess.run(
            [npx, "cap", "init", appname, package, "--web-dir", "www"],
            cwd=work_dir, capture_output=not ultra_verbose, check=True
        )

        # Capacitor needs a 'www' folder to exist even for external URLs
        www_dir = work_dir / "www"
        www_dir.mkdir(exist_ok=True)
        (www_dir / "index.html").write_text(f"<html><body>Loading {appname}...</body></html>")

        # Set the server URL in config
        cap_cfg_path = work_dir / "capacitor.config.json"
        cap_cfg = json.loads(cap_cfg_path.read_text(encoding="utf-8"))
        cap_cfg["server"] = {"url": url, "cleartext": url.startswith("http://")}
        cap_cfg_path.write_text(json.dumps(cap_cfg, indent=2), encoding="utf-8")

        # 4. Add Android
        log.info("Adding Android platform...")
        subprocess.run([npx, "cap", "add", "android"], cwd=work_dir, capture_output=not ultra_verbose, check=True)

        # 5. Gradle Build
        log.highlight("Building APK via Gradle...")
        android_dir = work_dir / "android"
        gradlew = "./gradlew" if os.name != "nt" else "gradlew.bat"
        
        # Ensure gradlew is executable on Linux/macOS
        if os.name != "nt":
            subprocess.run(["chmod", "+x", gradlew], cwd=android_dir)

        subprocess.run([gradlew, "assembleDebug"], cwd=android_dir, capture_output=not ultra_verbose, check=True)

    except subprocess.CalledProcessError as e:
        log.error(f"\nBuild step failed. Error code: {e.returncode}")
        if not ultra_verbose:
            log.info("Re-run with --ultra-verbose to see full command output.")
        sys.exit(1)

    # Locate APK
    apk_path = android_dir / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if apk_path.exists():
        return apk_path

    # Fallback search
    for apk in sorted(android_dir.rglob("*.apk")):
        if "debug" in apk.name.lower():
            return apk
    return None


# ── Public entry-point ────────────────────────────────────────────────────────

def cmd_pwa(
    url: str,
    output_dir: str,
    log: Logger,
    *,
    appname: str | None = None,
    package: str | None = None,
    icon: str | None = None,
    nobuild: bool = False,
    ultra_verbose: bool = False,
) -> None:
    """Handle `bomk create --pwa <url>`."""
    _validate_url(url, log)

    pkg  = package or _derive_package_name(url)
    name = appname or "My App"

    log.highlight(f"PWA mode → building Android App for: {url}")
    log.info(f"Package: {pkg}  |  App name: {name!r}")

    node_ver = _require_node(log)
    npx      = _require_npx(log)
    _require_sdk(log)

    with tempfile.TemporaryDirectory(prefix="bomk_pwa_") as tmp:
        work_dir = Path(tmp) / "app"
        work_dir.mkdir()

        if nobuild:
            # Just set up the directory and exit
            log.info("Setting up Capacitor project (nobuild)...")
            # Reuse logic if needed, but for now we stop here
            out = Path(output_dir).resolve() / "capacitor_project"
            log.success(f"Project structure ready at: {out}")
            return

        apk = _capacitor_build(
            work_dir=work_dir,
            url=url,
            package=pkg,
            appname=name,
            npx=npx,
            node_ver=node_ver,
            log=log,
            ultra_verbose=ultra_verbose
        )

        if apk and apk.exists():
            out  = Path(output_dir).resolve()
            out.mkdir(parents=True, exist_ok=True)
            # Use name-based filename
            safe_name = re.sub(r"[^a-zA-Z0-9]", "_", name)
            dest = out / f"{safe_name}-debug.apk"
            shutil.copy2(str(apk), str(dest))
            log.success(f"Done!  APK → {dest}")
        else:
            log.error("Build completed but the APK file could not be located.")
"""
bomk/inject.py – bundle HTML/CSS/JS groups and inject them into the
                 template's assets directory.

The assets dir is expected to contain only a placeholder.txt file.
All previous contents are wiped and replaced with the bundled HTML files.

IMPORTANT: output filenames intentionally keep the _$N shebang tag so the
Android template can locate the entry-point via its endsWith("_$1.html")
scan.  Do NOT strip shebangs here.
"""

import re
from pathlib import Path

from .lib    import strip_shebang, b64_data_uri, Logger
from .minify import minify_html


# ── Bundler ───────────────────────────────────────────────────────────────────

def bundle_group(
    files: list[Path],
    group_num: int,
    logger: Logger | None = None,
) -> tuple[str, str]:
    """
    Inline all CSS/JS into the HTML and base64-encode any other assets.
    Returns (output_filename, html_string).

    The output filename KEEPS the _$N shebang tag — the Android template
    uses it to identify the entry-point file at runtime.
    """
    html_file   = next(f for f in files if f.suffix.lower() == ".html")
    css_files   = [f for f in files if f.suffix.lower() == ".css"]
    js_files    = [f for f in files if f.suffix.lower() == ".js"]
    asset_files = [
        f for f in files
        if f.suffix.lower() not in (".html", ".css", ".js")
    ]

    html = html_file.read_text(encoding="utf-8")

    # ── 1. Remove existing <link> tags for bundled CSS ────────────────────────
    for css in css_files:
        for name in (css.name, strip_shebang(css)):
            html = re.sub(
                rf'<link\b[^>]*href=["\']?{re.escape(name)}["\']?[^>]*>',
                "", html, flags=re.IGNORECASE,
            )

    # ── 2. Remove existing <script src="..."> tags for bundled JS ─────────────
    for js in js_files:
        for name in (js.name, strip_shebang(js)):
            html = re.sub(
                rf'<script\b[^>]*src=["\']?{re.escape(name)}["\']?[^>]*>\s*</script>',
                "", html, flags=re.IGNORECASE | re.DOTALL,
            )

    # ── 3. Inline CSS before </head> ─────────────────────────────────────────
    if css_files:
        css_block = ""
        for css in css_files:
            css_block += css.read_text(encoding="utf-8") + "\n"
            logger and logger.verbose(f"  Inlined CSS: {css.name}")
        tag = f"<style>{css_block}</style>"
        html = (
            html.replace("</head>", f"{tag}\n</head>", 1)
            if "</head>" in html else tag + "\n" + html
        )

    # ── 4. Inline JS before </body> ──────────────────────────────────────────
    if js_files:
        js_block = ""
        for js in js_files:
            js_block += js.read_text(encoding="utf-8") + "\n"
            logger and logger.verbose(f"  Inlined JS:  {js.name}")
        tag = f"<script>{js_block}</script>"
        html = (
            html.replace("</body>", f"{tag}\n</body>", 1)
            if "</body>" in html else html + "\n" + tag
        )

    # ── 5. Base64-encode other assets referenced in HTML ─────────────────────
    for asset in asset_files:
        uri = b64_data_uri(asset)
        if uri is None:
            logger and logger.verbose(f"  Skipped (unknown MIME): {asset.name}")
            continue
        for name in (asset.name, strip_shebang(asset)):
            html = re.sub(
                rf'(src|href)=(["\']?){re.escape(name)}\2',
                lambda m, u=uri: f'{m.group(1)}="{u}"',
                html,
            )
        logger and logger.verbose(f"  Embedded asset: {asset.name}")

    # ── 6. Minify the final HTML ──────────────────────────────────────────────
    original_len = len(html.encode("utf-8"))
    html = minify_html(html)
    minified_len = len(html.encode("utf-8"))
    saved = original_len - minified_len
    pct   = (saved / original_len * 100) if original_len else 0
    logger and logger.verbose(
        f"  Minified: {original_len:,} → {minified_len:,} bytes "
        f"(saved {saved:,} / {pct:.1f}%)"
    )

    # Keep the original filename including the _$N tag (template needs it)
    output_name = html_file.name
    logger and logger.verbose(
        f"  Group ${group_num}: {[f.name for f in files]} → {output_name}"
    )
    return output_name, html


# ── Injector ──────────────────────────────────────────────────────────────────

def inject_assets(
    assets_dir: Path,
    bundled: dict[str, str],
    logger: Logger | None = None,
) -> None:
    """
    Clear the assets directory (keeping .gitkeep if present) and write
    all bundled HTML files into it.
    """
    if not assets_dir.exists():
        raise FileNotFoundError(
            f"Assets directory not found: {assets_dir}\n"
            "Check ASSETS_REL_PATH in bomk/config.py"
        )

    for f in assets_dir.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()
            logger and logger.verbose(f"  Removed: {f.name}")

    for name, content in bundled.items():
        (assets_dir / name).write_text(content, encoding="utf-8")
        logger and logger.verbose(f"  Injected: {name}")

    logger and logger.success(f"Assets injected ({len(bundled)} file(s)) → {assets_dir}")
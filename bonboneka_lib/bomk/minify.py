"""
bomk/minify.py – Lightweight HTML/CSS/JS minifier.

No external dependencies — pure regex + stdlib only.
Not a full parser; safe for the bundled single-file output that inject.py
produces (no template literals that span multiple lines with /* */ inside,
no conditional comments, etc.).

Public API
----------
minify_html(src: str) -> str
"""

import re


# ── CSS minifier ──────────────────────────────────────────────────────────────

def _minify_css(css: str) -> str:
    # Remove /* ... */ comments
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
    # Collapse whitespace
    css = re.sub(r'\s+', ' ', css)
    # Remove spaces around structural characters
    css = re.sub(r'\s*([{}:;,>~+])\s*', r'\1', css)
    # Remove trailing semicolon before }
    css = re.sub(r';+}', '}', css)
    return css.strip()


# ── JS minifier ───────────────────────────────────────────────────────────────

def _minify_js(js: str) -> str:
    # Remove single-line comments (// ...) — skip URLs (http://)
    js = re.sub(r'(?<![:/])//[^\n]*', '', js)
    # Remove /* ... */ block comments
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.DOTALL)
    # Collapse runs of whitespace (but preserve single spaces between tokens)
    js = re.sub(r'[ \t]+', ' ', js)
    # Remove blank lines
    js = re.sub(r'\n\s*\n', '\n', js)
    # Remove spaces around operators / punctuation that don't need them
    js = re.sub(r' *([=+\-*/%&|^~<>!,;:{}()\[\]]) *', r'\1', js)
    # But restore mandatory space after keywords to avoid e.g. "returnx"
    js = re.sub(
        r'\b(return|typeof|instanceof|in|of|new|delete|void|throw|case|var|let|const|function|class|if|else|for|while|do|switch|try|catch|finally|import|export|from|async|await)([a-zA-Z_$0-9({\[\'"`])',
        r'\1 \2',
        js,
    )
    return js.strip()


# ── HTML minifier ─────────────────────────────────────────────────────────────

# Tags whose text content must not be altered
_RAW_TAGS = re.compile(
    r'(<(script|style)[^>]*>)(.*?)(</\2\s*>)',
    flags=re.IGNORECASE | re.DOTALL,
)

def _process_raw_block(m: re.Match) -> str:
    open_tag  = m.group(1)
    tag_name  = m.group(2).lower()
    body      = m.group(3)
    close_tag = m.group(4)

    if tag_name == "style":
        body = _minify_css(body)
    elif tag_name == "script":
        # Don't touch non-JS script blocks (e.g. type="application/json")
        if re.search(r'type=["\'](?!text/javascript|module)', open_tag, re.IGNORECASE) is None:
            body = _minify_js(body)

    return f"{open_tag}{body}{close_tag}"


def minify_html(src: str) -> str:
    """
    Return a minified copy of *src* (an HTML string).

    Steps:
      1. Strip HTML comments (<!-- ... -->) except IE conditionals
      2. Minify inline <style> blocks
      3. Minify inline <script> blocks
      4. Collapse inter-tag whitespace
    """
    # 1. Remove HTML comments, keep IE conditionals (<!--[if ...]>)
    src = re.sub(r'<!--(?!\[if).*?-->', '', src, flags=re.DOTALL)

    # 2 & 3. Minify raw blocks in-place
    src = _RAW_TAGS.sub(_process_raw_block, src)

    # 4. Collapse whitespace between tags
    src = re.sub(r'>\s+<', '><', src)

    # 5. Collapse remaining runs of whitespace to a single space
    src = re.sub(r'\s{2,}', ' ', src)

    return src.strip()
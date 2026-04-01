"""
bomk/lib.py - shared utility classes and helpers.
"""

import re
import sys
import json
import base64
import mimetypes
from pathlib import Path

# ── Shebang regex ─────────────────────────────────────────────────────────────
# Matches:  basename_$<N>.ext
_SHEBANG_PATTERN = r"^(.+)_\$(\d+)(\.[^.]+)$"
SHEBANG_RE = re.compile(_SHEBANG_PATTERN)

# ── Fluid constants ───────────────────────────────────────────────────────────
FLUID_CONFIG_FILE = ".bombundlefig"
_FLUID_MARKER_PATTERN = r"<div\b[^>]*\bclass=[\"']id(\d+)[\"'][^>]*>"
FLUID_MARKER_RE = re.compile(_FLUID_MARKER_PATTERN, re.IGNORECASE)


# ── Logger ────────────────────────────────────────────────────────────────────

class Logger:
    SILENT  = 0
    NORMAL  = 1
    VERBOSE = 2

    _GREEN   = "\033[92m"
    _RED     = "\033[91m"
    _CYAN    = "\033[96m"
    _YELLOW  = "\033[93m"
    _BLUE    = "\033[94m"
    _MAGENTA = "\033[95m"
    _WHITE   = "\033[97m"
    _DIM     = "\033[2m"
    _BOLD    = "\033[1m"
    _RESET   = "\033[0m"

    def __init__(self, level: int = NORMAL):
        self.level = level
        if not sys.stdout.isatty():
            for attr in ("_GREEN", "_RED", "_CYAN", "_YELLOW", "_BLUE",
                         "_MAGENTA", "_WHITE", "_DIM", "_BOLD", "_RESET"):
                setattr(self, attr, "")

    def info(self, msg: str) -> None:
        if self.level >= self.NORMAL:
            print(f"{self._CYAN}[bomk]{self._RESET} {msg}")

    def verbose(self, msg: str) -> None:
        if self.level >= self.VERBOSE:
            print(f"{self._DIM}[bomk:verbose]{self._RESET} {msg}")

    def success(self, msg: str) -> None:
        if self.level >= self.NORMAL:
            print(f"{self._GREEN}[bomk:ok]{self._RESET} {msg}")

    def error(self, msg: str) -> None:
        print(f"{self._RED}[bomk:error]{self._RESET} {msg}", file=sys.stderr)

    def step(self, msg: str) -> None:
        if self.level >= self.NORMAL:
            print(f"{self._BOLD}{self._BLUE}[bomk]{self._RESET} {self._BOLD}{msg}{self._RESET}")

    def highlight(self, msg: str) -> None:
        if self.level >= self.NORMAL:
            print(f"{self._BOLD}{self._YELLOW}[bomk]{self._RESET} {self._BOLD}{msg}{self._RESET}")

    def debug(self, msg: str) -> None:
        if self.level >= self.VERBOSE:
            print(f"{self._MAGENTA}[bomk:debug]{self._RESET} {msg}")


# ── Shebang helpers ───────────────────────────────────────────────────────────

def strip_shebang(path: Path) -> str:
    """Return the clean filename without the _$N tag."""
    m = SHEBANG_RE.match(path.name)
    return (m.group(1) + m.group(3)) if m else path.name


def parse_groups(folder: str) -> dict[int, list[Path]]:
    """
    Scan a folder and return {group_number: [Path, ...]} for every
    shebang-tagged file. Raises ValueError on duplicate shebangs for
    the same group+extension combination.
    """
    groups: dict[int, list[Path]] = {}
    seen:   dict[tuple[int, str], Path] = {}

    for f in Path(folder).iterdir():
        if not f.is_file():
            continue
        m = SHEBANG_RE.match(f.name)
        if not m:
            continue

        n   = int(m.group(2))
        ext = m.group(3).lower()
        key = (n, ext)

        if key in seen:
            raise ValueError(
                f"Duplicate shebang: both '{seen[key].name}' and '{f.name}' "
                f"are tagged _${n} with extension '{ext}'."
            )
        seen[key] = f
        groups.setdefault(n, []).append(f)

    return groups


def validate_groups(groups: dict[int, list[Path]]) -> None:
    """
    Raise ValueError if:
      - no groups were found
      - group $1 (the prime shebang) is missing
      - any group has no HTML file
      - any group has more than one HTML file
    """
    if not groups:
        raise ValueError(
            "No shebang-tagged files found.\n"
            "  Rename your files like:  index_$1.html  styles_$1.css  script_$1.js"
        )
    if 1 not in groups:
        raise ValueError(
            "No $1 group found. The entry-point must be tagged _$1 "
            "(e.g. index_$1.html)."
        )
    for n, files in groups.items():
        html = [f for f in files if f.suffix.lower() == ".html"]
        if not html:
            raise ValueError(f"Group ${n} has no HTML file.")
        if len(html) > 1:
            raise ValueError(
                f"Group ${n} has more than one HTML file: "
                + ", ".join(f.name for f in html)
            )


# ── Fluid protocol ────────────────────────────────────────────────────────────

def parse_fluid_groups(
    folder: str,
    config_override: str | None = None,
) -> dict[int, list[Path]]:
    """
    Parse a Fluid project's .bombundlefig and return
    {group_number: [Path, ...]} exactly like parse_groups() does for shebang.

    .bombundlefig format:
        {
          "1": ["index.html", "styles.css", "app.js"],
          "2": ["about.html", "about.css"]
        }

    config_override: optional path to a .bombundlefig outside the project
                     folder (passed via bomk create --config <path>).
    """
    folder_path = Path(folder)
    config_path = (
        Path(config_override).resolve()
        if config_override
        else folder_path / FLUID_CONFIG_FILE
    )

    if not config_path.exists():
        raise ValueError(
            f"Fluid config not found: {config_path}\n"
            "  Create a .bombundlefig file in your project folder."
        )

    try:
        raw: dict = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f".bombundlefig is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(".bombundlefig must be a JSON object at the top level.")

    groups: dict[int, list[Path]] = {}
    seen_files: dict[str, int] = {}

    for key, filenames in raw.items():
        try:
            n = int(key)
        except ValueError:
            raise ValueError(
                f".bombundlefig key {key!r} is not a valid group number (must be an integer)."
            )
        if n < 1:
            raise ValueError(
                f".bombundlefig group numbers must be >= 1, got {n}."
            )
        if not isinstance(filenames, list):
            raise ValueError(
                f".bombundlefig group {n}: value must be a list of filenames, "
                f"got {type(filenames).__name__}."
            )

        paths: list[Path] = []
        for fname in filenames:
            if not isinstance(fname, str):
                raise ValueError(
                    f".bombundlefig group {n}: filename must be a string, got {fname!r}."
                )
            if fname in seen_files:
                raise ValueError(
                    f".bombundlefig: {fname!r} is listed in both "
                    f"group {seen_files[fname]} and group {n}."
                )
            seen_files[fname] = n

            p = folder_path / fname
            if not p.exists():
                raise ValueError(
                    f".bombundlefig group {n}: file not found: {fname}"
                )
            paths.append(p)

        groups[n] = paths

    return groups


def validate_fluid_groups(groups: dict[int, list[Path]]) -> None:
    """
    Raise ValueError if:
      - no groups were found
      - group 1 is missing
      - any group has no HTML file
      - any group has more than one HTML file
      - the HTML in each group is missing its <div class="idN"> marker
    """
    if not groups:
        raise ValueError(
            "No groups found in .bombundlefig.\n"
            '  Add at least: {"1": ["index.html"]}'
        )
    if 1 not in groups:
        raise ValueError(
            'Group 1 is missing from .bombundlefig.\n'
            '  The entry-point group must be "1".'
        )
    for n, files in groups.items():
        html_files = [f for f in files if f.suffix.lower() == ".html"]
        if not html_files:
            raise ValueError(f".bombundlefig group {n} has no HTML file.")
        if len(html_files) > 1:
            raise ValueError(
                f".bombundlefig group {n} has more than one HTML file: "
                + ", ".join(f.name for f in html_files)
            )
        html_file = html_files[0]
        src       = html_file.read_text(encoding="utf-8")
        markers   = FLUID_MARKER_RE.findall(src)
        if not any(int(m) == n for m in markers):
            raise ValueError(
                f".bombundlefig group {n}: {html_file.name} is missing "
                f"<div class=\"id{n}\"></div>.\n"
                f"  Add it anywhere in the <body> so the template can "
                f"locate the entry-point at runtime."
            )


# ── Auto-detection ────────────────────────────────────────────────────────────

def detect_protocol(folder: str) -> str:
    """Return 'fluid' if .bombundlefig exists in folder, else 'shebang'."""
    return "fluid" if (Path(folder) / FLUID_CONFIG_FILE).exists() else "shebang"


# ── Asset encoding ────────────────────────────────────────────────────────────

def b64_data_uri(path: Path) -> str | None:
    """Return a base64 data URI for a file, or None if MIME type is unknown."""
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        return None
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"
"""
bomk/cli.py – Bonboneka command-line interface.

This module is intentionally thin: it only handles argument parsing and
dispatches to the real implementations in build.py, pwa.py, and gitlink.py.

Commands:
    bomk create <folder>              Build an Android app from local files
    bomk create --encased <url>       Wrap a remote URL inside an app (WebView)
    bomk create --pwa <url>           Build a TWA APK from a PWA URL (bubblewrap)
    bomk doctor <template>            Validate an Android template
    bomk gitlink <template>           Manage template git configuration
"""

import sys
import argparse

from .lib     import Logger
from .build   import cmd_create, cmd_encased, cmd_doctor
from .pwa     import cmd_pwa
from .gitlink import set_origin, set_behaviour, get_behaviour, commit_template, disengage_template, push_template

VERSION = '2.0 "Choco-Milk-Sugar Goodness"'


# ── Arg normalisation ─────────────────────────────────────────────────────────

def _normalize_argv(argv: list[str]) -> list[str]:
    """Translate Windows-style /flag syntax into POSIX --flag syntax."""
    aliases = {"/s": "--silent", "/verbose": "--verbose", "/pwa": "--pwa"}
    out = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in aliases:
            out.append(aliases[arg])
            # /encased and /pwa take a following argument
            if arg in ("/pwa") and i + 1 < len(argv):
                i += 1
                out.append(argv[i])
        else:
            out.append(arg)
        i += 1
    return out


# ── Argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bomk",
        description=f"Bonboneka Ver {VERSION} — Bundle HTML/CSS/JS into an Android WebView app",
    )
    sub = p.add_subparsers(dest="command")

    # ── create ────────────────────────────────────────────────────────────────
    create = sub.add_parser(
        "create",
        help="Build an Android app from local files, a URL, or a PWA",
        description="""
Build an Android app from local HTML/CSS/JS files, a remote URL, or a PWA.

EXAMPLES:
  bomk create ./my_app                              # Build from local folder (StatiX shebang protocol)
  bomk create ./my_app --config ./config.json  # With custom .bombundlefig (Fluid protocol)
  bomk create ./my_app --icon ./icon.png            # With custom icon
  bomk create ./my_app --nobuild                    # Debug: skip APK build
  bomk create --pwa https://example.com             # TWA from a PWA (Capacitor)
  bomk create --pwa https://example.com \\
      --appname "My App" --package com.example.app  # PWA with custom metadata
  bomk create ./app -o ./build --verbose            # With detailed output
        """.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    create.add_argument(
        "folder", nargs="?",
        help="Folder containing shebang-tagged source files (omit when using --encased or --pwa)",
    )
    create.add_argument(
        "--pwa", metavar="URL",
        help="Build a TWA APK from a PWA URL using bubblewrap (requires Node.js + bubblewrap CLI)",
    )
    create.add_argument(
        "--appname", metavar="NAME", default="My App",
        help="App display name (used with --pwa, default: 'My App')",
    )
    create.add_argument(
        "--package", metavar="ID",
        help="Android package ID e.g. com.example.app (used with --pwa, auto-derived if omitted)",
    )
    create.add_argument(
        "--config", metavar="PATH",
        help="Path to a .bombundlefig file (Fluid protocol). "
             "Defaults to <folder>/.bombundlefig if not specified.",
    )
    create.add_argument(
        "--name", metavar="NAME", default=None,
        help="Override the Android app name shown on the launcher (patches strings.xml)",
    )
    create.add_argument(
        "--silent", "-s", action="store_true",
        help="Suppress all output",
    )
    create.add_argument(
        "--verbose", action="store_true",
        help="Show detailed progress and debug messages",
    )
    create.add_argument(
        "--nobuild", action="store_true",
        help="Skip APK build; output prepared project to directory (useful for debugging)",
    )
    create.add_argument(
        "--icon", metavar="PATH",
        help="Icon image file (PNG/JPG/WebP) — auto-resizes to all Android densities",
    )
    create.add_argument(
        "-o", "--output", default=".", metavar="DIR",
        help="Directory to copy the APK into (default: current working directory)",
    )

    # ── doctor ────────────────────────────────────────────────────────────────
    doctor = sub.add_parser(
        "doctor",
        help="Validate an Android WebView template",
        description="""
Check if an Android template is valid for use with Bonboneka.

Validates:
  • Assets folder exists
  • Assets folder contains HTML files with shebangs
  • At least one HTML has the prime shebang (_$1)

EXAMPLES:
  bomk doctor ./my_template
        """.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor.add_argument("template", help="Path to Android template directory")
    doctor.add_argument("--verbose", action="store_true", help="Show detailed diagnostic information")

    # ── gitlink ───────────────────────────────────────────────────────────────
    gitlink = sub.add_parser(
        "gitlink",
        help="Manage template git configuration and auto-commit",
        description="""
Configure git integration for your Android template.

EXAMPLES:
  bomk gitlink TEMPLATE_PATH --set https://github.com/user/template.git
  bomk gitlink TEMPLATE_PATH --behaviour commit-per-build
  bomk gitlink TEMPLATE_PATH --behaviour manual-commit
  bomk gitlink TEMPLATE_PATH --commit
  bomk gitlink TEMPLATE_PATH --push
  bomk gitlink TEMPLATE_PATH --disengage
        """.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    gitlink.add_argument("template", help="Path to Android template directory")
    gitlink.add_argument("--set", metavar="URL", help="Set or update the git origin URL")
    gitlink.add_argument(
        "--behaviour", choices=["commit-per-build", "manual-commit"],
        help="Set auto-commit behaviour",
    )
    gitlink.add_argument(
        "--commit", action="store_true",
        help="Manually commit all pending changes",
    )
    gitlink.add_argument(
        "--disengage", action="store_true",
        help="Reset template to default origin and remove gitlink configuration",
    )
    gitlink.add_argument(
        "--push", action="store_true",
        help="Push all commits to the remote repository",
    )

    return p


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    argv   = _normalize_argv(sys.argv[1:])
    parser = _build_parser()
    args   = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    level = (
        Logger.SILENT  if getattr(args, "silent",  False) else
        Logger.VERBOSE if getattr(args, "verbose", False) else
        Logger.NORMAL
    )
    log = Logger(level)

    # ── create ────────────────────────────────────────────────────────────────
    if args.command == "create":
        log.highlight(f"Bonboneka — Version {VERSION}")

        pwa_url     = getattr(args, "pwa",     None)
        encased_url = getattr(args, "encased", None)
        folder      = getattr(args, "folder",  None)

        # --name overrides --appname; fall back to --appname default
        resolved_name: str = args.name or args.appname

        if pwa_url:
            cmd_pwa(
                url=pwa_url,
                output_dir=args.output,
                log=log,
                appname=resolved_name,
                package=args.package,
                icon=getattr(args, "icon", None),
                nobuild=getattr(args, "nobuild", False),
            )
        elif folder:
            cmd_create(
                folder=folder,
                output_dir=args.output,
                log=log,
                nobuild=getattr(args, "nobuild", False),
                icon=getattr(args, "icon", None),
                appname=resolved_name,
                config=getattr(args, "config", None),
            )
        else:
            log.error(
                "Provide a source: a folder path, --encased <url>, or --pwa <url>.\n"
                "  bomk create ./my_app\n"
                "  bomk create --encased https://example.com\n"
                "  bomk create --pwa     https://example.com"
            )
            sys.exit(1)

    # ── doctor ────────────────────────────────────────────────────────────────
    elif args.command == "doctor":
        cmd_doctor(args.template, log)

    # ── gitlink ───────────────────────────────────────────────────────────────
    elif args.command == "gitlink":
        _dispatch_gitlink(args, log)


def _dispatch_gitlink(args: argparse.Namespace, log: Logger) -> None:
    from pathlib import Path
    template_path = Path(args.template).resolve()

    if not template_path.is_dir():
        log.error(f"Template directory not found: {template_path}")
        sys.exit(1)

    try:
        if args.disengage:
            disengage_template(template_path, log)
            return

        if args.set:
            log.step("Setting git origin")
            set_origin(template_path, args.set, log)

        if args.behaviour:
            log.step(f"Changing behaviour to: {args.behaviour}")
            set_behaviour(template_path, args.behaviour, log)

        if args.commit:
            log.step("Committing changes")
            commit_template(template_path, log)

        if args.push:
            push_template(template_path, log)

        if not any([args.commit, args.set, args.behaviour, args.push, args.disengage]):
            log.info(f"Current behaviour: {get_behaviour(template_path)}")

    except ValueError as exc:
        log.error(str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error(f"Git operation failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
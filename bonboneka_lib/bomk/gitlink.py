"""
bomk/gitlink.py – Manage template git configuration and auto-commit behavior.
"""

import subprocess
import json
from pathlib import Path
from .lib import Logger
from .config import TEMPLATE_REPO


GITLINK_CONFIG = ".bomk_gitlink.json"


def _run_git(args: list[str], cwd: str, *, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in *cwd* and return the CompletedProcess."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=capture,
        text=True,
    )


def set_origin(template_path: Path, url: str, log: Logger | None = None) -> None:
    """Set or update the git remote origin URL for a template."""
    _assert_git_repo(template_path)
    log and log.step(f"Setting origin to: {url}")

    r = _run_git(["remote", "get-url", "origin"], str(template_path))
    if r.returncode == 0 and r.stdout.strip():
        _run_git(["remote", "set-url", "origin", url], str(template_path))
        log and log.success("Origin updated")
    else:
        _run_git(["remote", "add", "origin", url], str(template_path))
        log and log.success("Origin added")


def set_behaviour(template_path: Path, behaviour: str, log: Logger | None = None) -> None:
    """Persist the auto-commit behaviour to the gitlink config file."""
    if behaviour not in ("commit-per-build", "manual-commit"):
        raise ValueError(
            f"Invalid behaviour: {behaviour!r}. "
            "Must be 'commit-per-build' or 'manual-commit'."
        )

    config = _read_config(template_path)
    config["behaviour"] = behaviour
    _write_config(template_path, config)
    log and log.success(f"Behaviour set to: {behaviour}")


def get_behaviour(template_path: Path) -> str:
    """Return the current auto-commit behaviour (defaults to 'manual-commit')."""
    return _read_config(template_path).get("behaviour", "manual-commit")


def commit_template(template_path: Path, log: Logger | None = None) -> None:
    """Stage and commit all changes in the template repository."""
    _assert_git_repo(template_path)
    log and log.step("Committing template changes")

    _run_git(["add", "-A"], str(template_path))

    # --quiet exits 0 when nothing is staged; non-zero means there are changes
    r = _run_git(["diff", "--cached", "--quiet"], str(template_path))
    if r.returncode == 0:
        log and log.info("No changes to commit")
        return

    _run_git(["commit", "-m", "Auto-commit by Bonboneka"], str(template_path))
    log and log.success("Changes committed")


def disengage_template(template_path: Path, log: Logger | None = None) -> None:
    """Reset the template origin to the default and remove the gitlink config."""
    _assert_git_repo(template_path)
    log and log.step("Disengaging template")

    _run_git(["remote", "set-url", "origin", TEMPLATE_REPO], str(template_path))
    log and log.success(f"Origin reset to: {TEMPLATE_REPO}")

    config_path = template_path / GITLINK_CONFIG
    if config_path.exists():
        config_path.unlink()
        log and log.success("Configuration removed")
    else:
        log and log.info("No configuration to remove")

    log and log.success("Template disengaged successfully")


def push_template(template_path: Path, log: Logger | None = None) -> None:
    """Push the current HEAD to the remote origin."""
    _assert_git_repo(template_path)
    log and log.step("Pushing changes to remote")

    r = _run_git(["push", "origin", "HEAD"], str(template_path))
    if r.returncode != 0:
        # BUG FIX: git may write progress/error to stdout on some versions
        err = (r.stderr or r.stdout or "").strip()
        raise ValueError(f"Git push failed:\n{err}")

    log and log.success("Changes pushed to remote")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_git_repo(path: Path) -> None:
    if not (path / ".git").exists():
        raise ValueError(f"Not a git repository: {path}")


def _read_config(template_path: Path) -> dict:
    config_path = template_path / GITLINK_CONFIG
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _write_config(template_path: Path, config: dict) -> None:
    config_path = template_path / GITLINK_CONFIG
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
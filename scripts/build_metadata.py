"""Shared helpers for continuous build metadata scripts."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = ROOT / "build"
DEFAULT_METADATA_PATH = DEFAULT_BUILD_DIR / "BUILD_INFO.json"
DEFAULT_PACKAGE_INFO_PATH = ROOT / "src" / "nes_py" / "_build_info.py"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def run_git(args: list[str]) -> str:
    """Run a git command from the repository root."""
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def read_base_version() -> str:
    """Read the committed project version from pyproject.toml."""
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError("Could not find project version in pyproject.toml")
    return match.group(1)


def discover_commit_sha() -> str:
    if commit_sha := os.getenv("GITHUB_SHA"):
        return commit_sha
    try:
        return run_git(["rev-parse", "HEAD"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "0" * 40


def discover_branch_name() -> str:
    branch = os.getenv("GITHUB_HEAD_REF") or os.getenv("GITHUB_REF_NAME")
    if branch:
        return branch
    try:
        return run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"


def discover_build_number() -> str:
    return os.getenv("GITHUB_RUN_NUMBER") or "0"


def build_version(base_version: str, build_number: str, short_sha: str) -> str:
    """Return a PEP 440 compatible continuous build version."""
    numeric_build = build_number if build_number.isdigit() else "0"
    return f"{base_version}.dev{numeric_build}+g{short_sha}"


def collect_metadata() -> dict[str, str]:
    """Collect build metadata from GitHub Actions or the local git checkout."""
    commit_sha = discover_commit_sha()
    short_sha = commit_sha[:7]
    base_version = read_base_version()
    build_number = discover_build_number()
    return {
        "version": build_version(base_version, build_number, short_sha),
        "base_version": base_version,
        "commit_sha": commit_sha,
        "short_commit_sha": short_sha,
        "branch_name": discover_branch_name(),
        "build_number": build_number,
        "build_timestamp_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def write_json(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_metadata(path: Path = DEFAULT_METADATA_PATH) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return collect_metadata()


def write_package_info(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '"""Generated build metadata. Do not edit by hand."""',
        "",
    ]
    for key in (
        "version",
        "base_version",
        "commit_sha",
        "short_commit_sha",
        "branch_name",
        "build_number",
        "build_timestamp_utc",
    ):
        lines.append(f"{key} = {metadata.get(key, '')!r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_project_version(version_value: str, path: Path = PYPROJECT_PATH) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^version = "[^"]+"$',
        f'version = "{version_value}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise RuntimeError("Could not update project version in pyproject.toml")
    path.write_text(updated, encoding="utf-8")


def previous_tag() -> str | None:
    try:
        return run_git(["describe", "--tags", "--abbrev=0", "HEAD^"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def comparison_base() -> str:
    tag = previous_tag()
    if tag:
        return tag
    try:
        return run_git(["rev-parse", "HEAD^"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            return run_git(["rev-list", "--max-parents=0", "HEAD"])
        except (FileNotFoundError, subprocess.CalledProcessError):
            return "initial commit"


def commit_lines(base: str) -> list[str]:
    try:
        output = run_git(["log", "--pretty=format:%h %s (%an)", f"{base}..HEAD"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            output = run_git(["log", "--pretty=format:%h %s (%an)", "HEAD"])
        except (FileNotFoundError, subprocess.CalledProcessError):
            output = ""
    return [line for line in output.splitlines() if line]


def changed_files(base: str) -> list[str]:
    try:
        output = run_git(["diff", "--name-only", f"{base}..HEAD"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            output = run_git(["show", "--pretty=", "--name-only", "HEAD"])
        except (FileNotFoundError, subprocess.CalledProcessError):
            output = ""
    return sorted({line for line in output.splitlines() if line})

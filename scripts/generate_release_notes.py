"""Generate release notes for the current continuous build."""

from __future__ import annotations

import argparse
from pathlib import Path

from build_metadata import DEFAULT_BUILD_DIR, DEFAULT_METADATA_PATH, read_metadata, write_json


def wheel_name(version: str) -> str:
    return f"pynes-{version}-py3-none-any.whl"


def render_release_notes(metadata_path: Path, output_path: Path) -> str:
    metadata = read_metadata(metadata_path)
    write_json(metadata_path, metadata)
    version = metadata["version"]
    lines = [
        f"# Continuous Build {version}",
        "",
        "## Summary",
        "",
        "This is an automated continuous build of the Python NES emulator project.",
        "",
        "## Validation",
        "",
        "This build is generated after running:",
        "",
        "- pytest",
        "- ruff check",
        "- python -m build",
        "- python -m nes_py --help",
        "- python -m nes_py --version",
        "",
        "## Installation",
        "",
        "Download the wheel artifact from this workflow run, then install it with:",
        "",
        "```bash",
        f"python -m pip install {wheel_name(version)}",
        "```",
        "",
        "Verify:",
        "",
        "```bash",
        "python -m nes_py --version",
        "nes-py --version",
        "```",
        "",
        "## Current limitations",
        "",
        "This project is still under development and may not yet emulate NES games.",
        "",
        "## Changelog",
        "",
        "See `CHANGELOG.md` in this workflow run's `build-changelog` artifact.",
        "",
        "## Build metadata",
        "",
        f"- Version: {version}",
        f"- Base version: {metadata['base_version']}",
        f"- Commit: {metadata['commit_sha']}",
        f"- Branch: {metadata['branch_name']}",
        f"- Build number: {metadata['build_number']}",
        f"- Built at: {metadata['build_timestamp_utc']}",
    ]
    content = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_BUILD_DIR / "RELEASE_NOTES.md")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    render_release_notes(args.metadata, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

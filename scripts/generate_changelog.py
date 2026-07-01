"""Generate a changelog for the current continuous build."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

from build_metadata import (
    DEFAULT_BUILD_DIR,
    DEFAULT_METADATA_PATH,
    changed_files,
    commit_lines,
    comparison_base,
    read_metadata,
    write_json,
)


def pull_request_numbers(commits: list[str]) -> list[str]:
    numbers: set[str] = set()
    for line in commits:
        numbers.update(re.findall(r"#(\d+)", line))
    return sorted(numbers, key=int)


def render_changelog(metadata_path: Path, output_path: Path) -> str:
    metadata = read_metadata(metadata_path)
    write_json(metadata_path, metadata)
    base = comparison_base()
    commits = commit_lines(base)
    files = changed_files(base)
    prs = pull_request_numbers(commits)

    lines = [
        f"# Changelog for {metadata['version']}",
        "",
        "## Build metadata",
        "",
        f"- Version: {metadata['version']}",
        f"- Base version: {metadata['base_version']}",
        f"- Commit: {metadata['commit_sha']}",
        f"- Branch: {metadata['branch_name']}",
        f"- Build number: {metadata['build_number']}",
        f"- Built at: {metadata['build_timestamp_utc']}",
        f"- Comparison base: {base}",
        "",
        "## Commits included",
        "",
    ]
    lines.extend(f"- {line}" for line in commits)
    if not commits:
        lines.append("- No commits found in comparison range.")

    lines.extend(["", "## Pull requests", ""])
    lines.extend(f"- #{number}" for number in prs)
    if not prs:
        lines.append("- No pull request references found.")

    lines.extend(["", "## Changed files", ""])
    lines.extend(f"- {file}" for file in files)
    if not files:
        lines.append("- No changed files found in comparison range.")

    content = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_BUILD_DIR / "CHANGELOG.md")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    render_changelog(args.metadata, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASES_DIR = REPO_ROOT / "docs" / "releases"
EXPECTED_RELEASES = (
    "v0.0.1",
    "v0.0.2",
    "v0.0.3",
    "v0.0.4",
    "v0.0.5",
    "v0.0.6",
    "v0.0.7",
    "v1.0.0",
    "v1.0.1",
)


def test_release_index_links_every_release_doc() -> None:
    index = (RELEASES_DIR / "index.md").read_text(encoding="utf-8")

    for version in EXPECTED_RELEASES:
        assert f"[{version}]({version}.md)" in index


def test_release_docs_exist_for_every_version() -> None:
    for version in EXPECTED_RELEASES:
        path = RELEASES_DIR / f"{version}.md"
        content = path.read_text(encoding="utf-8")

        assert re.search(rf"^# {re.escape(version)}\b", content)
        assert re.search(r"^Release date: \d{4}-\d{2}-\d{2}$", content, re.MULTILINE)
        assert f"Tag: `{version}`" in content
        assert "## Summary" in content
        assert "## Validation" in content
        assert "## Included Pull Requests" in content

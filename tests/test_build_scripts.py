from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_generate_changelog_script_runs_in_git_repo(tmp_path: Path) -> None:
    metadata = tmp_path / "BUILD_INFO.json"
    output = tmp_path / "CHANGELOG.md"

    run_script("generate_changelog.py", "--metadata", str(metadata), "--output", str(output))

    assert output.exists()
    assert "# Changelog for " in output.read_text(encoding="utf-8")
    assert metadata.exists()


def test_generate_release_notes_script_runs(tmp_path: Path) -> None:
    metadata = tmp_path / "BUILD_INFO.json"
    output = tmp_path / "RELEASE_NOTES.md"

    run_script("generate_release_notes.py", "--metadata", str(metadata), "--output", str(output))

    assert output.exists()
    assert "# Continuous Build " in output.read_text(encoding="utf-8")
    assert metadata.exists()

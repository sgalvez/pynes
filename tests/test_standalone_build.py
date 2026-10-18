from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_standalone_build_script_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_standalone.py"), "--help"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Build a standalone nes-py executable" in result.stdout
    assert "--name" in result.stdout

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_nes_module_can_be_run_directly_for_help() -> None:
    script = Path(__file__).resolve().parents[1] / "src" / "nes_py" / "nes.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Run a Python NES emulator." in result.stdout
    assert "--smoke-test" in result.stdout

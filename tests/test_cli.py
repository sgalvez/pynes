from __future__ import annotations

import pytest

from nes_py import __version__
import nes_py.cli
from nes_py.cli import main


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Run a Python NES emulator." in output
    assert "rom" in output
    assert "--version" in output


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert f"nes-py {__version__}" in capsys.readouterr().out


def test_cli_default_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "usage: nes-py" in output


def test_cli_runs_desktop_with_rom_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, int]] = []

    def fake_run_desktop(
        rom: str,
        *,
        scale: int,
        instructions_per_frame: int,
    ) -> int:
        calls.append((rom, scale, instructions_per_frame))
        return 0

    monkeypatch.setattr(nes_py.cli, "run_desktop", fake_run_desktop)

    assert main(["game.nes", "--scale", "2", "--instructions-per-frame", "123"]) == 0
    assert calls == [("game.nes", 2, 123)]

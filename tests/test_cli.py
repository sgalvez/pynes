from __future__ import annotations

import pytest

import nes_py.cli
from nes_py import __version__
from nes_py.cli import main
from nes_py.debug import SmokeTestResult


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Run a Python NES emulator." in output
    assert "rom" in output
    assert "--version" in output
    assert "--trace" in output
    assert "--smoke-test" in output


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
    calls: list[tuple[str, int, int, bool, bool, str | None, bool]] = []

    def fake_run_desktop(
        rom: str,
        *,
        scale: int,
        instructions_per_frame: int,
        trace: bool,
        disassemble: bool,
        trace_file: str | None,
        audio_pilot: bool,
    ) -> int:
        calls.append(
            (
                rom,
                scale,
                instructions_per_frame,
                trace,
                disassemble,
                trace_file,
                audio_pilot,
            )
        )
        return 0

    monkeypatch.setattr(nes_py.cli, "run_desktop", fake_run_desktop)

    assert main(["game.nes", "--scale", "2", "--instructions-per-frame", "123"]) == 0
    assert calls == [("game.nes", 2, 123, False, False, None, False)]


def test_cli_smoke_test_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, int, bool]] = []

    def fake_run_smoke_test(
        rom: str,
        *,
        instructions: int,
        trace_sink,
        include_disassembly: bool,
    ):
        calls.append((rom, instructions, include_disassembly))
        return SmokeTestResult(
            instructions=instructions,
            cpu_cycles=6,
            pc=0x8002,
            frame=0,
        )

    monkeypatch.setattr(nes_py.cli, "run_smoke_test", fake_run_smoke_test)

    assert main(["game.nes", "--smoke-test", "2", "--disassemble"]) == 0

    assert calls == [("game.nes", 2, True)]
    assert "Smoke test completed" in capsys.readouterr().out


def test_cli_reports_missing_display_dependency_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run_desktop(*args, **kwargs) -> int:
        raise nes_py.cli.DisplayUnavailableError("install pygame please")

    monkeypatch.setattr(nes_py.cli, "run_desktop", fake_run_desktop)

    with pytest.raises(SystemExit) as exc_info:
        main(["game.nes"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "install pygame please" in captured.err
    assert "Traceback" not in captured.err


def test_cli_passes_audio_pilot_flag(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        nes_py.cli, "run_desktop", lambda rom, **kwargs: calls.append(kwargs) or 0
    )
    assert main(["game.nes", "--audio-pilot"]) == 0
    assert calls[0]["audio_pilot"] is True


def test_cli_rejects_audio_pilot_in_smoke_mode(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["game.nes", "--audio-pilot", "--smoke-test", "1"])
    assert error.value.code == 2
    assert "requires desktop mode" in capsys.readouterr().err


def test_cli_reports_audio_backend_failure_without_traceback(
    monkeypatch, capsys
) -> None:
    from nes_py.audio import AudioUnavailableError

    def unavailable(*args, **kwargs):
        raise AudioUnavailableError("no SDL_mixer support")

    monkeypatch.setattr("nes_py.app.run_desktop", unavailable)
    with pytest.raises(SystemExit) as error:
        main(["game.nes", "--audio-pilot"])
    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "no SDL_mixer support" in output
    assert "Traceback" not in output


def test_cli_reports_cartridge_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run_desktop(*args, **kwargs) -> int:
        raise nes_py.cli.CartridgeError("unsupported mapper")

    monkeypatch.setattr(nes_py.cli, "run_desktop", fake_run_desktop)

    with pytest.raises(SystemExit) as exc_info:
        main(["game.nes"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "unsupported mapper" in captured.err
    assert "Traceback" not in captured.err

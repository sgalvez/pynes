import subprocess
import sys
import wave
from array import array
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apu_pilot.py"


@pytest.mark.parametrize(
    "channel", ("all", "pulse1", "pulse2", "triangle", "noise", "dmc")
)
def test_generated_demo_exports_non_silent_channels_without_pygame(
    tmp_path, channel
) -> None:
    output = tmp_path / "demo.wav"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--frames",
            "12",
            "--output",
            str(output),
            "--demo-channel",
            channel,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "APU pilot:" in result.stdout
    with wave.open(str(output), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (
            1,
            2,
            44100,
        )
        assert 8700 < audio.getnframes() < 8900
        samples = array("h")
        samples.frombytes(audio.readframes(audio.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
    assert min(samples) < 0 < max(samples)


def test_export_rejects_invalid_duration_before_creating_file(tmp_path) -> None:
    output = tmp_path / "invalid.wav"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--frames", "0", "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not output.exists()


def test_export_reports_missing_rom_without_traceback(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--rom", str(tmp_path / "missing.nes")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Unable to export APU pilot" in result.stderr
    assert "Traceback" not in result.stderr


def test_export_rejects_demo_channel_for_rom_capture(tmp_path) -> None:
    output = tmp_path / "invalid.wav"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--rom",
            str(tmp_path / "game.nes"),
            "--demo-channel",
            "noise",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "only applies to the generated demo" in result.stderr
    assert not output.exists()

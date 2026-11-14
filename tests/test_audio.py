import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from nes_py.audio import AudioUnavailableError, PygameAudioOutput, write_wav


class FakeChannel:
    def __init__(self):
        self.current = self.queued = None

    def get_busy(self):
        return self.current is not None

    def get_queue(self):
        return self.queued

    def play(self, sound):
        self.current = sound
        self.queued = None

    def queue(self, sound):
        self.queued = sound

    def stop(self):
        self.current = self.queued = None


def fake_audio():
    channel = FakeChannel()
    mixer = SimpleNamespace(
        get_init=lambda: (44100, -16, 1),
        Channel=lambda index: channel,
        Sound=lambda *, buffer: buffer,
    )
    return SimpleNamespace(mixer=mixer, error=RuntimeError), channel


def test_wav_has_exact_pcm_format_and_contents(tmp_path: Path) -> None:
    path = tmp_path / "audio" / "pilot.wav"
    pcm = b"\x00\x00\xff\x7f\x00\x80"
    write_wav(path, pcm, sample_rate=22050)
    with wave.open(str(path), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (
            1,
            2,
            22050,
        )
        assert audio.getnframes() == 3
        assert audio.readframes(3) == pcm


@pytest.mark.parametrize("rate,pcm", [(0, b""), (44100, b"\0")])
def test_wav_rejects_invalid_pcm_format(tmp_path, rate, pcm) -> None:
    with pytest.raises(ValueError):
        write_wav(tmp_path / "bad.wav", pcm, sample_rate=rate)


def test_playback_queues_ordered_blocks_without_replacing_queued_audio() -> None:
    pygame, channel = fake_audio()
    output = PygameAudioOutput(pygame)
    blocks = [bytes((value, 0)) * 1024 for value in (1, 2, 3)]
    output.submit(b"".join(blocks))
    assert channel.current == blocks[0]
    assert channel.queued == blocks[1]
    assert output.pending == blocks[2]
    channel.current, channel.queued = channel.queued, None
    output.submit(b"")
    assert channel.queued == blocks[2]
    assert not output.pending
    output.clear()
    assert not channel.get_busy()


def test_playback_backlog_is_bounded_and_clear_discards_pending_data() -> None:
    pygame, channel = fake_audio()
    output = PygameAudioOutput(pygame)
    output.submit(bytes(output.block_bytes * 100))
    assert channel.get_busy()
    assert len(output.pending) <= output.max_pending_bytes
    output.clear()
    assert not output.pending
    assert channel.get_queue() is None


def test_unavailable_device_has_a_useful_error() -> None:
    def unavailable(**kwargs):
        raise RuntimeError("no audio device")

    mixer = SimpleNamespace(get_init=lambda: None, quit=lambda: None, init=unavailable)
    with pytest.raises(AudioUnavailableError, match="export a WAV"):
        PygameAudioOutput(SimpleNamespace(mixer=mixer, error=RuntimeError))


def test_missing_mixer_has_an_actionable_error() -> None:
    with pytest.raises(AudioUnavailableError, match="no SDL_mixer support"):
        PygameAudioOutput(SimpleNamespace(mixer=None, error=RuntimeError))

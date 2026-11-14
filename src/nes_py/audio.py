"""WAV export and bounded pygame playback for the experimental APU."""

from __future__ import annotations

import sys
import wave
from array import array
from pathlib import Path

from .apu import DEFAULT_SAMPLE_RATE


class AudioUnavailableError(RuntimeError):
    """Raised when the requested PCM device cannot be initialized."""


def write_wav(
    path: str | Path, pcm: bytes, *, sample_rate: int = DEFAULT_SAMPLE_RATE
) -> None:
    """Write mono signed 16-bit little-endian PCM without an audio device."""
    if sample_rate <= 0 or len(pcm) % 2:
        raise ValueError(
            "WAV output requires a positive sample rate and whole 16-bit samples"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)


class PygameAudioOutput:
    """Queue small mono blocks, bounding backlog to keep pilot latency finite."""

    def __init__(
        self, pygame_module, *, sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> None:
        self.pygame = pygame_module
        self.block_bytes = 1024 * 2
        self.max_pending_bytes = self.block_bytes * 4
        self.pending = bytearray()
        if not self.pygame.mixer:
            raise AudioUnavailableError(
                "This pygame installation has no SDL_mixer support. "
                "Install pygame with mixer support for desktop audio, or use "
                "scripts/apu_pilot.py to export a WAV without an audio device."
            )
        try:
            expected = (sample_rate, -16, 1)
            if self.pygame.mixer.get_init() != expected:
                self.pygame.mixer.quit()
                self.pygame.mixer.init(
                    frequency=sample_rate,
                    size=-16,
                    channels=1,
                    buffer=512,
                    allowedchanges=0,
                )
            self.channel = self.pygame.mixer.Channel(0)
        except (self.pygame.error, NotImplementedError) as exc:
            raise AudioUnavailableError(
                f"Unable to initialize pilot audio: {exc}. "
                "Use scripts/apu_pilot.py to export a WAV without an audio device."
            ) from exc

    def submit(self, pcm: bytes) -> None:
        self.pending.extend(pcm)
        if len(self.pending) > self.max_pending_bytes:
            # Discard old whole samples if emulation outpaces the host device.
            del self.pending[: -self.max_pending_bytes]
        while len(self.pending) >= self.block_bytes:
            if self.channel.get_busy() and self.channel.get_queue() is not None:
                break
            block = bytes(self.pending[: self.block_bytes])
            del self.pending[: self.block_bytes]
            if sys.byteorder != "little":
                samples = array("h")
                samples.frombytes(block)
                samples.byteswap()
                block = samples.tobytes()
            sound = self.pygame.mixer.Sound(buffer=block)
            if self.channel.get_busy():
                self.channel.queue(sound)
            else:
                self.channel.play(sound)

    def clear(self) -> None:
        self.channel.stop()
        self.pending.clear()

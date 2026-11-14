"""Export the five-channel APU pilot to WAV from a generated demo or a local ROM."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nes_py.apu import DEFAULT_SAMPLE_RATE, NTSC_CPU_HZ
from nes_py.audio import write_wav
from nes_py.cartridge import CartridgeError
from nes_py.cpu import CPUError
from nes_py.nes import NES

DEMO_CHANNELS = {
    "all": 0x1F,
    "pulse1": 1,
    "pulse2": 2,
    "triangle": 4,
    "noise": 8,
    "dmc": 16,
}


def build_dmc_sample() -> bytes:
    """Encode an original decaying drum tone as 257 bytes of LSB-first DPCM."""
    data = bytearray(257)  # $4013 = 16: 16 * 16 + 1 bytes.
    level = 64
    bit_rate = NTSC_CPU_HZ / 190  # NTSC rate index 8.
    for bit in range(len(data) * 8):
        target = 64 + 40 * math.exp(-bit / 450) * math.sin(
            2 * math.pi * 140 * bit / bit_rate
        )
        if level < target:
            data[bit >> 3] |= 1 << (bit & 7)
            level += 2
        else:
            level -= 2
    return bytes(data)


def build_demo_rom() -> bytes:
    """A generated NROM that loops while its APU is controlled through NESBus."""
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4] = header[5] = 1
    prg = bytearray(16384)
    prg[:3] = b"\x4c\x00\x80"
    sample = build_dmc_sample()
    prg[0x800 : 0x800 + len(sample)] = sample  # $C800, mirrored in 16 KiB NROM.
    prg[-4:-2] = b"\x00\x80"
    return bytes(header) + bytes(prg) + bytes(8192)


def play_demo_frame(nes: NES, frame: int, frames: int, channel_mask: int) -> None:
    """Original melody, lower harmony, bass, noise hits, and DPCM drum sample."""
    notes = (440.0, 554.365, 659.255, 880.0)
    note = min(3, frame * 4 // frames)
    if frame == 0 or note != min(3, (frame - 1) * 4 // frames):
        if channel_mask & 0x10:
            nes.bus.write(0x4015, channel_mask)
        for base, divisor, frequency, control in (
            (0x4000, 16, notes[note], 0xBF),
            (0x4004, 16, notes[note] * 0.75, 0x76),
            (0x4008, 32, notes[note] / 4, None),
        ):
            period = round(NTSC_CPU_HZ / (divisor * frequency) - 1)
            if control is not None:
                nes.bus.write(base, control)
            nes.bus.write(base + 2, period & 0xFF)
            nes.bus.write(base + 3, 0x08 | (period >> 8))
    if frame % max(1, frames // 8) == 0 and frames - frame > 6:
        nes.bus.write(0x400F, 0)  # Reload the noise length/envelope for each hit.
    if frames - frame <= 6:
        nes.bus.write(0x4000, 0xB0 | ((frames - frame - 1) * 15 // 6))
        nes.bus.write(0x4004, 0x70 | ((frames - frame - 1) * 6 // 6))
        nes.bus.write(0x4008, 0x80)  # Halt the bass on the next quarter-frame.


def capture(
    *,
    rom: Path | None,
    frames: int,
    warmup: int,
    sample_rate: int,
    demo_channel: str = "all",
) -> bytes:
    nes = (
        NES.from_ines_file(rom, audio_sample_rate=sample_rate)
        if rom is not None
        else NES.from_ines_rom(build_demo_rom(), audio_sample_rate=sample_rate)
    )
    assert nes.apu is not None
    for _ in range(warmup):
        nes.run_frame()
        nes.apu.drain_samples()
    if rom is None:
        nes.bus.write(0x4017, 0x40)
        nes.bus.write(0x4001, 0x08)
        nes.bus.write(0x4005, 0x08)
        nes.bus.write(0x4008, 0xFF)
        nes.bus.write(0x400C, 0x02)
        nes.bus.write(0x400E, 0x04)
        nes.bus.write(0x4010, 0x08)
        nes.bus.write(0x4011, 64 if DEMO_CHANNELS[demo_channel] & 0x10 else 0)
        nes.bus.write(0x4012, 0x20)  # $C800
        nes.bus.write(0x4013, 16)
        nes.bus.write(0x4015, DEMO_CHANNELS[demo_channel])
    pcm = bytearray()
    for frame in range(frames):
        if rom is None:
            play_demo_frame(nes, frame, frames, DEMO_CHANNELS[demo_channel])
        nes.run_frame()
        pcm.extend(nes.apu.drain_samples())
    return bytes(pcm)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rom",
        type=Path,
        help="capture a local ROM instead of the generated four-note demo",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "apu-pilot.wav")
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--warmup-frames", type=int, default=0)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument(
        "--demo-channel",
        choices=DEMO_CHANNELS,
        default="all",
        help="isolate one channel in the generated demo (default: all)",
    )
    args = parser.parse_args()
    if args.frames <= 0 or args.warmup_frames < 0:
        parser.error(
            "--frames must be positive and --warmup-frames must be non-negative"
        )
    if not 1 <= args.sample_rate <= NTSC_CPU_HZ:
        parser.error(f"--sample-rate must be between 1 and {NTSC_CPU_HZ}")
    if args.rom is not None and args.demo_channel != "all":
        parser.error("--demo-channel only applies to the generated demo, without --rom")
    try:
        pcm = capture(
            rom=args.rom,
            frames=args.frames,
            warmup=args.warmup_frames,
            sample_rate=args.sample_rate,
            demo_channel=args.demo_channel,
        )
        write_wav(args.output, pcm, sample_rate=args.sample_rate)
    except (CartridgeError, CPUError, OSError) as exc:
        parser.exit(2, f"Unable to export APU pilot: {exc}\n")
    print(
        f"APU pilot: {args.output} | {len(pcm) // 2} samples | "
        f"{args.sample_rate} Hz | {len(pcm) / (2 * args.sample_rate):.3f} seconds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

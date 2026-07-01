"""Lightweight performance checks for the pynes project."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
PRG_ROM_BANK_SIZE = 16 * 1024
CHR_ROM_BANK_SIZE = 8 * 1024


@dataclass(frozen=True)
class Measurement:
    name: str
    value: float
    unit: str
    notes: str


def time_call(callback: Callable[[], None], *, repeat: int = 5) -> float:
    durations: list[float] = []
    for _ in range(repeat):
        start = perf_counter()
        callback()
        durations.append(perf_counter() - start)
    return statistics.median(durations)


def run_python(args: list[str]) -> None:
    subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def build_nop_rom() -> bytes:
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4] = 1
    header[5] = 1
    prg_rom = bytearray([0xEA] * PRG_ROM_BANK_SIZE)
    prg_rom[-4] = 0x00
    prg_rom[-3] = 0x80
    chr_rom = bytes(CHR_ROM_BANK_SIZE)
    return bytes(header) + bytes(prg_rom) + chr_rom


def measure_imports() -> Measurement:
    seconds = time_call(lambda: run_python(["-c", "import nes_py"]), repeat=7)
    return Measurement("Package import", seconds * 1000, "ms", "median of 7 subprocess imports")


def measure_cli_startup() -> Measurement:
    seconds = time_call(lambda: run_python(["-m", "nes_py", "--version"]), repeat=7)
    return Measurement("CLI version startup", seconds * 1000, "ms", "median of 7 subprocess runs")


def measure_cpu_steps(instructions: int) -> Measurement:
    from nes_py.nes import NES

    nes = NES.from_ines_rom(build_nop_rom())
    start = perf_counter()
    nes.run(instructions)
    elapsed = perf_counter() - start
    return Measurement("CPU/NES stepping", instructions / elapsed, "instructions/sec", f"{instructions} NOPs")


def measure_ppu_render(frames: int) -> Measurement:
    from nes_py.cartridge import load_ines_rom
    from nes_py.ppu import PPU

    ppu = PPU(load_ines_rom(build_nop_rom()))
    start = perf_counter()
    for _ in range(frames):
        ppu.render_background()
    elapsed = perf_counter() - start
    return Measurement("PPU background render", frames / elapsed, "frames/sec", f"{frames} renders")


def measure_changelog() -> Measurement:
    seconds = time_call(lambda: run_python(["scripts/generate_changelog.py"]), repeat=5)
    return Measurement("Changelog generation", seconds * 1000, "ms", "median of 5 subprocess runs")


def measure_release_notes() -> Measurement:
    seconds = time_call(lambda: run_python(["scripts/generate_release_notes.py"]), repeat=5)
    return Measurement("Release notes generation", seconds * 1000, "ms", "median of 5 subprocess runs")


def selected_measurements(args: argparse.Namespace) -> list[Measurement]:
    all_selected = not any(
        (
            args.imports,
            args.cli_startup,
            args.emulator_step,
            args.ppu_render,
            args.changelog,
            args.release_notes,
        )
    )
    measurements: list[Measurement] = []
    if all_selected or args.imports:
        measurements.append(measure_imports())
    if all_selected or args.cli_startup:
        measurements.append(measure_cli_startup())
    if all_selected or args.emulator_step:
        measurements.append(measure_cpu_steps(args.instructions))
    if all_selected or args.ppu_render:
        measurements.append(measure_ppu_render(args.frames))
    if all_selected or args.changelog:
        measurements.append(measure_changelog())
    if all_selected or args.release_notes:
        measurements.append(measure_release_notes())
    return measurements


def print_markdown(measurements: list[Measurement]) -> None:
    print("| Area | Measurement | Notes |")
    print("|---|---:|---|")
    for measurement in measurements:
        if measurement.unit == "ms":
            value = f"{measurement.value:.2f} ms"
        else:
            value = f"{measurement.value:,.0f} {measurement.unit}"
        print(f"| {measurement.name} | {value} | {measurement.notes} |")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imports", action="store_true", help="measure package import time")
    parser.add_argument("--cli-startup", action="store_true", help="measure `python -m nes_py --version` startup")
    parser.add_argument("--emulator-step", action="store_true", help="measure simple NES CPU stepping throughput")
    parser.add_argument("--ppu-render", action="store_true", help="measure background render throughput")
    parser.add_argument("--changelog", action="store_true", help="measure changelog generation time")
    parser.add_argument("--release-notes", action="store_true", help="measure release note generation time")
    parser.add_argument("--instructions", type=int, default=100_000, help="instruction count for stepping benchmark")
    parser.add_argument("--frames", type=int, default=20, help="frame count for PPU render benchmark")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print_markdown(selected_measurements(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

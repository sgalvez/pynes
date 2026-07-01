"""Command-line interface for pynes."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__
from .app import (
    DEFAULT_INSTRUCTIONS_PER_FRAME,
    DEFAULT_SCALE,
    DisplayUnavailableError,
    run_desktop,
)
from .cartridge import CartridgeError
from .debug import open_trace_sink, run_smoke_test
from .logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser."""
    parser = argparse.ArgumentParser(
        prog="nes-py",
        description="Run a Python NES emulator.",
    )
    parser.add_argument(
        "rom",
        nargs="?",
        help="path to an iNES .nes ROM file",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=DEFAULT_SCALE,
        help=f"window scale factor (default: {DEFAULT_SCALE})",
    )
    parser.add_argument(
        "--instructions-per-frame",
        type=int,
        default=DEFAULT_INSTRUCTIONS_PER_FRAME,
        help="CPU instructions to execute before drawing each frame",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="print CPU trace lines while running",
    )
    parser.add_argument(
        "--disassemble",
        action="store_true",
        help="include best-effort instruction disassembly in CPU traces",
    )
    parser.add_argument(
        "--trace-file",
        help="write CPU trace lines to this file instead of stdout",
    )
    parser.add_argument(
        "--smoke-test",
        type=int,
        metavar="INSTRUCTIONS",
        help="load the ROM, step a fixed instruction count, print a summary, and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose logging",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    if args.rom is None:
        parser.print_help()
        return 0
    try:
        if args.smoke_test is not None:
            trace_sink = None
            trace_handle = None
            try:
                if args.trace:
                    trace_sink, trace_handle = open_trace_sink(args.trace_file)
                result = run_smoke_test(
                    args.rom,
                    instructions=args.smoke_test,
                    trace_sink=trace_sink,
                    include_disassembly=args.disassemble,
                )
            finally:
                if trace_handle is not None:
                    trace_handle.close()
            print(
                "Smoke test completed: "
                f"instructions={result.instructions} "
                f"cpu_cycles={result.cpu_cycles} "
                f"pc=0x{result.pc:04X} "
                f"frame={result.frame}"
            )
            return 0
        return run_desktop(
            args.rom,
            scale=args.scale,
            instructions_per_frame=args.instructions_per_frame,
            trace=args.trace,
            disassemble=args.disassemble,
            trace_file=args.trace_file,
        )
    except (CartridgeError, DisplayUnavailableError) as exc:
        parser.exit(2, f"{exc}\n")
    except OSError as exc:
        parser.exit(2, f"Unable to load ROM {args.rom!r}: {exc}\n")

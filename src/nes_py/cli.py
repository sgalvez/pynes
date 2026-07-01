"""Command-line interface for pynes."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__
from .app import DEFAULT_INSTRUCTIONS_PER_FRAME, DEFAULT_SCALE, run_desktop
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
    return run_desktop(
        args.rom,
        scale=args.scale,
        instructions_per_frame=args.instructions_per_frame,
    )

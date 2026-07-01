"""Logging setup for command-line and future emulator modules."""

from __future__ import annotations

import logging


def configure_logging(*, verbose: bool = False) -> None:
    """Configure standard logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s:%(name)s:%(message)s",
    )

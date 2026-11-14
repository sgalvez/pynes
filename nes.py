#!/usr/bin/env python3
"""Run pynes directly from the repository root."""

import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from nes_py.cli import main

    raise SystemExit(main())

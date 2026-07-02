"""Build a standalone nes-py executable with PyInstaller."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST_DIR = ROOT / "dist" / "standalone"
LAUNCHER = ROOT / "scripts" / "nes_py_launcher.py"


def executable_name(name: str) -> str:
    if os.name == "nt" and not name.endswith(".exe"):
        return f"{name}.exe"
    return name


def build_executable(*, name: str, dist_dir: Path, clean: bool) -> Path:
    if clean:
        shutil.rmtree(ROOT / "build" / "pyinstaller", ignore_errors=True)
        shutil.rmtree(dist_dir, ignore_errors=True)

    dist_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build" / "pyinstaller"),
        "--collect-all",
        "pygame",
        str(LAUNCHER),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    executable = dist_dir / executable_name(name)
    if not executable.exists():
        raise FileNotFoundError(f"Expected executable was not created: {executable}")
    return executable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="nes-py", help="output executable name")
    parser.add_argument("--dist-dir", type=Path, default=DEFAULT_DIST_DIR)
    parser.add_argument("--no-clean", action="store_true", help="keep previous PyInstaller build output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    executable = build_executable(
        name=args.name,
        dist_dir=args.dist_dir,
        clean=not args.no_clean,
    )
    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

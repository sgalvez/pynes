# pynes

`pynes` is a Python NES emulator project. This repository is currently in its
bootstrap phase: it provides an installable package, a command-line entry point,
test configuration, and continuous integration for future emulator work.

The first milestone is an MVP NES emulator core with iNES/NROM loading, a 6502
CPU, a memory bus, a basic PPU framebuffer, keyboard input, and debugging tools.
Those pieces are intentionally not implemented in this initial scaffold.

## Requirements

- Python 3.11 or newer

## Development Setup

Create a virtual environment, install the project in editable mode, and include
the development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Running The CLI

After installation, run:

```bash
nes-py --help
nes-py --version
```

You can also run the package module directly:

```bash
python -m nes_py --help
```

## Running Tests

```bash
python -m pytest
```

## Project Layout

```text
.
├── README.md
├── pyproject.toml
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   └── nes_py/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       └── logging_config.py
└── tests/
    ├── __init__.py
    └── test_cli.py
```

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).

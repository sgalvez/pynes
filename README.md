# pynes

`pynes` is a Python NES emulator project. It provides an installable package,
a command-line entry point, test configuration, and continuous integration for
incremental NES emulator development.

The first milestone is an MVP NES emulator core with iNES/NROM loading, a 6502
CPU, a memory bus, a basic PPU framebuffer, keyboard input, and debugging tools.
Audio, advanced mappers, and full cycle-accurate emulation are out of scope for
the initial MVP.

## Requirements

- Python 3.11 or newer

## Development Setup

Create a virtual environment, install the project in editable mode, and include
the development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,display]"
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
nes-py path/to/game.nes
```

You can also run the package module directly:

```bash
python -m nes_py --help
python -m nes_py path/to/game.nes
```

The desktop runner uses pygame. Install the `display` extra when you want the
game window:

```bash
python -m pip install -e ".[display]"
```

## Controls

- Arrow keys: D-pad
- Z: B
- X: A
- Right Shift: Select
- Enter: Start
- Space: Pause or resume
- R: Reset
- Escape or window close: Quit

## Running Tests

```bash
python -m pytest
```

## Project Layout

```text
.
|-- README.md
|-- pyproject.toml
|-- .gitignore
|-- .github/
|   `-- workflows/
|       `-- ci.yml
|-- src/
|   `-- nes_py/
|       |-- __init__.py
|       |-- __main__.py
|       |-- app.py
|       |-- cartridge.py
|       |-- cli.py
|       |-- cpu.py
|       |-- input.py
|       |-- logging_config.py
|       |-- nes.py
|       `-- ppu.py
`-- tests/
    |-- __init__.py
    |-- test_app.py
    |-- test_cartridge.py
    |-- test_cli.py
    |-- test_cpu.py
    |-- test_nes.py
    `-- test_ppu.py
```

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).

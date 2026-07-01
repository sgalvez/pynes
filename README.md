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

## Release Status

- Current version: `0.0.1`
- Supported Python: Python 3.11+
- Validated platforms:
  - Windows
  - Linux
  - macOS

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

For release validation and package builds, the `dev` extra includes pytest,
Ruff, pygame, and Python build tooling:

```bash
python -m pip install -e ".[dev]"
```

## Running The CLI

After installation, run:

```bash
nes-py --help
nes-py --version
nes-py path/to/game.nes
nes-py path/to/game.nes --trace --disassemble
nes-py path/to/game.nes --smoke-test 1000
```

You can also run the package module directly:

```bash
python -m nes_py --help
python -m nes_py --version
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

## Debugging And Validation

Use `--trace` to print CPU trace lines while running. Each trace includes the
program counter, opcode, registers, status flags, stack pointer, and cycle
count. Add `--disassemble` for a best-effort instruction mnemonic:

```bash
python -m nes_py path/to/game.nes --trace --disassemble
```

For headless validation, use `--smoke-test` with a fixed instruction count. This
loads the ROM, steps CPU instructions, prints a summary, and exits without
opening a window:

```bash
python -m nes_py path/to/game.nes --smoke-test 1000 --trace --disassemble
```

Write longer traces to a file with `--trace-file`:

```bash
python -m nes_py path/to/game.nes --smoke-test 10000 --trace --trace-file trace.log
```

Use legal public-domain/homebrew ROMs, test ROMs whose licenses permit local
use, or your own locally supplied ROM dumps. Do not commit copyrighted ROMs to
the repository.

## Current Limitations

- Mapper support is incomplete.
- PPU behavior is incomplete and not cycle-accurate.
- Background rendering is basic; sprite rendering is not implemented.
- No APU/audio support.
- Input supports one keyboard-backed controller.

## Running Tests

```bash
python -m pytest
python -m ruff check .
```

## Building Packages

Build the source distribution and wheel with:

```bash
python -m build
```

The build writes release artifacts under `dist/`:

```text
dist/*.tar.gz
dist/*.whl
```

## Continuous Builds

Every push to `main`, `develop`, `feature/**`, or `issue/**`, and every pull
request, runs the continuous build workflow. The workflow validates the project,
generates build metadata, stamps a unique development version, builds Python
package artifacts, and uploads workflow artifacts.

Continuous build versions use the base project version plus the GitHub Actions
run number and commit SHA:

```text
Commit build version: 0.0.1.dev42+gabc1234
Formal release version: 0.0.1
Formal release tag: v0.0.1
```

Each continuous build uploads:

- `python-package`: `dist/*.tar.gz` and `dist/*.whl`
- `build-changelog`: `build/CHANGELOG.md`
- `build-release-notes`: `build/RELEASE_NOTES.md`
- `build-metadata`: `build/BUILD_INFO.json`

The generated package metadata lets the CLI report the stamped build version:

```bash
python -m nes_py --version
nes-py --version
```

Continuous build artifacts are downloadable from GitHub Actions workflow runs.
They are not published to PyPI and do not create permanent GitHub Releases.

## Installing From A Release Artifact

Download the wheel from a GitHub Release, then install it with:

```bash
python -m pip install nes_py-0.0.1-py3-none-any.whl
```

Verify the installed CLI:

```bash
python -m nes_py --help
python -m nes_py --version
nes-py --help
nes-py --version
```

## Creating A Release

Maintainers create a GitHub Release by pushing a version tag:

```bash
git checkout main
git pull
git tag v0.0.1
git push origin v0.0.1
```

Pushing the tag triggers the release workflow. The workflow installs the project,
runs tests and linting, builds the source distribution and wheel, creates or
updates the GitHub Release, and uploads the package artifacts. This project does
not publish to PyPI as part of the release workflow.

The tag-based release workflow remains separate from continuous builds:

```text
Every commit -> CI validation + packaged workflow artifacts
Version tag  -> formal GitHub Release
```

## Project Layout

```text
.
|-- README.md
|-- pyproject.toml
|-- .gitignore
|-- .github/
|   `-- workflows/
|       |-- ci.yml
|       |-- continuous-build.yml
|       `-- release.yml
|-- docs/
|   `-- releases/
|       `-- v0.0.1.md
|-- scripts/
|   |-- build_metadata.py
|   |-- generate_build_metadata.py
|   |-- generate_changelog.py
|   `-- generate_release_notes.py
|-- src/
|   `-- nes_py/
|       |-- __init__.py
|       |-- __main__.py
|       |-- app.py
|       |-- cartridge.py
|       |-- cli.py
|       |-- cpu.py
|       |-- debug.py
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

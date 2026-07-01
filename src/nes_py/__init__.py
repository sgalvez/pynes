"""Python NES emulator project package."""

from importlib.metadata import PackageNotFoundError, version

from .cartridge import (
    Cartridge,
    CartridgeError,
    INESHeader,
    Mirroring,
    load_ines_file,
    load_ines_rom,
)
from .input import Button, Controller
from .cpu import CPU6502, CPUError, MemoryBus, StatusFlag
from .debug import SmokeTestResult, disassemble_instruction, format_cpu_trace, run_smoke_test
from .nes import NES, NESBus, NESBusError
from .ppu import PPU, SCREEN_HEIGHT, SCREEN_WIDTH

try:
    __version__ = version("pynes")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    "Cartridge",
    "CartridgeError",
    "Button",
    "CPU6502",
    "CPUError",
    "Controller",
    "INESHeader",
    "MemoryBus",
    "Mirroring",
    "NES",
    "NESBus",
    "NESBusError",
    "PPU",
    "SCREEN_HEIGHT",
    "SCREEN_WIDTH",
    "SmokeTestResult",
    "StatusFlag",
    "__version__",
    "disassemble_instruction",
    "format_cpu_trace",
    "load_ines_file",
    "load_ines_rom",
    "run_smoke_test",
]

"""Python NES emulator project package."""

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
from .nes import NES, NESBus, NESBusError
from .ppu import PPU, SCREEN_HEIGHT, SCREEN_WIDTH

__version__ = "0.1.0"

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
    "StatusFlag",
    "__version__",
    "load_ines_file",
    "load_ines_rom",
]

"""Python NES emulator project package."""

from .cartridge import (
    Cartridge,
    CartridgeError,
    INESHeader,
    Mirroring,
    load_ines_file,
    load_ines_rom,
)
from .cpu import CPU6502, CPUError, MemoryBus, StatusFlag
from .nes import NES, NESBus, NESBusError

__version__ = "0.1.0"

__all__ = [
    "Cartridge",
    "CartridgeError",
    "CPU6502",
    "CPUError",
    "INESHeader",
    "MemoryBus",
    "Mirroring",
    "NES",
    "NESBus",
    "NESBusError",
    "StatusFlag",
    "__version__",
    "load_ines_file",
    "load_ines_rom",
]

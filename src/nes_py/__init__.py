"""Python NES emulator project package."""

from .version import get_build_info, get_version

__version__ = get_version()

_LAZY_EXPORTS = {
    "Button": ("input", "Button"),
    "Cartridge": ("cartridge", "Cartridge"),
    "CartridgeError": ("cartridge", "CartridgeError"),
    "Controller": ("input", "Controller"),
    "CPU6502": ("cpu", "CPU6502"),
    "CPUError": ("cpu", "CPUError"),
    "INESHeader": ("cartridge", "INESHeader"),
    "MemoryBus": ("cpu", "MemoryBus"),
    "Mirroring": ("cartridge", "Mirroring"),
    "NES": ("nes", "NES"),
    "NESBus": ("nes", "NESBus"),
    "NESBusError": ("nes", "NESBusError"),
    "PPU": ("ppu", "PPU"),
    "SCREEN_HEIGHT": ("ppu", "SCREEN_HEIGHT"),
    "SCREEN_WIDTH": ("ppu", "SCREEN_WIDTH"),
    "SmokeTestResult": ("debug", "SmokeTestResult"),
    "StatusFlag": ("cpu", "StatusFlag"),
    "disassemble_instruction": ("debug", "disassemble_instruction"),
    "format_cpu_trace": ("debug", "format_cpu_trace"),
    "load_ines_file": ("cartridge", "load_ines_file"),
    "load_ines_rom": ("cartridge", "load_ines_rom"),
    "run_smoke_test": ("debug", "run_smoke_test"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    module = __import__(f"{__name__}.{module_name}", fromlist=[attribute_name])
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


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
    "get_build_info",
    "get_version",
    "load_ines_file",
    "load_ines_rom",
    "run_smoke_test",
]

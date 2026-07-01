#!/usr/bin/env python3
"""NES system bus and execution loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "nes_py"

from .cartridge import Cartridge, load_ines_file, load_ines_rom
from .cpu import CPU6502
from .input import Controller
from .ppu import PPU

INTERNAL_RAM_SIZE = 2 * 1024
PPU_REGISTER_COUNT = 8
APU_IO_REGISTER_COUNT = 0x20


class NESBusError(ValueError):
    """Raised when the NES bus cannot satisfy an access."""


@dataclass
class HardwareRegisters:
    """Placeholder storage for hardware registers not implemented yet."""

    apu_io: bytearray = field(default_factory=lambda: bytearray(APU_IO_REGISTER_COUNT))
    expansion: bytearray = field(default_factory=lambda: bytearray(0x4000))


@dataclass
class NESBus:
    """CPU memory map for the NES."""

    cartridge: Cartridge
    ppu: PPU | None = None
    controller1: Controller = field(default_factory=Controller)
    controller2: Controller = field(default_factory=Controller)
    ram: bytearray = field(default_factory=lambda: bytearray(INTERNAL_RAM_SIZE))
    registers: HardwareRegisters = field(default_factory=HardwareRegisters)
    open_bus: int = 0

    def __post_init__(self) -> None:
        if self.ppu is None:
            self.ppu = PPU(self.cartridge)

    def read(self, address: int) -> int:
        """Read one byte from the CPU address space."""
        address &= 0xFFFF
        if 0x0000 <= address <= 0x1FFF:
            value = self.ram[address % INTERNAL_RAM_SIZE]
        elif 0x2000 <= address <= 0x3FFF:
            assert self.ppu is not None
            value = self.ppu.read_register(address - 0x2000)
        elif 0x4000 <= address <= 0x401F:
            if address == 0x4016:
                value = self.controller1.read()
            elif address == 0x4017:
                value = self.controller2.read()
            else:
                value = self.registers.apu_io[address - 0x4000]
        elif 0x4020 <= address <= 0x7FFF:
            value = self.registers.expansion[address - 0x4020]
        elif 0x8000 <= address <= 0xFFFF:
            value = self.cartridge.read_prg(address)
        else:
            raise NESBusError(f"Address 0x{address:04X} is outside the CPU address space")

        self.open_bus = value & 0xFF
        return self.open_bus

    def write(self, address: int, value: int) -> None:
        """Write one byte to the CPU address space."""
        address &= 0xFFFF
        value &= 0xFF
        self.open_bus = value

        if 0x0000 <= address <= 0x1FFF:
            self.ram[address % INTERNAL_RAM_SIZE] = value
        elif 0x2000 <= address <= 0x3FFF:
            assert self.ppu is not None
            self.ppu.write_register(address - 0x2000, value)
        elif 0x4000 <= address <= 0x401F:
            if address == 0x4016:
                self.controller1.write_strobe(value)
                self.controller2.write_strobe(value)
            self.registers.apu_io[address - 0x4000] = value
        elif 0x4020 <= address <= 0x7FFF:
            self.registers.expansion[address - 0x4020] = value
        elif 0x8000 <= address <= 0xFFFF:
            return
        else:
            raise NESBusError(f"Address 0x{address:04X} is outside the CPU address space")


@dataclass
class NES:
    """Minimal NES system wrapper around a cartridge, CPU bus, and CPU."""

    cartridge: Cartridge
    bus: NESBus = field(init=False)
    cpu: CPU6502 = field(init=False)
    ppu: PPU = field(init=False)
    controller1: Controller = field(default_factory=Controller)
    controller2: Controller = field(default_factory=Controller)
    cpu_cycles: int = 0
    ppu_cycles: int = 0
    frame_cycles: int = 0

    def __post_init__(self) -> None:
        self.ppu = PPU(self.cartridge)
        self.bus = NESBus(self.cartridge, self.ppu, self.controller1, self.controller2)
        self.cpu = CPU6502(self.bus)
        self.ppu.nmi_callback = self.cpu.nmi
        self.reset()

    @classmethod
    def from_ines_rom(cls, data: bytes) -> NES:
        """Create an NES instance from iNES ROM bytes."""
        return cls(load_ines_rom(data))

    @classmethod
    def from_ines_file(cls, path: str | Path) -> NES:
        """Create an NES instance from an iNES ROM file path."""
        return cls(load_ines_file(path))

    def reset(self) -> None:
        """Reset CPU state and cycle counters."""
        self.ppu.reset()
        self.cpu.reset()
        self.cpu_cycles = self.cpu.cycles
        self.ppu_cycles = self.cpu_cycles * 3
        self.frame_cycles = 0

    def step(self) -> int:
        """Execute one CPU instruction and advance placeholder timing."""
        cycles = self.cpu.step()
        self.cpu_cycles += cycles
        ppu_cycles = cycles * 3
        self.ppu.step(ppu_cycles)
        self.ppu_cycles += ppu_cycles
        self.frame_cycles = self.ppu.cycle
        return cycles

    def run(
        self,
        instruction_count: int,
        *,
        trace_callback: Callable[[CPU6502], None] | None = None,
    ) -> int:
        """Execute a fixed number of CPU instructions and return CPU cycles."""
        if instruction_count < 0:
            raise ValueError("instruction_count must be non-negative")

        total = 0
        for _ in range(instruction_count):
            if trace_callback is not None:
                trace_callback(self.cpu)
            total += self.step()
        return total


if __name__ == "__main__":
    from .cli import main

    raise SystemExit(main())

#!/usr/bin/env python3
"""NES system bus and execution loop."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "nes_py"

from .apu import APU
from .cartridge import Cartridge, load_ines_file, load_ines_rom
from .cpu import CPU6502
from .input import Controller
from .mmc5 import Mapper5
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
    dma_pending: bool = False
    apu: APU | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.ppu is None:
            self.ppu = PPU(self.cartridge)

    def read(self, address: int) -> int:
        """Read one byte from the CPU address space."""
        address &= 0xFFFF
        if address >= 0x8000:
            value = self.cartridge.prg_rom[
                self.cartridge.mapper.map_cpu_address(address)
            ]
        elif address <= 0x1FFF:
            value = self.ram[address & (INTERNAL_RAM_SIZE - 1)]
        elif 0x2000 <= address <= 0x3FFF:
            assert self.ppu is not None
            value = self.ppu.read_register(address - 0x2000)
        elif 0x4000 <= address <= 0x401F:
            if address == 0x4016:
                value = self.controller1.read()
            elif address == 0x4017:
                value = self.controller2.read()
            elif address == 0x4015 and self.apu is not None:
                # The internal status read does not drive the external data bus.
                return self.apu.read_status() | (self.open_bus & 0x20)
            elif self.apu is not None and address <= 0x4013:
                value = self.open_bus
            else:
                value = self.registers.apu_io[address - 0x4000]
        elif 0x4020 <= address <= 0x7FFF:
            header = self.cartridge.header
            if header.format_version == 1 or (
                address >= 0x6000 and header.prg_ram_size
            ):
                value = self.registers.expansion[address - 0x4020]
            else:
                value = self.open_bus
        else:
            raise NESBusError(
                f"Address 0x{address:04X} is outside the CPU address space"
            )

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
            if address == 0x4014:
                assert self.ppu is not None
                source = value << 8
                for offset in range(256):
                    self.ppu.write_register(4, self.read(source + offset))
                self.dma_pending = True
            elif address == 0x4016:
                self.controller1.write_strobe(value)
                self.controller2.write_strobe(value)
            elif self.apu is not None:
                self.apu.write_register(address, value)
            self.registers.apu_io[address - 0x4000] = value
        elif 0x4020 <= address <= 0x7FFF:
            header = self.cartridge.header
            if header.format_version == 1 or (
                address >= 0x6000 and header.prg_ram_size
            ):
                self.registers.expansion[address - 0x4020] = value
        elif 0x8000 <= address <= 0xFFFF:
            self.cartridge.write_prg(address, value)
        else:
            raise NESBusError(
                f"Address 0x{address:04X} is outside the CPU address space"
            )


@dataclass
class MMC5Bus(NESBus):
    """Route MMC5 registers and RAM/ROM windows without slowing other buses."""

    mmc5: Mapper5 = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        assert isinstance(self.cartridge.mapper, Mapper5)
        self.mmc5 = self.cartridge.mapper

    def read(self, address: int) -> int:
        address &= 0xFFFF
        if address >= 0x8000:
            mapper = self.mmc5
            if 0xFFFA <= address <= 0xFFFB:
                mapper.end_frame(clear_irq=True)
            # Mapper writes refresh these decoded windows. Read their backing
            # buffers here to avoid another Python call on each opcode fetch.
            storage, base = mapper._prg_pages[(address - 0x8000) >> 13]
            if storage is not None:
                self.open_bus = storage[base + (address & 0x1FFF)]
            return self.open_bus
        if address >= 0x4020:
            self.open_bus = self.mmc5.read_cpu(address, self.open_bus) & 0xFF
            return self.open_bus
        if address <= 0x1FFF:
            self.open_bus = self.ram[address & 0x7FF]
            return self.open_bus
        return super().read(address)

    def write(self, address: int, value: int) -> None:
        address &= 0xFFFF
        if address >= 0x4020:
            self.open_bus = value & 0xFF
            self.mmc5.write_cpu(address, self.open_bus)
        else:
            super().write(address, value)


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
    audio_sample_rate: int | None = field(default=None, kw_only=True)
    apu: APU | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.ppu = PPU(self.cartridge)
        if self.audio_sample_rate is not None:
            self.apu = APU(self.audio_sample_rate)
        mmc5 = isinstance(self.cartridge.mapper, Mapper5)
        bus_type = MMC5Bus if mmc5 else NESBus
        self.bus = bus_type(
            self.cartridge, self.ppu, self.controller1, self.controller2, apu=self.apu
        )
        self.cpu = CPU6502(self.bus)
        if self.apu is not None:
            self.apu.dmc_reader = self.bus.read
            self.apu.irq_callback = self._update_irq_line if mmc5 else self.cpu.set_irq_line
        if mmc5:
            self.cartridge.mapper.irq_callback = self._update_irq_line
        self.ppu.nmi_callback = self.cpu.nmi
        self.reset()

    @classmethod
    def from_ines_rom(cls, data: bytes, *, audio_sample_rate: int | None = None) -> NES:
        """Create an NES instance from iNES ROM bytes."""
        return cls(load_ines_rom(data), audio_sample_rate=audio_sample_rate)

    @classmethod
    def from_ines_file(
        cls, path: str | Path, *, audio_sample_rate: int | None = None
    ) -> NES:
        """Create an NES instance from an iNES ROM file path."""
        return cls(load_ines_file(path), audio_sample_rate=audio_sample_rate)

    def reset(self) -> None:
        """Reset CPU/PPU state and synchronize cycle counters."""
        if isinstance(self.cartridge.mapper, Mapper5):
            self.cartridge.mapper.reset()
        self.ppu.reset()
        if self.apu is not None:
            self.apu.reset()
        self.cpu.reset()
        self.bus.dma_pending = False
        self.ppu.step(self.cpu.cycles * 3)
        if self.apu is not None:
            self.apu.step(self.cpu.cycles)
        self.cpu_cycles = self.cpu.cycles
        self.ppu_cycles = self.cpu_cycles * 3
        self.frame_cycles = self.ppu.cycle

    def _update_irq_line(self, _asserted: bool) -> None:
        """APU and cartridge IRQ sources share one level-sensitive CPU input."""
        mapper = self.cartridge.mapper
        mapper_irq = isinstance(mapper, Mapper5) and mapper.irq_asserted
        apu_irq = self.apu is not None and self.apu.irq_asserted
        self.cpu.set_irq_line(mapper_irq or apu_irq)

    def step(self) -> int:
        """Execute an instruction/IRQ, accounting for OAM/DMC DMA and NMI cycles."""
        before = self.cpu.cycles
        apu = self.apu
        self.cpu.step()
        if self.bus.dma_pending:
            self.cpu.cycles += 513 + (self.cpu.cycles & 1)
            self.bus.dma_pending = False
        advanced = 0
        while advanced < self.cpu.cycles - before:
            cycles = self.cpu.cycles - before - advanced
            self.ppu.step(cycles * 3)
            advanced += cycles
            if apu is not None:
                apu.cpu_cycles = before + advanced
                if apu.cpu_cycles >= apu.next_cpu_event:
                    apu.flush()
                    self.cpu.cycles += apu.take_dma_stall_cycles()
        self.cpu_cycles = self.cpu.cycles
        self.ppu_cycles += advanced * 3
        self.frame_cycles = self.ppu.cycle
        return advanced

    def run_frame(
        self, *, trace_callback: Callable[[CPU6502], None] | None = None
    ) -> int:
        """Execute until the PPU completes one frame and return elapsed CPU cycles."""
        frame = self.ppu.frame
        cycles = 0
        while self.ppu.frame == frame:
            if trace_callback is not None:
                trace_callback(self.cpu)
            cycles += self.step()
        return cycles

    def run(
        self,
        instruction_count: int,
        *,
        trace_callback: Callable[[CPU6502], None] | None = None,
    ) -> int:
        """Execute a fixed number of instruction/IRQ steps and return CPU cycles."""
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

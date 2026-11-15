"""MMC5 memory, graphics registers, and scanline IRQs.

PPU fetch detection is driven by the scanline renderer. Expansion audio,
vertical-split rendering, and MMC5A features are not implemented here.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

PRG_PAGE = 0x2000
CHR_PAGE = 0x400
EMPTY_NAMETABLE = bytes(0x400)


@lru_cache(maxsize=64)
def _fill_nametable(tile: int, palette: int) -> bytes:
    return bytes([tile]) * 0x3C0 + bytes([palette]) * 0x40


class Mapper5:
    """MMC5 with explicit ExROM RAM-chip aliases and separate CHR contexts."""

    def __init__(self, prg_rom: bytes, chr_size: int, ram_size: int) -> None:
        self.prg_rom = prg_rom
        self.prg_ram = bytearray(ram_size)
        self.exram = bytearray(0x400)
        self.chr_size = chr_size
        self.irq_callback: Callable[[bool], None] | None = None
        self.irq_asserted = False
        self.reset()

    def reset(self) -> None:
        """Reset modeled control state without erasing cartridge memory."""
        self.prg_mode = self.chr_mode = 3
        self.protect1, self.protect2 = 1, 2
        self.exram_mode = 3
        self.nametable_select = self.fill_tile = self.fill_palette = 0
        self.ram_bank = 0
        self.prg_banks = [0xFF] * 4
        self.chr_sprite = [0] * 8
        self.chr_background = [0] * 4
        self.chr_upper = 0
        self.last_chr_background = False
        self.sprite_16 = self.rendering = False
        self.split_control = self.split_scroll = self.split_bank = 0
        self.irq_target = self.scanline_counter = 0
        self.in_frame = self.irq_pending = self.irq_enabled = False
        self.multiplier_a = self.multiplier_b = 0
        self.audio_registers = bytearray(0x16)
        self.unsupported_features: set[str] = set()
        self._update_prg()
        self._update_chr()
        self._update_irq()

    def _ram_base(self, bank: int) -> int | None:
        """Bits 0/1 address a chip; bit 2 selects a different SRAM chip."""
        bank &= 7
        size = len(self.prg_ram)
        if size == 0:
            return None
        if size == 0x4000:  # ETROM: two 8 KiB chips, not one 16 KiB chip.
            return (bank >> 2) * PRG_PAGE
        if size in (0x2000, 0x8000):
            return None if bank & 4 else (bank * PRG_PAGE) % size
        return (bank * PRG_PAGE) % size

    def _update_prg(self) -> None:
        mode, banks = self.prg_mode, self.prg_banks
        if mode == 0:
            slots = [(True, (banks[3] & 0x7C) + index) for index in range(4)]
        elif mode == 1:
            slots = [
                (bool(banks[1] & 0x80), (banks[1] & 0x7E) + index) for index in range(2)
            ]
            slots += [(True, (banks[3] & 0x7E) + index) for index in range(2)]
        elif mode == 2:
            slots = [
                (bool(banks[1] & 0x80), (banks[1] & 0x7E) + index) for index in range(2)
            ]
            slots += [(bool(banks[2] & 0x80), banks[2] & 0x7F), (True, banks[3] & 0x7F)]
        else:
            slots = [
                (bool(value & 0x80) or index == 3, value & 0x7F)
                for index, value in enumerate(banks)
            ]
        self._prg_pages: list[tuple[bytes | bytearray | None, int]] = []
        for is_rom, bank in slots:
            if is_rom:
                self._prg_pages.append(
                    (self.prg_rom, (bank * PRG_PAGE) % len(self.prg_rom))
                )
            else:
                base = self._ram_base(bank)
                self._prg_pages.append(
                    (None if base is None else self.prg_ram, base or 0)
                )
        self._ram_page = self._ram_base(self.ram_bank)

    def _update_chr(self) -> None:
        span = 1 << (3 - self.chr_mode)
        self._chr_sprite_pages = tuple(
            (
                (
                    (self.chr_sprite[page | (span - 1)] & ~(span - 1))
                    + (page & (span - 1))
                )
                * CHR_PAGE
            )
            % self.chr_size
            for page in range(8)
        )
        self._chr_background_pages = tuple(
            (
                (
                    (self.chr_background[(page | (span - 1)) & 3] & ~(span - 1))
                    + (page & (span - 1))
                )
                * CHR_PAGE
            )
            % self.chr_size
            for page in range(8)
        )

    def map_cpu_address(self, address: int) -> int:
        """Map a ROM page; RAM and registers use read_cpu/write_cpu instead."""
        if not 0x8000 <= address <= 0xFFFF:
            raise ValueError(f"MMC5 address 0x{address:04X} is outside PRG windows")
        storage, base = self._prg_pages[(address - 0x8000) >> 13]
        if storage is not self.prg_rom:
            raise ValueError(f"MMC5 address 0x{address:04X} is not mapped to ROM")
        return base + (address & 0x1FFF)

    def map_ppu_address(self, address: int) -> int:
        """CPU PPUDATA accesses follow the last written CHR register group."""
        pages = (
            self._chr_background_pages
            if self.last_chr_background
            else self._chr_sprite_pages
        )
        return pages[(address & 0x1FFF) >> 10] + (address & 0x3FF)

    def map_render_address(self, address: int, *, background: bool) -> int:
        pages = (
            self._chr_background_pages
            if background and self.sprite_16
            else self._chr_sprite_pages
        )
        return pages[(address & 0x1FFF) >> 10] + (address & 0x3FF)

    def render_chr_pages(self, *, background: bool) -> tuple[int, ...]:
        return (
            self._chr_background_pages
            if background and self.sprite_16
            else self._chr_sprite_pages
        )

    def read_cpu(self, address: int, open_bus: int = 0) -> int:
        if address >= 0x8000:
            if address in (0xFFFA, 0xFFFB):
                self.end_frame(clear_irq=True)
            storage, base = self._prg_pages[(address - 0x8000) >> 13]
            return open_bus if storage is None else storage[base + (address & 0x1FFF)]
        if address >= 0x6000:
            return (
                open_bus
                if self._ram_page is None
                else self.prg_ram[self._ram_page + (address & 0x1FFF)]
            )
        if address >= 0x5C00:
            return self.exram[address & 0x3FF] if self.exram_mode >= 2 else open_bus
        if address == 0x5204:
            status = (
                (open_bus & 0x3E)
                | (0x40 if self.in_frame else 0)
                | (0x80 if self.irq_pending else 0)
            )
            self.irq_pending = False
            self._update_irq()
            return status
        if address == 0x5205:
            return (self.multiplier_a * self.multiplier_b) & 0xFF
        if address == 0x5206:
            return (self.multiplier_a * self.multiplier_b) >> 8
        if address in (0x5010, 0x5015):
            return 0  # Expansion audio is explicitly outside this pilot.
        return open_bus

    def write_cpu(self, address: int, value: int) -> None:
        value &= 0xFF
        if address >= 0x6000:
            if self.protect1 != 2 or self.protect2 != 1:
                return
            if address >= 0x8000:
                storage, base = self._prg_pages[(address - 0x8000) >> 13]
                if storage is self.prg_ram:
                    storage[base + (address & 0x1FFF)] = value
            elif self._ram_page is not None:
                self.prg_ram[self._ram_page + (address & 0x1FFF)] = value
        elif address >= 0x5C00:
            if self.exram_mode == 2 or (self.exram_mode < 2 and self.in_frame):
                self.exram[address & 0x3FF] = value
            elif self.exram_mode < 2:
                # Blanking writes in graphics modes do not store CPU data.
                self.exram[address & 0x3FF] = 0
        elif 0x5000 <= address <= 0x5015:
            self.audio_registers[address - 0x5000] = value
            if (
                (address == 0x5015 and value & 3)
                or (address == 0x5011 and value)
                or (address == 0x5010 and value & 0x81)
            ):
                self.unsupported_features.add("expansion audio")
        elif address == 0x5100:
            self.prg_mode = value & 3
            self._update_prg()
        elif address == 0x5101:
            self.chr_mode = value & 3
            self._update_chr()
        elif address == 0x5102:
            self.protect1 = value & 3
        elif address == 0x5103:
            self.protect2 = value & 3
        elif address == 0x5104:
            self.exram_mode = value & 3
        elif address == 0x5105:
            self.nametable_select = value
        elif address == 0x5106:
            self.fill_tile = value
        elif address == 0x5107:
            self.fill_palette = (value & 3) * 0x55
        elif address == 0x5113:
            self.ram_bank = value & 7
            self._update_prg()
        elif 0x5114 <= address <= 0x5117:
            self.prg_banks[address - 0x5114] = value
            self._update_prg()
        elif 0x5120 <= address <= 0x512B:
            shift = 3 - self.chr_mode
            latched = (((value | (self.chr_upper << 8)) << shift) & 0x3FF) | (value & 1)
            if address <= 0x5127:
                self.chr_sprite[address - 0x5120] = latched
                self.last_chr_background = False
            else:
                self.chr_background[address - 0x5128] = latched
                self.last_chr_background = True
            self._update_chr()
        elif address == 0x5130:
            self.chr_upper = value & 3
        elif address == 0x5200:
            self.split_control = value
            if value & 0x80:
                self.unsupported_features.add("vertical split")
        elif address == 0x5201:
            self.split_scroll = value
        elif address == 0x5202:
            self.split_bank = value
        elif address == 0x5203:
            self.irq_target = value
        elif address == 0x5204:
            self.irq_enabled = bool(value & 0x80)
            self._update_irq()
        elif address == 0x5205:
            self.multiplier_a = value
        elif address == 0x5206:
            self.multiplier_b = value

    def read_nametable(self, address: int, ciram: bytearray) -> int:
        offset = (address - 0x2000) & 0xFFF
        source = (self.nametable_select >> ((offset >> 10) * 2)) & 3
        index = offset & 0x3FF
        if source < 2:
            return ciram[source * 0x400 + index]
        if source == 2:
            return self.exram[index] if self.exram_mode < 2 else 0
        return self.fill_palette if index >= 0x3C0 else self.fill_tile

    def nametable_page(
        self, table: int, ciram: bytearray
    ) -> tuple[bytes | bytearray, int]:
        """Expose a source page for batched background reads without stale copies."""
        source = (self.nametable_select >> (table * 2)) & 3
        if source < 2:
            return ciram, source * 0x400
        if source == 2:
            return (self.exram if self.exram_mode < 2 else EMPTY_NAMETABLE), 0
        return _fill_nametable(self.fill_tile, self.fill_palette), 0

    def write_nametable(self, address: int, value: int, ciram: bytearray) -> None:
        offset = (address - 0x2000) & 0xFFF
        source = (self.nametable_select >> ((offset >> 10) * 2)) & 3
        index = offset & 0x3FF
        if source < 2:
            ciram[source * 0x400 + index] = value
        elif source == 2 and self.exram_mode < 2:
            self.exram[index] = value

    def set_ppu_mask(self, value: int) -> None:
        rendering = bool(value & 0x18)
        if rendering != self.rendering:
            self.end_frame(clear_irq=rendering)
        self.rendering = rendering

    def clock_scanline(self) -> None:
        """Coarse substitute for the hardware's repeated-fetch detector."""
        if not self.rendering:
            self.end_frame()
            return
        if not self.in_frame:
            self.in_frame = True
            self.scanline_counter = 0
            self.irq_pending = False
        else:
            self.scanline_counter = (self.scanline_counter + 1) & 0xFF
            if self.irq_target and self.scanline_counter == self.irq_target:
                self.irq_pending = True
        self._update_irq()

    def end_frame(self, *, clear_irq: bool = False) -> None:
        self.in_frame = False
        self.scanline_counter = 0
        if clear_irq:
            self.irq_pending = False
        self._update_irq()

    def _update_irq(self) -> None:
        asserted = self.irq_enabled and self.irq_pending
        if asserted != self.irq_asserted:
            self.irq_asserted = asserted
            if self.irq_callback is not None:
                self.irq_callback(asserted)

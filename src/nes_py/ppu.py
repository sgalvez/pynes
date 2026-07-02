"""PPU foundation and background framebuffer rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .cartridge import Cartridge

SCREEN_WIDTH = 256
SCREEN_HEIGHT = 240
FRAMEBUFFER_SIZE = SCREEN_WIDTH * SCREEN_HEIGHT
NAMETABLE_SIZE = 2 * 1024
PALETTE_SIZE = 32
OAM_SIZE = 256
PPU_CYCLES_PER_SCANLINE = 341
PPU_SCANLINES_PER_FRAME = 262
VBLANK_START_SCANLINE = 241
PPU_CYCLES_PER_FRAME = PPU_CYCLES_PER_SCANLINE * PPU_SCANLINES_PER_FRAME
VBLANK_START_CYCLE = PPU_CYCLES_PER_SCANLINE * VBLANK_START_SCANLINE

RGB = tuple[int, int, int]

SYSTEM_PALETTE: tuple[RGB, ...] = (
    (84, 84, 84),
    (0, 30, 116),
    (8, 16, 144),
    (48, 0, 136),
    (68, 0, 100),
    (92, 0, 48),
    (84, 4, 0),
    (60, 24, 0),
    (32, 42, 0),
    (8, 58, 0),
    (0, 64, 0),
    (0, 60, 0),
    (0, 50, 60),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (152, 150, 152),
    (8, 76, 196),
    (48, 50, 236),
    (92, 30, 228),
    (136, 20, 176),
    (160, 20, 100),
    (152, 34, 32),
    (120, 60, 0),
    (84, 90, 0),
    (40, 114, 0),
    (8, 124, 0),
    (0, 118, 40),
    (0, 102, 120),
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 0),
    (236, 238, 236),
    (76, 154, 236),
    (120, 124, 236),
    (176, 98, 236),
    (228, 84, 236),
    (236, 88, 180),
    (236, 106, 100),
    (212, 136, 32),
    (160, 170, 0),
    (116, 196, 0),
    (76, 208, 32),
    (56, 204, 108),
    (56, 180, 204),
    (60, 60, 60),
    (0, 0, 0),
    (0, 0, 0),
    (236, 238, 236),
    (168, 204, 236),
    (188, 188, 236),
    (212, 178, 236),
    (236, 174, 236),
    (236, 174, 212),
    (236, 180, 176),
    (228, 196, 144),
    (204, 210, 120),
    (180, 222, 120),
    (168, 226, 144),
    (152, 226, 180),
    (160, 214, 228),
    (160, 162, 160),
    (0, 0, 0),
    (0, 0, 0),
)


@dataclass
class PPU:
    """Small but functional NES PPU foundation."""

    cartridge: Cartridge
    nmi_callback: Callable[[], None] | None = None
    ctrl: int = 0
    mask: int = 0
    status: int = 0
    oamaddr: int = 0
    oam: bytearray = field(default_factory=lambda: bytearray(OAM_SIZE))
    nametable: bytearray = field(default_factory=lambda: bytearray(NAMETABLE_SIZE))
    palette: bytearray = field(default_factory=lambda: bytearray(PALETTE_SIZE))
    framebuffer: list[RGB] = field(
        default_factory=lambda: [(0, 0, 0)] * FRAMEBUFFER_SIZE
    )
    framebuffer_bytes: bytearray = field(
        default_factory=lambda: bytearray(FRAMEBUFFER_SIZE * 3)
    )
    vram_address: int = 0
    scroll_x: int = 0
    scroll_y: int = 0
    _address_latch_high: bool = True
    _scroll_latch_x: bool = True
    cycle: int = 0
    frame: int = 0

    def reset(self) -> None:
        """Reset PPU registers and timing state."""
        self.ctrl = 0
        self.mask = 0
        self.status = 0
        self.oamaddr = 0
        self.vram_address = 0
        self.scroll_x = 0
        self.scroll_y = 0
        self._address_latch_high = True
        self._scroll_latch_x = True
        self.cycle = 0
        self.frame = 0

    @property
    def vblank(self) -> bool:
        return bool(self.status & 0x80)

    @property
    def nmi_enabled(self) -> bool:
        return bool(self.ctrl & 0x80)

    def read_register(self, register: int) -> int:
        """Read a CPU-visible PPU register."""
        register &= 0x07
        if register == 2:
            value = self.status
            self.status &= 0x7F
            self._address_latch_high = True
            self._scroll_latch_x = True
            return value
        if register == 4:
            return self.oam[self.oamaddr]
        if register == 7:
            value = self.read(self.vram_address)
            self.vram_address = (self.vram_address + self._vram_increment()) & 0x3FFF
            return value
        return 0

    def write_register(self, register: int, value: int) -> None:
        """Write a CPU-visible PPU register."""
        register &= 0x07
        value &= 0xFF
        if register == 0:
            self.ctrl = value
            if self.vblank and self.nmi_enabled:
                self._trigger_nmi()
        elif register == 1:
            self.mask = value
        elif register == 3:
            self.oamaddr = value
        elif register == 4:
            self.oam[self.oamaddr] = value
            self.oamaddr = (self.oamaddr + 1) & 0xFF
        elif register == 5:
            if self._scroll_latch_x:
                self.scroll_x = value
            else:
                self.scroll_y = value
            self._scroll_latch_x = not self._scroll_latch_x
        elif register == 6:
            if self._address_latch_high:
                self.vram_address = (value & 0x3F) << 8
            else:
                self.vram_address = (self.vram_address & 0x3F00) | value
            self._address_latch_high = not self._address_latch_high
        elif register == 7:
            self.write(self.vram_address, value)
            self.vram_address = (self.vram_address + self._vram_increment()) & 0x3FFF

    def read(self, address: int) -> int:
        """Read from PPU address space."""
        address &= 0x3FFF
        if 0x0000 <= address <= 0x1FFF:
            return self.cartridge.read_chr(address)
        if 0x2000 <= address <= 0x3EFF:
            return self.nametable[self._nametable_index(address)]
        return self.palette[self._palette_index(address)]

    def write(self, address: int, value: int) -> None:
        """Write to PPU address space."""
        address &= 0x3FFF
        value &= 0xFF
        if 0x0000 <= address <= 0x1FFF:
            self.cartridge.write_chr(address, value)
        elif 0x2000 <= address <= 0x3EFF:
            self.nametable[self._nametable_index(address)] = value
        else:
            self.palette[self._palette_index(address)] = value & 0x3F

    def step(self, cycles: int) -> None:
        """Advance PPU timing by a number of PPU cycles."""
        if cycles <= 0:
            return

        old_cycle = self.cycle
        new_cycle = old_cycle + cycles
        if old_cycle < VBLANK_START_CYCLE <= new_cycle:
            self.enter_vblank()

        while new_cycle >= PPU_CYCLES_PER_FRAME:
            new_cycle -= PPU_CYCLES_PER_FRAME
            self.frame += 1
            self.status &= 0x7F
            self.render_background()
            if new_cycle >= VBLANK_START_CYCLE:
                self.enter_vblank()

        self.cycle = new_cycle

    def enter_vblank(self) -> None:
        """Set vblank and notify the CPU if NMI output is enabled."""
        was_vblank = self.vblank
        self.status |= 0x80
        if not was_vblank and self.nmi_enabled:
            self._trigger_nmi()

    def render_background(self) -> list[RGB]:
        """Render nametable 0 background tiles into the framebuffer."""
        pattern_base = 0x1000 if self.ctrl & 0x10 else 0x0000
        framebuffer = self.framebuffer
        framebuffer_bytes = self.framebuffer_bytes
        nametable = self.nametable
        palette = self.palette
        system_palette = SYSTEM_PALETTE
        cartridge = self.cartridge
        for tile_y in range(30):
            for tile_x in range(32):
                tile_index = nametable[(tile_y * 32) + tile_x]
                palette_base = self._background_palette_base(tile_x, tile_y)
                for row in range(8):
                    low = cartridge.read_chr(pattern_base + tile_index * 16 + row)
                    high = cartridge.read_chr(pattern_base + tile_index * 16 + row + 8)
                    y = tile_y * 8 + row
                    pixel_offset = y * SCREEN_WIDTH + tile_x * 8
                    for col in range(8):
                        bit = 7 - col
                        color_bits = ((high >> bit) & 0x01) << 1 | ((low >> bit) & 0x01)
                        palette_address = palette_base + color_bits
                        color_index = palette[palette_address] & 0x3F
                        color = system_palette[color_index]
                        framebuffer[pixel_offset + col] = color
                        byte_offset = (pixel_offset + col) * 3
                        framebuffer_bytes[byte_offset] = color[0]
                        framebuffer_bytes[byte_offset + 1] = color[1]
                        framebuffer_bytes[byte_offset + 2] = color[2]
        return self.framebuffer

    def _background_palette_base(self, tile_x: int, tile_y: int) -> int:
        attribute_index = 0x03C0 + (tile_y // 4) * 8 + (tile_x // 4)
        attribute = self.nametable[attribute_index]
        shift = ((tile_y % 4) // 2) * 4 + ((tile_x % 4) // 2) * 2
        palette_number = (attribute >> shift) & 0x03
        return palette_number * 4

    def _vram_increment(self) -> int:
        return 32 if self.ctrl & 0x04 else 1

    def _nametable_index(self, address: int) -> int:
        return (address - 0x2000) % NAMETABLE_SIZE

    def _palette_index(self, address: int) -> int:
        index = (address - 0x3F00) % PALETTE_SIZE
        if index in (0x10, 0x14, 0x18, 0x1C):
            index -= 0x10
        return index

    def _trigger_nmi(self) -> None:
        if self.nmi_callback is not None:
            self.nmi_callback()

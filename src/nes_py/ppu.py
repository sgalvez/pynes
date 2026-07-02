"""PPU foundation and background framebuffer rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .cartridge import Cartridge, Mirroring

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
    background_framebuffer: list[RGB] = field(
        default_factory=lambda: [(0, 0, 0)] * FRAMEBUFFER_SIZE
    )
    background_framebuffer_bytes: bytearray = field(
        default_factory=lambda: bytearray(FRAMEBUFFER_SIZE * 3)
    )
    background_dirty: bool = True
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
        self.background_dirty = True

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
            self.background_dirty = True
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
            self.background_dirty = True
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
            self.background_dirty = True
        elif 0x2000 <= address <= 0x3EFF:
            self.nametable[self._nametable_index(address)] = value
            self.background_dirty = True
        else:
            self.palette[self._palette_index(address)] = value & 0x3F
            self.background_dirty = True

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
            self.render_frame()
            if new_cycle >= VBLANK_START_CYCLE:
                self.enter_vblank()

        self.cycle = new_cycle

    def enter_vblank(self) -> None:
        """Set vblank and notify the CPU if NMI output is enabled."""
        was_vblank = self.vblank
        self.status |= 0x80
        if not was_vblank and self.nmi_enabled:
            self._trigger_nmi()

    def render_frame(self) -> list[RGB]:
        """Render the current background and sprites into the framebuffer."""
        if self.background_dirty:
            self.render_background()
        else:
            self.framebuffer[:] = self.background_framebuffer
            self.framebuffer_bytes[:] = self.background_framebuffer_bytes
        self.render_sprites()
        return self.framebuffer

    def render_background(self) -> list[RGB]:
        """Render the scroll-selected background into the framebuffer."""
        pattern_base = 0x1000 if self.ctrl & 0x10 else 0x0000
        base_nametable = self.ctrl & 0x03
        base_tile_x = (base_nametable & 0x01) * 32
        base_tile_y = ((base_nametable >> 1) & 0x01) * 30
        coarse_scroll_x = self.scroll_x // 8
        coarse_scroll_y = self.scroll_y // 8
        fine_scroll_x = self.scroll_x & 0x07
        fine_scroll_y = self.scroll_y & 0x07

        for screen_tile_y in range(31):
            world_tile_y = (base_tile_y + coarse_scroll_y + screen_tile_y) % 60
            nametable_y = world_tile_y // 30
            tile_y = world_tile_y % 30
            screen_y = screen_tile_y * 8 - fine_scroll_y
            for screen_tile_x in range(33):
                world_tile_x = (base_tile_x + coarse_scroll_x + screen_tile_x) % 64
                nametable_x = world_tile_x // 32
                tile_x = world_tile_x % 32
                nametable_base = 0x2000 + (nametable_y * 2 + nametable_x) * 0x0400
                self._render_background_tile(
                    pattern_base=pattern_base,
                    nametable_base=nametable_base,
                    tile_x=tile_x,
                    tile_y=tile_y,
                    screen_x=screen_tile_x * 8 - fine_scroll_x,
                    screen_y=screen_y,
                )
        self.background_framebuffer[:] = self.framebuffer
        self.background_framebuffer_bytes[:] = self.framebuffer_bytes
        self.background_dirty = False
        return self.framebuffer

    def render_sprites(self) -> list[RGB]:
        """Render 8x8 sprites from OAM over the current background."""
        if not self.mask & 0x10:
            return self.framebuffer

        pattern_base = 0x1000 if self.ctrl & 0x08 else 0x0000
        for sprite_index in range(63, -1, -1):
            offset = sprite_index * 4
            sprite_y = self.oam[offset] + 1
            tile_index = self.oam[offset + 1]
            attributes = self.oam[offset + 2]
            sprite_x = self.oam[offset + 3]
            palette_base = 0x10 + (attributes & 0x03) * 4
            flip_horizontal = bool(attributes & 0x40)
            flip_vertical = bool(attributes & 0x80)
            behind_background = bool(attributes & 0x20)

            for row in range(8):
                source_row = 7 - row if flip_vertical else row
                low = self.cartridge.read_chr(pattern_base + tile_index * 16 + source_row)
                high = self.cartridge.read_chr(pattern_base + tile_index * 16 + source_row + 8)
                y = sprite_y + row
                if y < 0 or y >= SCREEN_HEIGHT:
                    continue
                for col in range(8):
                    source_col = col if flip_horizontal else 7 - col
                    color_bits = ((high >> source_col) & 0x01) << 1 | ((low >> source_col) & 0x01)
                    if color_bits == 0:
                        continue
                    x = sprite_x + col
                    if x < 0 or x >= SCREEN_WIDTH:
                        continue
                    pixel_index = y * SCREEN_WIDTH + x
                    if behind_background and self.framebuffer[pixel_index] != SYSTEM_PALETTE[self.palette[0] & 0x3F]:
                        continue
                    color_index = self.palette[palette_base + color_bits] & 0x3F
                    self._set_pixel(pixel_index, SYSTEM_PALETTE[color_index])
        return self.framebuffer

    def _background_palette_base(self, nametable_base: int, tile_x: int, tile_y: int) -> int:
        attribute_address = nametable_base + 0x03C0 + (tile_y // 4) * 8 + (tile_x // 4)
        attribute = self.nametable[self._nametable_index(attribute_address)]
        shift = ((tile_y % 4) // 2) * 4 + ((tile_x % 4) // 2) * 2
        palette_number = (attribute >> shift) & 0x03
        return palette_number * 4

    def _render_background_tile(
        self,
        *,
        pattern_base: int,
        nametable_base: int,
        tile_x: int,
        tile_y: int,
        screen_x: int,
        screen_y: int,
    ) -> None:
        tile_index = self.nametable[self._nametable_index(nametable_base + tile_y * 32 + tile_x)]
        palette_base = self._background_palette_base(nametable_base, tile_x, tile_y)
        framebuffer = self.framebuffer
        framebuffer_bytes = self.framebuffer_bytes
        palette = self.palette
        system_palette = SYSTEM_PALETTE
        cartridge = self.cartridge
        for row in range(8):
            y = screen_y + row
            if y < 0 or y >= SCREEN_HEIGHT:
                continue
            low = cartridge.read_chr(pattern_base + tile_index * 16 + row)
            high = cartridge.read_chr(pattern_base + tile_index * 16 + row + 8)
            pixel_offset = y * SCREEN_WIDTH + screen_x
            for col in range(8):
                x = screen_x + col
                if x < 0 or x >= SCREEN_WIDTH:
                    continue
                bit = 7 - col
                color_bits = ((high >> bit) & 0x01) << 1 | ((low >> bit) & 0x01)
                color = system_palette[palette[palette_base + color_bits] & 0x3F]
                output_index = pixel_offset + col
                framebuffer[output_index] = color
                byte_offset = output_index * 3
                framebuffer_bytes[byte_offset] = color[0]
                framebuffer_bytes[byte_offset + 1] = color[1]
                framebuffer_bytes[byte_offset + 2] = color[2]

    def _vram_increment(self) -> int:
        return 32 if self.ctrl & 0x04 else 1

    def _nametable_index(self, address: int) -> int:
        index = (address - 0x2000) % 0x1000
        table = index // 0x0400
        offset = index % 0x0400
        if self.cartridge.mirroring == Mirroring.VERTICAL:
            mirrored_table = table % 2
        elif self.cartridge.mirroring == Mirroring.HORIZONTAL:
            mirrored_table = 0 if table in (0, 1) else 1
        else:
            mirrored_table = table % 2
        return mirrored_table * 0x0400 + offset

    def _palette_index(self, address: int) -> int:
        index = (address - 0x3F00) % PALETTE_SIZE
        if index in (0x10, 0x14, 0x18, 0x1C):
            index -= 0x10
        return index

    def _set_pixel(self, pixel_index: int, color: RGB) -> None:
        self.framebuffer[pixel_index] = color
        byte_offset = pixel_index * 3
        self.framebuffer_bytes[byte_offset] = color[0]
        self.framebuffer_bytes[byte_offset + 1] = color[1]
        self.framebuffer_bytes[byte_offset + 2] = color[2]

    def _trigger_nmi(self) -> None:
        if self.nmi_callback is not None:
            self.nmi_callback()

"""Scanline-based PPU with background and sprite framebuffer rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

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
PRE_RENDER_CYCLE = PPU_CYCLES_PER_SCANLINE * (PPU_SCANLINES_PER_FRAME - 1)

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


RGB_TABLES = tuple(
    bytes(SYSTEM_PALETTE[index][channel] if index < 64 else 0 for index in range(256))
    for channel in range(3)
)
NAMETABLE_PAGES = {
    Mirroring.HORIZONTAL: (0, 0, 1024, 1024),
    Mirroring.VERTICAL: (0, 1024, 0, 1024),
    Mirroring.FOUR_SCREEN: (0, 1024, 2048, 3072),
    Mirroring.SINGLE_SCREEN_LOWER: (0, 0, 0, 0),
    Mirroring.SINGLE_SCREEN_UPPER: (1024, 1024, 1024, 1024),
}


@lru_cache(maxsize=8192)
def _pattern_row(low: int, high: int) -> bytes:
    return bytes(
        ((low >> bit) & 1) | (((high >> bit) & 1) << 1) for bit in range(7, -1, -1)
    )


@lru_cache(maxsize=8192)
def _background_row(low: int, high: int, colors: bytes) -> tuple[bytes, bytes]:
    """Cache decoded transparency and palette colors by their actual bytes."""
    row = _pattern_row(low, high)
    return row, row.translate(colors)


@lru_cache(maxsize=512)
def _attribute_palettes(attributes: bytes, shift: int) -> bytes:
    palettes = bytearray()
    for attribute in attributes:
        value = attribute >> shift
        palettes.extend((value & 3, value & 3, (value >> 2) & 3, (value >> 2) & 3))
    return bytes(palettes)


@lru_cache(maxsize=512)
def _background_strip(
    low: bytes, high: bytes, palettes: bytes, tables: tuple[bytes, ...]
) -> tuple[bytes, bytes]:
    """Reuse composed tile strips only when pattern and palette bytes match."""
    raw_rows, color_rows = [], []
    for lo, hi, palette in zip(low, high, palettes):
        raw, colors = _background_row(lo, hi, tables[palette])
        raw_rows.append(raw)
        color_rows.append(colors)
    return b"".join(raw_rows), b"".join(color_rows)


@lru_cache(maxsize=8192)
def _sprite_pixels(low: int, high: int, flipped: bool) -> tuple[tuple[int, int], ...]:
    row = _pattern_row(low, high)
    if flipped:
        row = row[::-1]
    return tuple((column, color) for column, color in enumerate(row) if color)


@lru_cache(maxsize=64)
def _sprite_scanlines(oam: bytes, height: int) -> tuple[tuple[int, ...], ...]:
    """Evaluate OAM once per content change, retaining eight sprites plus overflow."""
    rows: list[list[int]] = [[] for _ in range(SCREEN_HEIGHT)]
    for index in range(0, OAM_SIZE, 4):
        top = oam[index] + 1
        for y in range(top, min(top + height, SCREEN_HEIGHT)):
            if len(rows[y]) < 9:
                rows[y].append(index)
    return tuple(tuple(row) for row in rows)


@lru_cache(maxsize=128)
def _palette_tables(palette: bytes, greyscale: bool) -> tuple[bytes, ...]:
    mask = 0x30 if greyscale else 0x3F
    backdrop = palette[0] & mask
    return tuple(
        bytes((backdrop, *(palette[base + color] & mask for color in (1, 2, 3))))
        + bytes(252)
        for base in range(0, 32, 4)
    )


def _increment_y(address: int) -> int:
    if address & 0x7000 != 0x7000:
        return address + 0x1000
    address &= ~0x7000
    coarse_y = (address >> 5) & 31
    if coarse_y == 29:
        coarse_y = 0
        address ^= 0x0800
    elif coarse_y == 31:
        coarse_y = 0
    else:
        coarse_y += 1
    return (address & ~0x03E0) | (coarse_y << 5)


@dataclass
class PPU:
    """NES PPU with scanline composition and coarse hardware timing."""

    cartridge: Cartridge
    nmi_callback: Callable[[], None] | None = None
    ctrl: int = 0
    mask: int = 0
    status: int = 0
    oamaddr: int = 0
    oam: bytearray = field(default_factory=lambda: bytearray(OAM_SIZE))
    nametable: bytearray = field(default_factory=lambda: bytearray(NAMETABLE_SIZE))
    palette: bytearray = field(default_factory=lambda: bytearray(PALETTE_SIZE))
    vram_address: int = 0
    scroll_x: int = 0
    scroll_y: int = 0
    cycle: int = 0
    frame: int = 0
    framebuffer_rgb: bytearray = field(
        default_factory=lambda: bytearray(FRAMEBUFFER_SIZE * 3), init=False, repr=False
    )
    _pixels: bytearray = field(
        default_factory=lambda: bytearray([0x0F]) * FRAMEBUFFER_SIZE,
        init=False,
        repr=False,
    )
    _display_pixels: bytes = field(
        default_factory=lambda: bytes([0x0F]) * FRAMEBUFFER_SIZE,
        init=False,
        repr=False,
    )
    _framebuffer: list[RGB] | None = field(default=None, init=False, repr=False)
    _temp_address: int = 0
    _fine_x: int = 0
    _write_toggle: bool = False
    _read_buffer: int = 0
    _next_event_cycle: int = 1
    _sprite_zero_hit_cycle: int = PPU_CYCLES_PER_FRAME + 1

    def __post_init__(self) -> None:
        if self.cartridge.mirroring is Mirroring.FOUR_SCREEN:
            self.nametable.extend(bytes(4 * 1024 - len(self.nametable)))

    @property
    def framebuffer_bytes(self) -> bytearray:
        """Compatibility name for the reusable packed RGB display buffer."""
        return self.framebuffer_rgb

    @property
    def framebuffer(self) -> list[RGB]:
        """Return the RGB pixel list, materializing it only when requested."""
        if self._framebuffer is None:
            self._framebuffer = [
                SYSTEM_PALETTE[index] for index in self._display_pixels
            ]
        return self._framebuffer

    def reset(self) -> None:
        """Reset registers, timing, and the displayed image."""
        self.ctrl = self.mask = self.status = self.oamaddr = 0
        self.vram_address = self._temp_address = self._fine_x = 0
        self.scroll_x = self.scroll_y = 0
        self._write_toggle = False
        self._read_buffer = 0
        self.cycle = self.frame = 0
        self._next_event_cycle = 1
        self._sprite_zero_hit_cycle = PPU_CYCLES_PER_FRAME + 1
        self._pixels[:] = bytes([0x0F]) * FRAMEBUFFER_SIZE
        self._display_pixels = bytes(self._pixels)
        self.framebuffer_rgb[:] = bytes(FRAMEBUFFER_SIZE * 3)
        self._framebuffer = None

    @property
    def vblank(self) -> bool:
        return bool(self.status & 0x80)

    @property
    def nmi_enabled(self) -> bool:
        return bool(self.ctrl & 0x80)

    def read_register(self, register: int) -> int:
        """Read a CPU-visible PPU register."""
        register &= 7
        if register == 2:
            value = self.status
            self.status &= 0x7F
            self._write_toggle = False
            return value
        if register == 4:
            return self.oam[self.oamaddr]
        if register == 7:
            address = self.vram_address & 0x3FFF
            value = self._read_buffer
            self._read_buffer = self.read(address)
            if address >= 0x3F00:
                value = self._read_buffer
                self._read_buffer = self.read(address - 0x1000)
            self.vram_address = (self.vram_address + self._vram_increment()) & 0x7FFF
            return value
        return 0

    def write_register(self, register: int, value: int) -> None:
        """Write a CPU-visible PPU register, including shared scroll/address state."""
        register &= 7
        value &= 0xFF
        if register == 0:
            was_enabled = self.nmi_enabled
            self.ctrl = value
            self._temp_address = (self._temp_address & ~0x0C00) | ((value & 3) << 10)
            if self.vblank and self.nmi_enabled and not was_enabled:
                self._trigger_nmi()
        elif register == 1:
            self.mask = value
        elif register == 3:
            self.oamaddr = value
        elif register == 4:
            self.oam[self.oamaddr] = value
            self.oamaddr = (self.oamaddr + 1) & 0xFF
        elif register == 5:
            if not self._write_toggle:
                self.scroll_x = value
                self._fine_x = value & 7
                self._temp_address = (self._temp_address & ~0x001F) | (value >> 3)
            else:
                self.scroll_y = value
                self._temp_address = (
                    (self._temp_address & ~0x73E0)
                    | ((value & 7) << 12)
                    | ((value & 0xF8) << 2)
                )
            self._write_toggle = not self._write_toggle
        elif register == 6:
            if not self._write_toggle:
                self._temp_address = (self._temp_address & 0x00FF) | (
                    (value & 0x3F) << 8
                )
            else:
                self._temp_address = (self._temp_address & 0x7F00) | value
                self.vram_address = self._temp_address
            self._write_toggle = not self._write_toggle
        elif register == 7:
            self.write(self.vram_address, value)
            self.vram_address = (self.vram_address + self._vram_increment()) & 0x7FFF

    def read(self, address: int) -> int:
        address &= 0x3FFF
        if address < 0x2000:
            return self.cartridge.read_chr(address)
        if address < 0x3F00:
            return self.nametable[self._nametable_index(address)]
        return self.palette[self._palette_index(address)]

    def write(self, address: int, value: int) -> None:
        address &= 0x3FFF
        value &= 0xFF
        if address < 0x2000:
            self.cartridge.write_chr(address, value)
        elif address < 0x3F00:
            self.nametable[self._nametable_index(address)] = value
        else:
            self.palette[self._palette_index(address)] = value & 0x3F

    def step(self, cycles: int) -> None:
        """Advance scanlines without visiting every PPU dot."""
        if cycles <= 0:
            return
        target = self.cycle + cycles
        while target >= self._next_event_cycle:
            event = self._next_event_cycle
            self._check_sprite_hit(event)
            self.cycle = event
            if event == PPU_CYCLES_PER_FRAME:
                self.frame += 1
                target -= PPU_CYCLES_PER_FRAME
                self.cycle = 0
                self._next_event_cycle = 1
                continue
            scanline, dot = divmod(event, PPU_CYCLES_PER_SCANLINE)
            if scanline < SCREEN_HEIGHT:
                if dot == 1:
                    hit, overflow = self._render_scanline(scanline, self.vram_address)
                    if hit is not None and not self.status & 0x40:
                        self._sprite_zero_hit_cycle = (
                            scanline * PPU_CYCLES_PER_SCANLINE + hit + 1
                        )
                    if overflow:
                        self.status |= 0x20
                    self._next_event_cycle = scanline * PPU_CYCLES_PER_SCANLINE + 257
                else:
                    if self.mask & 0x18:
                        self.vram_address = _increment_y(self.vram_address)
                        self.vram_address = (self.vram_address & ~0x041F) | (
                            self._temp_address & 0x041F
                        )
                    self._next_event_cycle = (
                        (scanline + 1) * PPU_CYCLES_PER_SCANLINE + 1
                        if scanline + 1 < SCREEN_HEIGHT
                        else VBLANK_START_CYCLE + 1
                    )
            elif scanline == VBLANK_START_SCANLINE:
                self._present_frame()
                self.enter_vblank()
                self._next_event_cycle = PRE_RENDER_CYCLE + 1
            elif dot == 1:
                self.status &= 0x1F
                self._sprite_zero_hit_cycle = PPU_CYCLES_PER_FRAME + 1
                self._next_event_cycle = PRE_RENDER_CYCLE + 280
            else:
                if self.mask & 0x18:
                    self.vram_address = self._temp_address
                self._next_event_cycle = PPU_CYCLES_PER_FRAME
        self._check_sprite_hit(target)
        self.cycle = target

    def _check_sprite_hit(self, target: int) -> None:
        if self._sprite_zero_hit_cycle <= target:
            self.status |= 0x40
            self._sprite_zero_hit_cycle = PPU_CYCLES_PER_FRAME + 1

    def enter_vblank(self) -> None:
        was_vblank = self.vblank
        self.status |= 0x80
        if not was_vblank and self.nmi_enabled:
            self._trigger_nmi()

    def render_background(self) -> list[RGB]:
        """Render a background snapshot without advancing hardware timing."""
        return self._render_snapshot(include_sprites=False)

    def render_frame(self) -> list[RGB]:
        """Render a complete background/sprite snapshot for inspection."""
        return self._render_snapshot(include_sprites=True)

    def render_sprites(self) -> list[RGB]:
        """Refresh a complete snapshot, including sprites, without advancing time."""
        return self.render_frame()

    def _render_snapshot(self, *, include_sprites: bool) -> list[RGB]:
        address = self._temp_address
        for y in range(SCREEN_HEIGHT):
            self._render_scanline(y, address, include_sprites=include_sprites)
            address = _increment_y(address)
        self._present_frame()
        return self.framebuffer

    def _render_scanline(
        self, y: int, address: int, *, include_sprites: bool = True
    ) -> tuple[int | None, bool]:
        tables = _palette_tables(bytes(self.palette), bool(self.mask & 1))
        chr_data = self.cartridge.chr_data
        map_chr = self.cartridge.mapper.map_ppu_address
        if self.mask & 0x08:
            nametable = self.nametable
            pages = NAMETABLE_PAGES[self.cartridge.mirroring]
            table = (address >> 10) & 3
            tile_y = (address >> 5) & 31
            fine_y = (address >> 12) & 7
            coarse_x = address & 31
            # Supported mappers map contiguous 4 KiB CHR banks. Resolve a bank
            # once per scanline while reading fresh CHR bytes for each tile.
            pattern_base = map_chr(0x1000 if self.ctrl & 0x10 else 0)
            tile_row = tile_y * 32
            attribute_row = 0x3C0 + (tile_y // 4) * 8
            shift_y = (tile_y & 2) << 1
            fine_x = self._fine_x
            first, second = pages[table], pages[table ^ 1]
            end = coarse_x + 32 + bool(fine_x)
            tiles = bytes(
                nametable[first + tile_row : first + tile_row + 32]
                + nametable[second + tile_row : second + tile_row + 32]
            )[coarse_x:end]
            palettes = (
                _attribute_palettes(
                    bytes(nametable[first + attribute_row : first + attribute_row + 8]),
                    shift_y,
                )
                + _attribute_palettes(
                    bytes(
                        nametable[second + attribute_row : second + attribute_row + 8]
                    ),
                    shift_y,
                )
            )[coarse_x:end]
            # Strided CHR slices make byte lookup tables for all 256 tile IDs.
            # Translation selects the actual pattern bytes in C, so cache keys
            # see CHR-RAM edits and bank changes without Python tile loops.
            low = chr_data[pattern_base + fine_y : pattern_base + 0x1000 : 16]
            high = chr_data[pattern_base + fine_y + 8 : pattern_base + 0x1000 : 16]
            raw, colors = _background_strip(
                tiles.translate(low), tiles.translate(high), palettes, tables[:4]
            )
            background = raw[fine_x : fine_x + SCREEN_WIDTH]
            pixels = bytearray(colors[fine_x : fine_x + SCREEN_WIDTH])
            if not self.mask & 0x02:
                pixels[:8] = bytes([tables[0][0]]) * 8
                background = bytes(8) + background[8:]
        else:
            pixels = bytearray([tables[0][0]]) * SCREEN_WIDTH
            background = bytes(SCREEN_WIDTH)

        hit = None
        overflow = False
        if include_sprites and self.mask & 0x10:
            height = 16 if self.ctrl & 0x20 else 8
            indices = _sprite_scanlines(bytes(self.oam), height)[y]
            overflow = len(indices) > 8
            claimed = bytearray(SCREEN_WIDTH)
            chr_bases = (map_chr(0), map_chr(0x1000))
            for index in indices[:8]:
                top = self.oam[index] + 1
                tile, attributes, left = self.oam[index + 1 : index + 4]
                row_y = y - top
                if attributes & 0x80:
                    row_y = height - 1 - row_y
                if height == 16:
                    pattern = (
                        chr_bases[tile & 1]
                        + ((tile & 0xFE) + row_y // 8) * 16
                        + (row_y & 7)
                    )
                else:
                    pattern = chr_bases[1 if self.ctrl & 8 else 0] + tile * 16 + row_y
                row = _sprite_pixels(
                    chr_data[pattern], chr_data[pattern + 8], bool(attributes & 0x40)
                )
                colors = tables[4 + (attributes & 3)]
                for col, color in row:
                    x = left + col
                    if (
                        x >= SCREEN_WIDTH
                        or (x < 8 and not self.mask & 0x04)
                        or claimed[x]
                    ):
                        continue
                    claimed[x] = 1
                    if index == 0 and background[x] and x != 255 and hit is None:
                        hit = x
                    if not (attributes & 0x20 and background[x]):
                        pixels[x] = colors[color]
        self._pixels[y * SCREEN_WIDTH : (y + 1) * SCREEN_WIDTH] = pixels
        return hit, overflow

    def _present_frame(self) -> None:
        self._display_pixels = bytes(self._pixels)
        for channel, table in enumerate(RGB_TABLES):
            self.framebuffer_rgb[channel::3] = self._display_pixels.translate(table)
        self._framebuffer = None

    def _vram_increment(self) -> int:
        return 32 if self.ctrl & 0x04 else 1

    def _nametable_index(self, address: int) -> int:
        offset = (address - 0x2000) & 0x0FFF
        return NAMETABLE_PAGES[self.cartridge.mirroring][offset // 1024] + (
            offset & 0x03FF
        )

    def _palette_index(self, address: int) -> int:
        index = (address - 0x3F00) % PALETTE_SIZE
        if index in (0x10, 0x14, 0x18, 0x1C):
            index -= 0x10
        return index

    def _trigger_nmi(self) -> None:
        if self.nmi_callback is not None:
            self.nmi_callback()

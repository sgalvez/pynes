"""Rendering regressions use generated graphics, without external ROMs."""

import pytest

from nes_py.cartridge import Mirroring, load_ines_rom
from nes_py.ppu import (
    PPU,
    PPU_CYCLES_PER_FRAME,
    PPU_CYCLES_PER_SCANLINE,
    PRE_RENDER_CYCLE,
    SCREEN_WIDTH,
    SYSTEM_PALETTE,
    VBLANK_START_CYCLE,
)
from tests.test_cartridge import build_rom, write_mapper1_register


def make_ppu(*, flags6: int = 0) -> PPU:
    ppu = PPU(load_ines_rom(build_rom(chr_banks=0, flags6=flags6)))
    ppu.oam[:] = bytes([0xFF]) * 256
    ppu.palette[0] = 0x01
    ppu.palette[1] = 0x12
    ppu.palette[2] = 0x23
    ppu.palette[17] = 0x15
    ppu.palette[18] = 0x26
    return ppu


def solid_tile(ppu: PPU, tile: int, color: int) -> None:
    for row in range(8):
        ppu.write(tile * 16 + row, 0xFF if color & 1 else 0)
        ppu.write(tile * 16 + row + 8, 0xFF if color & 2 else 0)


def test_sprite_scanline_cache_follows_direct_and_register_oam_writes() -> None:
    ppu = make_ppu()
    solid_tile(ppu, 1, 1)
    ppu.mask = 0x14
    sprite(ppu, x=20, y=10)
    assert ppu.render_frame()[10 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[0x15]
    ppu.oam[3] = 36
    image = ppu.render_frame()
    assert image[10 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[0x01]
    assert image[10 * SCREEN_WIDTH + 36] == SYSTEM_PALETTE[0x15]
    ppu.write_register(3, 3)
    ppu.write_register(4, 44)
    image = ppu.render_frame()
    assert image[10 * SCREEN_WIDTH + 36] == SYSTEM_PALETTE[0x01]
    assert image[10 * SCREEN_WIDTH + 44] == SYSTEM_PALETTE[0x15]


def test_sprite_scanline_cache_follows_sprite_height_changes() -> None:
    ppu = make_ppu()
    solid_tile(ppu, 2, 1)
    solid_tile(ppu, 3, 1)
    ppu.mask = 0x14
    sprite(ppu, x=20, y=10, tile=2)
    assert ppu.render_frame()[20 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[0x01]
    ppu.ctrl = 0x20
    assert ppu.render_frame()[20 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[0x15]


def sprite(
    ppu: PPU,
    *,
    index: int = 0,
    x: int = 20,
    y: int = 10,
    tile: int = 1,
    attributes: int = 0,
) -> None:
    ppu.oam[index * 4 : index * 4 + 4] = bytes((y - 1, tile, attributes, x))


@pytest.mark.parametrize(
    "flags6,pages", [(0, (0, 0, 1, 1)), (1, (0, 1, 0, 1)), (8, (0, 1, 2, 3))]
)
def test_nametable_mirroring_and_3000_mirrors(flags6, pages) -> None:
    ppu = make_ppu(flags6=flags6)
    for table in range(4):
        ppu.write(0x2000 + table * 1024, table + 1)
    expected = [
        max(index + 1 for index, page in enumerate(pages) if page == selected)
        for selected in pages
    ]
    assert [ppu.read(0x2000 + table * 1024) for table in range(4)] == expected
    assert ppu.read(0x3000) == ppu.read(0x2000)


@pytest.mark.parametrize(
    "mode,mirroring",
    list(
        enumerate(
            (
                Mirroring.SINGLE_SCREEN_LOWER,
                Mirroring.SINGLE_SCREEN_UPPER,
                Mirroring.VERTICAL,
                Mirroring.HORIZONTAL,
            )
        )
    ),
)
def test_mmc1_mirroring_changes_without_reloading_cartridge(mode, mirroring) -> None:
    ppu = make_ppu(flags6=0x10)
    ppu.nametable[0] = 0x11
    ppu.nametable[1024] = 0x22
    write_mapper1_register(ppu.cartridge, 0x8000, 0x0C | mode)
    assert ppu.cartridge.mirroring is mirroring
    assert ppu.read(0x2000) == (0x22 if mode == 1 else 0x11)


def test_transparent_background_uses_universal_color_and_respects_mask() -> None:
    ppu = make_ppu()
    ppu.palette[12] = 0x30
    ppu.nametable[0x3C0] = 3
    ppu.mask = 0x0A
    assert ppu.render_background()[0] == SYSTEM_PALETTE[0x01]
    solid_tile(ppu, 0, 1)
    ppu.palette[13] = 0x22
    ppu.mask = 0x08
    image = ppu.render_background()
    assert image[0] == SYSTEM_PALETTE[0x01]
    assert image[8] == SYSTEM_PALETTE[0x22]
    ppu.mask = 0
    assert set(ppu.render_frame()) == {SYSTEM_PALETTE[0x01]}


@pytest.mark.parametrize("vertical", (False, True))
def test_fine_scroll_crosses_nametable_boundaries(vertical) -> None:
    ppu = make_ppu(flags6=0 if vertical else 1)
    solid_tile(ppu, 1, 1)
    solid_tile(ppu, 2, 2)
    ppu.nametable[:960] = bytes([1]) * 960
    ppu.nametable[1024 : 1024 + 960] = bytes([2]) * 960
    ppu.mask = 0x0A
    ppu.write_register(5, 0 if vertical else 252)
    ppu.write_register(5, 239 if vertical else 0)
    image = ppu.render_background()
    assert image[0] == SYSTEM_PALETTE[0x12]
    assert image[SCREEN_WIDTH if vertical else 4] == SYSTEM_PALETTE[0x23]


def test_ppuctrl_selects_background_nametable() -> None:
    ppu = make_ppu(flags6=8)
    ppu.mask = 0x0A
    for table in range(4):
        solid_tile(ppu, table, 1 if table % 2 == 0 else 2)
        ppu.nametable[table * 1024 : table * 1024 + 960] = bytes([table]) * 960
    for table in range(4):
        ppu.write_register(0, table)
        expected = 0x12 if table % 2 == 0 else 0x23
        assert ppu.render_background()[0] == SYSTEM_PALETTE[expected]


@pytest.mark.parametrize(
    "attributes,x,y", [(0, 20, 10), (0x40, 27, 10), (0x80, 20, 17), (0xC0, 27, 17)]
)
def test_sprite_position_transparency_and_flips(attributes, x, y) -> None:
    ppu = make_ppu()
    ppu.mask = 0x14
    ppu.write(16, 0x80)
    sprite(ppu, attributes=attributes)
    image = ppu.render_frame()
    assert image[y * SCREEN_WIDTH + x] == SYSTEM_PALETTE[0x15]
    assert image[y * SCREEN_WIDTH + x + 1] == SYSTEM_PALETTE[0x01]


@pytest.mark.parametrize("flipped", (False, True))
def test_8x16_sprites_use_tile_bank_bit_and_flip_both_tiles(flipped) -> None:
    ppu = make_ppu()
    ppu.ctrl = 0x20
    ppu.mask = 0x14
    ppu.write(0x1000, 0x80)
    ppu.write(0x1010 + 7 + 8, 0x80)
    sprite(ppu, tile=1, attributes=0x80 if flipped else 0)
    image = ppu.render_frame()
    top, bottom = (0x26, 0x15) if flipped else (0x15, 0x26)
    assert image[10 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[top]
    assert image[25 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[bottom]


def test_sprite_priority_claims_pixel_before_background_priority() -> None:
    ppu = make_ppu()
    ppu.mask = 0x1E
    solid_tile(ppu, 0, 1)
    solid_tile(ppu, 1, 2)
    sprite(ppu, attributes=0x20)
    sprite(ppu, index=1)
    assert ppu.render_frame()[10 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[0x12]
    ppu.oam[2] = 0
    assert ppu.render_frame()[10 * SCREEN_WIDTH + 20] == SYSTEM_PALETTE[0x26]


def test_sprites_clip_at_right_and_bottom_edges_and_ff_y_stays_hidden() -> None:
    ppu = make_ppu()
    ppu.mask = 0x14
    solid_tile(ppu, 1, 1)
    sprite(ppu, x=254, y=239)
    image = ppu.render_frame()
    assert image[-2:] == [SYSTEM_PALETTE[0x15]] * 2
    assert image[0] == SYSTEM_PALETTE[0x01]
    ppu.oam[0] = 0xFF
    assert set(ppu.render_frame()) == {SYSTEM_PALETTE[0x01]}


def test_mmc1_chr_bank_changes_update_rendered_patterns() -> None:
    ppu = make_ppu(flags6=0x10)
    ppu.mask = 0x0A
    solid_tile(ppu, 0, 1)
    solid_tile(ppu, 256, 2)
    write_mapper1_register(ppu.cartridge, 0x8000, 0x1C)
    assert ppu.render_frame()[0] == SYSTEM_PALETTE[0x12]
    write_mapper1_register(ppu.cartridge, 0xA000, 1)
    assert ppu.render_frame()[0] == SYSTEM_PALETTE[0x23]


def test_eight_sprite_limit_and_overflow_clears_on_prerender() -> None:
    ppu = make_ppu()
    ppu.mask = 0x14
    solid_tile(ppu, 1, 1)
    for index in range(9):
        sprite(ppu, index=index, x=index * 9)
    image = ppu.render_frame()
    assert image[10 * SCREEN_WIDTH + 63] == SYSTEM_PALETTE[0x15]
    assert image[10 * SCREEN_WIDTH + 72] == SYSTEM_PALETTE[0x01]
    ppu.step(10 * PPU_CYCLES_PER_SCANLINE + 1)
    assert ppu.status & 0x20
    ppu.step(PRE_RENDER_CYCLE + 1 - ppu.cycle)
    assert not ppu.status & 0x60


def test_sprite_zero_hit_waits_for_pixel_and_status_read_preserves_it() -> None:
    ppu = make_ppu()
    ppu.mask = 0x1E
    solid_tile(ppu, 0, 1)
    solid_tile(ppu, 1, 1)
    sprite(ppu)
    hit_cycle = 10 * PPU_CYCLES_PER_SCANLINE + 21
    ppu.step(hit_cycle - 1)
    assert not ppu.status & 0x40
    ppu.step(1)
    assert ppu.read_register(2) & 0x40
    assert ppu.status & 0x40


@pytest.mark.parametrize("x,mask", [(255, 0x1E), (0, 0x18), (20, 0x0A), (20, 0x14)])
def test_sprite_zero_hit_requires_visible_nontransparent_layers(x, mask) -> None:
    ppu = make_ppu()
    ppu.mask = mask
    solid_tile(ppu, 0, 1)
    solid_tile(ppu, 1, 1)
    sprite(ppu, x=x)
    ppu.step(11 * PPU_CYCLES_PER_SCANLINE)
    assert not ppu.status & 0x40


def test_chr_and_palette_changes_invalidate_cached_colors_and_rgb_buffer_is_reused() -> (
    None
):
    ppu = make_ppu()
    ppu.mask = 0x0A
    buffer = ppu.framebuffer_rgb
    solid_tile(ppu, 0, 1)
    assert ppu.render_frame()[0] == SYSTEM_PALETTE[0x12]
    solid_tile(ppu, 0, 2)
    ppu.palette[2] = 0x2A
    assert ppu.render_frame()[0] == SYSTEM_PALETTE[0x2A]
    assert ppu.framebuffer_rgb is buffer
    assert bytes(buffer[:3]) == bytes(SYSTEM_PALETTE[0x2A])
    ppu.mask |= 1
    assert ppu.render_frame()[0] == SYSTEM_PALETTE[0x20]


def test_palette_reads_are_immediate_and_refresh_ppudata_buffer() -> None:
    ppu = make_ppu()
    ppu.write(0x2F00, 0xAB)
    ppu.write_register(6, 0x3F)
    ppu.write_register(6, 0)
    assert ppu.read_register(7) == ppu.palette[0]
    ppu.write_register(6, 0x20)
    ppu.write_register(6, 0)
    assert ppu.read_register(7) == 0xAB


def test_completed_frame_stays_stable_while_next_frame_starts_rendering() -> None:
    ppu = make_ppu()
    ppu.mask = 0x0A
    solid_tile(ppu, 0, 1)
    ppu.step(VBLANK_START_CYCLE + 1)
    completed = bytes(ppu.framebuffer_rgb)
    ppu.palette[1] = 0x23
    ppu.step(PPU_CYCLES_PER_FRAME - ppu.cycle + 1)
    assert bytes(ppu.framebuffer_rgb) == completed
    assert ppu.framebuffer[0] == SYSTEM_PALETTE[0x12]


def test_scroll_and_address_share_write_toggle_and_status_resets_it() -> None:
    ppu = make_ppu()
    ppu.write_register(5, 8)
    ppu.write_register(6, 0x23)
    assert ppu.vram_address == 0x23
    ppu.write_register(5, 99)
    ppu.read_register(2)
    ppu.write_register(6, 0x21)
    ppu.write_register(6, 0x34)
    assert ppu.vram_address == 0x2134


def test_nmi_is_triggered_on_enable_transition_and_once_per_frame() -> None:
    calls = []
    ppu = make_ppu()
    ppu.nmi_callback = lambda: calls.append(ppu.frame)
    ppu.enter_vblank()
    ppu.write_register(0, 0x80)
    ppu.write_register(0, 0x80)
    assert len(calls) == 1
    ppu.reset()
    calls.clear()
    ppu.write_register(0, 0x80)
    ppu.step(VBLANK_START_CYCLE)
    assert calls == []
    ppu.step(1)
    assert calls == [0]
    ppu.step(2 * PPU_CYCLES_PER_FRAME)
    assert calls == [0, 1, 2]
    assert ppu.frame == 2

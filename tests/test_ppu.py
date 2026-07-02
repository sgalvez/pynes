from __future__ import annotations

from nes_py.cartridge import CHR_RAM_SIZE, CHR_ROM_BANK_SIZE, PRG_ROM_BANK_SIZE, load_ines_rom
from nes_py.nes import NES
from nes_py.ppu import PPU, SCREEN_HEIGHT, SCREEN_WIDTH, SYSTEM_PALETTE


def build_rom(*, chr_data: bytes | None = None, chr_banks: int = 1) -> bytes:
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4] = 1
    header[5] = chr_banks
    prg_rom = bytearray(PRG_ROM_BANK_SIZE)
    prg_rom[-6] = 0x00
    prg_rom[-5] = 0x81
    prg_rom[-4] = 0x00
    prg_rom[-3] = 0x80
    chr_rom = chr_data if chr_data is not None else bytes(CHR_ROM_BANK_SIZE if chr_banks else 0)
    return bytes(header) + bytes(prg_rom) + chr_rom


def test_ppu_address_and_data_registers_access_nametable_and_palette_memory() -> None:
    ppu = PPU(load_ines_rom(build_rom()))

    ppu.write_register(6, 0x20)
    ppu.write_register(6, 0x00)
    ppu.write_register(7, 0x23)

    ppu.write_register(6, 0x20)
    ppu.write_register(6, 0x00)
    assert ppu.read_register(7) == 0x23

    ppu.write_register(6, 0x3F)
    ppu.write_register(6, 0x10)
    ppu.write_register(7, 0x2A)
    assert ppu.read(0x3F00) == 0x2A
    assert ppu.read(0x3F10) == 0x2A


def test_ppu_vram_increment_and_scroll_latches() -> None:
    ppu = PPU(load_ines_rom(build_rom()))

    ppu.write_register(0, 0x04)
    ppu.write_register(6, 0x20)
    ppu.write_register(6, 0x00)
    ppu.write_register(7, 0x11)

    assert ppu.vram_address == 0x2020

    ppu.write_register(5, 3)
    ppu.write_register(5, 7)

    assert ppu.scroll_x == 3
    assert ppu.scroll_y == 7


def test_ppu_oam_register_increments_oam_address() -> None:
    ppu = PPU(load_ines_rom(build_rom()))

    ppu.write_register(3, 0xFE)
    ppu.write_register(4, 0xAA)
    ppu.write_register(4, 0xBB)

    assert ppu.oam[0xFE] == 0xAA
    assert ppu.oam[0xFF] == 0xBB
    assert ppu.oamaddr == 0x00


def test_ppu_can_write_chr_ram_through_pattern_table_space() -> None:
    ppu = PPU(load_ines_rom(build_rom(chr_banks=0)))

    ppu.write(0x0000, 0xCC)

    assert len(ppu.cartridge.chr_data) == CHR_RAM_SIZE
    assert ppu.read(0x0000) == 0xCC


def test_background_rendering_uses_chr_tiles_nametable_attributes_and_palette() -> None:
    chr_data = bytearray(CHR_ROM_BANK_SIZE)
    chr_data[0] = 0b1000_0000
    chr_data[8] = 0
    chr_data[1] = 0b0100_0000
    chr_data[9] = 0b0100_0000
    ppu = PPU(load_ines_rom(build_rom(chr_data=bytes(chr_data))))
    ppu.nametable[0] = 0
    ppu.palette[0] = 0x01
    ppu.palette[1] = 0x02
    ppu.palette[3] = 0x03

    framebuffer = ppu.render_background()

    assert len(framebuffer) == SCREEN_WIDTH * SCREEN_HEIGHT
    assert framebuffer[0] == SYSTEM_PALETTE[0x02]
    assert framebuffer[1] == SYSTEM_PALETTE[0x01]
    assert framebuffer[SCREEN_WIDTH + 1] == SYSTEM_PALETTE[0x03]
    assert ppu.framebuffer_bytes[:6] == bytes((*SYSTEM_PALETTE[0x02], *SYSTEM_PALETTE[0x01]))


def test_background_rendering_uses_scroll_offsets() -> None:
    chr_data = bytearray(CHR_ROM_BANK_SIZE)
    chr_data[0] = 0b1000_0000
    chr_data[16 + 8] = 0b1000_0000
    ppu = PPU(load_ines_rom(build_rom(chr_data=bytes(chr_data))))
    ppu.nametable[0] = 0
    ppu.nametable[1] = 1
    ppu.palette[1] = 0x02
    ppu.palette[2] = 0x03

    ppu.render_background()
    assert ppu.framebuffer[0] == SYSTEM_PALETTE[0x02]

    ppu.scroll_x = 8
    ppu.render_background()

    assert ppu.framebuffer[0] == SYSTEM_PALETTE[0x03]


def test_render_frame_reuses_background_until_scroll_changes() -> None:
    chr_data = bytearray(CHR_ROM_BANK_SIZE)
    chr_data[0] = 0b1000_0000
    chr_data[16 + 8] = 0b1000_0000
    ppu = PPU(load_ines_rom(build_rom(chr_data=bytes(chr_data))))
    ppu.nametable[0] = 0
    ppu.nametable[1] = 1
    ppu.palette[1] = 0x02
    ppu.palette[2] = 0x03

    ppu.render_frame()
    assert not ppu.background_dirty
    assert ppu.framebuffer[0] == SYSTEM_PALETTE[0x02]

    ppu.write_register(5, 8)
    assert ppu.background_dirty
    ppu.render_frame()

    assert not ppu.background_dirty
    assert ppu.framebuffer[0] == SYSTEM_PALETTE[0x03]


def test_repeated_scroll_and_vram_writes_keep_background_cache_clean() -> None:
    ppu = PPU(load_ines_rom(build_rom()))
    ppu.write_register(5, 8)
    ppu.write_register(5, 16)
    ppu.render_frame()

    ppu.write_register(5, 8)
    ppu.write_register(5, 16)
    ppu.write(0x2000, ppu.nametable[0])
    ppu.write(0x3F00, ppu.palette[0])

    assert not ppu.background_dirty


def test_background_tile_row_cache_reuses_rows_across_redraws() -> None:
    chr_data = bytearray(CHR_ROM_BANK_SIZE)
    chr_data[0] = 0b1000_0000
    ppu = PPU(load_ines_rom(build_rom(chr_data=bytes(chr_data))))
    ppu.palette[1] = 0x02

    ppu.render_background()
    cache_size = len(ppu.tile_row_cache)
    ppu.background_dirty = True
    ppu.render_background()

    assert cache_size > 0
    assert len(ppu.tile_row_cache) == cache_size


def test_sprite_rendering_draws_oam_sprite_over_background() -> None:
    chr_data = bytearray(CHR_ROM_BANK_SIZE)
    chr_data[16] = 0b1000_0000
    chr_data[24] = 0
    ppu = PPU(load_ines_rom(build_rom(chr_data=bytes(chr_data))))
    ppu.mask = 0x10
    ppu.palette[0] = 0x01
    ppu.palette[0x11] = 0x30
    ppu.oam[0:4] = bytes([9, 1, 0, 12])

    ppu.render_background()
    ppu.render_sprites()

    pixel_index = 10 * SCREEN_WIDTH + 12
    assert ppu.framebuffer[pixel_index] == SYSTEM_PALETTE[0x30]
    assert ppu.framebuffer_bytes[pixel_index * 3 : pixel_index * 3 + 3] == bytes(SYSTEM_PALETTE[0x30])


def test_sprite_rendering_limits_visible_sprites_per_scanline() -> None:
    chr_data = bytearray(CHR_ROM_BANK_SIZE)
    chr_data[16] = 0b1000_0000
    ppu = PPU(load_ines_rom(build_rom(chr_data=bytes(chr_data))))
    ppu.mask = 0x10
    ppu.palette[0] = 0x01
    ppu.palette[0x11] = 0x30
    for sprite_index in range(8):
        offset = sprite_index * 4
        ppu.oam[offset : offset + 4] = bytes([9, 1, 0, sprite_index * 8])
    ppu.oam[32:36] = bytes([9, 1, 0, 80])

    ppu.render_background()
    ppu.render_sprites()

    assert ppu.framebuffer[10 * SCREEN_WIDTH + 80] == SYSTEM_PALETTE[0x01]


def test_vblank_status_read_clears_flag_and_nmi_callback_runs_once() -> None:
    nmi_count = 0

    def on_nmi() -> None:
        nonlocal nmi_count
        nmi_count += 1

    ppu = PPU(load_ines_rom(build_rom()), nmi_callback=on_nmi)
    ppu.write_register(0, 0x80)

    ppu.enter_vblank()
    ppu.enter_vblank()

    assert nmi_count == 1
    assert ppu.read_register(2) & 0x80
    assert not ppu.vblank


def test_nes_ppu_nmi_interrupts_cpu() -> None:
    nes = NES.from_ines_rom(build_rom())
    nes.bus.write(0x2000, 0x80)

    nes.ppu.enter_vblank()

    assert nes.cpu.pc == 0x8100
    assert nes.cpu.sp == 0xFA

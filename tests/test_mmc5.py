from __future__ import annotations

from pathlib import Path

import pytest

from nes_py.cartridge import CartridgeError, load_ines_rom
from nes_py.cli import main
from nes_py.mmc5 import Mapper5
from nes_py.nes import NES, MMC5Bus
from nes_py.ppu import PPU, PPU_CYCLES_PER_FRAME, SYSTEM_PALETTE


def mmc5_rom(
    *, ram: int = 7, nvram: int = 7, prg_pages: int = 8, chr_pages: int = 32
) -> bytes:
    """Generate labeled 8 KiB PRG / 1 KiB CHR pages with a reset loop."""
    header = bytearray(b"NES\x1a" + bytes(12))
    header[4:8] = bytes((prg_pages // 2, chr_pages // 8, 0x52, 8))
    header[10] = ram | (nvram << 4)
    header[15] = 1
    prg = bytearray().join(bytes([page & 0xFF]) * 0x2000 for page in range(prg_pages))
    prg[-0x2000 : -0x2000 + 3] = bytes.fromhex("4C 00 E0")
    prg[-6:] = bytes.fromhex("00 E0 00 E0 00 E0")
    chr_data = b"".join(bytes([page & 0xFF]) * 0x400 for page in range(chr_pages))
    return bytes(header) + prg + chr_data


def mapper(*, ram_size: int = 0x4000, chr_size: int = 0x100000) -> Mapper5:
    prg = b"".join(bytes([page]) * 0x2000 for page in range(128))
    return Mapper5(prg, chr_size, ram_size)


def unlock(mmc5: Mapper5) -> None:
    mmc5.write_cpu(0x5102, 2)
    mmc5.write_cpu(0x5103, 1)


def test_loader_constructs_mmc5_with_explicit_both_ram_chips_and_reset_vector() -> None:
    nes = NES.from_ines_rom(mmc5_rom())
    assert isinstance(nes.bus, MMC5Bus)
    assert isinstance(nes.cartridge.mapper, Mapper5)
    assert len(nes.cartridge.mapper.prg_ram) == 16384
    assert nes.cpu.pc == 0xE000
    assert nes.run(3) == 9
    assert nes.cpu.pc == 0xE000


@pytest.mark.parametrize(
    "mode,expected",
    [
        (0, [12, 13, 14, 15]),
        (1, [4, 5, 14, 15]),
        (2, [4, 5, 10, 15]),
        (3, [2, 5, 10, 15]),
    ],
)
def test_prg_modes_align_rom_banks_in_eight_kib_units(
    mode: int, expected: list[int]
) -> None:
    mmc5 = mapper()
    for address, bank in zip(
        range(0x5114, 0x5118), (0x82, 0x85, 0x8A, 0x0F), strict=True
    ):
        mmc5.write_cpu(address, bank)
    mmc5.write_cpu(0x5100, mode)
    assert [
        mmc5.read_cpu(address) for address in (0x8100, 0xA100, 0xC100, 0xE100)
    ] == expected
    assert mmc5.map_cpu_address(0xE123) == expected[-1] * 0x2000 + 0x123


@pytest.mark.parametrize(
    "size,expected",
    [
        (0, [None] * 8),
        (0x2000, [0, 0, 0, 0, None, None, None, None]),
        (0x4000, [0, 0, 0, 0, 1, 1, 1, 1]),
        (0x8000, [0, 1, 2, 3, None, None, None, None]),
        (0x10000, list(range(8))),
    ],
)
def test_ram_pages_follow_physical_chip_aliases(
    size: int, expected: list[int | None]
) -> None:
    mmc5 = mapper(ram_size=size)
    for page in range(size // 0x2000):
        mmc5.prg_ram[page * 0x2000 + 0x123] = 0x40 + page
    for bank, physical in enumerate(expected):
        mmc5.write_cpu(0x5113, bank)
        assert mmc5.read_cpu(0x6123, 0xA5) == (
            0xA5 if physical is None else 0x40 + physical
        )


def test_ram_aliases_across_cpu_windows_and_locks_prevent_writes() -> None:
    mmc5 = mapper()
    mmc5.write_cpu(0x5113, 4)
    mmc5.write_cpu(0x6123, 0x55)
    assert mmc5.read_cpu(0x6123) == 0
    unlock(mmc5)
    mmc5.write_cpu(0x6123, 0x55)
    mmc5.write_cpu(0x5114, 7)  # Same second chip, different CPU window/bank bits.
    assert mmc5.read_cpu(0x8123) == 0x55
    mmc5.write_cpu(0x8123, 0xA6)
    assert mmc5.read_cpu(0x6123) == 0xA6
    mmc5.write_cpu(0x5103, 0)
    mmc5.write_cpu(0x8123, 0xFF)
    assert mmc5.read_cpu(0x6123) == 0xA6
    mmc5.write_cpu(0x5114, 0x81)
    unlock(mmc5)
    mmc5.write_cpu(0x8123, 0xF0)
    assert mmc5.read_cpu(0x8123) == 1  # A ROM write never modifies its data.


@pytest.mark.parametrize("mode", [1, 2])
def test_sixteen_kib_ram_window_mirrors_an_eight_kib_chip(mode: int) -> None:
    mmc5 = mapper()
    unlock(mmc5)
    mmc5.write_cpu(0x5100, mode)
    mmc5.write_cpu(0x5115, 4)
    mmc5.write_cpu(0x8123, 0xD7)
    assert mmc5.read_cpu(0xA123) == 0xD7
    mmc5.write_cpu(0x5113, 6)
    assert mmc5.read_cpu(0x6123) == 0xD7


@pytest.mark.parametrize("mode,span", [(0, 8), (1, 4), (2, 2), (3, 1)])
def test_chr_bank_values_are_indices_of_the_selected_size(mode: int, span: int) -> None:
    mmc5 = mapper()
    mmc5.write_cpu(0x5101, mode)
    for register in range(8):
        mmc5.write_cpu(0x5120 + register, register + 2)
    for page in range(8):
        register = page | (span - 1)
        expected_page = (register + 2) * span + page % span
        assert (
            mmc5.map_render_address(page * 1024 + 17, background=False)
            == expected_page * 1024 + 17
        )


def test_chr_upper_bits_latch_on_write_and_survive_mode_changes() -> None:
    mmc5 = mapper()
    mmc5.write_cpu(0x5130, 2)
    mmc5.write_cpu(0x5120, 7)
    mmc5.write_cpu(0x5130, 0)
    assert mmc5.map_ppu_address(0) == (0x207 * 1024)
    mmc5.write_cpu(0x5101, 1)  # Existing bank registers are not shifted again.
    mmc5.write_cpu(0x5123, 3)
    assert mmc5.map_ppu_address(0) == 3 * 4096
    mmc5.write_cpu(0x5101, 3)
    assert mmc5.map_ppu_address(0) == 0x207 * 1024
    # Bit zero is retained when a wider bank register is later used in 1 KiB mode.
    assert mmc5.map_ppu_address(0xC00) == 13 * 1024


def test_sprite_background_and_cpu_ppudata_have_separate_chr_contexts() -> None:
    mmc5 = mapper()
    mmc5.write_cpu(0x5120, 1)
    mmc5.write_cpu(0x5128, 5)
    mmc5.sprite_16 = True
    assert mmc5.map_render_address(0, background=False) == 1024
    assert mmc5.map_render_address(0, background=True) == 5 * 1024
    assert mmc5.map_render_address(0x1000, background=True) == 5 * 1024
    assert mmc5.map_ppu_address(0) == 5 * 1024
    mmc5.write_cpu(0x5120, 2)
    assert mmc5.map_ppu_address(0) == 2 * 1024
    assert mmc5.map_render_address(0, background=True) == 5 * 1024
    mmc5.sprite_16 = False
    assert mmc5.map_render_address(0, background=True) == 2 * 1024


def test_nametable_sources_fill_mode_and_cpu_ppudata_access() -> None:
    ppu = PPU(load_ines_rom(mmc5_rom()))
    mmc5 = ppu.cartridge.mapper
    assert isinstance(mmc5, Mapper5)
    mmc5.write_cpu(0x5105, 0xE4)  # CIRAM 0, CIRAM 1, ExRAM, fill.
    mmc5.write_cpu(0x5104, 0)
    mmc5.write_cpu(0x5106, 0xA5)
    mmc5.write_cpu(0x5107, 2)
    for address, value in ((0x2000, 1), (0x2400, 2), (0x2800, 3), (0x2C00, 4)):
        ppu.write(address, value)
    assert [ppu.read(address) for address in (0x2000, 0x2400, 0x2800, 0x2C00)] == [
        1,
        2,
        3,
        0xA5,
    ]
    assert ppu.read(0x3000) == 1
    assert ppu.read(0x2FC0) == 0xAA
    mmc5.write_cpu(0x5104, 1)
    assert ppu.read(0x2800) == 3
    mmc5.write_cpu(0x5104, 2)
    assert ppu.read(0x2800) == 0
    assert mmc5.read_cpu(0x5C00) == 3


def test_exram_cpu_access_obeys_mode_and_rendering_state() -> None:
    mmc5 = mapper()
    mmc5.write_cpu(0x5C00, 0xF0)  # Default mode 3 is read-only.
    assert mmc5.read_cpu(0x5C00) == 0
    mmc5.write_cpu(0x5104, 2)
    mmc5.write_cpu(0x5C00, 0xA5)
    assert mmc5.read_cpu(0x5C00) == 0xA5
    mmc5.write_cpu(0x5104, 1)
    assert mmc5.read_cpu(0x5C00, 0x67) == 0x67
    mmc5.set_ppu_mask(8)
    mmc5.clock_scanline()
    mmc5.write_cpu(0x5C00, 0x66)
    assert mmc5.exram[0] == 0x66
    mmc5.end_frame()
    mmc5.write_cpu(0x5C00, 0xAA)
    assert mmc5.exram[0] == 0


def test_extended_attributes_select_chr_and_palette_for_each_eight_pixel_tile() -> None:
    ppu = PPU(load_ines_rom(mmc5_rom()))
    mmc5 = ppu.cartridge.mapper
    assert isinstance(mmc5, Mapper5)
    ppu.cartridge.chr_data[:] = bytes(len(ppu.cartridge.chr_data))
    ppu.cartridge.chr_data[:8] = bytes([0xFF]) * 8
    ppu.cartridge.chr_data[4096 + 8 : 4096 + 16] = bytes([0xFF]) * 8
    ppu.palette[5] = 0x16  # Palette 1, pixel 1.
    ppu.palette[10] = 0x2A  # Palette 2, pixel 2.
    mmc5.write_cpu(0x5104, 2)
    mmc5.write_cpu(0x5C00, 0x40)
    mmc5.write_cpu(0x5C01, 0x81)
    mmc5.write_cpu(0x5104, 1)
    ppu.write_register(1, 0x0A)
    pixels = ppu.render_frame()
    assert pixels[0] == SYSTEM_PALETTE[0x16]
    assert pixels[8] == SYSTEM_PALETTE[0x2A]
    # Changing a bank's bytes is visible despite the shared strip cache.
    ppu.cartridge.chr_data[4096 : 4096 + 8] = bytes([0xFF]) * 8
    ppu.palette[11] = 0x30
    assert ppu.render_frame()[8] == SYSTEM_PALETTE[0x30]


def test_extended_attributes_and_fine_scroll_cross_a_nametable_boundary() -> None:
    ppu = PPU(load_ines_rom(mmc5_rom()))
    mmc5 = ppu.cartridge.mapper
    assert isinstance(mmc5, Mapper5)
    ppu.cartridge.chr_data[:] = bytes(len(ppu.cartridge.chr_data))
    ppu.cartridge.chr_data[:8] = bytes([0xFF]) * 8
    ppu.cartridge.chr_data[4096 + 8 : 4096 + 16] = bytes([0xFF]) * 8
    ppu.palette[5], ppu.palette[10] = 0x16, 0x2A
    mmc5.write_cpu(0x5105, 4)
    mmc5.write_cpu(0x5104, 2)
    mmc5.write_cpu(0x5C1F, 0x40)
    mmc5.write_cpu(0x5C00, 0x81)
    mmc5.write_cpu(0x5104, 1)
    ppu.write_register(5, 253)
    ppu.write_register(5, 0)
    ppu.write_register(1, 0x0A)
    pixels = ppu.render_frame()
    assert pixels[:3] == [SYSTEM_PALETTE[0x16]] * 3
    assert pixels[3:11] == [SYSTEM_PALETTE[0x2A]] * 8


def test_normal_background_resolves_each_one_kib_chr_page_and_fill_attributes() -> None:
    ppu = PPU(load_ines_rom(mmc5_rom()))
    mmc5 = ppu.cartridge.mapper
    assert isinstance(mmc5, Mapper5)
    ppu.cartridge.chr_data[:] = bytes(len(ppu.cartridge.chr_data))
    for bank, color in ((1, 1), (2, 2), (3, 3), (4, 0)):
        base = bank * 1024
        ppu.cartridge.chr_data[base : base + 8] = bytes([255 if color & 1 else 0]) * 8
        ppu.cartridge.chr_data[base + 8 : base + 16] = (
            bytes([255 if color & 2 else 0]) * 8
        )
        mmc5.write_cpu(0x5120 + bank - 1, bank)
    ppu.nametable[:4] = bytes((0, 64, 128, 192))
    ppu.palette[:4] = bytes((0x0F, 0x16, 0x2A, 0x30))
    ppu.write_register(1, 0x0A)
    pixels = ppu.render_frame()
    assert [pixels[x] for x in (0, 8, 16, 24)] == [
        SYSTEM_PALETTE[index] for index in (0x16, 0x2A, 0x30, 0x0F)
    ]
    mmc5.write_cpu(0x5105, 0xFF)
    mmc5.write_cpu(0x5106, 64)
    mmc5.write_cpu(0x5107, 3)
    ppu.palette[14] = 0x25
    assert ppu.render_frame()[0] == SYSTEM_PALETTE[0x25]
    mmc5.fill_tile = 0  # Fill-page caching follows actual register values.
    ppu.palette[13] = 0x12
    assert ppu.render_frame()[0] == SYSTEM_PALETTE[0x12]


def test_specialized_cpu_bus_reads_current_rom_ram_windows_and_open_bus() -> None:
    nes = NES.from_ines_rom(mmc5_rom(ram=7, nvram=0))
    mmc5 = nes.cartridge.mapper
    assert isinstance(mmc5, Mapper5)
    unlock(mmc5)
    nes.bus.write(0x5114, 0)
    nes.bus.write(0x8123, 0xA6)
    assert nes.bus.read(0x8123) == 0xA6
    nes.bus.write(0x5114, 0x81)
    assert nes.bus.read(0x8123) == 1
    nes.bus.write(0x5114, 0)
    assert nes.bus.read(0x8123) == 0xA6
    nes.bus.write(0x5114, 4)  # An unpopulated second RAM chip.
    nes.bus.write(0, 0xA5)
    assert nes.bus.read(0x8123) == 0xA5


def test_multiply_registers_are_unsigned_and_reflect_either_operand() -> None:
    mmc5 = mapper()
    mmc5.write_cpu(0x5205, 255)
    mmc5.write_cpu(0x5206, 254)
    assert mmc5.read_cpu(0x5205) == 2
    assert mmc5.read_cpu(0x5206) == 253
    mmc5.write_cpu(0x5205, 3)
    assert mmc5.read_cpu(0x5205) == 250
    assert mmc5.read_cpu(0x5206) == 2


def test_scanline_irq_pending_enable_acknowledge_and_zero_target() -> None:
    mmc5 = mapper()
    levels = []
    mmc5.irq_callback = levels.append
    mmc5.set_ppu_mask(8)
    mmc5.write_cpu(0x5203, 2)
    for _ in range(3):
        mmc5.clock_scanline()
    assert mmc5.irq_pending and not mmc5.irq_asserted
    mmc5.write_cpu(0x5204, 0x80)
    assert levels == [True]
    assert mmc5.read_cpu(0x5204) == 0xC0
    assert levels == [True, False]
    assert mmc5.in_frame and mmc5.scanline_counter == 2
    mmc5.write_cpu(0x5203, 3)
    mmc5.clock_scanline()
    assert mmc5.irq_asserted
    mmc5.write_cpu(0x5204, 0)
    assert mmc5.irq_pending and not mmc5.irq_asserted
    mmc5.end_frame(clear_irq=True)
    mmc5.write_cpu(0x5203, 0)
    for _ in range(240):
        mmc5.clock_scanline()
    assert not mmc5.irq_pending


def test_ppu_drives_mapper_counter_at_dot_four_and_clears_in_frame_after_picture() -> (
    None
):
    ppu = PPU(load_ines_rom(mmc5_rom()))
    mmc5 = ppu.cartridge.mapper
    assert isinstance(mmc5, Mapper5)
    ppu.write_register(1, 8)
    mmc5.write_cpu(0x5203, 1)
    mmc5.write_cpu(0x5204, 0x80)
    ppu.step(3)
    assert not mmc5.in_frame
    ppu.step(1)
    assert mmc5.in_frame and not mmc5.irq_pending
    ppu.step(341)
    assert mmc5.irq_asserted
    ppu.step(240 * 341 + 9 - ppu.cycle)
    assert not mmc5.in_frame
    assert mmc5.irq_pending
    assert ppu.cycle < PPU_CYCLES_PER_FRAME


@pytest.mark.parametrize("first,second", [(0x4015, 0x5204), (0x5204, 0x4015)])
def test_mapper_and_apu_irq_levels_do_not_clear_each_other(
    first: int, second: int
) -> None:
    nes = NES.from_ines_rom(mmc5_rom(), audio_sample_rate=44100)
    nes.bus.write(0x2001, 8)
    nes.bus.write(0x5203, 1)
    nes.bus.write(0x5204, 0x80)
    nes.run_frame()
    nes.run_frame()
    nes.run(120)  # Enter the next visible frame after scanline-zero acknowledgement.
    assert nes.cpu.irq_line
    nes.bus.read(first)
    assert nes.cpu.irq_line
    nes.bus.read(second)
    assert not nes.cpu.irq_line


def test_nmi_vector_reads_acknowledge_mapper_irq_without_erasing_ram() -> None:
    nes = NES.from_ines_rom(mmc5_rom())
    mmc5 = nes.cartridge.mapper
    assert isinstance(mmc5, Mapper5)
    unlock(mmc5)
    nes.bus.write(0x6000, 0xA5)
    nes.bus.write(0x2001, 8)
    nes.bus.write(0x5203, 1)
    nes.bus.write(0x5204, 0x80)
    nes.run_frame()
    nes.run(120)
    assert nes.cpu.irq_line
    assert nes.bus.read(0xFFFA) == 0
    assert not nes.cpu.irq_line
    assert not mmc5.in_frame and not mmc5.irq_pending
    nes.reset()
    assert nes.bus.read(0x6000) == 0xA5
    assert nes.cpu.pc == 0xE000


def test_cpu_executes_mmc5_irq_handler_and_all_clocks_include_entry_time() -> None:
    data = bytearray(mmc5_rom())
    base = 16 + 7 * 0x2000
    data[base : base + 4] = bytes.fromhex("58 4C 01 E0")  # CLI; JMP $E001.
    data[base + 0x10 : base + 0x19] = bytes.fromhex("AD 04 52 E6 00 40 EA EA EA")
    data[16 + 8 * 0x2000 - 2 : 16 + 8 * 0x2000] = bytes.fromhex("10 E0")
    nes = NES.from_ines_rom(bytes(data))
    nes.bus.write(0x2001, 8)
    nes.bus.write(0x5203, 2)
    nes.bus.write(0x5204, 0x80)
    nes.run_frame()
    assert nes.bus.read(0) == 1
    assert nes.ppu_cycles == nes.cpu_cycles * 3
    assert nes.cpu.cycles == nes.cpu_cycles


def test_dmc_fetches_the_current_mmc5_bank_and_stalls_the_shared_timeline() -> None:
    nes = NES.from_ines_rom(mmc5_rom(), audio_sample_rate=44100)
    assert nes.apu is not None
    reads = []

    def read_sample(address: int) -> int:
        value = nes.bus.read(address)
        reads.append((address, value))
        return value

    nes.apu.dmc_reader = read_sample
    nes.bus.write(0x5116, 0x82)
    for address, value in ((0x4010, 15), (0x4012, 0), (0x4013, 0), (0x4015, 0x10)):
        nes.bus.write(address, value)
    cycles = nes.step()
    assert reads == [(0xC000, 2)]
    assert cycles == 6  # Three-cycle JMP plus the nominal initial DMA stall.
    assert nes.ppu_cycles == nes.cpu_cycles * 3


@pytest.mark.parametrize(
    "offset,value,message",
    [(8, 0x10, "submapper"), (10, 0x66, "PRG RAM"), (11, 0x70, "CHR layouts")],
)
def test_nes2_mmc5_rejects_unmodeled_variants(
    offset: int, value: int, message: str
) -> None:
    data = bytearray(mmc5_rom())
    data[offset] = value
    with pytest.raises(CartridgeError, match=message):
        load_ines_rom(data)


def test_generated_mmc5_cli_smoke_executes_cpu(tmp_path: Path, capsys) -> None:
    path = tmp_path / "generated.nes"
    path.write_bytes(mmc5_rom())
    assert main([str(path), "--smoke-test", "12"]) == 0
    assert "instructions=12 cpu_cycles=36 pc=0xE000" in capsys.readouterr().out

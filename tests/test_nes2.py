from __future__ import annotations

from pathlib import Path

import pytest

from nes_py.cartridge import (
    CHR_RAM_SIZE,
    CHR_ROM_BANK_SIZE,
    PRG_ROM_BANK_SIZE,
    CartridgeError,
    Mirroring,
    load_ines_rom,
    parse_ines_header,
)
from nes_py.cli import main
from nes_py.nes import NES, NESBus


def nes2_header(
    *, prg_banks: int = 2, chr_banks: int = 0, mapper: int = 2, submapper: int = 2
) -> bytearray:
    """Describe a small generated board; no commercial ROM data is used."""
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4:6] = bytes((prg_banks, chr_banks))
    header[6] = ((mapper & 0x0F) << 4) | 1
    header[7] = (mapper & 0xF0) | 0x08
    header[8] = (submapper << 4) | (mapper >> 8)
    header[11] = 7 if not chr_banks else 0  # Explicit 8 KiB CHR RAM.
    header[15] = 1  # Standard controllers.
    return header


def nes2_program() -> bytes:
    header = nes2_header()
    prg = bytearray(2 * PRG_ROM_BANK_SIZE)
    # Execute in the fixed bank: LDA #2; STA $00; JMP $C000.
    prg[PRG_ROM_BANK_SIZE : PRG_ROM_BANK_SIZE + 7] = bytes.fromhex(
        "A9 02 85 00 4C 00 C0"
    )
    prg[-4:-2] = bytes((0, 0xC0))
    return bytes(header) + prg


def test_nes2_metadata_keeps_all_mapper_size_and_ram_bits() -> None:
    data = nes2_header(prg_banks=0x34, chr_banks=0x56, mapper=0x5AB, submapper=12)
    data[6] |= 4
    data[9:13] = bytes((0x21, 0x76, 0x87, 2))
    data[14:16] = bytes((2, 0x40))

    header = parse_ines_header(data)

    assert header.format_version == 2
    assert header.mapper_number == 0x5AB
    assert header.submapper_number == 12
    assert header.prg_rom_banks == 0x134
    assert header.chr_rom_banks == 0x256
    assert header.prg_rom_size == 0x134 * PRG_ROM_BANK_SIZE
    assert header.chr_rom_size == 0x256 * CHR_ROM_BANK_SIZE
    assert header.prg_ram_size == 4096
    assert header.prg_nvram_size == 8192
    assert header.chr_ram_size == 8192
    assert header.chr_nvram_size == 16384
    assert header.mirroring is Mirroring.VERTICAL
    assert header.has_trainer
    assert header.timing_mode == 2
    assert header.misc_rom_count == 2
    assert header.expansion_device == 0x40


@pytest.mark.parametrize("flags7", [0, 4, 12])
def test_legacy_header_does_not_interpret_nes2_extension_bytes(flags7: int) -> None:
    data = nes2_header(submapper=0)
    data[7] = flags7
    data[8:16] = bytes([0xFF]) * 8

    header = parse_ines_header(data)

    assert header.format_version == 1
    assert header.mapper_number == 2
    assert header.submapper_number == 0
    assert header.prg_rom_banks == 2
    assert header.chr_ram_size == CHR_RAM_SIZE
    assert header.timing_mode == 0


@pytest.mark.parametrize(
    "prg,chr_,expected_prg,expected_chr",
    [(0x40, 0x34, 65536, 8192), (0x39, 0x35, 49152, 24576)],
)
def test_nes2_exponent_multiplier_sizes(
    prg: int, chr_: int, expected_prg: int, expected_chr: int
) -> None:
    data = nes2_header(prg_banks=prg, chr_banks=chr_)
    data[9] = 0xFF

    header = parse_ines_header(data)

    assert header.prg_rom_size == expected_prg
    assert header.chr_rom_size == expected_chr


@pytest.mark.parametrize(
    "offset,low,high,message",
    [(4, 0x34, 0x0F, "PRG ROM size 8192"), (5, 0x30, 0xF0, "CHR ROM size 4096")],
)
def test_nes2_rejects_sizes_that_need_unsupported_partial_banks(
    offset: int, low: int, high: int, message: str
) -> None:
    data = nes2_header()
    data[offset] = low
    data[9] = high
    with pytest.raises(CartridgeError, match=message):
        load_ines_rom(data)


def test_nes2_extended_mapper_is_not_mistaken_for_supported_low_byte() -> None:
    data = nes2_header(mapper=0x102)
    with pytest.raises(CartridgeError, match="Unsupported mapper 258"):
        load_ines_rom(data)


@pytest.mark.parametrize("mapper,prg_banks", [(0, 1), (1, 2), (2, 2)])
def test_nes2_uses_existing_mapper_and_explicit_chr_ram(mapper: int, prg_banks: int) -> None:
    header = nes2_header(prg_banks=prg_banks, mapper=mapper, submapper=0)
    cartridge = load_ines_rom(bytes(header) + bytes(prg_banks * PRG_ROM_BANK_SIZE))

    assert cartridge.mapper_number == mapper
    assert cartridge.has_chr_ram
    assert len(cartridge.chr_data) == 8192
    cartridge.write_chr(0x1FFF, 0xA5)
    assert cartridge.read_chr(0x1FFF) == 0xA5


def test_nes2_exponent_sizes_locate_real_prg_and_chr_payloads() -> None:
    header = nes2_header(prg_banks=0x3C, chr_banks=0x34, mapper=0, submapper=0)
    header[9] = 0xFF
    cartridge = load_ines_rom(bytes(header) + bytes([0xA6]) * 32768 + bytes([0x5C]) * 8192)

    assert cartridge.read_prg(0xFFFF) == 0xA6
    assert cartridge.read_chr(0x1FFF) == 0x5C
    assert not cartridge.has_chr_ram


def test_nes2_payload_uses_trainer_offset_and_checks_truncation() -> None:
    header = nes2_header()
    header[6] |= 4
    data = bytes(header) + bytes([0xEE]) * 512 + bytes([0xA5]) * 32768

    assert load_ines_rom(data).read_prg(0x8000) == 0xA5
    with pytest.raises(CartridgeError, match="ROM is truncated"):
        load_ines_rom(data[:-1])


@pytest.mark.parametrize(
    "offset,value,message",
    [
        (8, 0x30, "Unsupported submapper 3 for mapper 2"),
        (7, 0x09, "console type"),
        (7, 0x0A, "console type"),
        (7, 0x0B, "console type"),
        (12, 1, "timing"),
        (12, 3, "timing"),
        (14, 1, "miscellaneous ROMs"),
        (15, 2, "expansion device"),
        (15, 0x40, "expansion device"),
        (10, 0x70, "nonvolatile"),
        (11, 0x70, "nonvolatile"),
        (10, 6, "PRG RAM size"),
        (10, 7, "UxROM with PRG RAM"),
        (11, 0, "CHR RAM size"),
        (11, 8, "CHR RAM size"),
        (4, 17, "at most 256 KiB"),
    ],
)
def test_nes2_reports_unsupported_hardware_instead_of_ignoring_it(
    offset: int, value: int, message: str
) -> None:
    data = nes2_header()
    data[offset] = value
    with pytest.raises(CartridgeError, match=message):
        load_ines_rom(data)


@pytest.mark.parametrize(
    "mapper,prg,chr_,chr_ram,submapper,message",
    [
        (0, 1, 1, 7, 0, "mixed CHR ROM/RAM"),
        (0, 1, 2, 0, 0, "at most 8192 bytes of CHR ROM"),
        (1, 17, 0, 7, 0, "at most 256 KiB"),
        (1, 2, 17, 0, 0, "at most 128 KiB"),
        (1, 2, 0, 7, 5, "Unsupported submapper 5 for mapper 1"),
    ],
)
def test_nes2_checks_layout_limits_of_each_mapper(
    mapper: int, prg: int, chr_: int, chr_ram: int, submapper: int, message: str
) -> None:
    data = nes2_header(prg_banks=prg, chr_banks=chr_, mapper=mapper, submapper=submapper)
    data[11] = chr_ram
    with pytest.raises(CartridgeError, match=message):
        load_ines_rom(data)


@pytest.mark.parametrize("submapper,expected_banks", [(0, [1, 2, 0]), (1, [3, 3, 3]), (2, [1, 2, 0])])
def test_uxrom_bank_writes_apply_declared_bus_conflicts_before_switching(
    submapper: int, expected_banks: list[int]
) -> None:
    header = nes2_header(prg_banks=4, submapper=submapper)
    prg = b"".join(bytes([value]) * PRG_ROM_BANK_SIZE for value in (1, 8, 4, 2))
    cartridge = load_ines_rom(bytes(header) + prg)
    for address, expected in zip((0x8000, 0xC000, 0x8000), expected_banks, strict=True):
        cartridge.write_prg(address, 3)
        assert cartridge.mapper.selected_bank == expected


@pytest.mark.parametrize("ram_shift,expected", [(0, 0x3C), (7, 0xA5)])
def test_nes2_cpu_bus_only_exposes_declared_prg_ram(ram_shift: int, expected: int) -> None:
    header = nes2_header(prg_banks=1, chr_banks=1, mapper=0, submapper=0)
    header[10] = ram_shift
    bus = NESBus(load_ines_rom(bytes(header) + bytes(PRG_ROM_BANK_SIZE + CHR_ROM_BANK_SIZE)))

    bus.write(0x6000, 0xA5)
    bus.write(0x0000, 0x3C)  # Change the last driven bus value.
    assert bus.read(0x6000) == expected
    if ram_shift:
        bus.write(0x7FFF, 0x7B)
        assert bus.read(0x7FFF) == 0x7B
    bus.write(0x4020, 0x11)
    bus.write(0x0000, 0x6E)
    assert bus.read(0x4020) == 0x6E  # No expansion device is present.


def test_nes2_multi_region_rom_runs_with_current_ntsc_model() -> None:
    data = bytearray(nes2_program())
    data[12] = 2
    nes = NES.from_ines_rom(data)
    assert nes.run(3) == 8
    assert nes.bus.read(0) == 2


def test_nes2_program_executes_frames_and_emits_audio() -> None:
    nes = NES.from_ines_rom(nes2_program(), audio_sample_rate=44100)
    assert nes.apu is not None
    for address, value in [(0x4015, 1), (0x4000, 0xBF), (0x4002, 253), (0x4003, 8)]:
        nes.bus.write(address, value)

    for _ in range(2):
        assert nes.run_frame() > 0

    assert nes.ppu.frame == 2
    assert nes.bus.read(0) == 2
    assert nes.ppu_cycles == nes.cpu_cycles * 3
    pcm = nes.apu.drain_samples()
    assert len(pcm) > 2000
    assert any(pcm)


def test_nes2_cli_smoke_path_executes_generated_rom(tmp_path: Path, capsys) -> None:
    path = tmp_path / "generated.nes"
    path.write_bytes(nes2_program())
    assert main([str(path), "--smoke-test", "12"]) == 0
    output = capsys.readouterr().out
    assert "instructions=12 cpu_cycles=32 pc=0xC000" in output

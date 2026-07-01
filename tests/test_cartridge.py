from __future__ import annotations

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


def build_rom(
    *,
    prg_banks: int = 1,
    chr_banks: int = 1,
    flags6: int = 0,
    flags7: int = 0,
    trainer: bytes = b"",
) -> bytes:
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4] = prg_banks
    header[5] = chr_banks
    header[6] = flags6
    header[7] = flags7

    prg_rom = bytes((index % 256 for index in range(prg_banks * PRG_ROM_BANK_SIZE)))
    chr_rom = bytes(((index + 7) % 256 for index in range(chr_banks * CHR_ROM_BANK_SIZE)))
    return bytes(header) + trainer + prg_rom + chr_rom


def test_parse_ines_header_extracts_mapper_and_mirroring() -> None:
    rom = build_rom(prg_banks=2, chr_banks=1, flags6=0x21, flags7=0x00)

    header = parse_ines_header(rom)

    assert header.prg_rom_banks == 2
    assert header.chr_rom_banks == 1
    assert header.mapper_number == 2
    assert header.mirroring is Mirroring.VERTICAL


def test_invalid_magic_fails_with_clear_error() -> None:
    with pytest.raises(CartridgeError, match="missing NES magic bytes"):
        load_ines_rom(b"NOTNES" + bytes(10))


def test_unsupported_mapper_fails_with_clear_error() -> None:
    rom = build_rom(flags6=0x10)

    with pytest.raises(CartridgeError, match="Unsupported mapper 1"):
        load_ines_rom(rom)


def test_invalid_mapper0_prg_bank_count_fails_with_clear_error() -> None:
    rom = build_rom(prg_banks=16)

    with pytest.raises(CartridgeError, match="Invalid Mapper 0 ROM"):
        load_ines_rom(rom)


def test_mapper0_reads_16kb_prg_rom_with_mirroring() -> None:
    cartridge = load_ines_rom(build_rom(prg_banks=1, chr_banks=1))

    assert cartridge.read_prg(0x8000) == 0
    assert cartridge.read_prg(0xBFFF) == 0xFF
    assert cartridge.read_prg(0xC000) == 0
    assert cartridge.read_prg(0xFFFF) == 0xFF


def test_mapper0_reads_32kb_prg_rom_without_mirroring() -> None:
    cartridge = load_ines_rom(build_rom(prg_banks=2, chr_banks=1))

    assert cartridge.read_prg(0x8000) == 0
    assert cartridge.read_prg(0xC000) == 0
    assert cartridge.read_prg(0xC001) == 1
    assert cartridge.read_prg(0xFFFF) == 0xFF


def test_chr_rom_is_read_only() -> None:
    cartridge = load_ines_rom(build_rom(chr_banks=1))

    assert cartridge.read_chr(0x0000) == 7
    assert cartridge.read_chr(0x1FFF) == 6
    with pytest.raises(CartridgeError, match="Cannot write to CHR ROM"):
        cartridge.write_chr(0x0000, 0xAA)


def test_chr_ram_is_allocated_when_rom_has_no_chr_banks() -> None:
    cartridge = load_ines_rom(build_rom(chr_banks=0))

    assert cartridge.has_chr_ram
    assert len(cartridge.chr_data) == CHR_RAM_SIZE
    assert cartridge.read_chr(0x0000) == 0

    cartridge.write_chr(0x0000, 0x1FF)

    assert cartridge.read_chr(0x0000) == 0xFF


def test_mapper2_switches_lower_prg_bank_and_keeps_last_bank_fixed() -> None:
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4] = 4
    header[5] = 0
    header[6] = 0x20
    prg_rom = b"".join(bytes([bank]) * PRG_ROM_BANK_SIZE for bank in range(4))
    cartridge = load_ines_rom(bytes(header) + prg_rom)

    assert cartridge.mapper_number == 2
    assert cartridge.read_prg(0x8000) == 0
    assert cartridge.read_prg(0xC000) == 3

    cartridge.write_prg(0x8000, 2)

    assert cartridge.read_prg(0x8000) == 2
    assert cartridge.read_prg(0xBFFF) == 2
    assert cartridge.read_prg(0xC000) == 3


def test_truncated_rom_fails_with_clear_error() -> None:
    rom = build_rom(prg_banks=1, chr_banks=1)[:-1]

    with pytest.raises(CartridgeError, match="ROM is truncated"):
        load_ines_rom(rom)


def test_rom_with_trainer_skips_trainer_bytes() -> None:
    trainer = bytes([0xEE]) * 512
    cartridge = load_ines_rom(build_rom(flags6=0x04, trainer=trainer))

    assert cartridge.header.has_trainer
    assert cartridge.read_prg(0x8000) == 0

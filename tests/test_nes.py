from __future__ import annotations

import pytest

from nes_py.cartridge import CHR_ROM_BANK_SIZE, PRG_ROM_BANK_SIZE, load_ines_rom
from nes_py.nes import INTERNAL_RAM_SIZE, NES, NESBus


def build_test_rom(program: bytes, *, reset_vector: int = 0x8000, prg_banks: int = 1) -> bytes:
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4] = prg_banks
    header[5] = 1

    prg_rom = bytearray(prg_banks * PRG_ROM_BANK_SIZE)
    prg_rom[: len(program)] = program
    prg_rom[-4] = reset_vector & 0xFF
    prg_rom[-3] = reset_vector >> 8
    chr_rom = bytes(CHR_ROM_BANK_SIZE)
    return bytes(header) + bytes(prg_rom) + chr_rom


def test_internal_ram_is_mirrored_every_2kb() -> None:
    bus = NESBus(load_ines_rom(build_test_rom(b"\xEA")))

    bus.write(0x0002, 0xAB)

    assert bus.read(0x0002) == 0xAB
    assert bus.read(0x0002 + INTERNAL_RAM_SIZE) == 0xAB
    assert bus.read(0x0002 + (3 * INTERNAL_RAM_SIZE)) == 0xAB


def test_ppu_apu_controller_and_expansion_register_stubs_do_not_crash() -> None:
    bus = NESBus(load_ines_rom(build_test_rom(b"\xEA")))

    bus.write(0x2000, 0x10)
    bus.write(0x2008, 0x20)
    bus.write(0x4000, 0x30)
    bus.write(0x4016, 0x40)
    bus.write(0x4020, 0x50)

    assert bus.read(0x2000) == 0x20
    assert bus.read(0x4000) == 0x30
    assert bus.read(0x4016) == 0x40
    assert bus.read(0x4020) == 0x50


def test_cartridge_prg_rom_reads_are_mapped_into_cpu_space() -> None:
    bus = NESBus(load_ines_rom(build_test_rom(bytes([0xA9, 0x42]))))

    assert bus.read(0x8000) == 0xA9
    assert bus.read(0x8001) == 0x42
    assert bus.read(0xFFFC) == 0x00
    assert bus.read(0xFFFD) == 0x80


def test_writes_to_prg_rom_address_space_are_ignored() -> None:
    bus = NESBus(load_ines_rom(build_test_rom(bytes([0xA9, 0x42]))))

    bus.write(0x8000, 0x00)

    assert bus.read(0x8000) == 0xA9


def test_nes_resets_cpu_from_prg_rom_vector() -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\xEA", reset_vector=0x8000))

    assert nes.cpu.pc == 0x8000
    assert nes.cpu_cycles == 7
    assert nes.ppu_cycles == 21


def test_nes_steps_fixed_number_of_cpu_instructions_from_rom() -> None:
    nes = NES.from_ines_rom(
        build_test_rom(
            bytes(
                [
                    0xA9,
                    0x12,  # LDA #$12
                    0x85,
                    0x00,  # STA $00
                    0xE6,
                    0x00,  # INC $00
                    0xEA,  # NOP
                ]
            )
        )
    )

    cycles = nes.run(4)

    assert cycles == 12
    assert nes.bus.read(0x0000) == 0x13
    assert nes.cpu.a == 0x12
    assert nes.cpu.pc == 0x8007
    assert nes.cpu_cycles == 19
    assert nes.ppu_cycles == 57


def test_nes_run_rejects_negative_instruction_counts() -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\xEA"))

    with pytest.raises(ValueError, match="non-negative"):
        nes.run(-1)

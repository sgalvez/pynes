from __future__ import annotations

import pytest

from nes_py.cartridge import CHR_ROM_BANK_SIZE, PRG_ROM_BANK_SIZE, load_ines_rom
from nes_py.input import Button
from nes_py.nes import INTERNAL_RAM_SIZE, NES, NESBus


def build_test_rom(
    program: bytes, *, reset_vector: int = 0x8000, prg_banks: int = 1
) -> bytes:
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
    bus = NESBus(load_ines_rom(build_test_rom(b"\xea")))

    bus.write(0x0002, 0xAB)

    assert bus.read(0x0002) == 0xAB
    assert bus.read(0x0002 + INTERNAL_RAM_SIZE) == 0xAB
    assert bus.read(0x0002 + (3 * INTERNAL_RAM_SIZE)) == 0xAB


def test_ppu_apu_controller_and_expansion_register_stubs_do_not_crash() -> None:
    bus = NESBus(load_ines_rom(build_test_rom(b"\xea")))

    bus.write(0x2000, 0x10)
    bus.write(0x2008, 0x20)
    bus.write(0x4000, 0x30)
    bus.write(0x4016, 0x40)
    bus.write(0x4020, 0x50)

    assert bus.ppu is not None
    assert bus.ppu.ctrl == 0x20
    assert bus.read(0x2002) == 0
    assert bus.read(0x4000) == 0x30
    assert bus.read(0x4016) in (0, 1)
    assert bus.read(0x4020) == 0x50


def test_controller_input_reaches_4016_serial_reads() -> None:
    bus = NESBus(load_ines_rom(build_test_rom(b"\xea")))
    bus.controller1.set_button(Button.A, True)
    bus.controller1.set_button(Button.START, True)

    bus.write(0x4016, 1)
    bus.write(0x4016, 0)

    assert [bus.read(0x4016) for _ in range(10)] == [1, 0, 0, 1, 0, 0, 0, 0, 1, 1]


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
    nes = NES.from_ines_rom(build_test_rom(b"\xea", reset_vector=0x8000))

    assert nes.cpu.pc == 0x8000
    assert nes.cpu_cycles == 7
    assert nes.ppu_cycles == 21
    assert nes.frame_cycles == nes.ppu.cycle == 21


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
    nes = NES.from_ines_rom(build_test_rom(b"\xea"))

    with pytest.raises(ValueError, match="non-negative"):
        nes.run(-1)


def test_oam_dma_copies_bus_memory_and_wraps_oam_address() -> None:
    bus = NESBus(load_ines_rom(build_test_rom(b"\xea")))
    assert bus.ppu is not None
    bus.ram[:256] = bytes(range(256))
    bus.ppu.oamaddr = 0xFE
    bus.write(0x4014, 0x08)  # Mirrored CPU RAM must be read through the bus.
    assert bus.ppu.oam[0xFE:] == bytes((0, 1))
    assert bus.ppu.oam[:0xFE] == bytes(range(2, 256))
    assert bus.ppu.oamaddr == 0xFE
    assert bus.dma_pending
    assert bus.read(0x4014) == 0x08


@pytest.mark.parametrize("prefix,stall", [(b"", 514), (b"\x24\x00", 513)])
def test_dma_stall_cycles_advance_ppu_and_cpu_together(prefix, stall) -> None:
    nes = NES.from_ines_rom(build_test_rom(prefix + b"\xa9\x02\x8d\x14\x40\xea"))
    if prefix:
        nes.step()
    nes.step()
    assert nes.step() == 4 + stall
    assert not nes.bus.dma_pending
    assert nes.cpu.cycles == nes.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3
    assert nes.step() == 2


def test_run_frame_completes_a_single_ppu_frame_and_accounts_for_nmi() -> None:
    from nes_py.ppu import PPU_CYCLES_PER_FRAME

    nes = NES.from_ines_rom(build_test_rom(b"\x4c\x00\x80"))
    nes.bus.write(0x2000, 0x80)
    pcs = []
    before = nes.cpu_cycles
    cycles = nes.run_frame(trace_callback=lambda cpu: pcs.append(cpu.pc))
    assert nes.ppu.frame == 1
    assert cycles == nes.cpu_cycles - before
    assert nes.cpu.cycles == nes.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3
    assert nes.ppu.cycle == nes.ppu_cycles % PPU_CYCLES_PER_FRAME
    assert pcs


def test_nes_run_frame_advances_one_frame_and_exposes_audio() -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\x4c\x00\x80"), audio_sample_rate=44100)
    for address, value in (
        (0x4015, 1),
        (0x4000, 0xBF),
        (0x4001, 8),
        (0x4002, 253),
        (0x4003, 8),
    ):
        nes.bus.write(address, value)
    cycles = nes.run_frame()
    assert cycles > 0
    assert nes.ppu.frame == 1
    assert any(nes.apu.drain_samples())


def test_nes_run_frame_uses_scanlines_without_a_redundant_snapshot(monkeypatch) -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\x4c\x00\x80"))

    def fail_render():
        raise AssertionError("render_frame should not be called")

    monkeypatch.setattr(nes.ppu, "render_frame", fail_render)
    assert nes.run_frame() > 0
    assert nes.ppu.frame == 1

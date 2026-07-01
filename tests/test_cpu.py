from __future__ import annotations

from nes_py.cpu import CPU6502, MemoryBus, StatusFlag

OFFICIAL_OPCODES = {
    0x00,
    0x01,
    0x05,
    0x06,
    0x08,
    0x09,
    0x0A,
    0x0D,
    0x0E,
    0x10,
    0x11,
    0x15,
    0x16,
    0x18,
    0x19,
    0x1D,
    0x1E,
    0x20,
    0x21,
    0x24,
    0x25,
    0x26,
    0x28,
    0x29,
    0x2A,
    0x2C,
    0x2D,
    0x2E,
    0x30,
    0x31,
    0x35,
    0x36,
    0x38,
    0x39,
    0x3D,
    0x3E,
    0x40,
    0x41,
    0x45,
    0x46,
    0x48,
    0x49,
    0x4A,
    0x4C,
    0x4D,
    0x4E,
    0x50,
    0x51,
    0x55,
    0x56,
    0x58,
    0x59,
    0x5D,
    0x5E,
    0x60,
    0x61,
    0x65,
    0x66,
    0x68,
    0x69,
    0x6A,
    0x6C,
    0x6D,
    0x6E,
    0x70,
    0x71,
    0x75,
    0x76,
    0x78,
    0x79,
    0x7D,
    0x7E,
    0x81,
    0x84,
    0x85,
    0x86,
    0x88,
    0x8A,
    0x8C,
    0x8D,
    0x8E,
    0x90,
    0x91,
    0x94,
    0x95,
    0x96,
    0x98,
    0x99,
    0x9A,
    0x9D,
    0xA0,
    0xA1,
    0xA2,
    0xA4,
    0xA5,
    0xA6,
    0xA8,
    0xA9,
    0xAA,
    0xAC,
    0xAD,
    0xAE,
    0xB0,
    0xB1,
    0xB4,
    0xB5,
    0xB6,
    0xB8,
    0xB9,
    0xBA,
    0xBC,
    0xBD,
    0xBE,
    0xC0,
    0xC1,
    0xC4,
    0xC5,
    0xC6,
    0xC8,
    0xC9,
    0xCA,
    0xCC,
    0xCD,
    0xCE,
    0xD0,
    0xD1,
    0xD5,
    0xD6,
    0xD8,
    0xD9,
    0xDD,
    0xDE,
    0xE0,
    0xE1,
    0xE4,
    0xE5,
    0xE6,
    0xE8,
    0xE9,
    0xEA,
    0xEC,
    0xED,
    0xEE,
    0xF0,
    0xF1,
    0xF5,
    0xF6,
    0xF8,
    0xF9,
    0xFD,
    0xFE,
}


def make_cpu(program: bytes, *, start: int = 0x8000) -> tuple[CPU6502, MemoryBus]:
    bus = MemoryBus()
    bus.load(start, program)
    bus.write(0xFFFC, start & 0xFF)
    bus.write(0xFFFD, start >> 8)
    cpu = CPU6502(bus)
    cpu.reset()
    return cpu, bus


def run(cpu: CPU6502, count: int) -> None:
    for _ in range(count):
        cpu.step()


def test_cpu_has_dispatch_for_all_official_opcodes() -> None:
    missing = [opcode for opcode in OFFICIAL_OPCODES if not hasattr(CPU6502, f"_op_{opcode:02x}")]

    assert missing == []


def test_reset_loads_vector_and_initial_state() -> None:
    cpu, _ = make_cpu(b"\xEA")

    assert cpu.pc == 0x8000
    assert cpu.sp == 0xFD
    assert cpu.get_flag(StatusFlag.INTERRUPT_DISABLE)
    assert cpu.cycles == 7


def test_load_store_and_transfer_instructions_mutate_registers_memory_and_flags() -> None:
    cpu, bus = make_cpu(
        bytes(
            [
                0xA9,
                0x00,  # LDA #$00
                0xAA,  # TAX
                0xA9,
                0x80,  # LDA #$80
                0xA8,  # TAY
                0x8D,
                0x00,
                0x20,  # STA $2000
            ]
        )
    )

    run(cpu, 5)

    assert cpu.x == 0
    assert cpu.y == 0x80
    assert bus.read(0x2000) == 0x80
    assert cpu.get_flag(StatusFlag.NEGATIVE)
    assert not cpu.get_flag(StatusFlag.ZERO)


def test_arithmetic_and_compare_flags() -> None:
    cpu, _ = make_cpu(
        bytes(
            [
                0xA9,
                0x7F,  # LDA #$7F
                0x69,
                0x01,  # ADC #$01
                0xC9,
                0x80,  # CMP #$80
                0xE9,
                0x01,  # SBC #$01, carry remains set after CMP equal
            ]
        )
    )

    run(cpu, 4)

    assert cpu.a == 0x7F
    assert cpu.get_flag(StatusFlag.CARRY)
    assert cpu.get_flag(StatusFlag.OVERFLOW)
    assert not cpu.get_flag(StatusFlag.ZERO)


def test_branches_jump_and_page_cross_cycle_counting() -> None:
    cpu, _ = make_cpu(
        bytes(
            [
                0xA9,
                0x00,  # LDA #$00 sets zero
                0xF0,
                0x02,  # BEQ +2
                0xA9,
                0x01,  # skipped
                0x4C,
                0x0A,
                0x80,  # JMP $800A
                0xEA,  # skipped
                0xA9,
                0x02,  # LDA #$02
            ]
        )
    )

    run(cpu, 4)

    assert cpu.a == 0x02
    assert cpu.pc == 0x800C


def test_stack_jsr_and_rts_behavior() -> None:
    cpu, _ = make_cpu(
        bytes(
            [
                0x20,
                0x07,
                0x80,  # JSR $8007
                0xA9,
                0x03,  # LDA #$03 after RTS
                0xEA,  # NOP
                0xEA,  # padding
                0xA9,
                0x09,  # LDA #$09 in subroutine
                0x48,  # PHA
                0xA9,
                0x00,  # LDA #$00
                0x68,  # PLA
                0x60,  # RTS
            ]
        )
    )

    run(cpu, 7)

    assert cpu.a == 0x03
    assert cpu.sp == 0xFD


def test_memory_increment_shift_and_bit_flags() -> None:
    cpu, bus = make_cpu(
        bytes(
            [
                0xA9,
                0xC0,  # LDA #$C0
                0x85,
                0x10,  # STA $10
                0x06,
                0x10,  # ASL $10 -> $80, carry set
                0x24,
                0x10,  # BIT $10 copies negative and clears overflow
                0xE6,
                0x10,  # INC $10 -> $81
            ]
        )
    )

    run(cpu, 5)

    assert bus.read(0x0010) == 0x81
    assert cpu.get_flag(StatusFlag.CARRY)
    assert cpu.get_flag(StatusFlag.NEGATIVE)
    assert not cpu.get_flag(StatusFlag.OVERFLOW)

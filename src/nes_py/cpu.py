"""MOS 6502 CPU core used by the NES."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag
from typing import Protocol


class CPUError(RuntimeError):
    """Raised when the CPU encounters an unsupported or invalid operation."""


class StatusFlag(IntFlag):
    CARRY = 0x01
    ZERO = 0x02
    INTERRUPT_DISABLE = 0x04
    DECIMAL = 0x08
    BREAK = 0x10
    UNUSED = 0x20
    OVERFLOW = 0x40
    NEGATIVE = 0x80


class Bus(Protocol):
    """Minimal CPU memory bus protocol."""

    def read(self, address: int) -> int:
        """Read one byte from a 16-bit address."""

    def write(self, address: int, value: int) -> None:
        """Write one byte to a 16-bit address."""


@dataclass
class MemoryBus:
    """Simple 64 KB memory bus useful for CPU tests and early integration."""

    memory: bytearray = field(default_factory=lambda: bytearray(0x10000))

    def read(self, address: int) -> int:
        return self.memory[address & 0xFFFF]

    def write(self, address: int, value: int) -> None:
        self.memory[address & 0xFFFF] = value & 0xFF

    def load(self, start: int, data: bytes) -> None:
        end = start + len(data)
        self.memory[start:end] = data


@dataclass
class CPU6502:
    """Official-opcode 6502 execution core."""

    bus: Bus
    a: int = 0
    x: int = 0
    y: int = 0
    pc: int = 0
    sp: int = 0xFD
    status: int = int(StatusFlag.UNUSED | StatusFlag.INTERRUPT_DISABLE)
    cycles: int = 0

    def reset(self) -> None:
        """Reset the CPU from the reset vector at 0xFFFC/0xFFFD."""
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFD
        self.status = int(StatusFlag.UNUSED | StatusFlag.INTERRUPT_DISABLE)
        self.pc = self._read_u16(0xFFFC)
        self.cycles = 7

    def nmi(self) -> None:
        """Service a non-maskable interrupt."""
        self._push((self.pc >> 8) & 0xFF)
        self._push(self.pc & 0xFF)
        self._push(self.status & ~int(StatusFlag.BREAK) | int(StatusFlag.UNUSED))
        self.set_flag(StatusFlag.INTERRUPT_DISABLE, True)
        self.pc = self._read_u16(0xFFFA)
        self.cycles += 7

    def step(self) -> int:
        """Execute one instruction and return the cycles it consumed."""
        opcode = self._fetch_byte()
        method = getattr(self, f"_op_{opcode:02x}", None)
        if method is None:
            raise CPUError(f"Unsupported opcode 0x{opcode:02X} at 0x{(self.pc - 1) & 0xFFFF:04X}")
        before = self.cycles
        method()
        self.status |= int(StatusFlag.UNUSED)
        return self.cycles - before

    def get_flag(self, flag: StatusFlag) -> bool:
        return bool(self.status & int(flag))

    def set_flag(self, flag: StatusFlag, value: bool) -> None:
        if value:
            self.status |= int(flag)
        else:
            self.status &= ~int(flag) & 0xFF
        self.status |= int(StatusFlag.UNUSED)

    def _read(self, address: int) -> int:
        return self.bus.read(address & 0xFFFF) & 0xFF

    def _write(self, address: int, value: int) -> None:
        self.bus.write(address & 0xFFFF, value & 0xFF)

    def _read_u16(self, address: int) -> int:
        low = self._read(address)
        high = self._read(address + 1)
        return low | (high << 8)

    def _read_u16_bug(self, address: int) -> int:
        low = self._read(address)
        high_address = (address & 0xFF00) | ((address + 1) & 0x00FF)
        return low | (self._read(high_address) << 8)

    def _fetch_byte(self) -> int:
        value = self._read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return value

    def _fetch_word(self) -> int:
        low = self._fetch_byte()
        high = self._fetch_byte()
        return low | (high << 8)

    def _push(self, value: int) -> None:
        self._write(0x0100 | self.sp, value)
        self.sp = (self.sp - 1) & 0xFF

    def _pull(self) -> int:
        self.sp = (self.sp + 1) & 0xFF
        return self._read(0x0100 | self.sp)

    def _set_zn(self, value: int) -> None:
        value &= 0xFF
        self.set_flag(StatusFlag.ZERO, value == 0)
        self.set_flag(StatusFlag.NEGATIVE, bool(value & 0x80))

    def _page_crossed(self, left: int, right: int) -> bool:
        return (left & 0xFF00) != (right & 0xFF00)

    def _addr_zp(self) -> tuple[int, bool]:
        return self._fetch_byte(), False

    def _addr_zpx(self) -> tuple[int, bool]:
        return (self._fetch_byte() + self.x) & 0xFF, False

    def _addr_zpy(self) -> tuple[int, bool]:
        return (self._fetch_byte() + self.y) & 0xFF, False

    def _addr_abs(self) -> tuple[int, bool]:
        return self._fetch_word(), False

    def _addr_absx(self) -> tuple[int, bool]:
        base = self._fetch_word()
        address = (base + self.x) & 0xFFFF
        return address, self._page_crossed(base, address)

    def _addr_absy(self) -> tuple[int, bool]:
        base = self._fetch_word()
        address = (base + self.y) & 0xFFFF
        return address, self._page_crossed(base, address)

    def _addr_indx(self) -> tuple[int, bool]:
        pointer = (self._fetch_byte() + self.x) & 0xFF
        return self._read(pointer) | (self._read((pointer + 1) & 0xFF) << 8), False

    def _addr_indy(self) -> tuple[int, bool]:
        pointer = self._fetch_byte()
        base = self._read(pointer) | (self._read((pointer + 1) & 0xFF) << 8)
        address = (base + self.y) & 0xFFFF
        return address, self._page_crossed(base, address)

    def _branch(self, condition: bool) -> None:
        offset = self._fetch_byte()
        if offset & 0x80:
            offset -= 0x100
        self.cycles += 2
        if condition:
            old_pc = self.pc
            self.pc = (self.pc + offset) & 0xFFFF
            self.cycles += 1
            if self._page_crossed(old_pc, self.pc):
                self.cycles += 1

    def _load(self, register: str, value: int) -> None:
        setattr(self, register, value & 0xFF)
        self._set_zn(value)

    def _compare(self, register: int, value: int) -> None:
        result = (register - value) & 0x1FF
        self.set_flag(StatusFlag.CARRY, register >= value)
        self._set_zn(result & 0xFF)

    def _adc(self, value: int) -> None:
        carry = 1 if self.get_flag(StatusFlag.CARRY) else 0
        total = self.a + value + carry
        result = total & 0xFF
        self.set_flag(StatusFlag.CARRY, total > 0xFF)
        self.set_flag(StatusFlag.OVERFLOW, bool((~(self.a ^ value) & (self.a ^ result)) & 0x80))
        self.a = result
        self._set_zn(self.a)

    def _sbc(self, value: int) -> None:
        self._adc(value ^ 0xFF)

    def _asl_value(self, value: int) -> int:
        self.set_flag(StatusFlag.CARRY, bool(value & 0x80))
        value = (value << 1) & 0xFF
        self._set_zn(value)
        return value

    def _lsr_value(self, value: int) -> int:
        self.set_flag(StatusFlag.CARRY, bool(value & 0x01))
        value = (value >> 1) & 0xFF
        self._set_zn(value)
        return value

    def _rol_value(self, value: int) -> int:
        carry_in = 1 if self.get_flag(StatusFlag.CARRY) else 0
        self.set_flag(StatusFlag.CARRY, bool(value & 0x80))
        value = ((value << 1) | carry_in) & 0xFF
        self._set_zn(value)
        return value

    def _ror_value(self, value: int) -> int:
        carry_in = 0x80 if self.get_flag(StatusFlag.CARRY) else 0
        self.set_flag(StatusFlag.CARRY, bool(value & 0x01))
        value = ((value >> 1) | carry_in) & 0xFF
        self._set_zn(value)
        return value

    def _read_op(self, addr_mode, operation, cycles: int, page_cycle: bool = False) -> None:
        address, page = addr_mode()
        operation(self._read(address))
        self.cycles += cycles + (1 if page_cycle and page else 0)

    def _write_op(self, addr_mode, value: int, cycles: int) -> None:
        address, _ = addr_mode()
        self._write(address, value)
        self.cycles += cycles

    def _modify_op(self, addr_mode, operation, cycles: int) -> None:
        address, _ = addr_mode()
        self._write(address, operation(self._read(address)))
        self.cycles += cycles

    def _ora(self, value: int) -> None:
        self.a = (self.a | value) & 0xFF
        self._set_zn(self.a)

    def _and(self, value: int) -> None:
        self.a &= value
        self._set_zn(self.a)

    def _eor(self, value: int) -> None:
        self.a ^= value
        self._set_zn(self.a)

    def _bit(self, value: int) -> None:
        self.set_flag(StatusFlag.ZERO, (self.a & value) == 0)
        self.set_flag(StatusFlag.OVERFLOW, bool(value & 0x40))
        self.set_flag(StatusFlag.NEGATIVE, bool(value & 0x80))

    def _inc_value(self, value: int) -> int:
        value = (value + 1) & 0xFF
        self._set_zn(value)
        return value

    def _dec_value(self, value: int) -> int:
        value = (value - 1) & 0xFF
        self._set_zn(value)
        return value

    def _lda(self, value: int) -> None:
        self._load("a", value)

    def _ldx(self, value: int) -> None:
        self._load("x", value)

    def _ldy(self, value: int) -> None:
        self._load("y", value)

    def _cmp(self, value: int) -> None:
        self._compare(self.a, value)

    def _cpx(self, value: int) -> None:
        self._compare(self.x, value)

    def _cpy(self, value: int) -> None:
        self._compare(self.y, value)

    def _imm(self) -> tuple[int, bool]:
        address = self.pc
        self.pc = (self.pc + 1) & 0xFFFF
        return address, False


def _make_read_op(operation: str, addr_mode: str, cycles: int, page_cycle: bool = False):
    def opcode(self: CPU6502) -> None:
        self._read_op(getattr(self, addr_mode), getattr(self, operation), cycles, page_cycle)

    return opcode


def _make_store_op(register: str, addr_mode: str, cycles: int):
    def opcode(self: CPU6502) -> None:
        self._write_op(getattr(self, addr_mode), getattr(self, register), cycles)

    return opcode


def _make_modify_op(operation: str, addr_mode: str, cycles: int):
    def opcode(self: CPU6502) -> None:
        self._modify_op(getattr(self, addr_mode), getattr(self, operation), cycles)

    return opcode


def _make_accumulator_op(operation: str, cycles: int = 2):
    def opcode(self: CPU6502) -> None:
        self.a = getattr(self, operation)(self.a)
        self.cycles += cycles

    return opcode


def _make_branch_op(flag: StatusFlag, expected: bool):
    def opcode(self: CPU6502) -> None:
        self._branch(self.get_flag(flag) is expected)

    return opcode


def _make_flag_op(flag: StatusFlag, value: bool):
    def opcode(self: CPU6502) -> None:
        self.set_flag(flag, value)
        self.cycles += 2

    return opcode


def _make_transfer_op(source: str, destination: str):
    def opcode(self: CPU6502) -> None:
        value = getattr(self, source)
        setattr(self, destination, value & 0xFF)
        self._set_zn(value)
        self.cycles += 2

    return opcode


def _make_inc_register_op(register: str, delta: int):
    def opcode(self: CPU6502) -> None:
        value = (getattr(self, register) + delta) & 0xFF
        setattr(self, register, value)
        self._set_zn(value)
        self.cycles += 2

    return opcode


def _op_nop(self: CPU6502) -> None:
    self.cycles += 2


def _op_brk(self: CPU6502) -> None:
    self.pc = (self.pc + 1) & 0xFFFF
    self._push((self.pc >> 8) & 0xFF)
    self._push(self.pc & 0xFF)
    self._push(self.status | int(StatusFlag.BREAK | StatusFlag.UNUSED))
    self.set_flag(StatusFlag.INTERRUPT_DISABLE, True)
    self.pc = self._read_u16(0xFFFE)
    self.cycles += 7


def _op_jsr(self: CPU6502) -> None:
    target = self._fetch_word()
    return_address = (self.pc - 1) & 0xFFFF
    self._push((return_address >> 8) & 0xFF)
    self._push(return_address & 0xFF)
    self.pc = target
    self.cycles += 6


def _op_rts(self: CPU6502) -> None:
    low = self._pull()
    high = self._pull()
    self.pc = ((low | (high << 8)) + 1) & 0xFFFF
    self.cycles += 6


def _op_rti(self: CPU6502) -> None:
    self.status = (self._pull() & ~int(StatusFlag.BREAK)) | int(StatusFlag.UNUSED)
    low = self._pull()
    high = self._pull()
    self.pc = low | (high << 8)
    self.cycles += 6


def _op_jmp_abs(self: CPU6502) -> None:
    self.pc = self._fetch_word()
    self.cycles += 3


def _op_jmp_ind(self: CPU6502) -> None:
    self.pc = self._read_u16_bug(self._fetch_word())
    self.cycles += 5


def _op_php(self: CPU6502) -> None:
    self._push(self.status | int(StatusFlag.BREAK | StatusFlag.UNUSED))
    self.cycles += 3


def _op_plp(self: CPU6502) -> None:
    self.status = (self._pull() & ~int(StatusFlag.BREAK)) | int(StatusFlag.UNUSED)
    self.cycles += 4


def _op_pha(self: CPU6502) -> None:
    self._push(self.a)
    self.cycles += 3


def _op_pla(self: CPU6502) -> None:
    self.a = self._pull()
    self._set_zn(self.a)
    self.cycles += 4


def _op_txs(self: CPU6502) -> None:
    self.sp = self.x
    self.cycles += 2


def _op_tsx(self: CPU6502) -> None:
    self.x = self.sp
    self._set_zn(self.x)
    self.cycles += 2


def _op_tax(self: CPU6502) -> None:
    self.x = self.a
    self._set_zn(self.x)
    self.cycles += 2


def _op_tay(self: CPU6502) -> None:
    self.y = self.a
    self._set_zn(self.y)
    self.cycles += 2


def _op_txa(self: CPU6502) -> None:
    self.a = self.x
    self._set_zn(self.a)
    self.cycles += 2


def _op_tya(self: CPU6502) -> None:
    self.a = self.y
    self._set_zn(self.a)
    self.cycles += 2


def _op_clv(self: CPU6502) -> None:
    self.set_flag(StatusFlag.OVERFLOW, False)
    self.cycles += 2


def _op_bit_zp(self: CPU6502) -> None:
    self._read_op(self._addr_zp, self._bit, 3)


def _op_bit_abs(self: CPU6502) -> None:
    self._read_op(self._addr_abs, self._bit, 4)


def _install_official_opcodes() -> None:
    read_ops = {
        "_ora": [
            (0x09, "_imm", 2, False),
            (0x05, "_addr_zp", 3, False),
            (0x15, "_addr_zpx", 4, False),
            (0x0D, "_addr_abs", 4, False),
            (0x1D, "_addr_absx", 4, True),
            (0x19, "_addr_absy", 4, True),
            (0x01, "_addr_indx", 6, False),
            (0x11, "_addr_indy", 5, True),
        ],
        "_and": [
            (0x29, "_imm", 2, False),
            (0x25, "_addr_zp", 3, False),
            (0x35, "_addr_zpx", 4, False),
            (0x2D, "_addr_abs", 4, False),
            (0x3D, "_addr_absx", 4, True),
            (0x39, "_addr_absy", 4, True),
            (0x21, "_addr_indx", 6, False),
            (0x31, "_addr_indy", 5, True),
        ],
        "_eor": [
            (0x49, "_imm", 2, False),
            (0x45, "_addr_zp", 3, False),
            (0x55, "_addr_zpx", 4, False),
            (0x4D, "_addr_abs", 4, False),
            (0x5D, "_addr_absx", 4, True),
            (0x59, "_addr_absy", 4, True),
            (0x41, "_addr_indx", 6, False),
            (0x51, "_addr_indy", 5, True),
        ],
        "_adc": [
            (0x69, "_imm", 2, False),
            (0x65, "_addr_zp", 3, False),
            (0x75, "_addr_zpx", 4, False),
            (0x6D, "_addr_abs", 4, False),
            (0x7D, "_addr_absx", 4, True),
            (0x79, "_addr_absy", 4, True),
            (0x61, "_addr_indx", 6, False),
            (0x71, "_addr_indy", 5, True),
        ],
        "_sbc": [
            (0xE9, "_imm", 2, False),
            (0xE5, "_addr_zp", 3, False),
            (0xF5, "_addr_zpx", 4, False),
            (0xED, "_addr_abs", 4, False),
            (0xFD, "_addr_absx", 4, True),
            (0xF9, "_addr_absy", 4, True),
            (0xE1, "_addr_indx", 6, False),
            (0xF1, "_addr_indy", 5, True),
        ],
        "_lda": [
            (0xA9, "_imm", 2, False),
            (0xA5, "_addr_zp", 3, False),
            (0xB5, "_addr_zpx", 4, False),
            (0xAD, "_addr_abs", 4, False),
            (0xBD, "_addr_absx", 4, True),
            (0xB9, "_addr_absy", 4, True),
            (0xA1, "_addr_indx", 6, False),
            (0xB1, "_addr_indy", 5, True),
        ],
        "_ldx": [
            (0xA2, "_imm", 2, False),
            (0xA6, "_addr_zp", 3, False),
            (0xB6, "_addr_zpy", 4, False),
            (0xAE, "_addr_abs", 4, False),
            (0xBE, "_addr_absy", 4, True),
        ],
        "_ldy": [
            (0xA0, "_imm", 2, False),
            (0xA4, "_addr_zp", 3, False),
            (0xB4, "_addr_zpx", 4, False),
            (0xAC, "_addr_abs", 4, False),
            (0xBC, "_addr_absx", 4, True),
        ],
        "_cmp": [
            (0xC9, "_imm", 2, False),
            (0xC5, "_addr_zp", 3, False),
            (0xD5, "_addr_zpx", 4, False),
            (0xCD, "_addr_abs", 4, False),
            (0xDD, "_addr_absx", 4, True),
            (0xD9, "_addr_absy", 4, True),
            (0xC1, "_addr_indx", 6, False),
            (0xD1, "_addr_indy", 5, True),
        ],
        "_cpx": [(0xE0, "_imm", 2, False), (0xE4, "_addr_zp", 3, False), (0xEC, "_addr_abs", 4, False)],
        "_cpy": [(0xC0, "_imm", 2, False), (0xC4, "_addr_zp", 3, False), (0xCC, "_addr_abs", 4, False)],
    }
    for operation, specs in read_ops.items():
        for opcode, addr_mode, cycles, page_cycle in specs:
            setattr(CPU6502, f"_op_{opcode:02x}", _make_read_op(operation, addr_mode, cycles, page_cycle))

    stores = [
        ("a", [(0x85, "_addr_zp", 3), (0x95, "_addr_zpx", 4), (0x8D, "_addr_abs", 4), (0x9D, "_addr_absx", 5), (0x99, "_addr_absy", 5), (0x81, "_addr_indx", 6), (0x91, "_addr_indy", 6)]),
        ("x", [(0x86, "_addr_zp", 3), (0x96, "_addr_zpy", 4), (0x8E, "_addr_abs", 4)]),
        ("y", [(0x84, "_addr_zp", 3), (0x94, "_addr_zpx", 4), (0x8C, "_addr_abs", 4)]),
    ]
    for register, specs in stores:
        for opcode, addr_mode, cycles in specs:
            setattr(CPU6502, f"_op_{opcode:02x}", _make_store_op(register, addr_mode, cycles))

    modifies = {
        "_asl_value": [(0x06, "_addr_zp", 5), (0x16, "_addr_zpx", 6), (0x0E, "_addr_abs", 6), (0x1E, "_addr_absx", 7)],
        "_rol_value": [(0x26, "_addr_zp", 5), (0x36, "_addr_zpx", 6), (0x2E, "_addr_abs", 6), (0x3E, "_addr_absx", 7)],
        "_lsr_value": [(0x46, "_addr_zp", 5), (0x56, "_addr_zpx", 6), (0x4E, "_addr_abs", 6), (0x5E, "_addr_absx", 7)],
        "_ror_value": [(0x66, "_addr_zp", 5), (0x76, "_addr_zpx", 6), (0x6E, "_addr_abs", 6), (0x7E, "_addr_absx", 7)],
        "_dec_value": [(0xC6, "_addr_zp", 5), (0xD6, "_addr_zpx", 6), (0xCE, "_addr_abs", 6), (0xDE, "_addr_absx", 7)],
        "_inc_value": [(0xE6, "_addr_zp", 5), (0xF6, "_addr_zpx", 6), (0xEE, "_addr_abs", 6), (0xFE, "_addr_absx", 7)],
    }
    for operation, specs in modifies.items():
        for opcode, addr_mode, cycles in specs:
            setattr(CPU6502, f"_op_{opcode:02x}", _make_modify_op(operation, addr_mode, cycles))

    for opcode, operation in [(0x0A, "_asl_value"), (0x2A, "_rol_value"), (0x4A, "_lsr_value"), (0x6A, "_ror_value")]:
        setattr(CPU6502, f"_op_{opcode:02x}", _make_accumulator_op(operation))

    for opcode, flag, expected in [
        (0x10, StatusFlag.NEGATIVE, False),
        (0x30, StatusFlag.NEGATIVE, True),
        (0x50, StatusFlag.OVERFLOW, False),
        (0x70, StatusFlag.OVERFLOW, True),
        (0x90, StatusFlag.CARRY, False),
        (0xB0, StatusFlag.CARRY, True),
        (0xD0, StatusFlag.ZERO, False),
        (0xF0, StatusFlag.ZERO, True),
    ]:
        setattr(CPU6502, f"_op_{opcode:02x}", _make_branch_op(flag, expected))

    for opcode, flag, value in [
        (0x18, StatusFlag.CARRY, False),
        (0x38, StatusFlag.CARRY, True),
        (0x58, StatusFlag.INTERRUPT_DISABLE, False),
        (0x78, StatusFlag.INTERRUPT_DISABLE, True),
        (0xD8, StatusFlag.DECIMAL, False),
        (0xF8, StatusFlag.DECIMAL, True),
    ]:
        setattr(CPU6502, f"_op_{opcode:02x}", _make_flag_op(flag, value))

    for opcode, source, destination in [
        (0xAA, "a", "x"),
        (0xA8, "a", "y"),
        (0x8A, "x", "a"),
        (0x98, "y", "a"),
    ]:
        setattr(CPU6502, f"_op_{opcode:02x}", _make_transfer_op(source, destination))

    for opcode, register, delta in [(0xE8, "x", 1), (0xC8, "y", 1), (0xCA, "x", -1), (0x88, "y", -1)]:
        setattr(CPU6502, f"_op_{opcode:02x}", _make_inc_register_op(register, delta))

    fixed = {
        0x00: _op_brk,
        0x08: _op_php,
        0x20: _op_jsr,
        0x24: _op_bit_zp,
        0x28: _op_plp,
        0x2C: _op_bit_abs,
        0x40: _op_rti,
        0x48: _op_pha,
        0x4C: _op_jmp_abs,
        0x60: _op_rts,
        0x68: _op_pla,
        0x6C: _op_jmp_ind,
        0x9A: _op_txs,
        0xBA: _op_tsx,
        0xB8: _op_clv,
        0xEA: _op_nop,
    }
    for opcode, method in fixed.items():
        setattr(CPU6502, f"_op_{opcode:02x}", method)


_install_official_opcodes()

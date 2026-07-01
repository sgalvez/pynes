"""Debug tracing, disassembly, and smoke validation helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .cpu import CPU6502, StatusFlag
from .nes import NES

DisassemblerOperand = tuple[int, str]

ADDRESSING_MODES: dict[int, DisassemblerOperand] = {
    0x00: (1, "BRK"),
    0x01: (2, "ORA ($%02X,X)"),
    0x05: (2, "ORA $%02X"),
    0x06: (2, "ASL $%02X"),
    0x08: (1, "PHP"),
    0x09: (2, "ORA #$%02X"),
    0x0A: (1, "ASL A"),
    0x0D: (3, "ORA $%04X"),
    0x0E: (3, "ASL $%04X"),
    0x10: (2, "BPL $%04X"),
    0x11: (2, "ORA ($%02X),Y"),
    0x15: (2, "ORA $%02X,X"),
    0x16: (2, "ASL $%02X,X"),
    0x18: (1, "CLC"),
    0x19: (3, "ORA $%04X,Y"),
    0x1D: (3, "ORA $%04X,X"),
    0x1E: (3, "ASL $%04X,X"),
    0x20: (3, "JSR $%04X"),
    0x21: (2, "AND ($%02X,X)"),
    0x24: (2, "BIT $%02X"),
    0x25: (2, "AND $%02X"),
    0x26: (2, "ROL $%02X"),
    0x28: (1, "PLP"),
    0x29: (2, "AND #$%02X"),
    0x2A: (1, "ROL A"),
    0x2C: (3, "BIT $%04X"),
    0x2D: (3, "AND $%04X"),
    0x2E: (3, "ROL $%04X"),
    0x30: (2, "BMI $%04X"),
    0x31: (2, "AND ($%02X),Y"),
    0x35: (2, "AND $%02X,X"),
    0x36: (2, "ROL $%02X,X"),
    0x38: (1, "SEC"),
    0x39: (3, "AND $%04X,Y"),
    0x3D: (3, "AND $%04X,X"),
    0x3E: (3, "ROL $%04X,X"),
    0x40: (1, "RTI"),
    0x48: (1, "PHA"),
    0x4C: (3, "JMP $%04X"),
    0x60: (1, "RTS"),
    0x68: (1, "PLA"),
    0x69: (2, "ADC #$%02X"),
    0x6C: (3, "JMP ($%04X)"),
    0x8D: (3, "STA $%04X"),
    0x90: (2, "BCC $%04X"),
    0xA0: (2, "LDY #$%02X"),
    0xA2: (2, "LDX #$%02X"),
    0xA9: (2, "LDA #$%02X"),
    0xAA: (1, "TAX"),
    0xD0: (2, "BNE $%04X"),
    0xE8: (1, "INX"),
    0xEA: (1, "NOP"),
    0xF0: (2, "BEQ $%04X"),
}

BRANCH_OPCODES = {0x10, 0x30, 0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0}


@dataclass(frozen=True)
class SmokeTestResult:
    """Summary from a fixed-instruction emulator smoke run."""

    instructions: int
    cpu_cycles: int
    pc: int
    frame: int


def status_flags(status: int) -> str:
    """Format processor status flags in NV-BDIZC order."""
    flag_order = [
        ("N", StatusFlag.NEGATIVE),
        ("V", StatusFlag.OVERFLOW),
        ("U", StatusFlag.UNUSED),
        ("B", StatusFlag.BREAK),
        ("D", StatusFlag.DECIMAL),
        ("I", StatusFlag.INTERRUPT_DISABLE),
        ("Z", StatusFlag.ZERO),
        ("C", StatusFlag.CARRY),
    ]
    return "".join(name if status & int(flag) else name.lower() for name, flag in flag_order)


def disassemble_instruction(cpu: CPU6502, address: int | None = None) -> str:
    """Return a small single-instruction disassembly string."""
    pc = cpu.pc if address is None else address & 0xFFFF
    opcode = cpu.bus.read(pc)
    length, template = ADDRESSING_MODES.get(opcode, (1, "???"))
    operands = [cpu.bus.read(pc + index) for index in range(1, length)]
    if opcode in BRANCH_OPCODES and operands:
        offset = operands[0] - 0x100 if operands[0] & 0x80 else operands[0]
        target = (pc + 2 + offset) & 0xFFFF
        text = template % target
    elif length == 2:
        text = template % operands[0]
    elif length == 3:
        text = template % (operands[0] | (operands[1] << 8))
    else:
        text = template
    bytes_text = " ".join(f"{cpu.bus.read(pc + index):02X}" for index in range(length))
    return f"{bytes_text:<8} {text}"


def format_cpu_trace(cpu: CPU6502, *, include_disassembly: bool = False) -> str:
    """Format CPU state before executing the next instruction."""
    opcode = cpu.bus.read(cpu.pc)
    parts = [
        f"PC={cpu.pc:04X}",
        f"OP={opcode:02X}",
        f"A={cpu.a:02X}",
        f"X={cpu.x:02X}",
        f"Y={cpu.y:02X}",
        f"SP={cpu.sp:02X}",
        f"P={cpu.status:02X}({status_flags(cpu.status)})",
        f"CYC={cpu.cycles}",
    ]
    if include_disassembly:
        parts.append(disassemble_instruction(cpu))
    return " ".join(parts)


def make_trace_callback(
    sink: Callable[[str], object],
    *,
    include_disassembly: bool = False,
) -> Callable[[CPU6502], None]:
    """Create a callback suitable for `NES.run(..., trace_callback=...)`."""

    def trace(cpu: CPU6502) -> None:
        sink(format_cpu_trace(cpu, include_disassembly=include_disassembly))

    return trace


def open_trace_sink(path: str | Path | None) -> tuple[Callable[[str], object], TextIO | None]:
    """Return a trace sink and optional file handle that must be closed."""
    if path is None:
        return print, None
    handle = Path(path).open("w", encoding="utf-8")
    return lambda line: print(line, file=handle), handle


def run_smoke_test(
    rom_path: str | Path,
    *,
    instructions: int,
    trace_sink: Callable[[str], object] | None = None,
    include_disassembly: bool = False,
) -> SmokeTestResult:
    """Load a ROM and step a fixed instruction count without opening a window."""
    nes = NES.from_ines_file(rom_path)
    callback = (
        make_trace_callback(trace_sink, include_disassembly=include_disassembly)
        if trace_sink is not None
        else None
    )
    cpu_cycles = nes.run(instructions, trace_callback=callback)
    return SmokeTestResult(
        instructions=instructions,
        cpu_cycles=cpu_cycles,
        pc=nes.cpu.pc,
        frame=nes.ppu.frame,
    )

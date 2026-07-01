from __future__ import annotations

from nes_py.cpu import CPU6502, MemoryBus
from nes_py.debug import disassemble_instruction, format_cpu_trace, run_smoke_test
from tests.test_nes import build_test_rom


def make_cpu(program: bytes) -> CPU6502:
    bus = MemoryBus()
    bus.load(0x8000, program)
    bus.write(0xFFFC, 0x00)
    bus.write(0xFFFD, 0x80)
    cpu = CPU6502(bus)
    cpu.reset()
    return cpu


def test_disassemble_instruction_formats_operands() -> None:
    cpu = make_cpu(bytes([0xA9, 0x42, 0xF0, 0xFC]))

    assert disassemble_instruction(cpu) == "A9 42    LDA #$42"
    assert disassemble_instruction(cpu, 0x8002) == "F0 FC    BEQ $8000"


def test_cpu_trace_includes_required_registers_flags_cycles_and_disassembly() -> None:
    cpu = make_cpu(bytes([0xA9, 0x42]))

    line = format_cpu_trace(cpu, include_disassembly=True)

    assert "PC=8000" in line
    assert "OP=A9" in line
    assert "A=00" in line
    assert "X=00" in line
    assert "Y=00" in line
    assert "SP=FD" in line
    assert "P=24" in line
    assert "CYC=7" in line
    assert "LDA #$42" in line


def test_nes_run_invokes_trace_callback_before_each_instruction() -> None:
    from nes_py.nes import NES

    nes = NES.from_ines_rom(build_test_rom(bytes([0xA9, 0x01, 0xEA])))
    pcs: list[int] = []

    nes.run(2, trace_callback=lambda cpu: pcs.append(cpu.pc))

    assert pcs == [0x8000, 0x8002]


def test_run_smoke_test_loads_and_steps_rom(tmp_path) -> None:
    rom_path = tmp_path / "smoke.nes"
    rom_path.write_bytes(build_test_rom(bytes([0xA9, 0x01, 0xEA])))
    traces: list[str] = []

    result = run_smoke_test(
        rom_path,
        instructions=2,
        trace_sink=traces.append,
        include_disassembly=True,
    )

    assert result.instructions == 2
    assert result.cpu_cycles == 4
    assert result.pc == 0x8003
    assert len(traces) == 2
    assert "LDA #$01" in traces[0]

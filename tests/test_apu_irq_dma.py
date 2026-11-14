"""Generated-ROM tests for CPU/APU IRQs and instruction-boundary DMC DMA."""

from nes_py.apu import APU
from nes_py.nes import NES
from tests.test_nes import build_test_rom


def irq_rom(program=b"\x58\xea\x4c\x01\x80", handler=b"\xe6\x00\xad\x15\x40\x40"):
    rom = bytearray(build_test_rom(program, prg_banks=2))
    rom[16 + 0x1000 : 16 + 0x1000 + len(handler)] = handler
    rom[16 + 0x2000] = 0x40  # NMI: RTI
    rom[16 + 0x4000 : 16 + 0x4100] = bytes([0x0F]) * 256  # Sample at $C000.
    rom[16 + 0x7FFA : 16 + 0x8000] = b"\x00\xa0\x00\x80\x00\x90"
    return bytes(rom)


def start_dmc(nes, *, length=1, control=0x4F):
    for address, value in (
        (0x4017, 0x40),
        (0x4010, control),
        (0x4011, 64),
        (0x4012, 0),
        (0x4013, length),
        (0x4015, 0x10),
    ):
        nes.bus.write(address, value)


def test_frame_irq_reaches_the_cpu_without_pcm_reads_and_handler_acknowledges_it() -> (
    None
):
    nes = NES.from_ines_rom(irq_rom(), audio_sample_rate=44100)
    nes.run_frame()
    nes.run_frame()
    assert nes.bus.read(0) == 1
    assert not nes.cpu.irq_line
    assert not nes.apu.frame_irq
    assert nes.cpu.pc in (0x8001, 0x8002)
    assert nes.cpu_cycles == nes.cpu.cycles == nes.apu.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3


def test_generated_program_starts_dmc_and_services_its_irq_once() -> None:
    program = bytearray()
    for address, value in (
        (0x4017, 0x40),
        (0x4010, 0x8F),
        (0x4011, 64),
        (0x4012, 0),
        (0x4013, 0),
        (0x4015, 0x10),
    ):
        program.extend((0xA9, value, 0x8D, address & 255, address >> 8))
    program.extend(b"\x58\xea")
    loop = 0x8000 + len(program)
    program.extend((0x4C, loop & 255, loop >> 8))
    # Save the IRQ source, acknowledge DMC via $4015, count entries, and return.
    handler = b"\xad\x15\x40\x85\x01\xa9\x00\x8d\x15\x40\xe6\x00\x40"
    nes = NES.from_ines_rom(irq_rom(bytes(program), handler), audio_sample_rate=44100)
    nes.run(100)
    assert nes.bus.read(0) == 1
    assert nes.bus.read(1) == 0x80
    assert not nes.cpu.irq_line and not nes.apu.dmc.irq
    assert nes.cpu.pc == loop
    assert nes.cpu_cycles == nes.apu.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3


def test_dmc_fetch_stalls_are_added_to_cpu_ppu_and_apu_clocks() -> None:
    nes = NES.from_ines_rom(irq_rom(b"\x4c\x00\x80"), audio_sample_rate=44100)
    reads = []
    original = nes.apu.dmc_reader

    def read(address):
        reads.append(address)
        return original(address)

    nes.apu.dmc_reader = read
    start_dmc(nes)
    before = nes.cpu_cycles
    cycles = nes.run(2000)  # Every opcode is JMP $8000: three cycles.
    assert len(reads) > 10
    assert cycles == 2000 * 3 + 3 + 4 * (len(reads) - 1)
    assert nes.cpu_cycles == before + cycles == nes.apu.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3
    assert nes.apu.take_dma_stall_cycles() == 0
    count = len(reads)
    nes.apu.drain_samples()
    assert len(reads) == count  # Draining cannot introduce unaccounted fetches.


def test_oam_dma_dmc_dma_and_nmi_keep_all_clocks_synchronized() -> None:
    nes = NES.from_ines_rom(irq_rom(b"\x4c\x00\x80"), audio_sample_rate=44100)
    start_dmc(nes)
    nes.bus.write(0x2000, 0x80)
    nes.bus.write(0x4014, 0)
    assert nes.step() >= 513 + 3 + 3
    assert not nes.bus.dma_pending
    for _ in range(2):
        nes.run_frame()
        nes.apu.drain_samples()
    assert nes.cpu_cycles == nes.cpu.cycles == nes.apu.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3
    assert nes.apu.dmc.bytes_remaining > 0


def test_dmc_reads_each_byte_through_the_current_mapper_bank() -> None:
    header = bytearray(16)
    header[:4] = b"NES\x1a"
    header[4], header[5], header[6] = 4, 1, 0x10  # MMC1
    prg = bytearray().join(bytes([bank * 0x11]) * 16384 for bank in range(4))
    prg[:3] = b"\x4c\x00\x80"
    prg[-4:-2] = b"\x00\x80"
    nes = NES.from_ines_rom(bytes(header) + prg + bytes(8192), audio_sample_rate=44100)
    mapper = nes.cartridge.mapper
    mapper.control = 0x08  # Fixed first bank at $8000; switchable bank at $C000.
    mapper.prg_bank = 1
    reads = []
    original = nes.apu.dmc_reader

    def read(address):
        value = original(address)
        reads.append((address, value))
        return value

    nes.apu.dmc_reader = read
    start_dmc(nes, control=15)
    assert reads == [(0xC000, 0x11)]
    mapper.prg_bank = 2
    while len(reads) < 2 and nes.cpu_cycles < 2000:
        nes.step()
    assert reads[:2] == [(0xC000, 0x11), (0xC001, 0x22)]


def test_cpu_synchronization_stays_batched_at_memory_fetches(monkeypatch) -> None:
    nes = NES.from_ines_rom(irq_rom(b"\x4c\x00\x80"), audio_sample_rate=44100)
    nes.bus.write(0x4017, 0x40)
    calls = []
    original = APU.flush

    def flush(apu):
        calls.append(apu.cpu_cycles)
        return original(apu)

    monkeypatch.setattr(APU, "flush", flush)
    nes.run(1000)
    assert calls == []
    start_dmc(nes)
    calls.clear()
    nes.run(1000)
    assert 0 < len(calls) < 20


def test_reset_clears_cpu_irq_and_pending_dmc_stalls() -> None:
    nes = NES.from_ines_rom(irq_rom(), audio_sample_rate=44100)
    start_dmc(nes, length=0, control=0x8F)
    assert nes.cpu.irq_line
    nes.reset()
    assert not nes.cpu.irq_line and not nes.apu.irq_asserted
    assert nes.apu.take_dma_stall_cycles() == 0
    assert nes.apu.dmc.sample_buffer is None
    assert nes.cpu_cycles == nes.apu.cpu_cycles == 7
    assert nes.ppu_cycles == 21


def test_stress_benchmark_keeps_fetching_when_the_game_disables_dmc() -> None:
    from scripts.profile_performance import enable_dmc_stress

    # The game repeatedly enables only pulse 1, which normally stops DMC reads.
    nes = NES.from_ines_rom(
        irq_rom(b"\xa9\x01\x8d\x15\x40\x4c\x00\x80"), audio_sample_rate=44100
    )
    reads = []
    original = nes.apu.dmc_reader

    def read(address):
        reads.append(address)
        return original(address)

    nes.apu.dmc_reader = read
    enable_dmc_stress(nes)
    nes.run_frame()
    assert len(reads) > 50
    assert nes.apu.dmc.bytes_remaining > 0
    assert nes.cpu_cycles == nes.apu.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3

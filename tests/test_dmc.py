"""DMC output, memory-reader, status, and shared IRQ regressions."""

from itertools import pairwise

import pytest

from nes_py.apu import APU, DMC_PERIODS, NTSC_CPU_HZ, DMCChannel
from tests.test_apu import decode


def sample_apu(*, data=0x0F, loop=False, irq=False, length=0, rate=15):
    reads = []

    def read(address):
        reads.append(address)
        return data

    apu = APU(dmc_reader=read)
    for address, value in (
        (0x4017, 0x40),
        (0x4010, (0x80 if irq else 0) | (0x40 if loop else 0) | rate),
        (0x4011, 64),
        (0x4012, 0),
        (0x4013, length),
        (0x4015, 0x10),
    ):
        apu.write_register(address, value)
    return apu, reads


@pytest.mark.parametrize("index,period", tuple(enumerate(DMC_PERIODS)))
def test_dmc_registers_use_ntsc_rate_and_sample_address_length(index, period) -> None:
    apu = APU()
    apu.write_register(0x4010, index)
    assert apu.dmc.timer_period == period
    apu.write_register(0x4012, 0xFF)
    apu.write_register(0x4013, 0xFF)
    assert apu.dmc.sample_address == 0xFFC0
    assert apu.dmc.sample_length == 4081
    assert apu.read_status() == 0


@pytest.mark.parametrize("data", (0x00, 0xFF, 0x55, 0xAA, 0x81))
@pytest.mark.parametrize("initial", (0, 1, 64, 125, 126, 127))
def test_dmc_decodes_lsb_first_and_never_wraps_the_dac(data, initial) -> None:
    reads = []
    dmc = DMCChannel(
        reader=lambda address, load: reads.append((address, load)) or data,
        timer_period=54,
        timer_remaining=54,
        output_level=initial,
    )
    dmc.set_enabled(True)
    assert reads == [(0xC000, True)]
    dmc.advance(54 * 8)  # Finish the silent cycle and load the first byte.
    assert dmc.output_level == initial and not dmc.silence
    expected = initial
    for bit in range(8):
        if (data >> bit) & 1:
            if expected <= 125:
                expected += 2
        elif expected >= 2:
            expected -= 2
        dmc.advance(54)
        assert dmc.output_level == expected
    assert dmc.silence
    dmc.advance(54 * 100)
    assert dmc.output_level == expected
    assert len(reads) == 1


def test_dmc_wraps_ffff_to_8000_and_asserts_irq_on_the_last_fetch() -> None:
    reads = []
    dmc = DMCChannel(
        reader=lambda address, load: reads.append(address) or 0,
        irq_enabled=True,
        timer_period=54,
        timer_remaining=54,
        sample_address=0xFFC0,
        sample_length=65,
    )
    dmc.set_enabled(True)
    assert not dmc.irq
    dmc.advance(54 * 8 * 63)
    assert dmc.bytes_remaining == 1 and not dmc.irq
    dmc.advance(54 * 8)
    assert reads == list(range(0xFFC0, 0x10000)) + [0x8000]
    assert dmc.current_address == 0x8001
    assert dmc.bytes_remaining == 0 and dmc.irq
    assert dmc.sample_buffer == 0  # IRQ occurs while the last byte is buffered.


def test_dmc_loop_restarts_the_reader_and_suppresses_irq() -> None:
    apu, reads = sample_apu(loop=True, irq=True)
    apu.step(10000)
    assert len(reads) > 10
    assert set(reads) == {0xC000}
    assert apu.read_status() == 0x10
    assert not apu.dmc.irq and not apu.irq_asserted


def test_dmc_status_acknowledges_irq_only_on_4015_write_or_4010_disable() -> None:
    levels = []
    apu, _ = sample_apu(irq=True)
    apu.irq_callback = levels.append
    assert apu.irq_asserted and apu.read_status() == 0x80
    assert apu.read_status() == 0x80
    apu.step(29829)
    assert apu.read_status() == 0x80  # Frame IRQ was inhibited by the helper.
    apu.write_register(0x4017, 0)
    apu.step(29829)
    assert apu.read_status() == 0xC0
    assert apu.read_status() == 0x80
    assert apu.irq_asserted
    apu.write_register(0x4010, 0x0F)
    assert not apu.irq_asserted and apu.read_status() == 0
    assert levels == [False]
    apu.write_register(0x4010, 0x8F)
    apu.write_register(0x4015, 0x10)
    assert apu.read_status() == 0x80
    apu.write_register(0x4015, 0)
    assert apu.read_status() == 0
    assert levels == [False, True, False]


def test_disabling_dmc_preserves_buffered_audio_and_held_dac() -> None:
    apu, reads = sample_apu(data=0, length=1)
    assert apu.read_status() == 0x10
    apu.write_register(0x4015, 0)
    assert apu.read_status() == 0
    assert apu.dmc.sample_buffer == 0
    apu.step(10000)
    assert apu.dmc.output_level == 48
    assert apu.dmc.silence
    assert reads == [0xC000]
    apu.write_register(0x4011, 0xFF)
    apu.write_register(0x4015, 0)
    assert apu.dmc.output_level == 127


def test_reenabling_dmc_does_not_restart_an_active_reader_or_discard_its_buffer() -> (
    None
):
    apu, reads = sample_apu(length=1)
    assert apu.dmc.bytes_remaining == 16
    apu.write_register(0x4012, 3)
    apu.write_register(0x4013, 2)
    apu.write_register(0x4015, 0x10)
    assert apu.dmc.current_address == 0xC001
    assert apu.dmc.bytes_remaining == 16
    assert reads == [0xC000]
    apu.write_register(0x4015, 0)
    apu.write_register(0x4015, 0x10)
    assert apu.dmc.current_address == 0xC0C0
    assert apu.dmc.bytes_remaining == 33
    assert reads == [0xC000]  # Old buffered data is consumed before the next read.


def test_dmc_timer_runs_while_idle_and_rate_writes_preserve_phase() -> None:
    dmc = DMCChannel(timer_period=54, timer_remaining=54)
    dmc.advance(54 * 3 + 17)
    assert dmc.bits_remaining == 5 and dmc.timer_remaining == 37
    dmc.write(0, 0)
    assert dmc.timer_remaining == 37 and dmc.timer_period == 428
    dmc.set_enabled(True)
    dmc.advance(37 + 428 * 4 - 1)
    assert dmc.silence
    dmc.advance(1)
    assert not dmc.silence


def test_dmc_chunking_and_deferred_writes_preserve_pcm_reader_and_stalls() -> None:
    whole, whole_reads = sample_apu(loop=True, length=1)
    chunked, chunked_reads = sample_apu(loop=True, length=1)
    deferred, deferred_reads = sample_apu(loop=True, length=1)
    for cycles, register, value in (
        (1537, 0x4010, 0xC8),
        (9, 0x4011, 97),
        (11007, 0x4012, 2),
        (313, 0x4015, 0),
        (617, 0x4015, 16),
        (17777, 0x4013, 0),
    ):
        whole.step(cycles)
        left = cycles
        while left:
            step = min(left, 7)
            chunked.step(step)
            left -= step
        deferred.cpu_cycles += cycles
        for apu in (whole, chunked, deferred):
            apu.write_register(register, value)
    assert whole.drain_samples() == chunked.drain_samples() == deferred.drain_samples()
    assert whole.dmc == chunked.dmc == deferred.dmc
    assert whole_reads == chunked_reads == deferred_reads
    assert (
        whole.take_dma_stall_cycles()
        == chunked.take_dma_stall_cycles()
        == deferred.take_dma_stall_cycles()
    )


@pytest.mark.parametrize("rate", (0, 8, 15))
def test_looped_dpcm_frequency_follows_the_cpu_timer(rate) -> None:
    apu, _ = sample_apu(loop=True, rate=rate)
    apu.step(NTSC_CPU_HZ)
    samples = decode(apu.drain_samples())
    # Exclude the initial DAC/DC transient before counting steady-state periods.
    settled = samples[4410:]
    crossings = sum(left <= 0 < right for left, right in pairwise(settled))
    frequency = NTSC_CPU_HZ / (8 * DMC_PERIODS[rate])
    assert len(samples) == 44100
    assert abs(crossings - frequency * len(settled) / 44100) < 2
    assert min(samples) < -100 < 100 < max(samples)


def test_reset_clears_dmc_irq_dma_audio_and_reader_state() -> None:
    apu, reads = sample_apu(irq=True)
    apu.step(1000)
    apu.cpu_cycles += 20000
    apu.reset()
    assert apu.read_status() == 0 and not apu.irq_asserted
    assert apu.dmc.output_level == 0
    assert apu.dmc.sample_buffer is None
    assert apu.take_dma_stall_cycles() == 0
    assert apu.drain_samples() == b""
    apu.step(10000)
    assert set(decode(apu.drain_samples())) == {0}
    assert len(reads) == 1

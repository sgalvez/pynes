"""APU regressions use generated programs and numerical PCM checks."""

import sys
from array import array
from itertools import pairwise

import pytest

from nes_py.apu import APU, NOISE_PERIODS, NTSC_CPU_HZ, NoiseChannel
from nes_py.input import Button
from nes_py.nes import NES
from tests.test_nes import build_test_rom


def tone(*, period=253, control=0xBF, channel=1) -> APU:
    apu = APU()
    apu.write_register(0x4017, 0x40)
    apu.write_register(0x4015, 1 << (channel - 1))
    base = 0x4000 + (channel - 1) * 4
    apu.write_register(base, control)
    apu.write_register(base + 1, 0x08)
    apu.write_register(base + 2, period & 0xFF)
    apu.write_register(base + 3, 0x08 | (period >> 8))
    return apu


def ensemble() -> APU:
    apu = tone(control=0x82)
    apu.write_register(0x4015, 0x0F)
    for address, value in (
        (0x4004, 0x7B),
        (0x4005, 8),
        (0x4006, 126),
        (0x4007, 8),
        (0x4008, 0x83),
        (0x400A, 253),
        (0x400B, 8),
        (0x400C, 2),
        (0x400E, 4),
        (0x400F, 8),
    ):
        apu.write_register(address, value)
    return apu


def decode(pcm: bytes) -> array:
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


@pytest.mark.parametrize("period,frequency", [(253, 440.4), (126, 880.8)])
@pytest.mark.parametrize("channel", (1, 2))
def test_pulse_frequency_and_pcm_duration_follow_cpu_clock(
    period, frequency, channel
) -> None:
    apu = tone(period=period, channel=channel)
    apu.step(NTSC_CPU_HZ)
    samples = decode(apu.drain_samples())
    assert len(samples) == 44100
    assert min(samples) < -1000 < 1000 < max(samples)
    crossings = sum(left <= 0 < right for left, right in pairwise(samples))
    assert abs(crossings - frequency) < 2
    assert abs(sum(samples) / len(samples)) < 100


@pytest.mark.parametrize("duty,high_steps", [(0, 1), (1, 2), (2, 4), (3, 6)])
@pytest.mark.parametrize("channel", (1, 2))
def test_four_pulse_duties_have_expected_high_time(duty, high_steps, channel) -> None:
    apu = tone(control=(duty << 6) | 0x3F, channel=channel)
    pulse = getattr(apu, f"pulse{channel}")
    levels = []
    for _ in range(8):
        pulse.advance(2 * 254)
        levels.append(pulse.output())
    assert levels.count(15) == high_steps


@pytest.mark.parametrize("factory", (tone, ensemble))
def test_chunk_boundaries_do_not_change_generated_audio(factory) -> None:
    whole, chunked = factory(), factory()
    whole.step(100000)
    remaining = 100000
    sizes = (1, 3, 8, 13, 512, 11)
    index = 0
    while remaining:
        size = min(remaining, sizes[index % len(sizes)])
        chunked.step(size)
        remaining -= size
        index += 1
    assert chunked.cpu_cycles == whole.cpu_cycles
    assert chunked.pulse1.length_counter == whole.pulse1.length_counter
    assert chunked.pulse1.envelope_decay == whole.pulse1.envelope_decay
    assert chunked.pulse2 == whole.pulse2
    assert chunked.triangle == whole.triangle
    assert chunked.noise == whole.noise
    assert chunked.drain_samples() == whole.drain_samples()


def test_pulse_enable_length_load_and_disable_status() -> None:
    apu = APU()
    apu.write_register(0x4003, 0x18)
    assert apu.read_status() == 0
    apu.write_register(0x4015, 1)
    assert apu.read_status() == 0
    apu.write_register(0x4003, 0x18)  # Length-table entry 3 is two half-frames.
    assert apu.read_status() == 1
    apu.step(14912)
    assert apu.pulse1.length_counter == 2
    apu.step(1)
    assert apu.pulse1.length_counter == 1
    apu.step(14916)
    assert apu.read_status() & 1 == 0
    apu.write_register(0x4003, 0x18)
    apu.write_register(0x4015, 0)
    assert apu.pulse1.length_counter == 0


def test_halt_preserves_length_and_envelope_loops() -> None:
    apu = tone(control=0xA0)
    length = apu.pulse1.length_counter
    apu.step(7457)
    assert apu.pulse1.envelope_decay == 15
    apu.step(14913 - 7457)
    assert apu.pulse1.envelope_decay == 14
    assert apu.pulse1.length_counter == length
    for _ in range(15):
        apu.pulse1.quarter_frame()
    assert apu.pulse1.envelope_decay == 15


def test_envelope_divider_delays_decay() -> None:
    apu = tone(control=0x82)
    apu.pulse1.quarter_frame()
    assert apu.pulse1.envelope_decay == 15
    apu.pulse1.quarter_frame()
    apu.pulse1.quarter_frame()
    assert apu.pulse1.envelope_decay == 15
    apu.pulse1.quarter_frame()
    assert apu.pulse1.envelope_decay == 14


@pytest.mark.parametrize("channel,expected", [(1, 499), (2, 500)])
def test_sweep_negation_differs_between_pulse_channels(channel, expected) -> None:
    apu = tone(period=1000, channel=channel)
    apu.write_register(0x4001 + (channel - 1) * 4, 0x89)
    apu.step(14913)
    assert getattr(apu, f"pulse{channel}").timer_period == expected


@pytest.mark.parametrize("period,sweep", [(7, 0x08), (1500, 0x01), (1024, 0)])
def test_invalid_period_or_sweep_target_silences_pulse(period, sweep) -> None:
    apu = tone(period=period)
    apu.write_register(0x4001, sweep)
    apu.step(NTSC_CPU_HZ // 20)
    assert set(decode(apu.drain_samples())) == {0}


def test_four_step_irq_status_acknowledge_inhibit_and_five_step_mode() -> None:
    apu = APU()
    apu.step(29828)
    assert not apu.frame_irq
    apu.step(1)
    assert apu.read_status() == 0x40
    assert apu.read_status() == 0
    apu.step(29830)
    assert apu.frame_irq
    apu.write_register(0x4017, 0x40)
    assert not apu.frame_irq
    apu.step(29830)
    assert apu.read_status() == 0
    apu.write_register(0x4017, 0x80)
    apu.step(37282 * 2)
    assert not apu.frame_irq


@pytest.mark.parametrize("factory", (tone, ensemble))
def test_reset_silences_channels_and_discards_pending_audio(factory) -> None:
    apu = factory()
    apu.step(10000)
    apu.reset()
    assert apu.cpu_cycles == 0
    assert apu.drain_samples() == b""
    assert apu.read_status() == 0
    apu.step(10000)
    assert set(decode(apu.drain_samples())) == {0}


def test_pcm_buffer_is_bounded_and_draining_consumes_samples() -> None:
    apu = tone()
    apu.step(NTSC_CPU_HZ * 2)
    assert len(apu.drain_samples()) == 44100 * 2
    assert apu.drain_samples() == b""


@pytest.mark.parametrize("sample_rate", (0, -1, NTSC_CPU_HZ + 1))
def test_invalid_sample_rates_are_rejected(sample_rate) -> None:
    with pytest.raises(ValueError, match="sample_rate"):
        APU(sample_rate)


def test_negative_cycles_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        APU().step(-1)


def test_cpu_rom_writes_drive_apu_and_dma_nmi_cycles_stay_synchronized() -> None:
    program = bytearray()
    for address, value in (
        (0x4017, 0x40),
        (0x4015, 1),
        (0x4000, 0xBF),
        (0x4001, 8),
        (0x4002, 253),
        (0x4003, 8),
    ):
        program.extend((0xA9, value, 0x8D, address & 0xFF, address >> 8))
    loop = 0x8000 + len(program)
    program.extend((0x4C, loop & 0xFF, loop >> 8))
    nes = NES.from_ines_rom(build_test_rom(bytes(program)), audio_sample_rate=44100)
    assert nes.apu is not None
    assert nes.apu.cpu_cycles == nes.cpu_cycles == 7
    nes.bus.write(0x4014, 0)
    nes.bus.write(0x2000, 0x80)
    nes.run_frame()
    assert nes.apu.cpu_cycles == nes.cpu.cycles == nes.cpu_cycles
    assert nes.ppu_cycles == nes.cpu_cycles * 3
    assert any(decode(nes.apu.drain_samples()))
    nes.reset()
    assert nes.apu.cpu_cycles == 7
    assert not nes.apu.pulse1.enabled


def test_4017_writes_configure_apu_and_reads_still_use_controller_two() -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\xea"), audio_sample_rate=44100)
    assert nes.apu is not None
    nes.controller2.set_button(Button.A, True)
    nes.bus.write(0x4016, 1)
    nes.bus.write(0x4016, 0)
    nes.bus.write(0x4017, 0xC0)
    assert nes.apu.five_step and nes.apu.irq_inhibit
    assert nes.bus.read(0x4017) == 1
    assert nes.bus.read(0x4017) == 0


def test_direct_dmc_dac_outputs_pcm_without_enabling_memory_playback() -> None:
    apu = APU()
    apu.write_register(0x4011, 0xFF)
    apu.step(10000)
    assert apu.read_status() == 0
    assert apu.dmc.output_level == 127
    assert max(decode(apu.drain_samples())) > 1000


def test_write_only_apu_registers_read_open_bus_and_status_preserves_it() -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\xea"), audio_sample_rate=44100)
    nes.bus.write(0x4000, 0xBF)
    nes.bus.write(0, 0xAB)
    assert nes.bus.read(0x4000) == 0xAB
    assert nes.bus.read(0x4015) == 0x20
    assert nes.bus.open_bus == 0xAB


def test_apu_is_opt_in() -> None:
    assert NES.from_ines_rom(build_test_rom(b"\xea")).apu is None


def test_deferred_cpu_time_preserves_all_channels_across_register_writes_and_status_reads() -> (
    None
):
    immediate, deferred = ensemble(), ensemble()
    actions = (
        (7, 0x4002, 126),
        (11, 0x4000, 0xA3),
        (7447, 0x4003, 0x18),
        (12345, 0x4001, 0x89),
        (3, 0x4005, 0x89),
        (333, 0x4007, 0x18),
        (11, 0x4008, 0x01),
        (17, 0x400B, 0x18),
        (997, 0x400E, 0x80),
        (1, 0x400F, 0x18),
        (12287, None, None),
        (3, 0x4017, 0xC0),
        (7651, 0x4015, 0),
        (137, 0x4015, 0x0F),
        (17, 0x4003, 0x08),
        (30000, None, None),
    )
    for cycles, address, value in actions:
        # The CPU can publish time in small instruction increments without
        # synthesizing until an observable APU access or PCM read.
        remaining = cycles
        while remaining:
            instruction = min(3, remaining)
            deferred.cpu_cycles += instruction
            remaining -= instruction
        immediate.step(cycles)
        if address is None:
            assert deferred.read_status() == immediate.read_status()
        else:
            deferred.write_register(address, value)
            immediate.write_register(address, value)
    deferred.cpu_cycles += 1777
    immediate.step(1777)
    assert deferred.drain_samples() == immediate.drain_samples()
    assert deferred.pulse1 == immediate.pulse1
    assert deferred.pulse2 == immediate.pulse2
    assert deferred.triangle == immediate.triangle
    assert deferred.noise == immediate.noise


@pytest.mark.parametrize("channel", ("pulse1", "pulse2", "triangle", "noise"))
def test_hardware_state_observation_flushes_deferred_cpu_time(channel) -> None:
    immediate, deferred = ensemble(), ensemble()
    deferred.cpu_cycles = 12345
    immediate.step(12345)
    assert getattr(deferred, channel) == getattr(immediate, channel)
    irq = APU()
    irq.cpu_cycles = 29829
    assert irq.frame_irq
    assert irq.read_status() == 0x40
    assert not irq.frame_irq


def test_reset_discards_unrendered_audio_time() -> None:
    apu = tone()
    apu.cpu_cycles = NTSC_CPU_HZ
    apu.reset()
    apu.step(10000)
    assert apu.cpu_cycles == 10000
    assert set(decode(apu.drain_samples())) == {0}


@pytest.mark.parametrize("mask", (0, 1, 2, 4, 8, 5, 10, 15))
def test_each_channel_enable_and_status_bit_are_independent(mask) -> None:
    apu = ensemble()
    assert apu.read_status() == 15
    apu.write_register(0x4015, mask)
    assert apu.read_status() == mask
    apu.write_register(0x4015, 15)  # Re-enabling does not reload length counters.
    assert apu.read_status() == mask


def test_half_frames_clock_length_for_all_channels() -> None:
    apu = ensemble()
    for base in (0x4000, 0x4004, 0x4008, 0x400C):
        apu.write_register(base, 1)  # No length halt/control flag.
        apu.write_register(base + 3, 0x18)  # Two half-frames.
    apu.step(14913)
    assert apu.read_status() == 15
    assert [
        apu.pulse1.length_counter,
        apu.pulse2.length_counter,
        apu.triangle.length_counter,
        apu.noise.length_counter,
    ] == [1] * 4
    apu.step(29829 - 14913)
    assert apu.read_status() == 0


def test_five_step_write_clocks_all_channels_immediately() -> None:
    apu = ensemble()
    apu.write_register(0x4017, 0xC0)
    assert apu.pulse1.envelope_decay == apu.noise.envelope_decay == 15
    assert apu.triangle.linear_counter == 3
    assert apu.pulse1.length_counter == 253


@pytest.mark.parametrize("period,frequency", [(253, 220.2), (126, 440.4)])
def test_triangle_frequency_and_pcm_follow_cpu_clock(period, frequency) -> None:
    apu = APU()
    for address, value in (
        (0x4015, 4),
        (0x4008, 0xFF),
        (0x400A, period),
        (0x400B, 8),
        (0x4017, 0xC0),
    ):
        apu.write_register(address, value)
    apu.step(NTSC_CPU_HZ)
    samples = decode(apu.drain_samples())
    assert len(samples) == 44100
    assert min(samples) < -1000 < 1000 < max(samples)
    crossings = sum(left <= 0 < right for left, right in pairwise(samples))
    assert abs(crossings - frequency) < 2


def test_triangle_linear_counter_reload_control_and_held_output() -> None:
    apu = ensemble()
    apu.write_register(0x4008, 2)
    apu.step(7457)
    assert apu.triangle.linear_counter == 2
    assert not apu.triangle.linear_reload
    apu.step(14913 - 7457)
    assert apu.triangle.linear_counter == 1
    apu.step(22371 - 14913)
    assert apu.triangle.linear_counter == 0
    phase, level = apu.triangle.sequence_index, apu.triangle.output()
    assert apu.read_status() & 4  # Status reports length, not the linear gate.
    apu.step(10000)
    assert (apu.triangle.sequence_index, apu.triangle.output()) == (phase, level)
    apu.write_register(0x4008, 0x83)
    apu.triangle.quarter_frame()
    assert apu.triangle.linear_counter == 0  # $4008 does not set reload flag.
    apu.write_register(0x400B, 8)
    assert apu.triangle.sequence_index == phase  # High writes preserve phase.
    apu.triangle.quarter_frame()
    apu.triangle.quarter_frame()
    assert apu.triangle.linear_counter == 3
    assert apu.triangle.linear_reload
    apu.step(1000)
    assert apu.triangle.sequence_index != phase
    apu.write_register(0x4015, 0)
    held = apu.triangle.output()
    apu.step(10000)
    assert apu.triangle.output() == held


@pytest.mark.parametrize("period", (0, 1))
def test_ultrasonic_triangle_is_averaged_instead_of_aliasing(period) -> None:
    apu = APU()
    for address, value in (
        (0x4015, 4),
        (0x4008, 0xFF),
        (0x400A, period),
        (0x400B, 8),
        (0x4017, 0xC0),
    ):
        apu.write_register(address, value)
    apu.step(NTSC_CPU_HZ // 4)
    samples = decode(apu.drain_samples())
    assert max(samples) > 1000  # DC transition passes through the high-pass.
    assert set(samples[-1000:]) == {0}


@pytest.mark.parametrize("short_mode,tap", ((False, 1), (True, 6)))
@pytest.mark.parametrize(
    "initial,steps",
    ((1, 1), (1, 93), (1, 32767), (0x1234, 512), (0x4000, 50000), (0x7FFF, 101)),
)
def test_noise_fast_advancement_matches_bitwise_hardware(
    short_mode, tap, initial, steps
) -> None:
    noise = NoiseChannel(short_mode=short_mode, shift_register=initial)
    expected = initial
    for _ in range(steps):
        feedback = ((expected >> tap) ^ expected) & 1
        expected = (expected >> 1) | (feedback << 14)
    noise.advance(steps * 4)
    assert noise.shift_register == expected
    assert noise.timer_remaining == 4


def test_noise_mode_and_period_changes_preserve_state_and_timer_phase() -> None:
    noise = NoiseChannel()
    noise.advance(3)
    noise.write(2, 0x84)
    assert noise.shift_register == 1
    assert noise.timer_remaining == 1
    noise.advance(1)
    assert noise.shift_register == 0x4000
    assert noise.timer_remaining == 64
    noise.write(2, 0)
    assert noise.shift_register == 0x4000
    assert noise.timer_remaining == 64
    noise.advance(63)
    assert noise.shift_register == 0x4000
    noise.advance(1)
    assert noise.shift_register == 0x2000
    assert noise.timer_remaining == 4


def test_noise_period_table_gating_envelope_and_disabled_length_load() -> None:
    apu = APU()
    for index, period in enumerate(NOISE_PERIODS):
        apu.write_register(0x400E, index)
        assert apu.noise.timer_period == period
    apu.write_register(0x400F, 8)
    assert apu.noise.length_counter == 0
    apu.write_register(0x4015, 8)
    apu.write_register(0x400C, 0x20)  # Looping envelope, period zero.
    apu.write_register(0x400F, 8)
    apu.step(7457)
    assert apu.noise.envelope_decay == 15
    apu.noise.shift_register = 2
    assert apu.noise.output() == 15
    apu.step(14913 - 7457)
    assert apu.noise.envelope_decay == 14
    assert apu.noise.length_counter == 254
    for _ in range(15):
        apu.noise.quarter_frame()
    assert apu.noise.envelope_decay == 15
    apu.write_register(0x400C, 0x3A)
    apu.noise.shift_register = 2
    assert apu.noise.output() == 10
    apu.noise.shift_register = 3
    assert apu.noise.output() == 0
    apu.write_register(0x4015, 0)
    apu.noise.shift_register = 2
    assert apu.noise.output() == 0


def test_mixed_audio_has_headroom_without_clipping() -> None:
    apu = ensemble()
    for address in (0x4000, 0x4004, 0x400C):
        apu.write_register(address, 0xBF)
    apu.step(NTSC_CPU_HZ)
    samples = decode(apu.drain_samples())
    assert min(samples) < -1000 < 1000 < max(samples)
    assert all(-32768 < sample < 32767 for sample in samples)
    assert len(set(samples)) > 1000


@pytest.mark.parametrize(
    "levels",
    ((0, 0, 0, 0), (15, 0, 0, 0), (0, 15, 0, 0), (15, 15, 15, 15), (10, 7, 3, 5)),
)
@pytest.mark.parametrize("dmc", (0, 64, 127))
def test_nonlinear_mixer_preserves_hardware_channel_balance(levels, dmc) -> None:
    apu = APU(sample_rate=NTSC_CPU_HZ)  # Observe exactly the first CPU-cycle sample.
    apu.write_register(0x4015, 15)
    pulse1, pulse2, triangle, noise = levels
    for base, volume in ((0x4000, pulse1), (0x4004, pulse2)):
        for offset, value in ((0, 0xB0 | volume), (1, 8), (2, 253), (3, 8)):
            apu.write_register(base + offset, value)
    apu.pulse1.sequence_index = apu.pulse2.sequence_index = 1
    # Hold known DAC values without depending on oscillator phase.
    apu.triangle.sequence_index = 15 - triangle
    apu.write_register(0x400C, 0x30 | noise)
    apu.write_register(0x400F, 8)
    apu.noise.shift_register = 2
    apu.write_register(0x4011, dmc)
    apu.step(1)
    pulse_sum = pulse1 + pulse2
    pulse_mix = 95.88 / (8128 / pulse_sum + 100) if pulse_sum else 0
    tnd_input = triangle / 8227 + noise / 12241 + dmc / 22638
    tnd_mix = 159.79 / (1 / tnd_input + 100) if tnd_input else 0
    maximum = 95.88 / (8128 / 30 + 100) + 159.79 / (
        1 / (15 / 8227 + 15 / 12241 + 127 / 22638) + 100
    )
    gain = 0.8 * 32767 / maximum
    high_pass = 1 / (1 + 2 * 3.141592653589793 * 90 / NTSC_CPU_HZ)
    assert decode(apu.drain_samples()) == array(
        "h", [round((pulse_mix + tnd_mix) * gain * high_pass)]
    )


def test_noise_shift_register_keeps_running_while_channel_is_disabled() -> None:
    apu = APU()
    apu.step(400)
    expected = NoiseChannel()
    expected.advance(400)
    assert apu.noise.shift_register == expected.shift_register != 1
    assert apu.noise.output() == 0
    state = apu.noise.shift_register
    apu.write_register(0x4015, 8)
    apu.write_register(0x400F, 8)
    assert apu.noise.shift_register == state


def test_cpu_generated_program_activates_all_four_status_bits() -> None:
    program = bytearray()
    for address, value in (
        (0x4017, 0x40),
        (0x4015, 0x1F),
        (0x4003, 8),
        (0x4007, 8),
        (0x400B, 8),
        (0x400F, 8),
    ):
        program.extend((0xA9, value, 0x8D, address & 255, address >> 8))
    program.extend((0xAD, 0x15, 0x40, 0x85, 0x00))  # LDA $4015; STA $00
    nes = NES.from_ines_rom(build_test_rom(bytes(program)), audio_sample_rate=44100)
    for _ in range(14):
        nes.step()
    assert nes.bus.read(0) == 0x0F  # The default one-byte DMC read already ended.

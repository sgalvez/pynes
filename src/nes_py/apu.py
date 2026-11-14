"""Experimental five-channel NTSC APU, driven by elapsed CPU cycles.

Register writes, IRQ delivery, and DMC DMA use instruction boundaries.
See docs/apu/pilot.md for the remaining timing limits.
"""

from __future__ import annotations

import math
import sys
from array import array
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

NTSC_CPU_HZ = 1_789_773
DEFAULT_SAMPLE_RATE = 44_100
LENGTH_TABLE = (
    10,
    254,
    20,
    2,
    40,
    4,
    80,
    6,
    160,
    8,
    60,
    10,
    14,
    12,
    26,
    14,
    12,
    16,
    24,
    18,
    48,
    20,
    96,
    22,
    192,
    24,
    72,
    26,
    16,
    28,
    32,
    30,
)
DUTY_SEQUENCES = (
    (0, 1, 0, 0, 0, 0, 0, 0),
    (0, 1, 1, 0, 0, 0, 0, 0),
    (0, 1, 1, 1, 1, 0, 0, 0),
    (1, 0, 0, 1, 1, 1, 1, 1),
)
# Quarter/half-frame events, expressed in CPU cycles from the sequence origin.
FOUR_STEP_EVENTS = ((7457, False), (14913, True), (22371, False), (29829, True))
FIVE_STEP_EVENTS = ((7457, False), (14913, True), (22371, False), (37281, True))
TRIANGLE_SEQUENCE = tuple(range(15, -1, -1)) + tuple(range(16))
NOISE_PERIODS = (
    4,
    8,
    16,
    32,
    64,
    96,
    128,
    160,
    202,
    254,
    380,
    508,
    762,
    1016,
    2034,
    4068,
)
DMC_PERIODS = (
    428,
    380,
    340,
    320,
    286,
    254,
    226,
    214,
    190,
    160,
    142,
    128,
    106,
    84,
    72,
    54,
)
NO_CPU_EVENT = sys.maxsize
PULSE_MIX = (0.0,) + tuple(95.88 / (8128.0 / level + 100) for level in range(1, 31))
# The final triangle row represents the filtered 7.5 average at ultrasonic
# periods. Fixed five-channel gain preserves the relative hardware levels.
PCM_GAIN = (
    0.8
    * 32767
    / (
        PULSE_MIX[30]
        + 159.79 / (1.0 / (15 / 8227.0 + 15 / 12241.0 + 127 / 22638.0) + 100)
    )
)
PULSE_PCM = tuple(level * PCM_GAIN for level in PULSE_MIX)
TND_PCM = array(
    "d",
    (
        PCM_GAIN
        * 159.79
        / (1.0 / (triangle / 8227.0 + noise / 12241.0 + dmc / 22638.0) + 100)
        if triangle or noise or dmc
        else 0.0
        for triangle in (*range(16), 7.5)
        for noise in range(16)
        for dmc in range(128)
    ),
)


@dataclass
class Envelope:
    """Volume/envelope unit shared by the pulse and noise channels."""

    constant_volume: bool = False
    length_halt: bool = False
    volume: int = 0
    envelope_start: bool = False
    envelope_divider: int = 0
    envelope_decay: int = 0

    def quarter_frame(self) -> None:
        if self.envelope_start:
            self.envelope_start = False
            self.envelope_decay = 15
            self.envelope_divider = self.volume
        elif self.envelope_divider:
            self.envelope_divider -= 1
        else:
            self.envelope_divider = self.volume
            if self.envelope_decay:
                self.envelope_decay -= 1
            elif self.length_halt:
                self.envelope_decay = 15


@dataclass
class PulseChannel(Envelope):
    """Pulse waveform with the channel-specific sweep negation correction."""

    enabled: bool = False
    duty: int = 0
    timer_period: int = 0
    length_counter: int = 0
    sequence_index: int = 0
    timer_remaining: int = 2
    negate_extra: int = 1
    sweep_enabled: bool = False
    sweep_period: int = 0
    sweep_negate: bool = False
    sweep_shift: int = 0
    sweep_divider: int = 0
    sweep_reload: bool = False

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.duty = value >> 6
            self.length_halt = bool(value & 0x20)
            self.constant_volume = bool(value & 0x10)
            self.volume = value & 0x0F
        elif register == 1:
            self.sweep_enabled = bool(value & 0x80)
            self.sweep_period = (value >> 4) & 7
            self.sweep_negate = bool(value & 8)
            self.sweep_shift = value & 7
            self.sweep_reload = True
        elif register == 2:
            self.timer_period = (self.timer_period & 0x700) | value
        elif register == 3:
            self.timer_period = (self.timer_period & 0xFF) | ((value & 7) << 8)
            if self.enabled:
                self.length_counter = LENGTH_TABLE[value >> 3]
            self.sequence_index = 0
            self.envelope_start = True

    def advance(self, cpu_cycles: int) -> None:
        self.timer_remaining -= cpu_cycles
        if self.timer_remaining <= 0:
            period = 2 * (self.timer_period + 1)
            steps = 1 + (-self.timer_remaining) // period
            self.timer_remaining += steps * period
            self.sequence_index = (self.sequence_index + steps) & 7

    def sweep_target(self) -> int:
        change = self.timer_period >> self.sweep_shift
        return (
            max(0, self.timer_period - change - self.negate_extra)
            if self.sweep_negate
            else self.timer_period + change
        )

    def output(self) -> int:
        if not self.enabled or not self.length_counter or self.timer_period < 8:
            return 0
        if (
            self.sweep_target() > 0x7FF
            or not DUTY_SEQUENCES[self.duty][self.sequence_index]
        ):
            return 0
        return self.volume if self.constant_volume else self.envelope_decay

    def half_frame(self) -> None:
        if self.length_counter and not self.length_halt:
            self.length_counter -= 1
        if (
            self.sweep_divider == 0
            and self.sweep_enabled
            and self.sweep_shift
            and self.timer_period >= 8
            and self.sweep_target() <= 0x7FF
        ):
            self.timer_period = self.sweep_target()
        if self.sweep_divider == 0 or self.sweep_reload:
            self.sweep_divider = self.sweep_period
            self.sweep_reload = False
        else:
            self.sweep_divider -= 1


@dataclass
class TriangleChannel:
    """CPU-clocked 32-step triangle with linear/length gating and held DAC."""

    enabled: bool = False
    control: bool = False
    linear_reload_value: int = 0
    linear_counter: int = 0
    linear_reload: bool = False
    length_counter: int = 0
    timer_period: int = 0
    timer_remaining: int = 1
    sequence_index: int = 15  # Quiet initial DAC; register writes preserve phase.

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.control = bool(value & 0x80)
            self.linear_reload_value = value & 0x7F
        elif register == 2:
            self.timer_period = (self.timer_period & 0x700) | value
        elif register == 3:
            self.timer_period = (self.timer_period & 0xFF) | ((value & 7) << 8)
            if self.enabled:
                self.length_counter = LENGTH_TABLE[value >> 3]
            self.linear_reload = True

    def advance(self, cpu_cycles: int) -> None:
        self.timer_remaining -= cpu_cycles
        if self.timer_remaining <= 0:
            period = self.timer_period + 1
            steps = 1 + (-self.timer_remaining) // period
            self.timer_remaining += steps * period
            if self.length_counter and self.linear_counter:
                self.sequence_index = (self.sequence_index + steps) & 31

    def output(self) -> int | float:
        if self.timer_period < 2 and self.length_counter and self.linear_counter:
            return 7.5
        return TRIANGLE_SEQUENCE[self.sequence_index]

    def quarter_frame(self) -> None:
        if self.linear_reload:
            self.linear_counter = self.linear_reload_value
        elif self.linear_counter:
            self.linear_counter -= 1
        if not self.control:
            self.linear_reload = False

    def half_frame(self) -> None:
        if self.length_counter and not self.control:
            self.length_counter -= 1


@lru_cache(maxsize=2)
def _noise_cycles(tap: int) -> tuple[array, array, array, array]:
    """Index the finite LFSR cycles for exact constant-time state advancement."""
    states = array("H")
    positions = array("H", [0]) * 32768
    starts, lengths = array("H"), array("H")
    visited = bytearray(32768)
    for origin in range(32768):
        if visited[origin]:
            continue
        state, start = origin, len(states)
        while not visited[state]:
            visited[state] = 1
            positions[state] = len(states)
            states.append(state)
            feedback = (state ^ (state >> tap)) & 1
            state = (state >> 1) | (feedback << 14)
        length = len(states) - start
        starts.extend([start] * length)
        lengths.extend([length] * length)
    return states, positions, starts, lengths


@dataclass
class NoiseChannel(Envelope):
    """15-bit LFSR noise with both tap modes, envelope, and length counter."""

    enabled: bool = False
    length_counter: int = 0
    short_mode: bool = False
    timer_period: int = 4
    timer_remaining: int = 4
    shift_register: int = 1
    _long_cycles: tuple[array, array, array, array] = field(
        init=False, repr=False, compare=False
    )
    _short_cycles: tuple[array, array, array, array] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        # Construct both cached tables at startup, avoiding a mid-song mode hitch.
        self._long_cycles = _noise_cycles(1)
        self._short_cycles = _noise_cycles(6)

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.length_halt = bool(value & 0x20)
            self.constant_volume = bool(value & 0x10)
            self.volume = value & 0x0F
        elif register == 2:
            self.short_mode = bool(value & 0x80)
            self.timer_period = NOISE_PERIODS[value & 15]
        elif register == 3:
            if self.enabled:
                self.length_counter = LENGTH_TABLE[value >> 3]
            self.envelope_start = True

    def advance(self, cpu_cycles: int) -> None:
        self.timer_remaining -= cpu_cycles
        if self.timer_remaining <= 0:
            steps = 1 + (-self.timer_remaining) // self.timer_period
            self.timer_remaining += steps * self.timer_period
            states, positions, starts, lengths = (
                self._short_cycles if self.short_mode else self._long_cycles
            )
            position = positions[self.shift_register]
            start = starts[position]
            position = start + (position - start + steps) % lengths[position]
            self.shift_register = states[position]

    def output(self) -> int:
        if not self.enabled or not self.length_counter or self.shift_register & 1:
            return 0
        return self.volume if self.constant_volume else self.envelope_decay

    def half_frame(self) -> None:
        if self.length_counter and not self.length_halt:
            self.length_counter -= 1


@dataclass
class DMCChannel:
    """Buffered delta playback, continuously running bit timer, and held DAC.

    The reader receives (address, initial_load), so the host can charge the
    nominal three-cycle load or four-cycle refill stall without per-cycle work.
    """

    reader: Callable[[int, bool], int] | None = field(
        default=None, repr=False, compare=False
    )
    irq_enabled: bool = False
    loop: bool = False
    irq: bool = False
    timer_period: int = DMC_PERIODS[0]
    timer_remaining: int = DMC_PERIODS[0]
    output_level: int = 0
    sample_address: int = 0xC000
    sample_length: int = 1
    current_address: int = 0xC000
    bytes_remaining: int = 0
    sample_buffer: int | None = None
    shift_register: int = 0
    bits_remaining: int = 8
    silence: bool = True

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.irq_enabled = bool(value & 0x80)
            self.loop = bool(value & 0x40)
            self.timer_period = DMC_PERIODS[value & 15]
            if not self.irq_enabled:
                self.irq = False
        elif register == 1:
            self.output_level = value & 0x7F
        elif register == 2:
            self.sample_address = 0xC000 | (value << 6)
        elif register == 3:
            self.sample_length = (value << 4) | 1

    def set_enabled(self, enabled: bool) -> None:
        self.irq = False  # Every $4015 write acknowledges DMC IRQ.
        if not enabled:
            self.bytes_remaining = 0
        elif not self.bytes_remaining:
            self._restart()
            self._fill_buffer(initial_load=True)

    def _restart(self) -> None:
        self.current_address = self.sample_address
        self.bytes_remaining = self.sample_length

    def _fill_buffer(self, *, initial_load: bool = False) -> None:
        if self.sample_buffer is not None or not self.bytes_remaining:
            return
        self.sample_buffer = (
            self.reader(self.current_address, initial_load) & 0xFF
            if self.reader is not None
            else 0
        )
        self.current_address = (self.current_address + 1) & 0xFFFF or 0x8000
        self.bytes_remaining -= 1
        if not self.bytes_remaining:
            if self.loop:
                self._restart()
            elif self.irq_enabled:
                self.irq = True

    def advance(self, cpu_cycles: int) -> None:
        self.timer_remaining -= cpu_cycles
        if self.timer_remaining > 0:
            return
        clocks = 1 + (-self.timer_remaining) // self.timer_period
        self.timer_remaining += clocks * self.timer_period
        if self.silence and self.sample_buffer is None:
            # The silent output unit still advances its eight-bit phase.
            self.bits_remaining = (self.bits_remaining - clocks - 1) % 8 + 1
            if self.shift_register:
                self.shift_register >>= clocks
            return
        for _ in range(clocks):
            if not self.silence:
                if self.shift_register & 1:
                    if self.output_level <= 125:
                        self.output_level += 2
                elif self.output_level >= 2:
                    self.output_level -= 2
            self.shift_register >>= 1
            self.bits_remaining -= 1
            if not self.bits_remaining:
                self.bits_remaining = 8
                self.silence = self.sample_buffer is None
                if not self.silence:
                    self.shift_register = self.sample_buffer
                    self.sample_buffer = None
                    self._fill_buffer()

    def cycles_until_fetch(self) -> int:
        if not self.bytes_remaining:
            return NO_CPU_EVENT
        if self.sample_buffer is None:
            return 0
        return self.timer_remaining + (self.bits_remaining - 1) * self.timer_period


@dataclass
class APU:
    """Five channels mixed into bounded mono signed 16-bit little-endian PCM."""

    sample_rate: int = DEFAULT_SAMPLE_RATE
    dmc_reader: Callable[[int], int] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    irq_callback: Callable[[bool], None] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _pulse1: PulseChannel = field(default_factory=PulseChannel, init=False, repr=False)
    _pulse2: PulseChannel = field(
        default_factory=lambda: PulseChannel(negate_extra=0), init=False, repr=False
    )
    _triangle: TriangleChannel = field(
        default_factory=TriangleChannel, init=False, repr=False
    )
    _noise: NoiseChannel = field(default_factory=NoiseChannel, init=False, repr=False)
    _dmc: DMCChannel = field(init=False, repr=False)
    _channels: tuple[PulseChannel, PulseChannel, TriangleChannel, NoiseChannel] = field(
        init=False, repr=False, compare=False
    )
    cpu_cycles: int = field(default=0, init=False)
    _processed_cycles: int = field(default=0, init=False)
    _frame_irq: bool = field(default=False, init=False, repr=False)
    irq_asserted: bool = field(default=False, init=False)
    next_cpu_event: int = field(default=29829, init=False)
    _dma_stall_cycles: int = field(default=0, init=False, repr=False)
    five_step: bool = field(default=False, init=False)
    irq_inhibit: bool = field(default=False, init=False)
    _samples: deque[int] = field(init=False, repr=False)
    _sample_index: int = field(default=0, init=False)
    _frame_origin: int = field(default=0, init=False)
    _frame_index: int = field(default=0, init=False)
    _next_sample: int = field(init=False)
    _next_frame: int = field(default=7457, init=False)
    _next_event: int = field(init=False)
    _filter_alpha: float = field(init=False)
    _last_input: float = field(default=0.0, init=False)
    _last_output: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if not 1 <= self.sample_rate <= NTSC_CPU_HZ:
            raise ValueError(f"sample_rate must be between 1 and {NTSC_CPU_HZ}")
        self._channels = (self._pulse1, self._pulse2, self._triangle, self._noise)
        self._dmc = DMCChannel(reader=self._read_dmc_byte)
        self._samples = deque(maxlen=self.sample_rate)
        self._filter_alpha = 1.0 / (1.0 + 2.0 * math.pi * 90.0 / self.sample_rate)
        self._next_sample = (NTSC_CPU_HZ + self.sample_rate - 1) // self.sample_rate
        self._next_event = min(self._next_sample, self._next_frame)

    def reset(self) -> None:
        self._pulse1 = PulseChannel()
        self._pulse2 = PulseChannel(negate_extra=0)
        self._triangle = TriangleChannel()
        self._noise = NoiseChannel()
        self._dmc = DMCChannel(reader=self._read_dmc_byte)
        self._channels = (self._pulse1, self._pulse2, self._triangle, self._noise)
        self.cpu_cycles = self._sample_index = self._frame_origin = (
            self._frame_index
        ) = 0
        self._processed_cycles = 0
        self._frame_irq = self.five_step = self.irq_inhibit = False
        self._dma_stall_cycles = 0
        self._samples.clear()
        self._last_input = self._last_output = 0.0
        self._next_frame = 7457
        self._next_sample = (NTSC_CPU_HZ + self.sample_rate - 1) // self.sample_rate
        self._next_event = min(self._next_sample, self._next_frame)
        self._update_cpu_event()

    @property
    def pulse1(self) -> PulseChannel:
        """Synchronize the channel before exposing its hardware state."""
        self.flush()
        return self._pulse1

    @property
    def pulse2(self) -> PulseChannel:
        self.flush()
        return self._pulse2

    @property
    def triangle(self) -> TriangleChannel:
        self.flush()
        return self._triangle

    @property
    def noise(self) -> NoiseChannel:
        self.flush()
        return self._noise

    @property
    def dmc(self) -> DMCChannel:
        self.flush()
        return self._dmc

    @property
    def frame_irq(self) -> bool:
        """Expose IRQ status at the current CPU time, including deferred events."""
        self.flush()
        return self._frame_irq

    def write_register(self, address: int, value: int) -> None:
        # Render elapsed time with the old settings before applying this write.
        self.flush()
        value &= 0xFF
        if 0x4000 <= address <= 0x400F:
            self._channels[(address - 0x4000) >> 2].write(address & 3, value)
        elif 0x4010 <= address <= 0x4013:
            self._dmc.write(address & 3, value)
        elif address == 0x4015:
            for index, channel in enumerate(self._channels):
                channel.enabled = bool(value & (1 << index))
                if not channel.enabled:
                    channel.length_counter = 0
            self._dmc.set_enabled(bool(value & 0x10))
        elif address == 0x4017:
            self.five_step = bool(value & 0x80)
            self.irq_inhibit = bool(value & 0x40)
            if self.irq_inhibit:
                self._frame_irq = False
            self._frame_origin = self.cpu_cycles
            self._frame_index = 0
            self._next_frame = self._frame_origin + 7457
            if self.five_step:
                for channel in self._channels:
                    channel.quarter_frame()
                    channel.half_frame()
            self._next_event = min(self._next_sample, self._next_frame)
        self._update_cpu_event()

    def read_status(self) -> int:
        self.flush()
        status = (
            sum(
                1 << index
                for index, channel in enumerate(self._channels)
                if channel.length_counter
            )
            | (0x10 if self._dmc.bytes_remaining else 0)
            | (0x40 if self._frame_irq else 0)
            | (0x80 if self._dmc.irq else 0)
        )
        self._frame_irq = False
        self._update_cpu_event()
        return status

    def _read_dmc_byte(self, address: int, initial_load: bool) -> int:
        self._dma_stall_cycles += 3 if initial_load else 4
        return self.dmc_reader(address) if self.dmc_reader is not None else 0

    def take_dma_stall_cycles(self) -> int:
        """Consume nominal DMC stalls; the NES feeds these back into all clocks."""
        cycles, self._dma_stall_cycles = self._dma_stall_cycles, 0
        self._update_cpu_event()
        return cycles

    def _update_cpu_event(self) -> None:
        # Only frame IRQs and memory fetches need CPU synchronization. Sample
        # generation can still be deferred across thousands of instructions.
        frame = (
            self._frame_origin + 29829
            if not (self.five_step or self.irq_inhibit or self._frame_irq)
            else NO_CPU_EVENT
        )
        fetch = self._dmc.cycles_until_fetch()
        self.next_cpu_event = min(frame, self._processed_cycles + fetch)
        if self._dma_stall_cycles:
            self.next_cpu_event = min(self.next_cpu_event, self._processed_cycles)
        asserted = self._frame_irq or self._dmc.irq
        if asserted != self.irq_asserted:
            self.irq_asserted = asserted
            if self.irq_callback is not None:
                self.irq_callback(asserted)

    def step(self, cpu_cycles: int) -> None:
        if cpu_cycles < 0:
            raise ValueError("cpu_cycles must be non-negative")
        self.cpu_cycles += cpu_cycles
        self.flush()

    def flush(self) -> None:
        """Synthesize the published CPU timeline at sample/frame event boundaries.

        NES advances cpu_cycles with its CPU clock and flushes on APU I/O or PCM
        consumption. Standalone callers can keep using step(cycles).
        """
        target = self.cpu_cycles
        if target < self._next_event:
            self._advance_channels(target - self._processed_cycles)
            self._processed_cycles = target
            self._update_cpu_event()
            return
        while self._next_event <= target:
            event = self._next_event
            self._advance_channels(event - self._processed_cycles)
            self._processed_cycles = event
            if event == self._next_frame:
                self._clock_frame()
            if event == self._next_sample:
                self._sample()
                self._sample_index += 1
                self._next_sample = (
                    (self._sample_index + 1) * NTSC_CPU_HZ + self.sample_rate - 1
                ) // self.sample_rate
            self._next_event = min(self._next_sample, self._next_frame)
        self._advance_channels(target - self._processed_cycles)
        self._processed_cycles = target
        self._update_cpu_event()

    def _advance_channels(self, cpu_cycles: int) -> None:
        if cpu_cycles:
            for channel in self._channels:
                channel.advance(cpu_cycles)
            self._dmc.advance(cpu_cycles)

    def _clock_frame(self) -> None:
        events = FIVE_STEP_EVENTS if self.five_step else FOUR_STEP_EVENTS
        for channel in self._channels:
            channel.quarter_frame()
            if events[self._frame_index][1]:
                channel.half_frame()
        self._frame_index += 1
        if self._frame_index == len(events):
            if not self.five_step and not self.irq_inhibit:
                self._frame_irq = True
            self._frame_origin += 37282 if self.five_step else 29830
            self._frame_index = 0
        self._next_frame = self._frame_origin + events[self._frame_index][0]

    def _sample(self) -> None:
        triangle = self._triangle.output()
        triangle_index = 16 if triangle == 7.5 else triangle
        value = (
            PULSE_PCM[self._pulse1.output() + self._pulse2.output()]
            + TND_PCM[
                (triangle_index * 16 + self._noise.output()) * 128
                + self._dmc.output_level
            ]
        )
        filtered = self._filter_alpha * (self._last_output + value - self._last_input)
        self._last_input, self._last_output = value, filtered
        self._samples.append(max(-32768, min(32767, round(filtered))))

    def drain_samples(self) -> bytes:
        """Consume buffered PCM; at most the newest second is retained."""
        self.flush()
        samples = array("h", self._samples)
        self._samples.clear()
        if sys.byteorder != "little":
            samples.byteswap()
        return samples.tobytes()

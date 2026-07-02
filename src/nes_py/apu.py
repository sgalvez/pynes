"""Small NES APU foundation for pulse, triangle, and noise audio."""

from __future__ import annotations

from dataclasses import dataclass, field

CPU_CLOCK_HZ = 1_789_773
DEFAULT_AUDIO_SAMPLE_RATE = 44_100
APU_REGISTER_COUNT = 0x18
# Conservative output shaping keeps the simple APU model from clipping into
# brittle metallic peaks while preserving recognizable pulse/triangle melodies.
AUDIO_LOW_PASS_ALPHA = 0.18
AUDIO_OUTPUT_GAIN = 1.25
NOISE_MIX_GAIN = 0.58
NOISE_OUTPUT_ALPHA = 0.16
NOISE_PERIODS: tuple[int, ...] = (
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


def poly_blep(phase: float, phase_step: float) -> float:
    """Return a compact band-limited edge correction for pulse transitions."""
    if phase_step <= 0.0:
        return 0.0
    if phase < phase_step:
        t = phase / phase_step
        return t + t - t * t - 1.0
    if phase > 1.0 - phase_step:
        t = (phase - 1.0) / phase_step
        return t * t + t + t + 1.0
    return 0.0


@dataclass
class PulseChannel:
    """Approximate one NES pulse channel from its CPU-visible registers."""

    control: int = 0
    sweep: int = 0
    timer_low: int = 0
    timer_high: int = 0
    enabled: bool = False
    phase: float = 0.0

    @property
    def timer(self) -> int:
        return self.timer_low | ((self.timer_high & 0x07) << 8)

    @property
    def volume(self) -> int:
        return self.control & 0x0F

    @property
    def duty_cycle(self) -> float:
        return (1, 2, 4, 6)[(self.control >> 6) & 0x03] / 8

    @property
    def frequency(self) -> float:
        timer = self.timer
        if timer < 8:
            return 0.0
        return CPU_CLOCK_HZ / (16 * (timer + 1))

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.control = value
        elif register == 1:
            self.sweep = value
        elif register == 2:
            self.timer_low = value
        elif register == 3:
            self.timer_high = value
            self.phase = 0.0

    def output(self, sample_rate: int) -> float:
        if not self.enabled or self.volume == 0:
            return 0.0

        frequency = self.frequency
        if frequency <= 0.0 or frequency >= sample_rate / 2:
            return 0.0

        phase_step = frequency / sample_rate
        duty = self.duty_cycle
        sample = 1.0 if self.phase < duty else 0.0
        sample += poly_blep(self.phase, phase_step)
        sample -= poly_blep((self.phase - duty) % 1.0, phase_step)
        self.phase = (self.phase + phase_step) % 1.0
        return self.volume * max(0.0, min(1.0, sample))


@dataclass
class TriangleChannel:
    """Approximate the NES triangle channel."""

    linear_counter: int = 0
    timer_low: int = 0
    timer_high: int = 0
    enabled: bool = False
    phase: float = 0.0

    @property
    def timer(self) -> int:
        return self.timer_low | ((self.timer_high & 0x07) << 8)

    @property
    def frequency(self) -> float:
        timer = self.timer
        if timer < 2:
            return 0.0
        return CPU_CLOCK_HZ / (32 * (timer + 1))

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.linear_counter = value & 0x7F
        elif register == 2:
            self.timer_low = value
        elif register == 3:
            self.timer_high = value
            self.phase = 0.0

    def output(self, sample_rate: int) -> float:
        if not self.enabled:
            return 0.0

        frequency = self.frequency
        if frequency <= 0.0 or frequency >= sample_rate / 2:
            return 0.0

        self.phase = (self.phase + frequency / sample_rate) % 1.0
        return 15.0 * (1.0 - abs(self.phase * 2.0 - 1.0))


@dataclass
class NoiseChannel:
    """Approximate the NES noise channel with a 15-bit LFSR."""

    control: int = 0
    period: int = 0
    length: int = 0
    enabled: bool = False
    shift_register: int = 1
    cycles_since_shift: float = 0.0
    filtered_output: float = 0.0

    @property
    def volume(self) -> int:
        return self.control & 0x0F

    @property
    def period_cycles(self) -> int:
        return NOISE_PERIODS[self.period & 0x0F]

    @property
    def short_mode(self) -> bool:
        return bool(self.period & 0x80)

    def write(self, register: int, value: int) -> None:
        if register == 0:
            self.control = value
        elif register == 2:
            self.period = value
        elif register == 3:
            self.length = value

    def output(self, cycles_per_sample: float) -> float:
        if not self.enabled or self.volume == 0:
            self.filtered_output += (0.0 - self.filtered_output) * NOISE_OUTPUT_ALPHA
            return self.filtered_output

        self.cycles_since_shift += cycles_per_sample
        while self.cycles_since_shift >= self.period_cycles:
            self.cycles_since_shift -= self.period_cycles
            tap = 6 if self.short_mode else 1
            feedback = (self.shift_register & 0x01) ^ ((self.shift_register >> tap) & 0x01)
            self.shift_register = (self.shift_register >> 1) | (feedback << 14)

        raw_output = 0.0 if self.shift_register & 0x01 else float(self.volume)
        self.filtered_output += (raw_output - self.filtered_output) * NOISE_OUTPUT_ALPHA
        return self.filtered_output


@dataclass
class APU:
    """Approximate NES APU generator producing signed 16-bit mono PCM."""

    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE
    registers: bytearray = field(default_factory=lambda: bytearray(APU_REGISTER_COUNT))
    pulse1: PulseChannel = field(default_factory=PulseChannel)
    pulse2: PulseChannel = field(default_factory=PulseChannel)
    triangle: TriangleChannel = field(default_factory=TriangleChannel)
    noise: NoiseChannel = field(default_factory=NoiseChannel)
    cycles_since_sample: float = 0.0
    dc_bias: float = 0.0
    low_pass_sample: float = 0.0

    @property
    def cycles_per_sample(self) -> float:
        return CPU_CLOCK_HZ / self.sample_rate

    def reset(self) -> None:
        self.registers[:] = b"\x00" * APU_REGISTER_COUNT
        self.pulse1 = PulseChannel()
        self.pulse2 = PulseChannel()
        self.triangle = TriangleChannel()
        self.noise = NoiseChannel()
        self.cycles_since_sample = 0.0
        self.dc_bias = 0.0
        self.low_pass_sample = 0.0

    def read_register(self, address: int) -> int:
        address &= 0xFFFF
        if address == 0x4015:
            return (
                (1 if self.pulse1.enabled else 0)
                | (2 if self.pulse2.enabled else 0)
                | (4 if self.triangle.enabled else 0)
                | (8 if self.noise.enabled else 0)
            )
        if 0x4000 <= address <= 0x4017:
            return self.registers[address - 0x4000]
        return 0

    def write_register(self, address: int, value: int) -> None:
        address &= 0xFFFF
        value &= 0xFF
        if 0x4000 <= address <= 0x4017:
            self.registers[address - 0x4000] = value

        if 0x4000 <= address <= 0x4003:
            self.pulse1.write(address - 0x4000, value)
        elif 0x4004 <= address <= 0x4007:
            self.pulse2.write(address - 0x4004, value)
        elif 0x4008 <= address <= 0x400B:
            self.triangle.write(address - 0x4008, value)
        elif 0x400C <= address <= 0x400F:
            self.noise.write(address - 0x400C, value)
        elif address == 0x4015:
            self.pulse1.enabled = bool(value & 0x01)
            self.pulse2.enabled = bool(value & 0x02)
            self.triangle.enabled = bool(value & 0x04)
            self.noise.enabled = bool(value & 0x08)

    def generate_samples(self, cpu_cycles: int) -> bytes:
        """Generate little-endian signed 16-bit mono PCM for elapsed CPU cycles."""
        output = bytearray()
        self.generate_samples_into(cpu_cycles, output)
        return bytes(output)

    def generate_samples_into(self, cpu_cycles: int, output: bytearray) -> None:
        """Append little-endian signed 16-bit mono PCM for elapsed CPU cycles."""
        if cpu_cycles <= 0:
            return

        cycles_per_sample = self.cycles_per_sample
        self.cycles_since_sample += cpu_cycles
        while self.cycles_since_sample >= cycles_per_sample:
            self.cycles_since_sample -= cycles_per_sample
            mixed = self._mixed_sample()
            self.dc_bias += (mixed - self.dc_bias) * 0.001
            mixed -= self.dc_bias
            self.low_pass_sample += (mixed - self.low_pass_sample) * AUDIO_LOW_PASS_ALPHA
            mixed = self.low_pass_sample
            mixed = self._soft_clip(mixed)
            value = int(max(-1.0, min(1.0, mixed)) * 32767)
            packed = value & 0xFFFF
            output.append(packed & 0xFF)
            output.append((packed >> 8) & 0xFF)

    def _mixed_sample(self) -> float:
        pulse_sum = self.pulse1.output(self.sample_rate) + self.pulse2.output(self.sample_rate)
        pulse_out = 0.0 if pulse_sum == 0 else 95.88 / ((8128 / pulse_sum) + 100)

        triangle = self.triangle.output(self.sample_rate)
        noise = self.noise.output(self.cycles_per_sample) * NOISE_MIX_GAIN
        tnd_input = triangle / 8227 + noise / 12241
        tnd_out = 0.0 if tnd_input == 0 else 159.79 / ((1 / tnd_input) + 100)
        return (pulse_out + tnd_out) * AUDIO_OUTPUT_GAIN

    def _soft_clip(self, sample: float) -> float:
        """Round off sharp peaks before integer conversion."""
        return sample / (1.0 + abs(sample))

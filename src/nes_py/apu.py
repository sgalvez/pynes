"""Small NES APU foundation for pulse-channel audio."""

from __future__ import annotations

from dataclasses import dataclass, field

CPU_CLOCK_HZ = 1_789_773
DEFAULT_AUDIO_SAMPLE_RATE = 44_100
APU_REGISTER_COUNT = 0x18

PULSE_DUTY_PATTERNS: tuple[tuple[int, ...], ...] = (
    (0, 1, 0, 0, 0, 0, 0, 0),
    (0, 1, 1, 0, 0, 0, 0, 0),
    (0, 1, 1, 1, 1, 0, 0, 0),
    (1, 0, 0, 1, 1, 1, 1, 1),
)


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
    def duty_pattern(self) -> tuple[int, ...]:
        return PULSE_DUTY_PATTERNS[(self.control >> 6) & 0x03]

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

    def sample(self, sample_rate: int) -> float:
        if not self.enabled or self.volume == 0:
            return 0.0

        frequency = self.frequency
        if frequency <= 0.0 or frequency >= sample_rate / 2:
            return 0.0

        self.phase = (self.phase + frequency / sample_rate) % 1.0
        duty_index = int(self.phase * 8) & 0x07
        amplitude = self.volume / 15.0
        return amplitude if self.duty_pattern[duty_index] else -amplitude


@dataclass
class APU:
    """Minimal audio generator for the NES pulse channels."""

    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE
    registers: bytearray = field(default_factory=lambda: bytearray(APU_REGISTER_COUNT))
    pulse1: PulseChannel = field(default_factory=PulseChannel)
    pulse2: PulseChannel = field(default_factory=PulseChannel)
    cycles_since_sample: float = 0.0

    @property
    def cycles_per_sample(self) -> float:
        return CPU_CLOCK_HZ / self.sample_rate

    def reset(self) -> None:
        self.registers[:] = b"\x00" * APU_REGISTER_COUNT
        self.pulse1 = PulseChannel()
        self.pulse2 = PulseChannel()
        self.cycles_since_sample = 0.0

    def read_register(self, address: int) -> int:
        address &= 0xFFFF
        if address == 0x4015:
            return (1 if self.pulse1.enabled else 0) | (2 if self.pulse2.enabled else 0)
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
        elif address == 0x4015:
            self.pulse1.enabled = bool(value & 0x01)
            self.pulse2.enabled = bool(value & 0x02)

    def generate_samples(self, cpu_cycles: int) -> bytes:
        """Generate little-endian signed 16-bit mono PCM for elapsed CPU cycles."""
        if cpu_cycles <= 0:
            return b""

        output = bytearray()
        self.cycles_since_sample += cpu_cycles
        while self.cycles_since_sample >= self.cycles_per_sample:
            self.cycles_since_sample -= self.cycles_per_sample
            mixed = (self.pulse1.sample(self.sample_rate) + self.pulse2.sample(self.sample_rate)) * 0.25
            value = int(max(-1.0, min(1.0, mixed)) * 32767)
            output.extend(value.to_bytes(2, byteorder="little", signed=True))
        return bytes(output)

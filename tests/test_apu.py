from __future__ import annotations

from nes_py.apu import APU


def test_apu_pulse_registers_generate_audio_samples() -> None:
    apu = APU()
    apu.write_register(0x4000, 0xBF)
    apu.write_register(0x4002, 0xFF)
    apu.write_register(0x4003, 0x00)
    apu.write_register(0x4015, 0x01)

    audio = apu.generate_samples(1_789_773 // 60)

    assert apu.read_register(0x4015) & 0x01
    assert len(audio) > 0
    assert len(audio) % 2 == 0
    assert any(byte != 0 for byte in audio)


def test_apu_triangle_and_noise_channels_generate_audio_samples() -> None:
    apu = APU()
    apu.write_register(0x4008, 0x80)
    apu.write_register(0x400A, 0x40)
    apu.write_register(0x400B, 0x00)
    apu.write_register(0x400C, 0x0F)
    apu.write_register(0x400E, 0x02)
    apu.write_register(0x400F, 0x00)
    apu.write_register(0x4015, 0x0C)

    audio = apu.generate_samples(1_789_773 // 60)

    assert apu.read_register(0x4015) & 0x0C == 0x0C
    assert len(audio) > 0
    assert any(byte != 0 for byte in audio)

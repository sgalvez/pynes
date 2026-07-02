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

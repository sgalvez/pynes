from __future__ import annotations

import pytest

from nes_py.app import DisplayUnavailableError, KeyBindings, apply_key_event, framebuffer_to_rgb_bytes, load_pygame
from nes_py.input import Button
from nes_py.nes import NES
from tests.test_nes import build_test_rom


def test_framebuffer_to_rgb_bytes_packs_pixels() -> None:
    assert framebuffer_to_rgb_bytes([(1, 2, 3), (4, 5, 6)]) == bytes([1, 2, 3, 4, 5, 6])


def test_framebuffer_to_rgb_bytes_reuses_packed_bytearray() -> None:
    framebuffer = bytearray([1, 2, 3])

    assert framebuffer_to_rgb_bytes(framebuffer) is framebuffer


def test_apply_key_event_updates_controller_and_returns_control_actions() -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\xEA"))
    bindings = KeyBindings(
        a=1,
        b=2,
        select=3,
        start=4,
        up=5,
        down=6,
        left=7,
        right=8,
        pause=9,
        reset=10,
        quit=11,
    )

    assert apply_key_event(nes, 1, True, bindings) is None
    assert nes.controller1.buttons[Button.A]
    assert apply_key_event(nes, 1, False, bindings) is None
    assert not nes.controller1.buttons[Button.A]
    assert apply_key_event(nes, 9, True, bindings) == "pause"
    assert apply_key_event(nes, 10, True, bindings) == "reset"
    assert apply_key_event(nes, 11, True, bindings) == "quit"


def test_load_pygame_error_message_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = __import__

    def fake_import(name: str, *args, **kwargs):
        if name == "pygame":
            raise ImportError("missing pygame")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(DisplayUnavailableError, match=r"\.\[display\]"):
        load_pygame()

from __future__ import annotations

import pytest

from nes_py.app import (
    DisplayUnavailableError,
    KeyBindings,
    apply_key_event,
    framebuffer_to_rgb_bytes,
    load_pygame,
    run_desktop,
)
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


def test_run_desktop_scaled_render_does_not_pass_destination_surface(tmp_path) -> None:
    class FakeClock:
        def tick(self, fps: int) -> None:
            assert fps == 60

    class FakeDisplay:
        def set_mode(self, size):
            return self

        def set_caption(self, caption: str) -> None:
            assert caption

        def blit(self, surface, position) -> None:
            assert position == (0, 0)

        def flip(self) -> None:
            pass

    class FakePygame:
        QUIT = 1
        KEYDOWN = 2
        KEYUP = 3
        K_x = 10
        K_z = 11
        K_RSHIFT = 12
        K_RETURN = 13
        K_UP = 14
        K_DOWN = 15
        K_LEFT = 16
        K_RIGHT = 17
        K_SPACE = 18
        K_r = 19
        K_ESCAPE = 20

        def __init__(self) -> None:
            self.display = FakeDisplay()
            self.time = type("Time", (), {"Clock": FakeClock})
            self.mixer = type("Mixer", (), {"get_init": lambda *_: None})
            self.event = type("EventQueue", (), {"get": lambda *_: [type("Event", (), {"type": self.QUIT})()]})
            self.image = type("Image", (), {"frombuffer": lambda *args: object()})
            self.transform = type("Transform", (), {"scale": self.scale})

        def init(self) -> None:
            pass

        def quit(self) -> None:
            pass

        def scale(self, source, size):
            assert size == (512, 480)
            return source

    rom_path = tmp_path / "test.nes"
    rom_path.write_bytes(build_test_rom(b"\xEA"))

    assert run_desktop(rom_path, scale=2, instructions_per_frame=1, pygame_module=FakePygame()) == 0

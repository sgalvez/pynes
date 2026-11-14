from __future__ import annotations

import pytest

from nes_py.app import (
    DisplayUnavailableError,
    FrameStats,
    KeyBindings,
    apply_key_event,
    default_key_bindings,
    framebuffer_to_rgb_bytes,
    load_pygame,
)
from nes_py.input import Button
from nes_py.nes import NES
from tests.test_nes import build_test_rom


def test_frame_stats_separates_pacing_time_from_frame_work_and_resets_averages() -> (
    None
):
    stats = FrameStats(start=0)
    for index in range(1, 30):
        assert stats.record(0.010, 0.002, 0.003, index / 60) is None
    report = stats.record(0.010, 0.002, 0.003, 0.5)
    assert report == "60.0 FPS | emu 10.0 ms | audio 2.0 ms | video 3.0 ms | slow 0/30"
    for index in range(1, 25):
        assert stats.record(0.012, 0.003, 0.004, 0.5 + index / 50) is None
    report = stats.record(0.012, 0.003, 0.004, 1.0)
    assert report == "50.0 FPS | emu 12.0 ms | audio 3.0 ms | video 4.0 ms | slow 25/25"


def test_framebuffer_to_rgb_bytes_packs_pixels() -> None:
    assert framebuffer_to_rgb_bytes([(1, 2, 3), (4, 5, 6)]) == bytes([1, 2, 3, 4, 5, 6])


def test_framebuffer_to_rgb_bytes_reuses_packed_bytearray() -> None:
    framebuffer = bytearray([1, 2, 3])
    assert framebuffer_to_rgb_bytes(framebuffer) is framebuffer


def test_default_key_bindings_maps_z_to_a_and_x_to_b() -> None:
    class FakePygame:
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

    bindings = default_key_bindings(FakePygame)
    assert bindings.a == FakePygame.K_z
    assert bindings.b == FakePygame.K_x


def test_apply_key_event_updates_controller_and_returns_control_actions() -> None:
    nes = NES.from_ines_rom(build_test_rom(b"\xea"))
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


def test_load_pygame_error_message_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = __import__

    def fake_import(name: str, *args, **kwargs):
        if name == "pygame":
            raise ImportError("missing pygame")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(DisplayUnavailableError, match=r"\.\[display\]"):
        load_pygame()


def test_desktop_presents_one_ppu_frame_and_reuses_surface(monkeypatch) -> None:
    from nes_py.app import run_desktop

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame = load_pygame()
    nes = NES.from_ines_rom(build_test_rom(b"\x4c\x00\x80"))
    monkeypatch.setattr(NES, "from_ines_file", lambda path: nes)
    events = iter(([], [], [pygame.event.Event(pygame.QUIT)]))
    monkeypatch.setattr(pygame.event, "get", lambda: next(events))
    buffers = []
    original_frombuffer = pygame.image.frombuffer

    def frombuffer(buffer, *args):
        buffers.append(buffer)
        return original_frombuffer(buffer, *args)

    monkeypatch.setattr(pygame.image, "frombuffer", frombuffer)
    assert run_desktop("generated.nes", scale=2, pygame_module=pygame) == 0
    assert nes.ppu.frame == 2
    assert len(buffers) == 1
    assert buffers[0] is nes.ppu.framebuffer_rgb
    assert not pygame.get_init()


@pytest.fixture
def color_bar_desktop(monkeypatch):
    """Exercise the pygame display using known RGB data instead of a private ROM."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame = load_pygame()
    nes = NES.from_ines_rom(build_test_rom(b"\x4c\x00\x80"))
    row = bytes((255, 0, 0)) * 85 + bytes((0, 255, 0)) * 85 + bytes((0, 0, 255)) * 86
    nes.ppu.framebuffer_rgb[:] = row * 240
    monkeypatch.setattr(NES, "from_ines_file", lambda path: nes)
    monkeypatch.setattr(nes, "run_frame", lambda **kwargs: 0)
    try:
        yield pygame
    finally:
        pygame.quit()


@pytest.mark.parametrize("scale", (1, 2, 3))
def test_desktop_scaling_preserves_red_green_and_blue(
    color_bar_desktop, monkeypatch, scale
) -> None:
    from nes_py.app import run_desktop

    pygame = color_bar_desktop
    events = iter(([], [pygame.event.Event(pygame.QUIT)]))
    monkeypatch.setattr(pygame.event, "get", lambda: next(events))
    colors = []

    def capture_frame():
        screen = pygame.display.get_surface()
        width, height = screen.get_size()
        colors.extend(
            tuple(screen.get_at((width * part // 6, height // 2)))[:3]
            for part in (1, 3, 5)
        )

    monkeypatch.setattr(pygame.display, "flip", capture_frame)
    assert run_desktop("generated.nes", scale=scale, pygame_module=pygame) == 0
    assert colors == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


@pytest.mark.parametrize("scale", (1, 3))
def test_desktop_resizes_maximizes_and_restores_without_changing_colors(
    color_bar_desktop, monkeypatch, scale
) -> None:
    from nes_py.app import run_desktop

    pygame = color_bar_desktop
    # Size, expected image size, expected image position.
    layouts = [
        ((256 * scale, 240 * scale), (256 * scale, 240 * scale), (0, 0)),
        ((1920, 1080), (1152, 1080), (384, 0)),
        ((1920, 1080), (1152, 1080), (384, 0)),
        ((320, 800), (320, 300), (0, 250)),
        ((128, 120), (128, 120), (0, 0)),
        ((256, 240), (256, 240), (0, 0)),
        ((256 * scale, 240 * scale), (256 * scale, 240 * scale), (0, 0)),
    ]
    frames = []
    scale_calls = []
    original_scale = pygame.transform.scale

    def resize_or_quit():
        index = len(frames)
        if index == len(layouts):
            return [pygame.event.Event(pygame.QUIT)]
        if index:
            size = layouts[index][0]
            # pygame 2 updates the display surface when the OS changes the window.
            pygame.display.set_mode(size, pygame.RESIZABLE)
            return [pygame.event.Event(pygame.WINDOWSIZECHANGED, x=size[0], y=size[1])]
        return []

    def capture_frame():
        screen = pygame.display.get_surface()
        size, image_size, (left, top) = layouts[len(frames)]
        assert screen.get_size() == size
        width, height = image_size
        colors = [
            tuple(screen.get_at((left + width * part // 6, top + height // 2)))[:3]
            for part in (1, 3, 5)
        ]
        assert colors == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        if left or top:
            assert tuple(screen.get_at((0, 0)))[:3] == (0, 0, 0)
        frames.append(size)

    def track_scale(source, size, destination=None):
        result = (
            original_scale(source, size)
            if destination is None
            else original_scale(source, size, destination)
        )
        assert result.get_masks() == source.get_masks()
        scale_calls.append((tuple(size), destination, result))
        return result

    monkeypatch.setattr(pygame.event, "get", resize_or_quit)
    monkeypatch.setattr(pygame.display, "flip", capture_frame)
    monkeypatch.setattr(pygame.transform, "scale", track_scale)
    assert run_desktop("generated.nes", scale=scale, pygame_module=pygame) == 0
    assert len(frames) == len(layouts)
    maximized = [call for call in scale_calls if call[0] == (1152, 1080)]
    assert len(maximized) == 2
    assert maximized[0][1] is None
    assert maximized[1][1] is maximized[0][2]


def test_audio_pilot_drains_pcm_and_clears_playback_on_pause_reset_and_quit(
    monkeypatch,
) -> None:
    from nes_py.app import run_desktop

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame = load_pygame()
    nes = NES.from_ines_rom(build_test_rom(b"\x4c\x00\x80"), audio_sample_rate=44100)
    monkeypatch.setattr(NES, "from_ines_file", lambda path, **kwargs: nes)
    sent = []
    clears = []

    class Output:
        def __init__(self, pygame_module):
            pass

        def submit(self, pcm):
            sent.append(pcm)

        def clear(self):
            clears.append(True)

    events = iter(
        (
            [],
            [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)],
            [],
            [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)],
            [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r)],
            [pygame.event.Event(pygame.QUIT)],
        )
    )
    monkeypatch.setattr(pygame.event, "get", lambda: next(events))
    monkeypatch.setattr("nes_py.app.PygameAudioOutput", Output)
    assert run_desktop("generated.nes", audio_pilot=True, pygame_module=pygame) == 0
    assert len(sent) == 3
    assert all(len(pcm) > 0 and len(pcm) % 2 == 0 for pcm in sent)
    assert len(clears) == 4
    assert not pygame.get_init()


def test_five_channel_audio_plays_pcm_through_real_dummy_mixer(monkeypatch) -> None:
    from nes_py.app import run_desktop

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame = load_pygame()
    if not pygame.mixer:
        pytest.skip("pygame was built without SDL_mixer")
    nes = NES.from_ines_rom(build_test_rom(b"\x4c\x00\x80"), audio_sample_rate=44100)
    for address, value in (
        (0x4010, 0x4F),
        (0x4011, 64),
        (0x4012, 0),
        (0x4013, 1),
        (0x4015, 31),
        (0x4000, 0xBF),
        (0x4001, 8),
        (0x4002, 253),
        (0x4003, 8),
        (0x4004, 0x76),
        (0x4005, 8),
        (0x4006, 126),
        (0x4007, 8),
        (0x4008, 0xFF),
        (0x400A, 253),
        (0x400B, 8),
        (0x400C, 0x3A),
        (0x400E, 4),
        (0x400F, 8),
    ):
        nes.bus.write(address, value)
    monkeypatch.setattr(NES, "from_ines_file", lambda path, **kwargs: nes)
    events = iter(([], [], [], [pygame.event.Event(pygame.QUIT)]))
    monkeypatch.setattr(pygame.event, "get", lambda: next(events))
    sound_factory = pygame.mixer.Sound
    blocks = []

    def sound(*, buffer):
        assert pygame.mixer.get_init() == (44100, -16, 1)
        blocks.append(buffer)
        return sound_factory(buffer=buffer)

    monkeypatch.setattr(pygame.mixer, "Sound", sound)
    assert run_desktop("generated.nes", audio_pilot=True, pygame_module=pygame) == 0
    assert nes.ppu.frame == 3
    assert nes.apu.read_status() & 31 == 31
    assert blocks and any(any(block) for block in blocks)
    assert all(len(block) == 2048 for block in blocks)
    assert nes.apu.cpu_cycles == nes.cpu_cycles
    assert nes.apu.drain_samples() == b""
    assert not pygame.get_init()

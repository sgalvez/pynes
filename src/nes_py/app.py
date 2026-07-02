"""Desktop emulator application using pygame."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from time import perf_counter
import warnings

from .debug import make_trace_callback, open_trace_sink
from .input import Button
from .nes import NES
from .ppu import SCREEN_HEIGHT, SCREEN_WIDTH
from .settings import DEFAULT_SCALE

TARGET_FRAME_SECONDS = 1 / 60
SLOW_FRAME_THRESHOLD = TARGET_FRAME_SECONDS * 1.15
MAX_AUTO_FRAME_SKIP = 2


class DisplayUnavailableError(RuntimeError):
    """Raised when pygame is required but unavailable."""


@dataclass(frozen=True)
class KeyBindings:
    """Keyboard mapping for one NES controller."""

    a: int
    b: int
    select: int
    start: int
    up: int
    down: int
    left: int
    right: int
    pause: int
    reset: int
    quit: int


def load_pygame():
    """Import pygame lazily so headless tests do not need it installed."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Your system is avx2 capable.*",
                category=RuntimeWarning,
            )
            import pygame  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DisplayUnavailableError(
            "pygame is required for the desktop window. Install it with "
            "`python -m pip install -e \".[display]\"`."
        ) from exc
    return pygame


def default_key_bindings(pygame_module) -> KeyBindings:
    return KeyBindings(
        a=pygame_module.K_z,
        b=pygame_module.K_x,
        select=pygame_module.K_RSHIFT,
        start=pygame_module.K_RETURN,
        up=pygame_module.K_UP,
        down=pygame_module.K_DOWN,
        left=pygame_module.K_LEFT,
        right=pygame_module.K_RIGHT,
        pause=pygame_module.K_SPACE,
        reset=pygame_module.K_r,
        quit=pygame_module.K_ESCAPE,
    )


def apply_key_event(nes: NES, key: int, pressed: bool, bindings: KeyBindings) -> str | None:
    """Apply a pygame key event to emulator input and return control actions."""
    button_map = {
        bindings.a: Button.A,
        bindings.b: Button.B,
        bindings.select: Button.SELECT,
        bindings.start: Button.START,
        bindings.up: Button.UP,
        bindings.down: Button.DOWN,
        bindings.left: Button.LEFT,
        bindings.right: Button.RIGHT,
    }
    if key in button_map:
        nes.controller1.set_button(button_map[key], pressed)
        return None
    if not pressed:
        return None
    if key == bindings.pause:
        return "pause"
    if key == bindings.reset:
        return "reset"
    if key == bindings.quit:
        return "quit"
    return None


def framebuffer_to_rgb_bytes(framebuffer: list[tuple[int, int, int]] | bytearray) -> bytes | bytearray:
    """Convert a framebuffer list to tightly packed RGB bytes."""
    if isinstance(framebuffer, bytearray):
        return framebuffer
    return bytes(channel for pixel in framebuffer for channel in pixel)


def run_desktop(
    rom_path: str | Path,
    *,
    scale: int = DEFAULT_SCALE,
    instructions_per_frame: int | None = None,
    trace: bool = False,
    disassemble: bool = False,
    trace_file: str | Path | None = None,
    pygame_module=None,
) -> int:
    """Run the emulator in a pygame desktop window."""
    pygame = pygame_module if pygame_module is not None else load_pygame()
    if pygame_module is None:
        pygame.mixer.pre_init(frequency=44_100, size=-16, channels=1, buffer=1024)
    pygame.init()
    trace_sink = None
    trace_handle = None
    if trace:
        trace_sink, trace_handle = open_trace_sink(trace_file)
        trace_callback = make_trace_callback(trace_sink, include_disassembly=disassemble)
    else:
        trace_callback = None
    try:
        nes = NES.from_ines_file(rom_path)
        bindings = default_key_bindings(pygame)
        screen = pygame.display.set_mode((SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale))
        pygame.display.set_caption(f"pynes - {Path(rom_path).name}")
        clock = pygame.time.Clock()
        audio_enabled = pygame.mixer.get_init() is not None
        audio_channel = pygame.mixer.Channel(0) if audio_enabled else None
        paused = False
        running = True
        frames_to_skip = 0

        while running:
            loop_started_at = perf_counter()
            rendered_frame = True
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    continue
                if event.type in (pygame.KEYDOWN, pygame.KEYUP):
                    action = apply_key_event(
                        nes,
                        event.key,
                        event.type == pygame.KEYDOWN,
                        bindings,
                    )
                    if action == "quit":
                        running = False
                    elif action == "pause":
                        paused = not paused
                    elif action == "reset":
                        nes.reset()

            if not paused:
                if instructions_per_frame is None:
                    rendered_frame = frames_to_skip == 0
                    _, audio = nes.run_frame(
                        trace_callback=trace_callback,
                        render=rendered_frame,
                    )
                    if frames_to_skip:
                        frames_to_skip -= 1
                else:
                    cycles = nes.run(instructions_per_frame, trace_callback=trace_callback)
                    audio = nes.apu.generate_samples(cycles)
                    nes.ppu.render_frame()
                    rendered_frame = True
                if audio_enabled and audio:
                    assert audio_channel is not None
                    sound = pygame.mixer.Sound(buffer=audio)
                    if audio_channel.get_busy():
                        if audio_channel.get_queue() is None:
                            audio_channel.queue(sound)
                    else:
                        audio_channel.play(sound)

            if rendered_frame:
                surface = pygame.image.frombuffer(
                    framebuffer_to_rgb_bytes(nes.ppu.framebuffer_bytes),
                    (SCREEN_WIDTH, SCREEN_HEIGHT),
                    "RGB",
                )
                if scale != 1:
                    surface = pygame.transform.scale(surface, (SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale))
                screen.blit(surface, (0, 0))
                pygame.display.flip()

            elapsed = perf_counter() - loop_started_at
            if (
                not paused
                and rendered_frame
                and instructions_per_frame is None
                and trace_callback is None
                and elapsed > SLOW_FRAME_THRESHOLD
            ):
                overrun_frames = int(elapsed / TARGET_FRAME_SECONDS)
                frames_to_skip = max(frames_to_skip, min(MAX_AUTO_FRAME_SKIP, overrun_frames))

            clock.tick(60 if rendered_frame else 0)
    finally:
        if trace_handle is not None:
            trace_handle.close()
        pygame.quit()

    return 0

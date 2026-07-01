"""Desktop emulator application using pygame."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .debug import make_trace_callback, open_trace_sink
from .input import Button
from .nes import NES
from .ppu import SCREEN_HEIGHT, SCREEN_WIDTH

DEFAULT_SCALE = 3
DEFAULT_INSTRUCTIONS_PER_FRAME = 30_000


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
    try:
        import pygame  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DisplayUnavailableError(
            "pygame is required for the desktop window. Install it with "
            "`python -m pip install -e \".[display]\"`."
        ) from exc
    return pygame


def default_key_bindings(pygame_module) -> KeyBindings:
    return KeyBindings(
        a=pygame_module.K_x,
        b=pygame_module.K_z,
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


def framebuffer_to_rgb_bytes(framebuffer: list[tuple[int, int, int]]) -> bytes:
    """Convert a framebuffer list to tightly packed RGB bytes."""
    return bytes(channel for pixel in framebuffer for channel in pixel)


def run_desktop(
    rom_path: str | Path,
    *,
    scale: int = DEFAULT_SCALE,
    instructions_per_frame: int = DEFAULT_INSTRUCTIONS_PER_FRAME,
    trace: bool = False,
    disassemble: bool = False,
    trace_file: str | Path | None = None,
    pygame_module=None,
) -> int:
    """Run the emulator in a pygame desktop window."""
    pygame = pygame_module if pygame_module is not None else load_pygame()
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
        paused = False
        running = True

        while running:
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
                nes.run(instructions_per_frame, trace_callback=trace_callback)
                nes.ppu.render_background()

            surface = pygame.image.frombuffer(
                framebuffer_to_rgb_bytes(nes.ppu.framebuffer),
                (SCREEN_WIDTH, SCREEN_HEIGHT),
                "RGB",
            )
            if scale != 1:
                surface = pygame.transform.scale(surface, (SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale))
            screen.blit(surface, (0, 0))
            pygame.display.flip()
            clock.tick(60)
    finally:
        if trace_handle is not None:
            trace_handle.close()
        pygame.quit()

    return 0

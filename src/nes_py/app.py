"""Desktop emulator application using pygame."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from .apu import DEFAULT_SAMPLE_RATE
from .audio import PygameAudioOutput
from .debug import make_trace_callback, open_trace_sink
from .input import Button
from .nes import NES
from .ppu import SCREEN_HEIGHT, SCREEN_WIDTH
from .settings import DEFAULT_INSTRUCTIONS_PER_FRAME, DEFAULT_SCALE


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
    stats: int | None = None


@dataclass
class FrameStats:
    """Half-second desktop timings, with pacing waits excluded from work time."""

    start: float = field(default_factory=perf_counter)
    frames: int = 0
    emulation: float = 0.0
    audio: float = 0.0
    video: float = 0.0
    late: int = 0

    def record(
        self, emulation: float, audio: float, video: float, now: float
    ) -> str | None:
        self.frames += 1
        self.emulation += emulation
        self.audio += audio
        self.video += video
        self.late += emulation + audio + video > 1 / 60
        elapsed = now - self.start
        if elapsed < 0.5:
            return None
        ms = 1000 / self.frames
        caption = (
            f"{self.frames / elapsed:.1f} FPS | emu {self.emulation * ms:.1f} ms | "
            f"audio {self.audio * ms:.1f} ms | video {self.video * ms:.1f} ms | "
            f"slow {self.late}/{self.frames}"
        )
        self.start = now
        self.frames = self.late = 0
        self.emulation = self.audio = self.video = 0.0
        return caption


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
            '`python -m pip install -e ".[display]"`.'
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
        stats=getattr(pygame_module, "K_F3", None),
    )


def apply_key_event(
    nes: NES, key: int, pressed: bool, bindings: KeyBindings
) -> str | None:
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
    if key == bindings.stats:
        return "stats"
    return None


def framebuffer_to_rgb_bytes(
    framebuffer: list[tuple[int, int, int]] | bytearray,
) -> bytes | bytearray:
    """Convert a framebuffer list to tightly packed RGB bytes."""
    if isinstance(framebuffer, bytearray):
        return framebuffer
    return bytes(channel for pixel in framebuffer for channel in pixel)


def run_desktop(
    rom_path: str | Path,
    *,
    scale: int = DEFAULT_SCALE,
    instructions_per_frame: int | None = DEFAULT_INSTRUCTIONS_PER_FRAME,
    trace: bool = False,
    disassemble: bool = False,
    trace_file: str | Path | None = None,
    audio_pilot: bool = False,
    pygame_module=None,
) -> int:
    """Run the emulator in a pygame desktop window."""
    pygame = pygame_module if pygame_module is not None else load_pygame()
    pygame.init()
    trace_sink = None
    trace_handle = None
    audio_output = None
    try:
        if audio_pilot:
            audio_output = PygameAudioOutput(pygame)
        if trace:
            trace_sink, trace_handle = open_trace_sink(trace_file)
            trace_callback = make_trace_callback(
                trace_sink, include_disassembly=disassemble
            )
        else:
            trace_callback = None
        nes = (
            NES.from_ines_file(rom_path, audio_sample_rate=DEFAULT_SAMPLE_RATE)
            if audio_pilot
            else NES.from_ines_file(rom_path)
        )
        bindings = default_key_bindings(pygame)
        screen = pygame.display.set_mode(
            (SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale), pygame.RESIZABLE
        )
        title = f"pynes - {Path(rom_path).name}"
        pygame.display.set_caption(title)
        surface = pygame.image.frombuffer(
            nes.ppu.framebuffer_rgb, (SCREEN_WIDTH, SCREEN_HEIGHT), "RGB"
        )
        scaled_surface = None
        clock = pygame.time.Clock()
        paused = False
        running = True
        stats = None

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
                        if audio_output is not None:
                            audio_output.clear()
                    elif action == "reset":
                        nes.reset()
                        if audio_output is not None:
                            audio_output.clear()
                    elif action == "stats":
                        stats = FrameStats() if stats is None else None
                        if stats is None:
                            pygame.display.set_caption(title)

            if not running:
                break
            started = perf_counter() if stats is not None else 0.0
            if not paused:
                if instructions_per_frame is None:
                    nes.run_frame(trace_callback=trace_callback)
                else:
                    nes.run(instructions_per_frame, trace_callback=trace_callback)
            emulated = perf_counter() if stats is not None else 0.0
            if not paused and audio_output is not None:
                assert nes.apu is not None
                audio_output.submit(nes.apu.drain_samples())
            submitted = perf_counter() if stats is not None else 0.0
            screen = pygame.display.get_surface()
            if screen is None:
                break
            viewport = surface.get_rect().fit(screen.get_rect())
            if viewport.width > 0 and viewport.height > 0:
                if viewport.size == surface.get_size():
                    image = surface
                else:
                    if (
                        scaled_surface is None
                        or scaled_surface.get_size() != viewport.size
                    ):
                        # Let pygame preserve the source RGB channel masks.
                        scaled_surface = pygame.transform.scale(surface, viewport.size)
                    else:
                        pygame.transform.scale(surface, viewport.size, scaled_surface)
                    image = scaled_surface
                screen.fill((0, 0, 0))
                screen.blit(image, viewport.topleft)
                pygame.display.flip()
            presented = perf_counter() if stats is not None else 0.0
            clock.tick(60)
            if stats is not None:
                report = stats.record(
                    emulated - started,
                    submitted - emulated,
                    presented - submitted,
                    perf_counter(),
                )
                if report is not None:
                    state = "paused | " if paused else ""
                    pygame.display.set_caption(f"{title} | {state}{report}")
    finally:
        if audio_output is not None:
            audio_output.clear()
        if trace_handle is not None:
            trace_handle.close()
        pygame.quit()

    return 0

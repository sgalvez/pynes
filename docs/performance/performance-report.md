# Performance Report

Measurements were taken on the local Codex Windows runtime with:

```bash
python scripts/profile_performance.py
```

The script reports medians for subprocess-based startup checks and direct
throughput measurements for emulator operations. Results are intended as
lightweight development guidance, not machine-independent guarantees.

## Baseline

| Area | Measurement | Notes |
|---|---:|---|
| Package import | 66.23 ms | Median of 7 subprocess imports |
| CLI version startup | 71.88 ms | Median of 7 `python -m nes_py --version` subprocess runs |
| CPU/NES stepping | 727,251 instructions/sec | 100,000 NOP instructions |
| PPU background render | 126 frames/sec | 20 background renders |
| Changelog generation | 43.31 ms | Median of 5 subprocess runs |
| Release notes generation | 39.05 ms | Median of 5 subprocess runs |

## Bottlenecks Identified

- CPU stepping spent avoidable work on every instruction by formatting an opcode
  method name and looking it up with `getattr`.
- CLI/package startup imported most emulator modules even for simple version
  output. The impact was modest, but the unnecessary import work was measurable.
- PPU background rendering is comparatively expensive, but no targeted change was
  made because it is current emulator behavior and a safe optimization would
  require a separate, rendering-focused investigation.
- CI changelog and release-note generation were already fast enough for the
  current repository size.

## Changes Made

- Added `scripts/profile_performance.py` for lightweight startup, CI-script,
  CPU stepping, and PPU rendering measurements.
- Added a 256-entry CPU opcode dispatch table populated during opcode
  installation, avoiding per-instruction opcode-name formatting and dynamic
  lookup.
- Moved CLI defaults into `nes_py.settings` and kept desktop/debug imports lazy
  during CLI execution.
- Made top-level package exports lazy so simple `python -m nes_py --version`
  startup does not eagerly import CPU, PPU, cartridge, NES, and debug modules.

## After Optimization

| Area | Before | After | Change |
|---|---:|---:|---:|
| Package import | 66.23 ms | 61.11 ms | 7.7% faster |
| CLI version startup | 71.88 ms | 70.44 ms | 2.0% faster |
| CPU/NES stepping | 727,251 instructions/sec | 878,306 instructions/sec | 20.8% faster |
| PPU background render | 126 frames/sec | 121 frames/sec | 4.0% slower |
| Changelog generation | 43.31 ms | 45.30 ms | 4.6% slower |
| Release notes generation | 39.05 ms | 38.90 ms | 0.4% faster |

## Notes

- The CPU dispatch improvement is the only material runtime optimization in this
  pass.
- Startup improvements are intentionally small and focused on avoiding eager
  imports for version/help paths.
- The PPU and CI-script measurements vary enough at this scale that the slower
  after values are treated as non-actionable noise for this PR.
- No emulator features were added.

## Earlier Runtime Responsiveness

This historical section describes the earlier renderer. The current cycle-driven
path below renders scanlines while advancing timing and exposes F3 diagnostics;
it supersedes the former whole-frame render-skipping path.

The earlier desktop runner used bounded adaptive frame skipping in normal frame-paced
mode. When a rendered frame exceeds the 60 FPS frame budget by a small margin,
the next one or two emulated frames may skip the expensive PPU render and pygame
blit. CPU, PPU timing, input, and APU sample generation continue advancing, so
the emulator catches up instead of compounding delays during scene transitions or
busy gameplay.

This behavior is intentionally disabled while tracing and when
`--instructions-per-frame` is used, because those modes are for deterministic
debugging and manual validation.
## Scanline Rendering and Frame Pacing (2026-11-13)

Measured locally on Linux with Python 3.14 and a privately supplied mapper 1
ROM with CHR RAM. The ROM and screenshots are excluded from the repository.
Automated rendering tests generate their own ROM bytes and graphics.

The comparison warms up with 300,000 instructions, then times 120 emulated
frames. The baseline follows the old desktop preparation path: advance one
PPU frame, draw the background again, and convert RGB tuples in Python. The new
path advances one PPU frame and uses its completed RGB buffer, including
backgrounds and sprites. These measurements exclude the window, scaling, and
the 60 Hz display limiter.

| Frame workload | Before | After |
|---|---:|---:|
| Median frame time | 26.7 ms | 13.8 ms |
| Headless throughput | 37.5 frames/sec | 72.2 frames/sec |

This is about 1.9 times the throughput on this machine. It does not guarantee
60 displayed frames/sec on other hardware or in every scene.

Changes in this pass:

- Advance the desktop runner by PPU frames instead of 30,000 instructions per
  refresh, and remove its redundant background render.
- Decode pattern rows with a bounded cache keyed by their actual bytes, so
  CHR RAM writes and bank switches do not leave stale graphics.
- Build RGB channels with byte translation and reuse the RGB buffer and pygame
  surfaces. Keep the completed image separate from the next frame being drawn.
- Add scrolling, nametable selection/mirroring (including MMC1), sprites,
  clipping, OAM DMA stalls, and CPU/PPU accounting for NMI cycles.
- Update CPU zero/negative flags together and cache branch masks to reduce
  work in the instruction loop.

For future comparisons, use a local ROM without putting it into Git:

```bash
python scripts/profile_performance.py --rom rom/game.nes --frames 120 --warmup-frames 300
```

The new benchmark includes scanline composition and RGB preparation, without
printing CPU traces. Trace output can materially reduce runtime performance.

## Pulse-1 APU Pilot

A short paired headless check on the same local Linux/Python 3.14 environment
used a private mapper-1 ROM, 30 warmup frames, and 60 measured frames per mode:

| Mode | Headless throughput |
|---|---:|
| Audio disabled | 70.6 frames/sec |
| Pulse-1 synthesis at 44100 Hz, drained every frame | 60.5 frames/sec |

This measures early-game synthesis overhead, not audible playback or all game
scenes. At the time of this measurement pygame lacked SDL_mixer, so physical
playback timing was not measured. The initial pilot had little margin at 60 Hz on this
machine; further audio work should profile event processing and buffering before
adding channels. Full APU accuracy and stable device-clock synchronization remain
future work. See [APU pilot](../apu/pilot.md) for the current scope.

## Batched APU Synthesis (2026-11-14)

After reports of slower gameplay with audio, a private mapper-1 ROM was measured
with pulse-1 synthesis at 44100 Hz: 240 warmup frames followed by 60 timed frames,
draining PCM every frame. Neither timing includes a window or audio-device pacing.

| Audio-enabled workload | Before | After |
|---|---:|---:|
| Headless throughput | 59.5 frames/sec | 69.0 frames/sec |
| Average processing time per frame | 16.81 ms | 14.50 ms |

The CPU publishes elapsed time without invoking synthesis after every
instruction. Register writes, status reads, PCM drains, and hardware-state reads
flush pending audio in chronological order. A 30-frame profile reduced APU
synchronization from 290,628 instruction updates to 219 flushes, while producing
the same 22,014 PCM samples. Pulse timer advancement fell from 312,759 calls to
22,350 calls.

The generated demo and a local ROM capture retained identical sample counts and
SHA-256 PCM hashes before/after. Regression tests also compare deferred timing
against immediate stepping across register writes, status reads, inspection,
and reset. SDL_mixer is now available in this environment, and a dummy-driver
smoke test exercises the real PCM playback path.

This is approximately 16% more headless throughput on this workload. Window
scaling, WSL audio transport, and more demanding scenes can still affect displayed
FPS. Reproduce audio-enabled measurements with:

```bash
python scripts/profile_performance.py --rom rom/game.nes --audio-pilot --warmup-frames 240 --frames 60
```

## Four-Channel APU Pilot (2026-11-14)

The same private mapper-1 ROM was measured on Linux/Python 3.14 with 240
warmup frames and 60 timed frames. These paired measurements include scanline
and RGB rendering; audio mode synthesizes 44100 Hz PCM and drains every frame.
They exclude the window, scaling, host audio transport, and display pacing.

| Current mode | Headless throughput | Processing time per frame |
|---|---:|---:|
| Audio disabled | 70.13 frames/sec | 14.26 ms |
| Four-channel APU enabled | 66.84 frames/sec | 14.96 ms |

The earlier batched pulse-only pilot measured 69.0 frames/sec on this workload;
that historical measurement was taken separately. The expanded pilot retains
batching at APU accesses and PCM consumption. Pulse/triangle timers advance
arithmetically, and noise uses cached cycles of the 15-bit LFSR to jump directly
to the correct state without per-bit Python loops. The two noise-mode tables
use about 512 KiB of shared packed storage, prepared once at APU creation.

In this captured intro segment, the ROM writes pulse 1, pulse 2, and triangle;
it does not activate noise. Generated demos cover each channel separately and
all four together, and the dummy-SDL playback regression enables all four.
Noise jumps are also checked against a bitwise reference in both modes.

The measured workload retains headroom above 60 frames/sec. This does not
establish stable physical-device playback or throughput in more demanding
scenes. DMC and device-clock feedback remain pending. See the
[pilot guide](../apu/pilot.md) for capture and listening commands.

## DMC, APU IRQs, and CPU Read Overhead (2026-11-14)

The DMC increment was checked against a saved copy of the four-channel source
using the same private mapper-1 ROM and Linux/Python 3.14 environment. Inspection
found that the earlier 240-warmup/60-measured intro window produced silent PCM.
It measures synthesis overhead, but does not establish active-music throughput.
The measurements below instead use 360 warmup frames and 120 timed frames in
a section with music. All modes drain 44100 Hz PCM each frame and include
scanline/RGB rendering; they exclude the window and the physical audio device.

| Music-scene workload | Headless throughput | Processing time per frame |
|---|---:|---:|
| Saved four-channel baseline | 63.85 frames/sec | 15.66 ms |
| Five channels and IRQs, final CPU optimizations | 64.44 frames/sec | 15.52 ms |
| Five channels plus forced fastest looping DMC | 60.30 frames/sec | 16.58 ms |

The ordinary music scene uses pulse and triangle voices, without DMC fetches.
The artificial stress mode forces rate index 15 and looping reads, and keeps
bit 4 enabled when the game writes `$4015`. About 8,272 sample bytes are fetched
over the 120 measured video frames, including the initial load. This is a load
test, not the game's normal sample stream. CPU, PPU, and APU clock accounting
remains synchronized in both modes.

A profile showed avoidable CPU read dispatch work in addition to the new audio
work. Opcode/operand fetches now read the bus directly, and read-opcode handlers
resolve their private address/operation functions once at installation rather
than looking them up and constructing bound methods on every execution. Bus
accesses and cycle charges are preserved, including mapped audio/status reads.
The stress music workload rose from 58.58 to 60.30 frames/sec after the latter
optimization. Tests cover PC/zero-page wrap and page-crossing cycle costs.

Each measured music run produced 88,055 samples. Before/after CPU optimization,
the music and stress captures retained identical PCM hashes and final CPU
states. The old four-channel and new normal-game CPU states also match; their
PCM differs intentionally because five-channel mixer normalization reserves
headroom for the DMC DAC. Generated samples and the dummy-SDL test separately
exercise all five channels without proprietary assets.

Reproduce the current music and stress measurements with:

```bash
python scripts/profile_performance.py --rom rom/game.nes --audio-pilot --warmup-frames 360 --frames 120
python scripts/profile_performance.py --rom rom/game.nes --audio-pilot --dmc-stress --warmup-frames 360 --frames 120
```

The stress result has little margin over 60 frames/sec before window/audio
transport overhead. These short measurements do not guarantee sustained 60 Hz
playback. Precise DMA arbitration and audio-device clock feedback remain future
work; see [DMC and IRQ integration](../apu/dmc.md).

## Bubble Man Gameplay and Desktop Diagnostics (2026-11-14)

Following reports of slowdown and misaligned graphics in the water stage of
the local ROM, Bubble Man gameplay was reached using controller input. The
scrolling waterfall scene reproduced a substantial slowdown before any window
or audio-device overhead. This was a more demanding workload than the earlier
intro/music measurements.

A local checkpoint and the same 120-frame movement/jump/fire sequence were
used before and after optimization, with APU synthesis and PCM consumption.
Measurements include a rolling RGB/PCM hash for validation, but exclude the
window, scaling, and device playback. The checkpoint, ROM, and screenshots
remain local and Git-ignored.

| Bubble Man workload | Before | After |
|---|---:|---:|
| Headless throughput | 46.84 frames/sec | 61.88 frames/sec |
| Processing time per frame | 21.35 ms | 16.16 ms |

This is about 32% more throughput for this sequence. Changes target work shown
in the profile:

- CPU ROM reads take the common PRG path first and avoid an intermediate
  cartridge read wrapper. MMC1 PRG-window offsets are cached by their current
  register values, preserving serial writes and direct register changes.
- Store opcodes resolve their addressing handlers once, keeping the same
  mapped bus writes and cycle costs.
- Background rows use strided CHR lookup tables and byte translation to select
  pattern data. Complete tile strips are cached by actual pattern/palette
  bytes, and assembled in C-backed operations rather than repeated tile copies.
- Sprite scanline membership is cached by the complete OAM contents and sprite
  height. Nontransparent sprite pixels are decoded once per pattern/flip state.
  The eight-sprite limit, overflow status, priority, and sprite-zero hit are
  preserved. Caches have bounded sizes.

All 120 RGB frames, PCM output, and the final CPU state matched the reference
exactly. Regression checks cover CHR/palette edits, bank changes, scrolling,
sprite priority/overflow, direct/register OAM edits, and sprite-height changes.
The full suite passes 304 tests.

The optimization preserves existing rendering behavior; it does not establish
that the reported underwater alignment issue is fixed. The underwater
transition has not yet been isolated as a rendering/timing regression. The PPU
still samples visible scanlines, so raster effects remain an accuracy limit.
The measured frame time is also close to the 16.7 ms desktop budget; more
demanding scenes and WSL presentation can still reduce displayed FPS.

Press **F3** during normal desktop playback to show FPS, average emulation,
audio, and video work, plus slow-frame counts in the title. The timings refresh
every half-second. The FPS includes pacing time; component timings exclude the
pacing wait. Audio time includes deferred synthesis and mixer submission.
`slow X/N` reports work that exceeded the 60 Hz frame budget. Press F3 again to
hide the timings. Normal and maximized windows can now be compared at the
actual point where a problem occurs.

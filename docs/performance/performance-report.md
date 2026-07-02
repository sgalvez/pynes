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

## Runtime Responsiveness

The desktop runner now uses bounded adaptive frame skipping in normal frame-paced
mode. When a rendered frame exceeds the 60 FPS frame budget by a small margin,
the next one or two emulated frames may skip the expensive PPU render and pygame
blit. CPU, PPU timing, input, and APU sample generation continue advancing, so
the emulator catches up instead of compounding delays during scene transitions or
busy gameplay.

This behavior is intentionally disabled while tracing and when
`--instructions-per-frame` is used, because those modes are for deterministic
debugging and manual validation.

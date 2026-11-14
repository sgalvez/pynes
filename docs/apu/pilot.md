# NTSC five-channel APU pilot

This pilot emulates **all five base NES audio channels**: pulse 1, pulse 2,
triangle, noise, and DMC. CPU register writes and elapsed CPU cycles drive their
state, and nonlinear mixing produces mono 16-bit PCM. WAV export needs no audio
device; optional pygame playback uses `--audio-pilot`. Audio is disabled by
default. Frame and DMC IRQs reach the CPU; DMA and interrupt timing remain
approximate at instruction boundaries. See [DMC and IRQ integration](dmc.md).

For the original conceptual explanation in Spanish, see
[Cómo funciona la APU](overview.es.md).

## Try the generated demo

From the repository root, with the Python environment activated:

```bash
python scripts/apu_pilot.py
```

Open `build/apu-pilot.wav` in an audio player. It contains about two seconds of
four synthesized notes with melody (pulse 1), lower harmony (pulse 2), bass
(triangle), noise percussion, and an original DPCM drum sample. The demo builds
an NROM program and sample in memory and controls the channels through `NESBus`;
no game assets are involved.
WAV generation uses only Python's standard library and needs no audio device,
pygame, or WSL audio configuration.

To choose an output path or capture duration:

```bash
python scripts/apu_pilot.py --frames 240 --output build/apu-demo.wav
```

`--frames` counts emulated NTSC video frames, approximately 60.1 per second.
`--sample-rate` defaults to 44100 Hz.

Isolate an instrument to compare the waveforms:

```bash
python scripts/apu_pilot.py --demo-channel pulse1 --output build/pulse1.wav
python scripts/apu_pilot.py --demo-channel pulse2 --output build/pulse2.wav
python scripts/apu_pilot.py --demo-channel triangle --output build/triangle.wav
python scripts/apu_pilot.py --demo-channel noise --output build/noise.wav
python scripts/apu_pilot.py --demo-channel dmc --output build/dmc.wav
```

The default `--demo-channel all` mixes all five. This option applies only to
the generated demo; local ROM capture follows the game's channel settings.

## Capture a local ROM

```bash
python scripts/apu_pilot.py --rom rom/game.nes --frames 600 --output build/game-audio.wav
```

This captures all five base channels according to the game's register writes.
Startup can be silent; capture enough frames for the game's audio routine to
start. Use `--warmup-frames` to advance before recording:

```bash
python scripts/apu_pilot.py --rom rom/game.nes --warmup-frames 240 --frames 120 --output build/game-audio.wav
```

Private ROMs and derived game audio must remain local. Generated WAV files go
under the Git-ignored `build/` directory by default.

## Experimental desktop playback

```bash
python nes.py rom/game.nes --audio-pilot
```

This requires pygame **with SDL_mixer support** and a working audio device.
pygame is configured for mono signed 16-bit audio at 44100 Hz. Small audio
blocks are queued; pause, reset, and quit discard queued audio. Video resizing
continues to use the RGB-preserving scaling path.

If pygame lacks its mixer module, or an audio device cannot open, the command
reports an error with the WAV export alternative. Installing the `display`
extra is not sufficient if pygame was built without SDL_mixer. In WSL, the
host audio path is an additional requirement after synthesis works. A valid
WAV can be played outside WSL to check synthesis independently.

## What is implemented

| Component | Pilot behavior |
|---|---|
| Pulse 1 `$4000`–`$4003`, pulse 2 `$4004`–`$4007` | Four duty patterns, timers, volume/envelopes, length counters, sweep with the channel-specific negate difference |
| Triangle `$4008`, `$400A`, `$400B` | 32-step waveform, CPU-rate timer, linear and length counters, phase preservation, held DAC when halted |
| Noise `$400C`, `$400E`, `$400F` | NTSC period table, 15-bit LFSR, long/short tap modes, envelope, length counter |
| DMC `$4010`–`$4013` | NTSC bit rates, direct 7-bit DAC, sample address/length, LSB-first delta decoding, one-byte buffer, loop, address wrap, end-of-fetch IRQ |
| `$4015` | Independent channel enable/disable, length/DMC-reader status in bits 0–4, frame IRQ in bit 6, DMC IRQ in bit 7 |
| `$4017` writes | Four/five-step NTSC sequencer selection and IRQ inhibit |
| `$4017` reads | Remain controller-2 reads through `NESBus` |
| Time | CPU cycles, including reset, OAM/DMC DMA stalls, and NMI/IRQ service time |
| Mixing | Nonlinear pulse-sum and triangle/noise/DMC lookup tables with hardware-relative channel balance |
| PCM | Integer-cycle sample scheduling and a 90 Hz high-pass filter for DC removal |
| Buffers | APU retains at most the newest second; pygame pending data is bounded to four 1024-sample blocks |

Pulse frequency follows `CPU_Hz / (16 * (timer + 1))`; triangle frequency uses
`CPU_Hz / (32 * (timer + 1))`. The NTSC CPU clock is modeled as 1,789,773 Hz.
The triangle holds its current DAC level when a counter stops its sequence;
the high-pass removes the resulting DC offset. At triangle periods 0 and 1,
the mixer uses the 7.5 average level to avoid ultrasonic aliasing.

The mixer uses fixed gain with 20% headroom at the maximum five-channel level.
Individual voices therefore sound quieter than in the earlier one/four-channel
pilots. Relative channel levels follow the shared mixer; DMC's held DAC also
affects triangle/noise volume. The complete TND lookup uses a packed double
array of about 272 KiB.

Timers and sample scheduling use event boundaries and arithmetic advancement
rather than iterating over every CPU cycle. Noise advances through cached LFSR
cycles, preserving the exact state across mode changes with constant-time jumps.
Both noise tables are prepared at APU creation and shared between instances;
their packed arrays occupy about 512 KiB in total.

The NES wrapper publishes its CPU clock after each instruction. Synthesis is
batched until an APU register access, status read, PCM drain, hardware-state
inspection, predicted frame IRQ, or DMC memory fetch. Elapsed audio is rendered
before applying a register write, so note
changes preserve their original instruction timing. Direct APU users can still
call `step(cycles)` to advance and synthesize immediately.

## API and module layout

- `src/nes_py/apu.py`: five channels, frame sequencer, mixer, PCM, DMA requests,
  and IRQ levels.
- `src/nes_py/audio.py`: WAV export and optional pygame device/queue adapter.
- `src/nes_py/nes.py`: optional APU ownership, bus routing, and timing.
- `scripts/apu_pilot.py`: reproducible demo and local ROM capture.

```python
from nes_py import NES
from nes_py.audio import write_wav

nes = NES.from_ines_file("rom/game.nes", audio_sample_rate=44100)
assert nes.apu is not None
pcm = bytearray()
for _ in range(120):
    nes.run_frame()
    pcm.extend(nes.apu.drain_samples())
write_wav("build/capture.wav", bytes(pcm))
```

Consume PCM regularly: the bounded APU buffer deliberately drops old samples
when a consumer falls behind. WAV capture drains once per video frame.

## Migration from the earlier prototype

The cycle-driven core replaces the earlier four-channel sample generator and
whole-frame renderer. `NES.run_frame()` now returns elapsed CPU cycles; PCM is
consumed separately with `nes.apu.drain_samples()`. Enable synthesis explicitly
with `audio_sample_rate=44100`, or use `--audio-pilot` for desktop playback.
Default desktop playback opens the window without requesting an audio device.

PPU scanlines now advance with CPU, DMA, and interrupt time. The desktop no
longer uses the former whole-frame render-skipping path. `framebuffer_bytes`
remains an alias for the reusable RGB buffer, and `render_sprites()` remains a
snapshot convenience method. Use `write_register()` for scroll changes; caches
follow actual pattern, palette, nametable, and OAM contents rather than a
manually managed `background_dirty` flag.

The new pulse, triangle, and noise units expose hardware state rather than the
previous floating-point oscillator API. Mixing includes DMC and uses fixed
five-channel headroom. The previous oscillator edge correction and output
shaping are superseded; band-limited synthesis remains a stated follow-up.

## Limits and follow-up work

- Expansion audio is absent.
- NTSC timing only; PAL is not modeled.
- Register writes use the CPU core's instruction granularity. `$4017` reset
  and immediate five-step clocks omit the hardware's 3/4-cycle write delay.
- DMA charges nominal three-cycle initial loads and four-cycle refills, applied
  at instruction boundaries. Initial fetch delay, write-cycle retries, OAM/DMC
  arbitration, and DMA-induced repeated I/O reads are not emulated.
- IRQs use a level input and seven-cycle CPU entry, including delayed I-flag
  polling for CLI/SEI/PLP and immediate RTI restoration. Adjacent-cycle frame
  IRQ edges and interrupt hijacking/collision behavior remain approximate.
- Reset uses deterministic emulator power-on state for the APU, rather than
  reproducing every hardware warm-reset register-retention detail.
- Sampling is a first approximation. Band-limited resampling and the complete
  NES analog filter/mixer response are pending.
- Playback does not yet use audio-device clock feedback. Device scheduling or
  slow emulation can cause underruns; overload drops old pending blocks to
  bound latency. Physical-device playback still needs listening checks.

Band-limited synthesis, precise DMA arbitration, and device-clock feedback
remain follow-up work.

## Validation

```bash
python -m pytest tests/test_apu.py tests/test_dmc.py tests/test_apu_irq_dma.py tests/test_cpu.py tests/test_audio.py tests/test_apu_pilot.py tests/test_app.py tests/test_cli.py
python -m ruff check .
```

Numerical tests check both pulse frequencies and duties, their different sweep
negation, triangle frequency and linear gating, held DAC, ultrasonic averaging,
noise state against a bit-by-bit LFSR reference, mode/period changes, independent
status bits, envelopes, length clocks, mixing headroom, frame status, chunk-size
independence, reset, and DMA/NMI/IRQ clock accounting. DMC tests check bit order,
DAC bounds, idle phase, looping, address wrap, status acknowledgement, mapped
memory reads, and nominal DMA stalls. WAV tests verify every demo
channel, format, and sample contents. Playback tests exercise queue ordering,
device errors, and app controls with test doubles. A real dummy-SDL mixer smoke
test checks all five channels through the PCM playback path when SDL_mixer is
available; it cannot establish audible quality on a physical device.

## Hardware references

- [APU overview](https://www.nesdev.org/wiki/NES_APU)
- [Pulse channels](https://www.nesdev.org/wiki/APU_Pulse)
- [Envelope](https://www.nesdev.org/wiki/APU_Envelope)
- [Length counter](https://www.nesdev.org/wiki/APU_Length_Counter)
- [Sweep unit](https://www.nesdev.org/wiki/APU_Sweep)
- [Triangle channel](https://www.nesdev.org/wiki/APU_Triangle)
- [Noise channel](https://www.nesdev.org/wiki/APU_Noise)
- [DMC channel](https://www.nesdev.org/wiki/APU_DMC)
- [DMA](https://www.nesdev.org/wiki/DMA)
- [CPU interrupts](https://www.nesdev.org/wiki/CPU_interrupts)
- [Frame counter](https://www.nesdev.org/wiki/APU_Frame_Counter)
- [Mixer](https://www.nesdev.org/wiki/APU_Mixer)
- [Clock reference](https://www.nesdev.org/wiki/Cycle_reference_chart)
- [pygame mixer](https://www.pygame.org/docs/ref/mixer.html)

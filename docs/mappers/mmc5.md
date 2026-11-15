# MMC5 (mapper 5) pilot

MMC5 cartridges add memory, graphics controls, and interrupts beyond the base
NES. This pilot removes the mapper-5 startup rejection and connects those
devices to pynes. The local NES 2.0 Uncharted Waters image has been exercised
through its introduction, title, and character creation, with base APU music.
It does not establish compatibility with every MMC5 game or every later scene.

Run a locally supplied image with:

```bash
python nes.py rom/uncharted_waters.nes --audio-pilot
```

The five base APU channels provide audio. MMC5's additional pulse/PCM channels
are not synthesized. Cartridge RAM, including memory marked battery backed,
is retained across emulator reset but **is not saved to disk on exit**.

## Memory and CPU integration

[mmc5.py](../../src/nes_py/mmc5.py) implements the mapper, while the specialized
`MMC5Bus` in [nes.py](../../src/nes_py/nes.py) routes its CPU accesses. The normal
bus implementation remains in use for the other mapper cores.

The four PRG modes select 32 KiB, 16 KiB, and 8 KiB windows. Some windows can
select RAM instead of ROM; the final CPU window always selects ROM. Writes
update decoded memory windows, and the CPU reads their backing buffers directly.
RAM writes require both protection registers to be unlocked.

The mapper models the commercial 0, 8, 16, 32, and 64 KiB RAM arrangements.
For a 16 KiB board, banks 0–3 alias one 8 KiB chip and banks 4–7 alias the other.
This differs from a flat array in which bank 1 would select a different page
from bank 0. It also lets CPU windows at different addresses expose the same
physical RAM. Missing chips return the current open-bus value.

The NES 2.0 header supplies volatile and nonvolatile RAM sizes; both are
allocated for the in-memory model. Legacy iNES uses its existing RAM-size
assumption, which may not identify every board correctly. No ROM checksum
database or game-name special case is used.

Two multiplication operands produce a 16-bit unsigned result. Reads of the
low and high result registers reflect the current operands immediately.

## Graphics integration

The [PPU](../../src/nes_py/ppu.py) provides the rendering context that a simple
address-only mapper cannot infer from a whole-scanline snapshot:

- CHR banks use 1, 2, 4, or 8 KiB sizes. Bank writes latch their upper bits and
  current size interpretation; changing a mode does not rewrite old registers.
- CPU PPUDATA accesses follow the last written CHR group. Rendering can select
  independent background and 8x16 sprite groups.
- Each logical nametable can select either internal RAM page, ExRAM, or fill
  data. Fill attributes use the selected palette throughout the page.
- Extended attributes supply a palette and a 4 KiB CHR bank for each 8x8 tile,
  independently of the ordinary attribute table and normal CHR-bank registers.
- Background rendering snapshots current nametable and attribute rows, then
  reuses decoded strips keyed by actual pattern and palette bytes. CHR edits,
  bank changes, fine scrolling, and nametable crossings remain visible.

ExRAM's CPU access follows its selected mode. Graphics modes expose write-only
CPU access during rendering; RAM mode permits reads and writes, and read-only
mode ignores CPU writes. Blanking writes in graphics modes store zero in this
deterministic approximation of the hardware's restricted/corrupting behavior.

## IRQs and timing

Visible-scanline PPU events clock the mapper near dot 4. The first detected
line starts its counter at zero, and a nonzero target can latch a pending IRQ.
Disabling IRQ delivery leaves the pending condition latched. Reading status
acknowledges it; entering the CPU IRQ handler by itself does not.

The mapper stops reporting an active picture after the visible region. NMI
vector reads acknowledge its IRQ and reset frame detection. Mapper and APU
requests are combined before driving the CPU line, so acknowledging one source
does not cancel another source's request. DMC reads use the same mapped bus,
and their nominal stalls advance the shared clocks.

This is a scanline approximation of the hardware fetch detector. Exact dummy
reads, idle-gap detection, interrupt collisions, and changes within a line
remain outside the renderer's timing resolution.

## Validation and performance

[test_mmc5.py](../../tests/test_mmc5.py) uses generated headers, programs,
patterns, and labeled memory pages. Coverage includes:

- All PRG/CHR modes, RAM aliases and protection, ROM/RAM switching, missing
  chips, header limits, CHR latching, and distinct rendering contexts.
- Nametable sources, fill colors, ExRAM access, extended palettes/banks, fine
  scroll across nametables, and fresh graphics data after cache reuse.
- Multiplication, IRQ pending/enabling/acknowledgement, shared APU IRQ levels,
  NMI effects, actual CPU interrupt execution, DMA clocks, and CLI startup.

A local character-creation checkpoint was used for an optimization comparison:
60 warmup frames followed by 180 measured frames, including CPU, PPU, APU,
RGB output, and PCM draining. The checkpoint and commercial image remain local.

| Same local menu workload | Before optimization | After optimization |
|---|---:|---:|
| Headless throughput | 62.12 FPS | 73.43 FPS |
| Work per frame | 16.10 ms | 13.62 ms |

This is approximately 18% more throughput in one local comparison within the
pilot's development. All measured RGB frames, PCM, final CPU state, and
internal/cartridge RAM matched the reference. It excludes desktop scaling and
the audio device and does not guarantee the same performance on other hardware.

Press **F3** during play to inspect real desktop FPS and emulation/audio/video
work times. At 60 FPS, game logic can still choose to animate or move at a
slower pace. Lower FPS means the host is missing the emulator's presentation
target; a headless measurement alone cannot identify the desktop bottleneck.

## Remaining work

- Persistent save files; current cartridge RAM lasts only for the process.
- MMC5 expansion pulse/PCM audio and its PCM IRQ behavior.
- Vertical-split rendering; the registers are retained for diagnostics.
- Precise fetch detection, reset retention, and other hardware timing quirks.
- MMC5A timer features, larger/custom RAM layouts, and broader game validation.

The `unsupported_features` diagnostic records uses of the unimplemented split
or expansion-audio controls. The local introduction/character-creation checks
did not activate those controls.

Hardware reference: [NESdev MMC5 documentation](https://www.nesdev.org/wiki/MMC5).

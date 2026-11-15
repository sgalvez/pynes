# Cartridge formats and NES 2.0 support

pynes reads legacy iNES files and a basic subset of NES 2.0. Both use the
`.nes` extension and a 16-byte header. NES 2.0 adds more precise hardware
metadata to that header. Loading the format and emulating the cartridge's
hardware are separate requirements.

The loader now accepts supported NES 2.0 boards directly, including UxROM
images with submapper 2 and explicit 8 KiB CHR RAM. The original file is read
without modification. Game compatibility still depends on the CPU, graphics,
audio, mapper, and timing behavior the game uses.

## Supported NES 2.0 boards

| Mapper | Submappers | PRG ROM | CHR memory | PRG RAM |
|---|---|---|---|---|
| NROM (0) | 0 | 16 or 32 KiB | 8 KiB ROM or 8 KiB RAM | None or 8 KiB |
| MMC1 (1) | 0 | 16–256 KiB | Up to 128 KiB ROM, or 8 KiB RAM | None or 8 KiB |
| UxROM (2) | 0, 1, 2 | 32–256 KiB | 8 KiB ROM or 8 KiB RAM | None |
| MMC5 (5) | 0 | 16 KiB–1 MiB | Up to 1 MiB ROM, or 8 KiB RAM | 0, 8, 16, 32, or 64 KiB |

These are the limits of the current cores, not all layouts possible on those
mapper numbers. MMC1's additional outer PRG/RAM banking and RAM protection
behavior remain incomplete.

MMC5 uses the commercial ExROM RAM-chip arrangements, including the two 8 KiB
chips in a 16 KiB board. RAM marked nonvolatile is emulated in memory, with no
save-file persistence yet. See the [MMC5 pilot](mappers/mmc5.md) for bank aliases,
graphics features, and remaining limitations.

Only standard NES/Famicom console types and standard controllers are supported.
NTSC ROMs use the existing NTSC model. Multiple-region ROMs also run using NTSC;
PAL-only and Dendy timing are rejected. Expansion peripherals and miscellaneous
ROM areas are unsupported.

## Header sizes and memory

The loader recognizes the NES 2.0 marker in byte 7 and reads:

- The full 12-bit mapper number and 4-bit submapper from bytes 6–8.
- The extended linear PRG/CHR counts or exponent/multiplier sizes from bytes
  4, 5, and 9. The supported boards require whole 16 KiB PRG and 8 KiB CHR
  ROM banks; other sizes produce a specific error.
- Volatile and nonvolatile PRG/CHR RAM size declarations from bytes 10–11.
- Console type, timing, miscellaneous-ROM count, and default expansion device.

Sizes are decoded before checking the board's supported layout. A large
extended mapper number is never reduced to its low byte to select an unrelated
mapper. Unsupported size declarations are rejected before allocating cartridge RAM.
Truncated payloads are checked against the decoded ROM sizes and trainer offset.

NES 2.0 CHR RAM must be explicitly declared. If CHR ROM is absent, the current
cores require a declaration of exactly 8 KiB of CHR RAM. The loader does not
silently invent that RAM. Mixed CHR ROM/RAM and nonvolatile CHR RAM are
unsupported. Nonvolatile PRG RAM is accepted by MMC5's in-memory RAM model;
the other supported NES 2.0 mappers still reject it.

On supported NROM/MMC1 NES 2.0 boards, declared 8 KiB PRG RAM is visible at CPU
`$6000`–`$7FFF`. Reads from absent PRG RAM or the unused expansion region
return the last bus value, and writes do not store data there. Exact open-bus
electrical behavior is not modeled.

MMC5 owns additional registers at `$5000`–`$5206`, extended RAM at
`$5C00`–`$5FFF`, and banked RAM/ROM windows. Its chip-selection and write
protection rules replace the generic expansion storage for that cartridge.

Legacy iNES keeps its earlier RAM assumptions and placeholder expansion
storage. The loader skips a flagged 512-byte trainer to locate the PRG payload;
installing trainer contents into CPU memory remains unimplemented.

## UxROM bus conflicts

Some UxROM boards let both the cartridge ROM and CPU drive the data bus during
a mapper write. The bank register sees their bitwise AND. The ROM byte must
come from the mapping that was active **before** the write changes the bank.

For example, if the CPU writes `3` and the currently mapped ROM byte at that
address is `1`, the bank register receives `3 & 1`, or `1`.

| NES 2.0 UxROM submapper | Current behavior |
|---|---|
| 0 | Use AND conflicts, the common UxROM board behavior |
| 1 | Write the CPU value directly; no conflict |
| 2 | Apply AND conflicts with the currently mapped ROM byte |

Legacy iNES UxROM retains its previous nonconflicting behavior. Other UxROM
submappers are rejected. The distinction follows the
[NESdev submapper definitions](https://www.nesdev.org/wiki/NES_2.0_submappers).

## Running and troubleshooting

Use the same CLI for either supported format:

```bash
python nes.py rom/game.nes --audio-pilot
```

For a CPU startup check without a window or audio device:

```bash
python nes.py rom/game.nes --smoke-test 10000
```

The old message `NES 2.0 ROMs are not supported yet` indicates a loader from
before this change. Updated code reports the specific unsupported mapper,
submapper, RAM layout, timing, or device instead. Implementing header parsing
does not add hardware support for other mappers.

## Implementation and validation

- [cartridge.py](../src/nes_py/cartridge.py): metadata parsing, layout checks,
  payload extraction, mapper construction, and UxROM conflict handling.
- [nes.py](../src/nes_py/nes.py): declared PRG RAM and open-bus routing.
- [test_nes2.py](../tests/test_nes2.py): generated headers/programs covering
  extension fields, exponent sizes, memory declarations, rejection paths,
  bus conflicts across bank changes, CLI startup, frame execution, and PCM.

All automated examples are generated. Local ROM validation does not establish
full compatibility and does not add commercial data to the repository.

Hardware references:

- [NESdev: NES 2.0](https://www.nesdev.org/wiki/NES_2.0)
- [NESdev: UxROM](https://www.nesdev.org/wiki/UxROM)
- [NESdev: NES 2.0 submappers](https://www.nesdev.org/wiki/NES_2.0_submappers)

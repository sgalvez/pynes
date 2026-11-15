"""iNES/NES 2.0 ROM loading and cartridge abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from .mmc5 import Mapper5

INES_MAGIC = b"NES\x1a"
INES_HEADER_SIZE = 16
PRG_ROM_BANK_SIZE = 16 * 1024
CHR_ROM_BANK_SIZE = 8 * 1024
CHR_BANK_4KB_SIZE = 4 * 1024
PRG_RAM_SIZE = 8 * 1024
CHR_RAM_SIZE = 8 * 1024


class CartridgeError(ValueError):
    """Raised when a ROM cannot be loaded as a supported cartridge."""


class Mirroring(Enum):
    """Nametable mirroring mode from the cartridge header."""

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    FOUR_SCREEN = "four_screen"
    SINGLE_SCREEN_LOWER = "single_screen_lower"
    SINGLE_SCREEN_UPPER = "single_screen_upper"


@dataclass(frozen=True)
class INESHeader:
    """Parsed iNES/NES 2.0 metadata for the supported cartridge layouts."""

    prg_rom_banks: int
    chr_rom_banks: int
    mapper_number: int
    mirroring: Mirroring
    has_trainer: bool
    format_version: int = 1
    submapper_number: int = 0
    prg_ram_size: int = 0
    prg_nvram_size: int = 0
    chr_ram_size: int = 0
    chr_nvram_size: int = 0
    timing_mode: int = 0
    console_type: int = 0
    misc_rom_count: int = 0
    expansion_device: int = 0

    @property
    def prg_rom_size(self) -> int:
        return self.prg_rom_banks * PRG_ROM_BANK_SIZE

    @property
    def chr_rom_size(self) -> int:
        return self.chr_rom_banks * CHR_ROM_BANK_SIZE


@dataclass(frozen=True)
class Mapper0:
    """Mapper 0 / NROM address mapping."""

    prg_rom_size: int
    has_chr_ram: bool

    def map_cpu_address(self, address: int) -> int:
        """Map a CPU PRG ROM address into the cartridge PRG ROM buffer."""
        if not 0x8000 <= address <= 0xFFFF:
            raise CartridgeError(
                f"CPU address 0x{address:04X} is outside PRG ROM range 0x8000-0xFFFF"
            )

        if self.prg_rom_size == PRG_ROM_BANK_SIZE:
            return (address - 0x8000) % PRG_ROM_BANK_SIZE
        if self.prg_rom_size == 2 * PRG_ROM_BANK_SIZE:
            return address - 0x8000

        raise CartridgeError(
            f"Mapper 0 supports 16 KB or 32 KB PRG ROM, got {self.prg_rom_size} bytes"
        )

    def map_ppu_address(self, address: int) -> int:
        """Map a PPU CHR address into the cartridge CHR ROM/RAM buffer."""
        if not 0x0000 <= address <= 0x1FFF:
            raise CartridgeError(
                f"PPU address 0x{address:04X} is outside CHR range 0x0000-0x1FFF"
            )
        return address

    def write_cpu_address(self, address: int, value: int) -> None:
        """Ignore CPU writes to PRG ROM space."""


@lru_cache(maxsize=128)
def _mmc1_prg_bases(count: int, mode: int, selected: int) -> tuple[int, int]:
    """Resolve PRG windows by live register values, including direct mutations."""
    if mode in (0, 1):
        lower, upper = selected & 0x0E, (selected & 0x0E) + 1
    elif mode == 2:
        lower, upper = 0, selected
    else:
        lower, upper = selected, count - 1
    return (lower % count) * PRG_ROM_BANK_SIZE, (upper % count) * PRG_ROM_BANK_SIZE


@dataclass
class Mapper1:
    """Mapper 1 / MMC1 serial-register address mapping."""

    prg_rom_banks: int
    chr_rom_banks: int
    control: int = 0x0C
    chr_bank0: int = 0
    chr_bank1: int = 0
    prg_bank: int = 0
    shift_register: int = 0x10

    def map_cpu_address(self, address: int) -> int:
        """Map a CPU PRG ROM address into the cartridge PRG ROM buffer."""
        if not 0x8000 <= address <= 0xFFFF:
            raise CartridgeError(
                f"CPU address 0x{address:04X} is outside PRG ROM range 0x8000-0xFFFF"
            )

        lower, upper = _mmc1_prg_bases(
            self.prg_rom_banks, (self.control >> 2) & 3, self.prg_bank & 0x0F
        )
        return (lower if address < 0xC000 else upper) + (address & 0x3FFF)

    def map_ppu_address(self, address: int) -> int:
        """Map a PPU CHR address into the cartridge CHR ROM/RAM buffer."""
        if not 0x0000 <= address <= 0x1FFF:
            raise CartridgeError(
                f"PPU address 0x{address:04X} is outside CHR range 0x0000-0x1FFF"
            )

        chr_bank_count = self.chr_rom_banks * 2 if self.chr_rom_banks else 2
        chr_mode = (self.control >> 4) & 0x01
        if chr_mode == 0:
            bank = (self.chr_bank0 & 0x1E) + (address // CHR_BANK_4KB_SIZE)
        elif address < CHR_BANK_4KB_SIZE:
            bank = self.chr_bank0
        else:
            bank = self.chr_bank1
        return ((bank % chr_bank_count) * CHR_BANK_4KB_SIZE) + (address & 0x0FFF)

    def write_cpu_address(self, address: int, value: int) -> None:
        """Load MMC1's serial shift register and commit completed writes."""
        if not 0x8000 <= address <= 0xFFFF:
            raise CartridgeError(
                f"CPU address 0x{address:04X} is outside PRG ROM range 0x8000-0xFFFF"
            )
        if value & 0x80:
            self.shift_register = 0x10
            self.control |= 0x0C
            return

        commit = bool(self.shift_register & 0x01)
        self.shift_register = (self.shift_register >> 1) | ((value & 0x01) << 4)
        if not commit:
            return

        register_value = self.shift_register & 0x1F
        if 0x8000 <= address <= 0x9FFF:
            self.control = register_value
        elif 0xA000 <= address <= 0xBFFF:
            self.chr_bank0 = register_value
        elif 0xC000 <= address <= 0xDFFF:
            self.chr_bank1 = register_value
        else:
            self.prg_bank = register_value
        self.shift_register = 0x10


@dataclass
class Mapper2:
    """Mapper 2 / UxROM address mapping with a switchable lower PRG bank."""

    prg_rom_banks: int
    selected_bank: int = 0
    bus_conflicts: bool = False

    @property
    def prg_rom_size(self) -> int:
        return self.prg_rom_banks * PRG_ROM_BANK_SIZE

    def map_cpu_address(self, address: int) -> int:
        """Map a CPU PRG ROM address into the cartridge PRG ROM buffer."""
        if not 0x8000 <= address <= 0xFFFF:
            raise CartridgeError(
                f"CPU address 0x{address:04X} is outside PRG ROM range 0x8000-0xFFFF"
            )

        offset = address & 0x3FFF
        if 0x8000 <= address <= 0xBFFF:
            bank = self.selected_bank
        else:
            bank = self.prg_rom_banks - 1
        return (bank * PRG_ROM_BANK_SIZE) + offset

    def map_ppu_address(self, address: int) -> int:
        """Map a PPU CHR address into the cartridge CHR ROM/RAM buffer."""
        if not 0x0000 <= address <= 0x1FFF:
            raise CartridgeError(
                f"PPU address 0x{address:04X} is outside CHR range 0x0000-0x1FFF"
            )
        return address

    def write_cpu_address(self, address: int, value: int) -> None:
        """Select the switchable PRG ROM bank."""
        if not 0x8000 <= address <= 0xFFFF:
            raise CartridgeError(
                f"CPU address 0x{address:04X} is outside PRG ROM range 0x8000-0xFFFF"
            )
        self.selected_bank = (value & 0x0F) % self.prg_rom_banks


@dataclass
class Cartridge:
    """Loaded cartridge data and mapper behavior."""

    header: INESHeader
    prg_rom: bytes
    chr_data: bytearray
    mapper: Mapper0 | Mapper1 | Mapper2 | Mapper5

    @property
    def mapper_number(self) -> int:
        return self.header.mapper_number

    @property
    def mirroring(self) -> Mirroring:
        if isinstance(self.mapper, Mapper1):
            return (
                Mirroring.SINGLE_SCREEN_LOWER,
                Mirroring.SINGLE_SCREEN_UPPER,
                Mirroring.VERTICAL,
                Mirroring.HORIZONTAL,
            )[self.mapper.control & 0x03]
        return self.header.mirroring

    @property
    def has_chr_ram(self) -> bool:
        return self.header.chr_rom_banks == 0

    def read_prg(self, address: int) -> int:
        """Read a byte from CPU-visible PRG ROM."""
        if isinstance(self.mapper, Mapper5):
            return self.mapper.read_cpu(address)
        return self.prg_rom[self.mapper.map_cpu_address(address)]

    def write_prg(self, address: int, value: int) -> None:
        """Write a byte to CPU-visible cartridge space."""
        if isinstance(self.mapper, Mapper5):
            self.mapper.write_cpu(address, value)
            return
        if isinstance(self.mapper, Mapper2) and self.mapper.bus_conflicts:
            # Sample ROM using the old bank: both chips drive the data bus
            # during this write, before the bank register latches the AND.
            value &= self.read_prg(address)
        self.mapper.write_cpu_address(address, value & 0xFF)

    def read_chr(self, address: int) -> int:
        """Read a byte from PPU-visible CHR ROM/RAM."""
        return self.chr_data[self.mapper.map_ppu_address(address)]

    def write_chr(self, address: int, value: int) -> None:
        """Write a byte to CHR RAM."""
        if not self.has_chr_ram:
            raise CartridgeError("Cannot write to CHR ROM")
        self.chr_data[self.mapper.map_ppu_address(address)] = value & 0xFF


def _nes2_rom_banks(low: int, high: int, bank_size: int, kind: str) -> int:
    """Decode NES 2.0 linear or exponent/multiplier sizes into whole banks."""
    if high != 0x0F:
        return (high << 8) | low
    size = (1 << (low >> 2)) * (2 * (low & 3) + 1)
    if size % bank_size:
        raise CartridgeError(
            f"Unsupported NES 2.0 {kind} ROM size {size}: "
            f"supported boards require whole {bank_size}-byte banks"
        )
    return size // bank_size


def _nes2_ram_size(shift: int) -> int:
    return 64 << shift if shift else 0


def parse_ines_header(data: bytes) -> INESHeader:
    """Parse a 16-byte iNES or NES 2.0 header without allocating ROM/RAM."""
    if len(data) < INES_HEADER_SIZE:
        raise CartridgeError("ROM is too small to contain an iNES header")

    header = data[:INES_HEADER_SIZE]
    if header[:4] != INES_MAGIC:
        raise CartridgeError("Invalid iNES header: missing NES magic bytes")

    flags6 = header[6]
    flags7 = header[7]
    format_version = 2 if (flags7 & 0x0C) == 0x08 else 1
    mapper_number = (flags6 >> 4) | (flags7 & 0xF0)
    prg_banks, chr_banks = header[4], header[5]
    submapper = 0
    # Retain the conventional iNES RAM assumption for legacy metadata only.
    prg_memory = (header[8] or 1) * PRG_RAM_SIZE
    prg_ram = 0 if flags6 & 2 else prg_memory
    prg_nvram = prg_memory if flags6 & 2 else 0
    chr_ram = CHR_RAM_SIZE if chr_banks == 0 else 0
    chr_nvram = timing = console = misc_roms = expansion = 0
    if format_version == 2:
        mapper_number |= (header[8] & 0x0F) << 8
        submapper = header[8] >> 4
        prg_banks = _nes2_rom_banks(
            header[4], header[9] & 0x0F, PRG_ROM_BANK_SIZE, "PRG"
        )
        chr_banks = _nes2_rom_banks(
            header[5], header[9] >> 4, CHR_ROM_BANK_SIZE, "CHR"
        )
        prg_ram = _nes2_ram_size(header[10] & 0x0F)
        prg_nvram = _nes2_ram_size(header[10] >> 4)
        chr_ram = _nes2_ram_size(header[11] & 0x0F)
        chr_nvram = _nes2_ram_size(header[11] >> 4)
        timing = header[12] & 3
        console = flags7 & 3
        misc_roms = header[14] & 3
        expansion = header[15] & 0x7F
    if flags6 & 0x08:
        mirroring = Mirroring.FOUR_SCREEN
    elif flags6 & 0x01:
        mirroring = Mirroring.VERTICAL
    else:
        mirroring = Mirroring.HORIZONTAL

    return INESHeader(
        prg_rom_banks=prg_banks,
        chr_rom_banks=chr_banks,
        mapper_number=mapper_number,
        mirroring=mirroring,
        has_trainer=bool(flags6 & 0x04),
        format_version=format_version,
        submapper_number=submapper,
        prg_ram_size=prg_ram,
        prg_nvram_size=prg_nvram,
        chr_ram_size=chr_ram,
        chr_nvram_size=chr_nvram,
        timing_mode=timing,
        console_type=console,
        misc_rom_count=misc_roms,
        expansion_device=expansion,
    )


def _validate_nes2_hardware(header: INESHeader) -> None:
    """Reject NES 2.0 hardware that the existing mapper cores cannot model."""
    if header.format_version != 2:
        return
    submappers = (0, 1, 2) if header.mapper_number == 2 else (0,)
    if header.submapper_number not in submappers:
        raise CartridgeError(
            f"Unsupported submapper {header.submapper_number} for mapper "
            f"{header.mapper_number}; supported submappers: {submappers}"
        )
    if header.console_type:
        raise CartridgeError("Unsupported NES 2.0 console type; standard NES/Famicom only")
    if header.timing_mode not in (0, 2):
        raise CartridgeError("Unsupported NES 2.0 timing; NTSC or multiple-region ROMs only")
    if header.misc_rom_count:
        raise CartridgeError("NES 2.0 miscellaneous ROMs are not supported")
    if header.expansion_device not in (0, 1):
        raise CartridgeError("Unsupported NES 2.0 expansion device; standard controllers only")
    if header.mapper_number == 5:
        # MMC5 owns banked RAM, including memory marked battery backed. Its
        # layout is checked below; persistence is separate from RAM emulation.
        return
    if header.prg_nvram_size or header.chr_nvram_size:
        raise CartridgeError("NES 2.0 nonvolatile cartridge RAM is not supported")
    if header.prg_ram_size not in (0, PRG_RAM_SIZE):
        raise CartridgeError("Unsupported NES 2.0 PRG RAM size; expected 0 or 8192 bytes")
    if header.mapper_number == 2 and header.prg_ram_size:
        raise CartridgeError("NES 2.0 UxROM with PRG RAM is not supported")
    if header.chr_rom_banks:
        if header.chr_ram_size:
            raise CartridgeError("NES 2.0 mixed CHR ROM/RAM is not supported")
    elif header.chr_ram_size != CHR_RAM_SIZE:
        raise CartridgeError("Unsupported NES 2.0 CHR RAM size; expected 8192 bytes")
    if header.mapper_number in (0, 2) and header.chr_rom_banks > 1:
        raise CartridgeError("Supported NROM/UxROM boards have at most 8192 bytes of CHR ROM")
    if header.mapper_number in (1, 2) and header.prg_rom_banks > 16:
        raise CartridgeError("Supported MMC1/UxROM boards have at most 256 KiB of PRG ROM")
    if header.mapper_number == 1 and header.chr_rom_banks > 16:
        raise CartridgeError("Supported MMC1 boards have at most 128 KiB of CHR ROM")


def load_ines_rom(data: bytes) -> Cartridge:
    """Load a supported iNES or NES 2.0 cartridge from bytes."""
    header = parse_ines_header(data)
    if header.mapper_number == 0:
        if header.prg_rom_banks not in (1, 2):
            raise CartridgeError(
                "Invalid Mapper 0 ROM: expected 1 or 2 PRG ROM banks, "
                f"got {header.prg_rom_banks}. The ROM header may declare the wrong mapper."
            )
        mapper: Mapper0 | Mapper1 | Mapper2 | Mapper5 | None = Mapper0(
            prg_rom_size=header.prg_rom_size,
            has_chr_ram=header.chr_rom_banks == 0,
        )
    elif header.mapper_number == 1:
        if header.prg_rom_banks < 1:
            raise CartridgeError(
                f"Mapper 1 requires at least 1 PRG ROM bank, got {header.prg_rom_banks}"
            )
        mapper = Mapper1(
            prg_rom_banks=header.prg_rom_banks,
            chr_rom_banks=header.chr_rom_banks,
        )
    elif header.mapper_number == 2:
        if header.prg_rom_banks < 2:
            raise CartridgeError(
                f"Mapper 2 requires at least 2 PRG ROM banks, got {header.prg_rom_banks}"
            )
        mapper = Mapper2(
            prg_rom_banks=header.prg_rom_banks,
            # Unspecified NES 2.0 UxROM defaults to the common conflict board;
            # iNES keeps its prior behavior and submapper 1 explicitly has none.
            bus_conflicts=header.format_version == 2 and header.submapper_number != 1,
        )
    elif header.mapper_number == 5:
        if not 1 <= header.prg_rom_banks <= 64:
            raise CartridgeError("MMC5 requires 16 KiB to 1 MiB of PRG ROM")
        if header.chr_rom_banks > 128:
            raise CartridgeError("MMC5 supports at most 1 MiB of CHR ROM")
        if header.chr_nvram_size or (
            header.chr_ram_size != (0 if header.chr_rom_banks else CHR_RAM_SIZE)
        ):
            raise CartridgeError("Supported MMC5 CHR layouts are ROM or 8 KiB volatile RAM")
        ram_size = header.prg_ram_size + header.prg_nvram_size
        if ram_size not in (0, 0x2000, 0x4000, 0x8000, 0x10000) or (
            header.prg_ram_size % PRG_RAM_SIZE or header.prg_nvram_size % PRG_RAM_SIZE
        ):
            raise CartridgeError("Supported MMC5 PRG RAM sizes are 0, 8, 16, 32, or 64 KiB")
        mapper = None  # Construct MMC5 after validating/extracting its ROM data.
    else:
        raise CartridgeError(
            f"Unsupported mapper {header.mapper_number}; supported mappers: 0, 1, 2, 5"
        )

    _validate_nes2_hardware(header)
    prg_start = INES_HEADER_SIZE + (512 if header.has_trainer else 0)
    chr_start = prg_start + header.prg_rom_size
    expected_size = chr_start + header.chr_rom_size
    if len(data) < expected_size:
        raise CartridgeError(
            f"ROM is truncated: expected at least {expected_size} bytes, got {len(data)}"
        )

    prg_rom = data[prg_start:chr_start]
    chr_data = (
        bytearray(header.chr_ram_size)
        if header.chr_rom_banks == 0
        else bytearray(data[chr_start:expected_size])
    )
    if mapper is None:
        mapper = Mapper5(
            prg_rom,
            len(chr_data),
            header.prg_ram_size + header.prg_nvram_size,
        )

    return Cartridge(
        header=header,
        prg_rom=prg_rom,
        chr_data=chr_data,
        mapper=mapper,
    )


def load_ines_file(path: str | Path) -> Cartridge:
    """Load a supported iNES or NES 2.0 cartridge from a file path."""
    return load_ines_rom(Path(path).read_bytes())

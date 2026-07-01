"""iNES ROM loading and cartridge abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

INES_MAGIC = b"NES\x1a"
INES_HEADER_SIZE = 16
PRG_ROM_BANK_SIZE = 16 * 1024
CHR_ROM_BANK_SIZE = 8 * 1024
CHR_RAM_SIZE = 8 * 1024


class CartridgeError(ValueError):
    """Raised when a ROM cannot be loaded as a supported cartridge."""


class Mirroring(Enum):
    """Nametable mirroring mode from the cartridge header."""

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    FOUR_SCREEN = "four_screen"


@dataclass(frozen=True)
class INESHeader:
    """Parsed iNES header metadata."""

    prg_rom_banks: int
    chr_rom_banks: int
    mapper_number: int
    mirroring: Mirroring
    has_trainer: bool

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


@dataclass
class Mapper2:
    """Mapper 2 / UxROM address mapping with a switchable lower PRG bank."""

    prg_rom_banks: int
    selected_bank: int = 0

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
    """Loaded iNES cartridge data and mapper behavior."""

    header: INESHeader
    prg_rom: bytes
    chr_data: bytearray
    mapper: Mapper0 | Mapper2

    @property
    def mapper_number(self) -> int:
        return self.header.mapper_number

    @property
    def mirroring(self) -> Mirroring:
        return self.header.mirroring

    @property
    def has_chr_ram(self) -> bool:
        return self.header.chr_rom_banks == 0

    def read_prg(self, address: int) -> int:
        """Read a byte from CPU-visible PRG ROM."""
        return self.prg_rom[self.mapper.map_cpu_address(address)]

    def write_prg(self, address: int, value: int) -> None:
        """Write a byte to CPU-visible cartridge space."""
        self.mapper.write_cpu_address(address, value & 0xFF)

    def read_chr(self, address: int) -> int:
        """Read a byte from PPU-visible CHR ROM/RAM."""
        return self.chr_data[self.mapper.map_ppu_address(address)]

    def write_chr(self, address: int, value: int) -> None:
        """Write a byte to CHR RAM."""
        if not self.has_chr_ram:
            raise CartridgeError("Cannot write to CHR ROM")
        self.chr_data[self.mapper.map_ppu_address(address)] = value & 0xFF


def parse_ines_header(data: bytes) -> INESHeader:
    """Parse and validate a 16-byte iNES header."""
    if len(data) < INES_HEADER_SIZE:
        raise CartridgeError("ROM is too small to contain an iNES header")

    header = data[:INES_HEADER_SIZE]
    if header[:4] != INES_MAGIC:
        raise CartridgeError("Invalid iNES header: missing NES magic bytes")

    flags6 = header[6]
    flags7 = header[7]
    if (flags7 & 0x0C) == 0x08:
        raise CartridgeError("NES 2.0 ROMs are not supported yet")

    mapper_number = (flags6 >> 4) | (flags7 & 0xF0)
    if flags6 & 0x08:
        mirroring = Mirroring.FOUR_SCREEN
    elif flags6 & 0x01:
        mirroring = Mirroring.VERTICAL
    else:
        mirroring = Mirroring.HORIZONTAL

    return INESHeader(
        prg_rom_banks=header[4],
        chr_rom_banks=header[5],
        mapper_number=mapper_number,
        mirroring=mirroring,
        has_trainer=bool(flags6 & 0x04),
    )


def load_ines_rom(data: bytes) -> Cartridge:
    """Load a supported iNES ROM from bytes."""
    header = parse_ines_header(data)
    if header.mapper_number == 0:
        if header.prg_rom_banks not in (1, 2):
            raise CartridgeError(
                "Invalid Mapper 0 ROM: expected 1 or 2 PRG ROM banks, "
                f"got {header.prg_rom_banks}. The ROM header may declare the wrong mapper."
            )
        mapper: Mapper0 | Mapper2 = Mapper0(
            prg_rom_size=header.prg_rom_size,
            has_chr_ram=header.chr_rom_banks == 0,
        )
    elif header.mapper_number == 2:
        if header.prg_rom_banks < 2:
            raise CartridgeError(
                f"Mapper 2 requires at least 2 PRG ROM banks, got {header.prg_rom_banks}"
            )
        mapper = Mapper2(prg_rom_banks=header.prg_rom_banks)
    else:
        raise CartridgeError(
            f"Unsupported mapper {header.mapper_number}; supported mappers: 0, 2"
        )

    prg_start = INES_HEADER_SIZE + (512 if header.has_trainer else 0)
    chr_start = prg_start + header.prg_rom_size
    expected_size = chr_start + header.chr_rom_size
    if len(data) < expected_size:
        raise CartridgeError(
            f"ROM is truncated: expected at least {expected_size} bytes, got {len(data)}"
        )

    prg_rom = data[prg_start:chr_start]
    chr_data = (
        bytearray(CHR_RAM_SIZE)
        if header.chr_rom_banks == 0
        else bytearray(data[chr_start:expected_size])
    )

    return Cartridge(
        header=header,
        prg_rom=prg_rom,
        chr_data=chr_data,
        mapper=mapper,
    )


def load_ines_file(path: str | Path) -> Cartridge:
    """Load a supported iNES ROM from a file path."""
    return load_ines_rom(Path(path).read_bytes())

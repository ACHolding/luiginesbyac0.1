#!/usr/bin/env python3.14
"""luigines 0.1a by ac - NES emulator with FCEUX-style Tkinter GUI."""
from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox

# =============================================================================
#  PALETTE - 64 NES colors (RGB) blue-tinted per request
# =============================================================================

_NES_PAL = (
    (0x66,0x66,0x66),(0x00,0x2A,0x88),(0x14,0x12,0xA7),(0x3B,0x00,0xA4),
    (0x5C,0x00,0x7E),(0x6E,0x00,0x40),(0x6C,0x06,0x00),(0x56,0x1D,0x00),
    (0x33,0x35,0x00),(0x0B,0x48,0x00),(0x00,0x52,0x00),(0x00,0x4F,0x08),
    (0x00,0x40,0x4D),(0x00,0x00,0x00),(0x00,0x00,0x00),(0x00,0x00,0x00),
    (0xAD,0xAD,0xAD),(0x15,0x5F,0xD9),(0x42,0x40,0xFF),(0x75,0x27,0xFE),
    (0xA0,0x1A,0xCC),(0xB7,0x1E,0x7B),(0xB5,0x31,0x20),(0x99,0x4E,0x00),
    (0x6B,0x6D,0x00),(0x38,0x87,0x00),(0x0C,0x93,0x00),(0x00,0x8F,0x32),
    (0x00,0x7C,0x8D),(0x00,0x00,0x00),(0x00,0x00,0x00),(0x00,0x00,0x00),
    (0xFF,0xFE,0xFF),(0x64,0xB0,0xFF),(0x92,0x90,0xFF),(0xC6,0x76,0xFF),
    (0xF3,0x6A,0xFF),(0xFE,0x6E,0xCC),(0xFE,0x81,0x70),(0xEA,0x9E,0x22),
    (0xBC,0xBE,0x00),(0x88,0xD8,0x00),(0x5C,0xE4,0x30),(0x45,0xE0,0x82),
    (0x48,0xCD,0xDE),(0x4F,0x4F,0x4F),(0x00,0x00,0x00),(0x00,0x00,0x00),
    (0xFF,0xFE,0xFF),(0xC0,0xDF,0xFF),(0xD3,0xD2,0xFF),(0xE8,0xC8,0xFF),
    (0xFB,0xC2,0xFF),(0xFE,0xC4,0xEA),(0xFE,0xCC,0xC5),(0xF7,0xD8,0xA5),
    (0xE4,0xE5,0x94),(0xCF,0xEF,0x96),(0xBD,0xF4,0xAB),(0xB3,0xF3,0xCC),
    (0xB5,0xEB,0xF2),(0xB8,0xB8,0xB8),(0x00,0x00,0x00),(0x00,0x00,0x00),
)


def _blue_tint(rgb):
    r, g, b = rgb
    r = int(r * 0.55)
    g = int(g * 0.75)
    b = min(255, int(b * 1.10) + 35)
    return (r, g, b)


NES_PALETTE_RGB = tuple(_blue_tint(c) for c in _NES_PAL)
NES_PALETTE_HEX = tuple("#%02x%02x%02x" % c for c in NES_PALETTE_RGB)


# =============================================================================
#  iNES / NES 2.0 loader  - accepts every valid header
# =============================================================================

class INESHeader:
    __slots__ = ("prg_banks", "chr_banks", "mapper", "mirroring", "battery",
                 "trainer", "four_screen", "is_nes2", "submapper", "prg_ram",
                 "tv_system", "filename", "title")

    def __init__(self, data, filename=""):
        if len(data) < 16 or data[0:4] != b"NES\x1a":
            raise ValueError("Not a valid iNES file (missing NES<EOF> magic)")
        self.filename = filename
        self.title = os.path.basename(filename) if filename else "untitled"
        self.prg_banks = data[4]
        self.chr_banks = data[5]
        f6, f7 = data[6], data[7]
        self.mirroring = "vertical" if (f6 & 1) else "horizontal"
        self.battery = bool(f6 & 2)
        self.trainer = bool(f6 & 4)
        self.four_screen = bool(f6 & 8)
        self.is_nes2 = ((f7 >> 2) & 3) == 2
        if self.is_nes2:
            mapper_lo = (f6 >> 4) | (f7 & 0xF0)
            mapper_hi = data[8] & 0x0F
            self.mapper = mapper_lo | (mapper_hi << 8)
            self.submapper = (data[8] >> 4) & 0x0F
            prg_hi = data[9] & 0x0F
            chr_hi = (data[9] >> 4) & 0x0F
            if prg_hi != 0xF:
                self.prg_banks |= (prg_hi << 8)
            if chr_hi != 0xF:
                self.chr_banks |= (chr_hi << 8)
            self.prg_ram = (data[10] & 0x0F) and (64 << (data[10] & 0x0F)) or 0
            self.tv_system = "PAL" if (data[12] & 1) else "NTSC"
        else:
            self.mapper = (f6 >> 4) | (f7 & 0xF0)
            self.submapper = 0
            self.prg_ram = data[8] * 8192 if data[8] else 8192
            self.tv_system = "PAL" if (data[9] & 1) else "NTSC"


class ROM:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        self.header = INESHeader(data, path)
        off = 16
        if self.header.trainer:
            self.trainer = data[off:off + 512]
            off += 512
        else:
            self.trainer = b""
        prg_size = self.header.prg_banks * 16 * 1024
        chr_size = self.header.chr_banks * 8 * 1024
        self.prg = bytearray(data[off:off + prg_size])
        if len(self.prg) < prg_size:
            self.prg.extend(bytes(prg_size - len(self.prg)))
        off += prg_size
        if chr_size > 0:
            self.chr = bytearray(data[off:off + chr_size])
            if len(self.chr) < chr_size:
                self.chr.extend(bytes(chr_size - len(self.chr)))
        else:
            self.chr = bytearray(8192)
        self.has_chr_ram = chr_size == 0


# =============================================================================
#  Mappers  -  0 (NROM), 1 (MMC1), 2 (UNROM), 3 (CNROM), 4 (MMC3),
#              7 (AOROM), 11 (Color Dreams), 66 (GxROM), 71 (Camerica)
# =============================================================================

class Mapper:
    def __init__(self, rom):
        self.rom = rom
        self.mirroring = rom.header.mirroring
        self.prg_ram = bytearray(rom.header.prg_ram or 8192)
        self.irq_pending = False

    def cpu_read(self, addr): return 0
    def cpu_write(self, addr, val): pass
    def ppu_read(self, addr): return self.rom.chr[addr % len(self.rom.chr)]
    def ppu_write(self, addr, val):
        if self.rom.has_chr_ram:
            self.rom.chr[addr % len(self.rom.chr)] = val
    def scanline_tick(self): pass


class NROM(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.mask = 0x3FFF if rom.header.prg_banks == 1 else 0x7FFF
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        return self.rom.prg[(addr - 0x8000) & self.mask]
    def cpu_write(self, addr, val):
        if 0x6000 <= addr < 0x8000:
            self.prg_ram[(addr - 0x6000) % len(self.prg_ram)] = val


class MMC1(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.shift = 0x10
        self.control = 0x0C
        self.chr0 = 0
        self.chr1 = 0
        self.prg_bank = 0
        self._update()
    def _update(self):
        mode = (self.control >> 2) & 3
        cmode = (self.control >> 4) & 1
        banks = max(1, self.rom.header.prg_banks)
        if mode in (0, 1):
            b = (self.prg_bank & 0x0E) % banks
            self.prg_off0 = b * 16384
            self.prg_off1 = ((b + 1) % banks) * 16384
        elif mode == 2:
            self.prg_off0 = 0
            self.prg_off1 = ((self.prg_bank & 0x0F) % banks) * 16384
        else:
            self.prg_off0 = ((self.prg_bank & 0x0F) % banks) * 16384
            self.prg_off1 = (banks - 1) * 16384
        if cmode == 0:
            self.chr_off0 = (self.chr0 & 0x1E) * 4096
            self.chr_off1 = self.chr_off0 + 4096
        else:
            self.chr_off0 = self.chr0 * 4096
            self.chr_off1 = self.chr1 * 4096
        m = self.control & 3
        self.mirroring = ("one-screen-lo", "one-screen-hi", "vertical", "horizontal")[m]
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        if addr < 0xC000:
            return self.rom.prg[(self.prg_off0 + (addr - 0x8000)) % len(self.rom.prg)]
        return self.rom.prg[(self.prg_off1 + (addr - 0xC000)) % len(self.rom.prg)]
    def cpu_write(self, addr, val):
        if 0x6000 <= addr < 0x8000:
            self.prg_ram[(addr - 0x6000) % len(self.prg_ram)] = val
            return
        if val & 0x80:
            self.shift = 0x10
            self.control |= 0x0C
            self._update()
            return
        complete = self.shift & 1
        self.shift = (self.shift >> 1) | ((val & 1) << 4)
        if complete:
            reg = (addr >> 13) & 3
            v = self.shift
            self.shift = 0x10
            if reg == 0: self.control = v
            elif reg == 1: self.chr0 = v
            elif reg == 2: self.chr1 = v
            else: self.prg_bank = v
            self._update()
    def ppu_read(self, addr):
        chr_data = self.rom.chr
        if addr < 0x1000:
            return chr_data[(self.chr_off0 + addr) % len(chr_data)]
        return chr_data[(self.chr_off1 + (addr - 0x1000)) % len(chr_data)]
    def ppu_write(self, addr, val):
        if self.rom.has_chr_ram:
            self.rom.chr[addr % len(self.rom.chr)] = val


class UNROM(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.bank = 0
        self.last = (rom.header.prg_banks - 1) * 16384
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        if addr < 0xC000:
            return self.rom.prg[(self.bank * 16384 + (addr - 0x8000)) % len(self.rom.prg)]
        return self.rom.prg[(self.last + (addr - 0xC000)) % len(self.rom.prg)]
    def cpu_write(self, addr, val):
        if 0x6000 <= addr < 0x8000:
            self.prg_ram[(addr - 0x6000) % len(self.prg_ram)] = val
        elif addr >= 0x8000:
            self.bank = val & 0x0F


class CNROM(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.chr_bank = 0
        self.mask = 0x3FFF if rom.header.prg_banks == 1 else 0x7FFF
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        return self.rom.prg[(addr - 0x8000) & self.mask]
    def cpu_write(self, addr, val):
        if 0x6000 <= addr < 0x8000:
            self.prg_ram[(addr - 0x6000) % len(self.prg_ram)] = val
        elif addr >= 0x8000:
            self.chr_bank = val & 0x03
    def ppu_read(self, addr):
        return self.rom.chr[(self.chr_bank * 8192 + addr) % len(self.rom.chr)]


class AOROM(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.bank = 0
        self.mirroring = "one-screen-lo"
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        return self.rom.prg[(self.bank * 32768 + (addr - 0x8000)) % len(self.rom.prg)]
    def cpu_write(self, addr, val):
        if 0x6000 <= addr < 0x8000:
            self.prg_ram[(addr - 0x6000) % len(self.prg_ram)] = val
        elif addr >= 0x8000:
            self.bank = val & 0x07
            self.mirroring = "one-screen-hi" if (val & 0x10) else "one-screen-lo"


class GxROM(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.prg_bank = 0
        self.chr_bank = 0
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        return self.rom.prg[(self.prg_bank * 32768 + (addr - 0x8000)) % len(self.rom.prg)]
    def cpu_write(self, addr, val):
        if 0x6000 <= addr < 0x8000:
            self.prg_ram[(addr - 0x6000) % len(self.prg_ram)] = val
        elif addr >= 0x8000:
            self.prg_bank = (val >> 4) & 3
            self.chr_bank = val & 3
    def ppu_read(self, addr):
        return self.rom.chr[(self.chr_bank * 8192 + addr) % len(self.rom.chr)]


class ColorDreams(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.prg_bank = 0
        self.chr_bank = 0
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        return self.rom.prg[(self.prg_bank * 32768 + (addr - 0x8000)) % len(self.rom.prg)]
    def cpu_write(self, addr, val):
        if addr >= 0x8000:
            self.prg_bank = val & 3
            self.chr_bank = (val >> 4) & 0x0F
    def ppu_read(self, addr):
        return self.rom.chr[(self.chr_bank * 8192 + addr) % len(self.rom.chr)]


class Camerica(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.bank = 0
        self.last = (rom.header.prg_banks - 1) * 16384
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        if addr < 0xC000:
            return self.rom.prg[(self.bank * 16384 + (addr - 0x8000)) % len(self.rom.prg)]
        return self.rom.prg[(self.last + (addr - 0xC000)) % len(self.rom.prg)]
    def cpu_write(self, addr, val):
        if 0xC000 <= addr:
            self.bank = val & 0x0F


class MMC3(Mapper):
    def __init__(self, rom):
        super().__init__(rom)
        self.bank_select = 0
        self.banks = [0, 1, 0, 1, 0, 1, 0, 1]
        self.irq_latch = 0
        self.irq_counter = 0
        self.irq_reload = False
        self.irq_enable = False
        self.prg_banks_count = max(1, rom.header.prg_banks * 2)
        self._update()
    def _update(self):
        last = self.prg_banks_count - 1
        if self.bank_select & 0x40:
            self.prg_off = [last - 1, self.banks[7] & 0x3F, self.banks[6] & 0x3F, last]
        else:
            self.prg_off = [self.banks[6] & 0x3F, self.banks[7] & 0x3F, last - 1, last]
        if self.bank_select & 0x80:
            self.chr_off = [self.banks[2], self.banks[3], self.banks[4], self.banks[5],
                            self.banks[0] & 0xFE, (self.banks[0] & 0xFE) + 1,
                            self.banks[1] & 0xFE, (self.banks[1] & 0xFE) + 1]
        else:
            self.chr_off = [self.banks[0] & 0xFE, (self.banks[0] & 0xFE) + 1,
                            self.banks[1] & 0xFE, (self.banks[1] & 0xFE) + 1,
                            self.banks[2], self.banks[3], self.banks[4], self.banks[5]]
    def cpu_read(self, addr):
        if 0x6000 <= addr < 0x8000:
            return self.prg_ram[(addr - 0x6000) % len(self.prg_ram)]
        idx = (addr - 0x8000) >> 13
        off = self.prg_off[idx] * 8192 + ((addr - 0x8000) & 0x1FFF)
        return self.rom.prg[off % len(self.rom.prg)]
    def cpu_write(self, addr, val):
        if 0x6000 <= addr < 0x8000:
            self.prg_ram[(addr - 0x6000) % len(self.prg_ram)] = val
            return
        if addr < 0xA000:
            if addr & 1:
                self.banks[self.bank_select & 7] = val
            else:
                self.bank_select = val
            self._update()
        elif addr < 0xC000:
            if not (addr & 1):
                self.mirroring = "horizontal" if (val & 1) else "vertical"
        elif addr < 0xE000:
            if addr & 1:
                self.irq_reload = True
            else:
                self.irq_latch = val
        else:
            self.irq_enable = bool(addr & 1)
            if not self.irq_enable:
                self.irq_pending = False
    def ppu_read(self, addr):
        idx = (addr >> 10) & 7
        off = self.chr_off[idx] * 1024 + (addr & 0x3FF)
        return self.rom.chr[off % len(self.rom.chr)]
    def ppu_write(self, addr, val):
        if self.rom.has_chr_ram:
            idx = (addr >> 10) & 7
            off = self.chr_off[idx] * 1024 + (addr & 0x3FF)
            self.rom.chr[off % len(self.rom.chr)] = val
    def scanline_tick(self):
        if self.irq_counter == 0 or self.irq_reload:
            self.irq_counter = self.irq_latch
            self.irq_reload = False
        else:
            self.irq_counter -= 1
        if self.irq_counter == 0 and self.irq_enable:
            self.irq_pending = True


_MAPPER_TABLE = {
    0: NROM, 1: MMC1, 2: UNROM, 3: CNROM, 4: MMC3,
    7: AOROM, 11: ColorDreams, 66: GxROM, 71: Camerica,
}


def make_mapper(rom):
    cls = _MAPPER_TABLE.get(rom.header.mapper)
    if cls is None:
        return NROM(rom)
    return cls(rom)


# =============================================================================
#  PPU - Picture Processing Unit (simplified but functional)
# =============================================================================

class PPU:
    def __init__(self, mapper):
        self.mapper = mapper
        self.vram = bytearray(2048)
        self.palette = bytearray(32)
        self.oam = bytearray(256)
        self.framebuffer = bytearray(256 * 240)
        self.scanline = 0
        self.dot = 0
        self.frame = 0
        self.ctrl = 0
        self.mask = 0
        self.status = 0
        self.oam_addr = 0
        self.v = 0
        self.t = 0
        self.x = 0
        self.w = 0
        self.buffer = 0
        self.nmi = False
        self.odd_frame = False
        init = [0x09,0x01,0x00,0x01,0x00,0x02,0x02,0x0D,
                0x08,0x10,0x08,0x24,0x00,0x00,0x04,0x2C,
                0x09,0x01,0x34,0x03,0x00,0x04,0x00,0x14,
                0x00,0x00,0x00,0x05,0x00,0x00,0x00,0x00]
        for i, v in enumerate(init):
            self.palette[i] = v

    def _mirror_addr(self, addr):
        addr &= 0x0FFF
        m = self.mapper.mirroring
        if m == "horizontal":
            if addr < 0x0400: return addr
            if addr < 0x0800: return addr - 0x0400
            if addr < 0x0C00: return addr - 0x0400
            return addr - 0x0800
        if m == "vertical":
            return addr & 0x07FF
        if m == "one-screen-lo":
            return addr & 0x03FF
        if m == "one-screen-hi":
            return (addr & 0x03FF) | 0x0400
        return addr & 0x07FF

    def ppu_read(self, addr):
        addr &= 0x3FFF
        if addr < 0x2000:
            return self.mapper.ppu_read(addr)
        if addr < 0x3F00:
            return self.vram[self._mirror_addr(addr)]
        a = addr & 0x1F
        if a in (0x10, 0x14, 0x18, 0x1C):
            a -= 0x10
        return self.palette[a] & 0x3F

    def ppu_write(self, addr, val):
        addr &= 0x3FFF
        if addr < 0x2000:
            self.mapper.ppu_write(addr, val)
        elif addr < 0x3F00:
            self.vram[self._mirror_addr(addr)] = val
        else:
            a = addr & 0x1F
            if a in (0x10, 0x14, 0x18, 0x1C):
                a -= 0x10
            self.palette[a] = val & 0x3F

    def reg_read(self, reg):
        reg &= 7
        if reg == 2:
            v = self.status
            self.status &= 0x7F
            self.w = 0
            return v
        if reg == 4:
            return self.oam[self.oam_addr]
        if reg == 7:
            addr = self.v & 0x3FFF
            if addr < 0x3F00:
                ret = self.buffer
                self.buffer = self.ppu_read(addr)
            else:
                ret = self.ppu_read(addr)
                self.buffer = self.ppu_read(addr - 0x1000)
            self.v = (self.v + (32 if (self.ctrl & 4) else 1)) & 0x7FFF
            return ret
        return 0

    def reg_write(self, reg, val):
        reg &= 7
        if reg == 0:
            self.ctrl = val
            self.t = (self.t & 0xF3FF) | ((val & 3) << 10)
        elif reg == 1:
            self.mask = val
        elif reg == 3:
            self.oam_addr = val
        elif reg == 4:
            self.oam[self.oam_addr] = val
            self.oam_addr = (self.oam_addr + 1) & 0xFF
        elif reg == 5:
            if self.w == 0:
                self.t = (self.t & 0xFFE0) | (val >> 3)
                self.x = val & 7
                self.w = 1
            else:
                self.t = (self.t & 0x8FFF) | ((val & 7) << 12)
                self.t = (self.t & 0xFC1F) | ((val & 0xF8) << 2)
                self.w = 0
        elif reg == 6:
            if self.w == 0:
                self.t = (self.t & 0x00FF) | ((val & 0x3F) << 8)
                self.w = 1
            else:
                self.t = (self.t & 0xFF00) | val
                self.v = self.t
                self.w = 0
        elif reg == 7:
            self.ppu_write(self.v & 0x3FFF, val)
            self.v = (self.v + (32 if (self.ctrl & 4) else 1)) & 0x7FFF

    def oam_dma_write(self, data):
        a = self.oam_addr
        for b in data:
            self.oam[a] = b
            a = (a + 1) & 0xFF

    def _render_scanline(self, y):
        bg_color = self.palette[0] & 0x3F
        base = y * 256
        row = bytearray(256)
        if not (self.mask & 0x18):
            for x in range(256):
                self.framebuffer[base + x] = bg_color
            return
        nt_base = 0x2000 + ((self.ctrl & 3) << 10)
        pt_base = 0x1000 if (self.ctrl & 0x10) else 0
        line = y
        tile_y = line >> 3
        fine_y = line & 7
        bg_enabled = bool(self.mask & 0x08)
        sp_enabled = bool(self.mask & 0x10)
        if bg_enabled:
            mapper = self.mapper
            palette = self.palette
            for tx in range(32):
                nt_addr = nt_base + tile_y * 32 + tx
                tile_idx = self.ppu_read(nt_addr)
                at_addr = (nt_base | 0x3C0) + (tile_y >> 2) * 8 + (tx >> 2)
                at = self.ppu_read(at_addr)
                shift = ((tile_y & 2) << 1) | (tx & 2)
                pal_hi = ((at >> shift) & 3) << 2
                pt_addr = pt_base + tile_idx * 16 + fine_y
                lo = mapper.ppu_read(pt_addr)
                hi = mapper.ppu_read(pt_addr + 8)
                sx_base = tx * 8
                for px in range(8):
                    b = 7 - px
                    p = ((lo >> b) & 1) | (((hi >> b) & 1) << 1)
                    if p == 0:
                        row[sx_base + px] = palette[0] & 0x3F
                    else:
                        row[sx_base + px] = palette[pal_hi | p] & 0x3F
        else:
            for sx in range(256):
                row[sx] = bg_color
        if sp_enabled:
            sp_pt = 0x1000 if (self.ctrl & 0x08) else 0
            sp_h = 16 if (self.ctrl & 0x20) else 8
            count = 0
            for i in range(0, 256, 4):
                sy = self.oam[i]
                if sy >= 0xEF:
                    continue
                dy = line - sy
                if dy < 0 or dy >= sp_h:
                    continue
                if count >= 8:
                    self.status |= 0x20
                    break
                count += 1
                tile = self.oam[i + 1]
                attr = self.oam[i + 2]
                sx = self.oam[i + 3]
                pal_hi = ((attr & 3) << 2) | 0x10
                flip_h = bool(attr & 0x40)
                flip_v = bool(attr & 0x80)
                behind = bool(attr & 0x20)
                if sp_h == 16:
                    pt = (tile & 1) * 0x1000
                    t = tile & 0xFE
                    fy = dy
                    if flip_v:
                        fy = 15 - fy
                    if fy >= 8:
                        t += 1
                        fy -= 8
                    pt_addr = pt + t * 16 + fy
                else:
                    fy = dy if not flip_v else (7 - dy)
                    pt_addr = sp_pt + tile * 16 + fy
                lo = self.mapper.ppu_read(pt_addr)
                hi = self.mapper.ppu_read(pt_addr + 8)
                for px in range(8):
                    b = px if flip_h else (7 - px)
                    p = ((lo >> b) & 1) | (((hi >> b) & 1) << 1)
                    if p == 0:
                        continue
                    fx = sx + px
                    if fx >= 256:
                        break
                    if behind and bg_enabled:
                        if row[fx] != (self.palette[0] & 0x3F):
                            continue
                    row[fx] = self.palette[pal_hi | p] & 0x3F
                if i == 0 and bg_enabled and not (self.status & 0x40):
                    self.status |= 0x40
        self.framebuffer[base:base + 256] = row

    def step_scanline(self):
        if 0 <= self.scanline < 240:
            self._render_scanline(self.scanline)
            self.mapper.scanline_tick()
        elif self.scanline == 241:
            self.status |= 0x80
            if self.ctrl & 0x80:
                self.nmi = True
        elif self.scanline == 261:
            self.status &= 0x1F
        self.scanline += 1
        if self.scanline > 261:
            self.scanline = 0
            self.frame += 1
            self.odd_frame = not self.odd_frame


# =============================================================================
#  APU - audio stub (silent for now, registers absorb writes)
# =============================================================================

class APU:
    def __init__(self):
        self.reg = bytearray(0x18)
    def write(self, addr, val):
        addr -= 0x4000
        if 0 <= addr < len(self.reg):
            self.reg[addr] = val
    def read(self):
        return 0


# =============================================================================
#  Controller
# =============================================================================

class Controller:
    BTN_A      = 0x01
    BTN_B      = 0x02
    BTN_SELECT = 0x04
    BTN_START  = 0x08
    BTN_UP     = 0x10
    BTN_DOWN   = 0x20
    BTN_LEFT   = 0x40
    BTN_RIGHT  = 0x80
    def __init__(self):
        self.state = 0
        self.shift = 0
        self.strobe = False
    def set_strobe(self, val):
        old = self.strobe
        self.strobe = bool(val & 1)
        if old and not self.strobe:
            self.shift = self.state
    def read(self):
        if self.strobe:
            return self.state & 1
        v = self.shift & 1
        self.shift = (self.shift >> 1) | 0x80
        return v


# =============================================================================
#  CPU bus
# =============================================================================

class Bus:
    def __init__(self, mapper, ppu, apu, pad1, pad2):
        self.ram = bytearray(2048)
        self.mapper = mapper
        self.ppu = ppu
        self.apu = apu
        self.pad1 = pad1
        self.pad2 = pad2
        self.dma_stall = 0
        self.cpu = None

    def read(self, addr):
        addr &= 0xFFFF
        if addr < 0x2000:
            return self.ram[addr & 0x07FF]
        if addr < 0x4000:
            return self.ppu.reg_read(addr & 7)
        if addr == 0x4016:
            return 0x40 | self.pad1.read()
        if addr == 0x4017:
            return 0x40 | self.pad2.read()
        if addr < 0x4018:
            return 0
        return self.mapper.cpu_read(addr)

    def write(self, addr, val):
        addr &= 0xFFFF
        val &= 0xFF
        if addr < 0x2000:
            self.ram[addr & 0x07FF] = val
        elif addr < 0x4000:
            self.ppu.reg_write(addr & 7, val)
        elif addr == 0x4014:
            page = val << 8
            data = bytes(self.read(page + i) for i in range(256))
            self.ppu.oam_dma_write(data)
            self.dma_stall += 513
        elif addr == 0x4016:
            self.pad1.set_strobe(val)
            self.pad2.set_strobe(val)
        elif addr < 0x4018:
            self.apu.write(addr, val)
        else:
            self.mapper.cpu_write(addr, val)


# =============================================================================
#  6502 CPU
# =============================================================================

class CPU:
    FLAG_C = 0x01
    FLAG_Z = 0x02
    FLAG_I = 0x04
    FLAG_D = 0x08
    FLAG_B = 0x10
    FLAG_U = 0x20
    FLAG_V = 0x40
    FLAG_N = 0x80

    def __init__(self, bus):
        self.bus = bus
        bus.cpu = self
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFD
        self.p = 0x24
        self.pc = 0
        self.cycles = 0
        self.pending_nmi = False
        self.pending_irq = False
        self._build_table()

    def reset(self):
        lo = self.bus.read(0xFFFC)
        hi = self.bus.read(0xFFFD)
        self.pc = (hi << 8) | lo
        self.sp = 0xFD
        self.p = 0x24
        self.cycles = 7

    def _read(self, addr): return self.bus.read(addr) & 0xFF
    def _write(self, addr, val): self.bus.write(addr, val & 0xFF)
    def _read16(self, addr):
        return self._read(addr) | (self._read((addr + 1) & 0xFFFF) << 8)
    def _read16_bug(self, addr):
        a2 = (addr & 0xFF00) | ((addr + 1) & 0xFF)
        return self._read(addr) | (self._read(a2) << 8)
    def _push(self, val):
        self._write(0x100 | self.sp, val)
        self.sp = (self.sp - 1) & 0xFF
    def _pull(self):
        self.sp = (self.sp + 1) & 0xFF
        return self._read(0x100 | self.sp)
    def _push16(self, val):
        self._push((val >> 8) & 0xFF)
        self._push(val & 0xFF)
    def _pull16(self):
        lo = self._pull()
        hi = self._pull()
        return (hi << 8) | lo
    def _set_zn(self, v):
        v &= 0xFF
        self.p = (self.p & ~(self.FLAG_Z | self.FLAG_N))
        if v == 0: self.p |= self.FLAG_Z
        if v & 0x80: self.p |= self.FLAG_N

    def nmi(self): self.pending_nmi = True

    def _do_nmi(self):
        self._push16(self.pc)
        self._push((self.p | 0x20) & ~self.FLAG_B)
        self.p |= self.FLAG_I
        self.pc = self._read(0xFFFA) | (self._read(0xFFFB) << 8)
        self.cycles += 7

    def _do_irq(self):
        self._push16(self.pc)
        self._push((self.p | 0x20) & ~self.FLAG_B)
        self.p |= self.FLAG_I
        self.pc = self._read(0xFFFE) | (self._read(0xFFFF) << 8)
        self.cycles += 7

    # Addressing modes
    def _am_imm(self):
        a = self.pc; self.pc = (self.pc + 1) & 0xFFFF; return a, 0
    def _am_zp(self):
        a = self._read(self.pc); self.pc = (self.pc + 1) & 0xFFFF; return a, 0
    def _am_zpx(self):
        a = (self._read(self.pc) + self.x) & 0xFF
        self.pc = (self.pc + 1) & 0xFFFF; return a, 0
    def _am_zpy(self):
        a = (self._read(self.pc) + self.y) & 0xFF
        self.pc = (self.pc + 1) & 0xFFFF; return a, 0
    def _am_abs(self):
        a = self._read16(self.pc); self.pc = (self.pc + 2) & 0xFFFF; return a, 0
    def _am_absx(self, write=False):
        base = self._read16(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        a = (base + self.x) & 0xFFFF
        extra = 0 if write else (1 if (base & 0xFF00) != (a & 0xFF00) else 0)
        return a, extra
    def _am_absy(self, write=False):
        base = self._read16(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        a = (base + self.y) & 0xFFFF
        extra = 0 if write else (1 if (base & 0xFF00) != (a & 0xFF00) else 0)
        return a, extra
    def _am_ind(self):
        ptr = self._read16(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        return self._read16_bug(ptr), 0
    def _am_indx(self):
        zp = (self._read(self.pc) + self.x) & 0xFF
        self.pc = (self.pc + 1) & 0xFFFF
        return self._read(zp) | (self._read((zp + 1) & 0xFF) << 8), 0
    def _am_indy(self, write=False):
        zp = self._read(self.pc); self.pc = (self.pc + 1) & 0xFFFF
        base = self._read(zp) | (self._read((zp + 1) & 0xFF) << 8)
        a = (base + self.y) & 0xFFFF
        extra = 0 if write else (1 if (base & 0xFF00) != (a & 0xFF00) else 0)
        return a, extra
    def _am_rel(self):
        d = self._read(self.pc); self.pc = (self.pc + 1) & 0xFFFF
        if d & 0x80: d -= 0x100
        return (self.pc + d) & 0xFFFF, 0

    # Ops
    def _op_adc(self, a):
        m = self._read(a); c = self.p & 1
        r = self.a + m + c
        v = (~(self.a ^ m) & (self.a ^ r)) & 0x80
        self.p = (self.p & ~(self.FLAG_C | self.FLAG_V)) | (1 if r > 0xFF else 0) | (self.FLAG_V if v else 0)
        self.a = r & 0xFF
        self._set_zn(self.a)
    def _op_sbc(self, a):
        m = self._read(a) ^ 0xFF; c = self.p & 1
        r = self.a + m + c
        v = (~(self.a ^ m) & (self.a ^ r)) & 0x80
        self.p = (self.p & ~(self.FLAG_C | self.FLAG_V)) | (1 if r > 0xFF else 0) | (self.FLAG_V if v else 0)
        self.a = r & 0xFF
        self._set_zn(self.a)
    def _op_and(self, a): self.a &= self._read(a); self._set_zn(self.a)
    def _op_ora(self, a): self.a |= self._read(a); self._set_zn(self.a)
    def _op_eor(self, a): self.a ^= self._read(a); self._set_zn(self.a)
    def _op_asl_a(self):
        self.p = (self.p & ~1) | ((self.a >> 7) & 1)
        self.a = (self.a << 1) & 0xFF; self._set_zn(self.a)
    def _op_asl(self, a):
        m = self._read(a)
        self.p = (self.p & ~1) | ((m >> 7) & 1)
        m = (m << 1) & 0xFF; self._write(a, m); self._set_zn(m)
    def _op_lsr_a(self):
        self.p = (self.p & ~1) | (self.a & 1); self.a >>= 1; self._set_zn(self.a)
    def _op_lsr(self, a):
        m = self._read(a)
        self.p = (self.p & ~1) | (m & 1); m >>= 1; self._write(a, m); self._set_zn(m)
    def _op_rol_a(self):
        c = self.p & 1
        self.p = (self.p & ~1) | ((self.a >> 7) & 1)
        self.a = ((self.a << 1) | c) & 0xFF; self._set_zn(self.a)
    def _op_rol(self, a):
        m = self._read(a); c = self.p & 1
        self.p = (self.p & ~1) | ((m >> 7) & 1)
        m = ((m << 1) | c) & 0xFF; self._write(a, m); self._set_zn(m)
    def _op_ror_a(self):
        c = (self.p & 1) << 7
        self.p = (self.p & ~1) | (self.a & 1)
        self.a = (self.a >> 1) | c; self._set_zn(self.a)
    def _op_ror(self, a):
        m = self._read(a); c = (self.p & 1) << 7
        self.p = (self.p & ~1) | (m & 1)
        m = (m >> 1) | c; self._write(a, m); self._set_zn(m)
    def _op_bit(self, a):
        m = self._read(a); r = self.a & m
        self.p = (self.p & ~(self.FLAG_Z | self.FLAG_N | self.FLAG_V))
        if r == 0: self.p |= self.FLAG_Z
        self.p |= (m & 0xC0)
    def _op_cmp(self, reg, a):
        m = self._read(a); r = reg - m
        self.p = (self.p & ~1) | (1 if reg >= m else 0)
        self._set_zn(r & 0xFF)
    def _branch(self, cond, target):
        if not cond: return 0
        extra = 2 if (target & 0xFF00) != (self.pc & 0xFF00) else 1
        self.pc = target
        return extra

    def _build_table(self):
        T = [None] * 256
        def op(c, fn, cy): T[c] = (fn, cy)

        op(0x69, lambda: (self._op_adc(self._am_imm()[0]), 0)[1], 2)
        op(0x65, lambda: (self._op_adc(self._am_zp()[0]), 0)[1], 3)
        op(0x75, lambda: (self._op_adc(self._am_zpx()[0]), 0)[1], 4)
        op(0x6D, lambda: (self._op_adc(self._am_abs()[0]), 0)[1], 4)
        op(0x7D, lambda: (lambda r: (self._op_adc(r[0]), r[1])[1])(self._am_absx()), 4)
        op(0x79, lambda: (lambda r: (self._op_adc(r[0]), r[1])[1])(self._am_absy()), 4)
        op(0x61, lambda: (self._op_adc(self._am_indx()[0]), 0)[1], 6)
        op(0x71, lambda: (lambda r: (self._op_adc(r[0]), r[1])[1])(self._am_indy()), 5)
        op(0xE9, lambda: (self._op_sbc(self._am_imm()[0]), 0)[1], 2)
        op(0xEB, lambda: (self._op_sbc(self._am_imm()[0]), 0)[1], 2)
        op(0xE5, lambda: (self._op_sbc(self._am_zp()[0]), 0)[1], 3)
        op(0xF5, lambda: (self._op_sbc(self._am_zpx()[0]), 0)[1], 4)
        op(0xED, lambda: (self._op_sbc(self._am_abs()[0]), 0)[1], 4)
        op(0xFD, lambda: (lambda r: (self._op_sbc(r[0]), r[1])[1])(self._am_absx()), 4)
        op(0xF9, lambda: (lambda r: (self._op_sbc(r[0]), r[1])[1])(self._am_absy()), 4)
        op(0xE1, lambda: (self._op_sbc(self._am_indx()[0]), 0)[1], 6)
        op(0xF1, lambda: (lambda r: (self._op_sbc(r[0]), r[1])[1])(self._am_indy()), 5)
        op(0x29, lambda: (self._op_and(self._am_imm()[0]), 0)[1], 2)
        op(0x25, lambda: (self._op_and(self._am_zp()[0]), 0)[1], 3)
        op(0x35, lambda: (self._op_and(self._am_zpx()[0]), 0)[1], 4)
        op(0x2D, lambda: (self._op_and(self._am_abs()[0]), 0)[1], 4)
        op(0x3D, lambda: (lambda r: (self._op_and(r[0]), r[1])[1])(self._am_absx()), 4)
        op(0x39, lambda: (lambda r: (self._op_and(r[0]), r[1])[1])(self._am_absy()), 4)
        op(0x21, lambda: (self._op_and(self._am_indx()[0]), 0)[1], 6)
        op(0x31, lambda: (lambda r: (self._op_and(r[0]), r[1])[1])(self._am_indy()), 5)
        op(0x09, lambda: (self._op_ora(self._am_imm()[0]), 0)[1], 2)
        op(0x05, lambda: (self._op_ora(self._am_zp()[0]), 0)[1], 3)
        op(0x15, lambda: (self._op_ora(self._am_zpx()[0]), 0)[1], 4)
        op(0x0D, lambda: (self._op_ora(self._am_abs()[0]), 0)[1], 4)
        op(0x1D, lambda: (lambda r: (self._op_ora(r[0]), r[1])[1])(self._am_absx()), 4)
        op(0x19, lambda: (lambda r: (self._op_ora(r[0]), r[1])[1])(self._am_absy()), 4)
        op(0x01, lambda: (self._op_ora(self._am_indx()[0]), 0)[1], 6)
        op(0x11, lambda: (lambda r: (self._op_ora(r[0]), r[1])[1])(self._am_indy()), 5)
        op(0x49, lambda: (self._op_eor(self._am_imm()[0]), 0)[1], 2)
        op(0x45, lambda: (self._op_eor(self._am_zp()[0]), 0)[1], 3)
        op(0x55, lambda: (self._op_eor(self._am_zpx()[0]), 0)[1], 4)
        op(0x4D, lambda: (self._op_eor(self._am_abs()[0]), 0)[1], 4)
        op(0x5D, lambda: (lambda r: (self._op_eor(r[0]), r[1])[1])(self._am_absx()), 4)
        op(0x59, lambda: (lambda r: (self._op_eor(r[0]), r[1])[1])(self._am_absy()), 4)
        op(0x41, lambda: (self._op_eor(self._am_indx()[0]), 0)[1], 6)
        op(0x51, lambda: (lambda r: (self._op_eor(r[0]), r[1])[1])(self._am_indy()), 5)
        op(0x0A, lambda: (self._op_asl_a(), 0)[1], 2)
        op(0x06, lambda: (self._op_asl(self._am_zp()[0]), 0)[1], 5)
        op(0x16, lambda: (self._op_asl(self._am_zpx()[0]), 0)[1], 6)
        op(0x0E, lambda: (self._op_asl(self._am_abs()[0]), 0)[1], 6)
        op(0x1E, lambda: (self._op_asl(self._am_absx(True)[0]), 0)[1], 7)
        op(0x4A, lambda: (self._op_lsr_a(), 0)[1], 2)
        op(0x46, lambda: (self._op_lsr(self._am_zp()[0]), 0)[1], 5)
        op(0x56, lambda: (self._op_lsr(self._am_zpx()[0]), 0)[1], 6)
        op(0x4E, lambda: (self._op_lsr(self._am_abs()[0]), 0)[1], 6)
        op(0x5E, lambda: (self._op_lsr(self._am_absx(True)[0]), 0)[1], 7)
        op(0x2A, lambda: (self._op_rol_a(), 0)[1], 2)
        op(0x26, lambda: (self._op_rol(self._am_zp()[0]), 0)[1], 5)
        op(0x36, lambda: (self._op_rol(self._am_zpx()[0]), 0)[1], 6)
        op(0x2E, lambda: (self._op_rol(self._am_abs()[0]), 0)[1], 6)
        op(0x3E, lambda: (self._op_rol(self._am_absx(True)[0]), 0)[1], 7)
        op(0x6A, lambda: (self._op_ror_a(), 0)[1], 2)
        op(0x66, lambda: (self._op_ror(self._am_zp()[0]), 0)[1], 5)
        op(0x76, lambda: (self._op_ror(self._am_zpx()[0]), 0)[1], 6)
        op(0x6E, lambda: (self._op_ror(self._am_abs()[0]), 0)[1], 6)
        op(0x7E, lambda: (self._op_ror(self._am_absx(True)[0]), 0)[1], 7)
        op(0x24, lambda: (self._op_bit(self._am_zp()[0]), 0)[1], 3)
        op(0x2C, lambda: (self._op_bit(self._am_abs()[0]), 0)[1], 4)

        def _lda(a): self.a = self._read(a); self._set_zn(self.a)
        def _ldx(a): self.x = self._read(a); self._set_zn(self.x)
        def _ldy(a): self.y = self._read(a); self._set_zn(self.y)
        op(0xA9, lambda: (_lda(self._am_imm()[0]), 0)[1], 2)
        op(0xA5, lambda: (_lda(self._am_zp()[0]), 0)[1], 3)
        op(0xB5, lambda: (_lda(self._am_zpx()[0]), 0)[1], 4)
        op(0xAD, lambda: (_lda(self._am_abs()[0]), 0)[1], 4)
        op(0xBD, lambda: (lambda r: (_lda(r[0]), r[1])[1])(self._am_absx()), 4)
        op(0xB9, lambda: (lambda r: (_lda(r[0]), r[1])[1])(self._am_absy()), 4)
        op(0xA1, lambda: (_lda(self._am_indx()[0]), 0)[1], 6)
        op(0xB1, lambda: (lambda r: (_lda(r[0]), r[1])[1])(self._am_indy()), 5)
        op(0xA2, lambda: (_ldx(self._am_imm()[0]), 0)[1], 2)
        op(0xA6, lambda: (_ldx(self._am_zp()[0]), 0)[1], 3)
        op(0xB6, lambda: (_ldx(self._am_zpy()[0]), 0)[1], 4)
        op(0xAE, lambda: (_ldx(self._am_abs()[0]), 0)[1], 4)
        op(0xBE, lambda: (lambda r: (_ldx(r[0]), r[1])[1])(self._am_absy()), 4)
        op(0xA0, lambda: (_ldy(self._am_imm()[0]), 0)[1], 2)
        op(0xA4, lambda: (_ldy(self._am_zp()[0]), 0)[1], 3)
        op(0xB4, lambda: (_ldy(self._am_zpx()[0]), 0)[1], 4)
        op(0xAC, lambda: (_ldy(self._am_abs()[0]), 0)[1], 4)
        op(0xBC, lambda: (lambda r: (_ldy(r[0]), r[1])[1])(self._am_absx()), 4)
        op(0x85, lambda: (self._write(self._am_zp()[0], self.a), 0)[1], 3)
        op(0x95, lambda: (self._write(self._am_zpx()[0], self.a), 0)[1], 4)
        op(0x8D, lambda: (self._write(self._am_abs()[0], self.a), 0)[1], 4)
        op(0x9D, lambda: (self._write(self._am_absx(True)[0], self.a), 0)[1], 5)
        op(0x99, lambda: (self._write(self._am_absy(True)[0], self.a), 0)[1], 5)
        op(0x81, lambda: (self._write(self._am_indx()[0], self.a), 0)[1], 6)
        op(0x91, lambda: (self._write(self._am_indy(True)[0], self.a), 0)[1], 6)
        op(0x86, lambda: (self._write(self._am_zp()[0], self.x), 0)[1], 3)
        op(0x96, lambda: (self._write(self._am_zpy()[0], self.x), 0)[1], 4)
        op(0x8E, lambda: (self._write(self._am_abs()[0], self.x), 0)[1], 4)
        op(0x84, lambda: (self._write(self._am_zp()[0], self.y), 0)[1], 3)
        op(0x94, lambda: (self._write(self._am_zpx()[0], self.y), 0)[1], 4)
        op(0x8C, lambda: (self._write(self._am_abs()[0], self.y), 0)[1], 4)

        def _tax(): self.x = self.a; self._set_zn(self.x)
        def _tay(): self.y = self.a; self._set_zn(self.y)
        def _txa(): self.a = self.x; self._set_zn(self.a)
        def _tya(): self.a = self.y; self._set_zn(self.a)
        def _tsx(): self.x = self.sp; self._set_zn(self.x)
        def _txs(): self.sp = self.x
        op(0xAA, lambda: (_tax(), 0)[1], 2)
        op(0xA8, lambda: (_tay(), 0)[1], 2)
        op(0x8A, lambda: (_txa(), 0)[1], 2)
        op(0x98, lambda: (_tya(), 0)[1], 2)
        op(0xBA, lambda: (_tsx(), 0)[1], 2)
        op(0x9A, lambda: (_txs(), 0)[1], 2)

        op(0x48, lambda: (self._push(self.a), 0)[1], 3)
        op(0x08, lambda: (self._push(self.p | 0x30), 0)[1], 3)
        def _pla():
            self.a = self._pull(); self._set_zn(self.a)
        op(0x68, lambda: (_pla(), 0)[1], 4)
        def _plp(): self.p = (self._pull() & ~0x10) | 0x20
        op(0x28, lambda: (_plp(), 0)[1], 4)

        def _inc(a): m = (self._read(a) + 1) & 0xFF; self._write(a, m); self._set_zn(m)
        def _dec(a): m = (self._read(a) - 1) & 0xFF; self._write(a, m); self._set_zn(m)
        op(0xE6, lambda: (_inc(self._am_zp()[0]), 0)[1], 5)
        op(0xF6, lambda: (_inc(self._am_zpx()[0]), 0)[1], 6)
        op(0xEE, lambda: (_inc(self._am_abs()[0]), 0)[1], 6)
        op(0xFE, lambda: (_inc(self._am_absx(True)[0]), 0)[1], 7)
        op(0xC6, lambda: (_dec(self._am_zp()[0]), 0)[1], 5)
        op(0xD6, lambda: (_dec(self._am_zpx()[0]), 0)[1], 6)
        op(0xCE, lambda: (_dec(self._am_abs()[0]), 0)[1], 6)
        op(0xDE, lambda: (_dec(self._am_absx(True)[0]), 0)[1], 7)
        def _inx(): self.x = (self.x + 1) & 0xFF; self._set_zn(self.x)
        def _dex(): self.x = (self.x - 1) & 0xFF; self._set_zn(self.x)
        def _iny(): self.y = (self.y + 1) & 0xFF; self._set_zn(self.y)
        def _dey(): self.y = (self.y - 1) & 0xFF; self._set_zn(self.y)
        op(0xE8, lambda: (_inx(), 0)[1], 2)
        op(0xCA, lambda: (_dex(), 0)[1], 2)
        op(0xC8, lambda: (_iny(), 0)[1], 2)
        op(0x88, lambda: (_dey(), 0)[1], 2)

        op(0xC9, lambda: (self._op_cmp(self.a, self._am_imm()[0]), 0)[1], 2)
        op(0xC5, lambda: (self._op_cmp(self.a, self._am_zp()[0]), 0)[1], 3)
        op(0xD5, lambda: (self._op_cmp(self.a, self._am_zpx()[0]), 0)[1], 4)
        op(0xCD, lambda: (self._op_cmp(self.a, self._am_abs()[0]), 0)[1], 4)
        op(0xDD, lambda: (lambda r: (self._op_cmp(self.a, r[0]), r[1])[1])(self._am_absx()), 4)
        op(0xD9, lambda: (lambda r: (self._op_cmp(self.a, r[0]), r[1])[1])(self._am_absy()), 4)
        op(0xC1, lambda: (self._op_cmp(self.a, self._am_indx()[0]), 0)[1], 6)
        op(0xD1, lambda: (lambda r: (self._op_cmp(self.a, r[0]), r[1])[1])(self._am_indy()), 5)
        op(0xE0, lambda: (self._op_cmp(self.x, self._am_imm()[0]), 0)[1], 2)
        op(0xE4, lambda: (self._op_cmp(self.x, self._am_zp()[0]), 0)[1], 3)
        op(0xEC, lambda: (self._op_cmp(self.x, self._am_abs()[0]), 0)[1], 4)
        op(0xC0, lambda: (self._op_cmp(self.y, self._am_imm()[0]), 0)[1], 2)
        op(0xC4, lambda: (self._op_cmp(self.y, self._am_zp()[0]), 0)[1], 3)
        op(0xCC, lambda: (self._op_cmp(self.y, self._am_abs()[0]), 0)[1], 4)

        op(0x10, lambda: self._branch(not (self.p & self.FLAG_N), self._am_rel()[0]), 2)
        op(0x30, lambda: self._branch(bool(self.p & self.FLAG_N), self._am_rel()[0]), 2)
        op(0x50, lambda: self._branch(not (self.p & self.FLAG_V), self._am_rel()[0]), 2)
        op(0x70, lambda: self._branch(bool(self.p & self.FLAG_V), self._am_rel()[0]), 2)
        op(0x90, lambda: self._branch(not (self.p & self.FLAG_C), self._am_rel()[0]), 2)
        op(0xB0, lambda: self._branch(bool(self.p & self.FLAG_C), self._am_rel()[0]), 2)
        op(0xD0, lambda: self._branch(not (self.p & self.FLAG_Z), self._am_rel()[0]), 2)
        op(0xF0, lambda: self._branch(bool(self.p & self.FLAG_Z), self._am_rel()[0]), 2)

        def _jmp_abs():
            self.pc = self._am_abs()[0]
        def _jmp_ind():
            self.pc = self._am_ind()[0]
        def _jsr():
            a = self._am_abs()[0]
            self._push16((self.pc - 1) & 0xFFFF)
            self.pc = a
        def _rts():
            self.pc = (self._pull16() + 1) & 0xFFFF
        def _rti():
            self.p = (self._pull() & ~0x10) | 0x20
            self.pc = self._pull16()
        op(0x4C, lambda: (_jmp_abs(), 0)[1], 3)
        op(0x6C, lambda: (_jmp_ind(), 0)[1], 5)
        op(0x20, lambda: (_jsr(), 0)[1], 6)
        op(0x60, lambda: (_rts(), 0)[1], 6)
        op(0x40, lambda: (_rti(), 0)[1], 6)

        def _clc(): self.p &= ~self.FLAG_C
        def _sec(): self.p |= self.FLAG_C
        def _cli(): self.p &= ~self.FLAG_I
        def _sei(): self.p |= self.FLAG_I
        def _clv(): self.p &= ~self.FLAG_V
        def _cld(): self.p &= ~self.FLAG_D
        def _sed(): self.p |= self.FLAG_D
        op(0x18, lambda: (_clc(), 0)[1], 2)
        op(0x38, lambda: (_sec(), 0)[1], 2)
        op(0x58, lambda: (_cli(), 0)[1], 2)
        op(0x78, lambda: (_sei(), 0)[1], 2)
        op(0xB8, lambda: (_clv(), 0)[1], 2)
        op(0xD8, lambda: (_cld(), 0)[1], 2)
        op(0xF8, lambda: (_sed(), 0)[1], 2)

        # NOPs (official + common unofficial)
        for c in (0xEA, 0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA):
            op(c, lambda: 0, 2)
        for c in (0x80, 0x82, 0x89, 0xC2, 0xE2):
            op(c, lambda: (self._am_imm(), 0)[1], 2)
        for c in (0x04, 0x44, 0x64):
            op(c, lambda: (self._am_zp(), 0)[1], 3)
        for c in (0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4):
            op(c, lambda: (self._am_zpx(), 0)[1], 4)
        op(0x0C, lambda: (self._am_abs(), 0)[1], 4)
        for c in (0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC):
            op(c, lambda: (lambda r: r[1])(self._am_absx()), 4)

        def _brk():
            self.pc = (self.pc + 1) & 0xFFFF
            self._push16(self.pc)
            self._push(self.p | 0x30)
            self.p |= self.FLAG_I
            self.pc = self._read(0xFFFE) | (self._read(0xFFFF) << 8)
        op(0x00, lambda: (_brk(), 0)[1], 7)

        self._table = T

    def step(self):
        if self.pending_nmi:
            self.pending_nmi = False
            self._do_nmi()
            return 7
        if self.pending_irq and not (self.p & self.FLAG_I):
            self.pending_irq = False
            self._do_irq()
            return 7
        if self.bus.dma_stall:
            stalled = self.bus.dma_stall
            self.bus.dma_stall = 0
            self.cycles += stalled
            return stalled
        opcode = self._read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        entry = self._table[opcode]
        if entry is None:
            self.cycles += 2
            return 2
        fn, base_cy = entry
        extra = fn() or 0
        cy = base_cy + extra
        self.cycles += cy
        return cy


# =============================================================================
#  NES system
# =============================================================================

class NES:
    def __init__(self, rom_path):
        self.rom = ROM(rom_path)
        self.mapper = make_mapper(self.rom)
        self.ppu = PPU(self.mapper)
        self.apu = APU()
        self.pad1 = Controller()
        self.pad2 = Controller()
        self.bus = Bus(self.mapper, self.ppu, self.apu, self.pad1, self.pad2)
        self.cpu = CPU(self.bus)
        self.cpu.reset()
        self.ppu.scanline = 0

    def run_frame(self):
        cycles_per_scanline = 113.667
        ppu = self.ppu
        cpu = self.cpu
        mapper = self.mapper
        target = 0.0
        for _ in range(262):
            target += cycles_per_scanline
            while cpu.cycles < target:
                cpu.step()
                if mapper.irq_pending:
                    cpu.pending_irq = True
                    mapper.irq_pending = False
            ppu.step_scanline()
            if ppu.nmi:
                ppu.nmi = False
                cpu.nmi()
        cpu.cycles -= int(target)


# =============================================================================
#  Tkinter GUI - FCEUX-style, blue hue, black bg, blue text, buttons on
# =============================================================================

SCALE = 2
SCREEN_W = 256
SCREEN_H = 240

KEYMAP_P1 = {
    "x": Controller.BTN_A,
    "X": Controller.BTN_A,
    "z": Controller.BTN_B,
    "Z": Controller.BTN_B,
    "Return": Controller.BTN_START,
    "Shift_R": Controller.BTN_SELECT,
    "Shift_L": Controller.BTN_SELECT,
    "Up": Controller.BTN_UP,
    "Down": Controller.BTN_DOWN,
    "Left": Controller.BTN_LEFT,
    "Right": Controller.BTN_RIGHT,
    "w": Controller.BTN_UP, "W": Controller.BTN_UP,
    "s": Controller.BTN_DOWN, "S": Controller.BTN_DOWN,
    "a": Controller.BTN_LEFT, "A": Controller.BTN_LEFT,
    "d": Controller.BTN_RIGHT, "D": Controller.BTN_RIGHT,
}


class EmuApp:
    BG = "#000000"
    FG = "#5fbfff"
    ACCENT = "#1f4e8f"

    def __init__(self, root, rom_path=None):
        self.root = root
        self.root.title("luigines by ac")
        self.root.configure(bg=self.BG)
        self.nes = None
        self.running = False
        self.paused = False
        self.frame_count = 0
        self.last_fps_t = time.time()
        self.fps = 0.0
        self._build_menu()
        self._build_widgets()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        if rom_path and os.path.isfile(rom_path):
            self._open(rom_path)
        else:
            self._show_splash()
        self._schedule_frame()

    def _build_menu(self):
        opt = {"bg": self.BG, "fg": self.FG,
               "activebackground": self.ACCENT, "activeforeground": "#ffffff",
               "selectcolor": self.FG}
        menubar = tk.Menu(self.root, **opt)

        m_file = tk.Menu(menubar, tearoff=0, **opt)
        m_file.add_command(label="Open ROM...    Ctrl+O", command=self._open_dialog)
        m_file.add_command(label="Close",                  command=self._close_rom)
        m_file.add_separator()
        m_file.add_command(label="Exit",                   command=self._quit)
        menubar.add_cascade(label="File", menu=m_file)

        m_nes = tk.Menu(menubar, tearoff=0, **opt)
        m_nes.add_command(label="Reset           Ctrl+R", command=self._reset)
        m_nes.add_command(label="Power",                   command=self._power_cycle)
        m_nes.add_separator()
        m_nes.add_command(label="Pause           P",       command=self._toggle_pause)
        menubar.add_cascade(label="NES", menu=m_nes)

        m_tools = tk.Menu(menubar, tearoff=0, **opt)
        m_tools.add_command(label="Cheats... (n/a)",    state="disabled")
        m_tools.add_command(label="Hex Editor (n/a)",   state="disabled")
        m_tools.add_command(label="PPU Viewer (n/a)",   state="disabled")
        menubar.add_cascade(label="Tools", menu=m_tools)

        m_cfg = tk.Menu(menubar, tearoff=0, **opt)
        m_cfg.add_command(label="Input    (keyboard)",      state="disabled")
        m_cfg.add_command(label="Video    2x scale, blue hue", state="disabled")
        menubar.add_cascade(label="Config", menu=m_cfg)

        m_help = tk.Menu(menubar, tearoff=0, **opt)
        m_help.add_command(label="About luigines", command=self._about)
        m_help.add_command(label="Controls",       command=self._controls_help)
        menubar.add_cascade(label="Help", menu=m_help)

        self.root.config(menu=menubar)

    def _build_widgets(self):
        bar = tk.Frame(self.root, bg=self.BG, bd=0)
        bar.pack(side="top", fill="x")
        btn_opt = {"bg": self.ACCENT, "fg": self.FG,
                   "activebackground": self.FG, "activeforeground": "#000000",
                   "relief": "flat", "padx": 10, "pady": 3, "bd": 0,
                   "font": ("TkFixedFont", 9, "bold"),
                   "highlightbackground": self.BG}
        for label, cmd in (
                ("Open",  self._open_dialog),
                ("Reset", self._reset),
                ("Pause", self._toggle_pause),
                ("Power", self._power_cycle),
                ("About", self._about),
        ):
            tk.Button(bar, text=label, command=cmd, **btn_opt).pack(side="left", padx=2, pady=2)

        cw = SCREEN_W * SCALE
        ch = SCREEN_H * SCALE
        self.canvas = tk.Canvas(self.root, width=cw, height=ch,
                                bg=self.BG, highlightthickness=1,
                                highlightbackground=self.ACCENT)
        self.canvas.pack(padx=4, pady=4)
        self.photo = tk.PhotoImage(width=cw, height=ch)
        self.canvas_img = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")

        self.status_var = tk.StringVar(value="No ROM loaded.")
        status = tk.Label(self.root, textvariable=self.status_var, anchor="w",
                          bg=self.BG, fg=self.FG, font=("TkFixedFont", 9))
        status.pack(side="bottom", fill="x", padx=4)

    def _bind_keys(self):
        self.root.bind("<KeyPress>",   self._on_key_down)
        self.root.bind("<KeyRelease>", self._on_key_up)
        self.root.bind("<Control-o>",  lambda e: self._open_dialog())
        self.root.bind("<Control-O>",  lambda e: self._open_dialog())
        self.root.bind("<Control-r>",  lambda e: self._reset())
        self.root.bind("<Control-R>",  lambda e: self._reset())
        self.root.bind("<KeyPress-p>", lambda e: self._toggle_pause())
        self.root.bind("<Pause>",      lambda e: self._toggle_pause())

    def _on_key_down(self, ev):
        bit = KEYMAP_P1.get(ev.keysym)
        if bit is not None and self.nes is not None:
            self.nes.pad1.state |= bit

    def _on_key_up(self, ev):
        bit = KEYMAP_P1.get(ev.keysym)
        if bit is not None and self.nes is not None:
            self.nes.pad1.state &= ~bit & 0xFF

    def _show_splash(self):
        cw = SCREEN_W * SCALE
        ch = SCREEN_H * SCALE
        self.photo.put("#000000", to=(0, 0, cw, ch))
        self.canvas.delete("splash")
        self.canvas.create_text(cw // 2, ch // 2 - 20, anchor="center",
                                text="luigines 0.1a by ac", fill=self.FG,
                                font=("TkFixedFont", 18, "bold"), tags="splash")
        self.canvas.create_text(cw // 2, ch // 2 + 8, anchor="center",
                                text="File > Open ROM... to begin",
                                fill="#aaccff", font=("TkFixedFont", 10),
                                tags="splash")
        self.canvas.create_text(cw // 2, ch - 22, anchor="center",
                                text=f"Python {sys.version.split()[0]} | NTSC | 60 FPS target",
                                fill=self.ACCENT, font=("TkFixedFont", 9),
                                tags="splash")

    def _hide_splash(self):
        self.canvas.delete("splash")

    def _open_dialog(self):
        path = filedialog.askopenfilename(
            title="Open NES ROM",
            filetypes=[("NES iNES ROM", "*.nes"), ("All files", "*.*")])
        if path:
            self._open(path)

    def _open(self, path):
        try:
            nes = NES(path)
        except Exception as e:
            messagebox.showerror("luigines",
                                 f"Failed to load ROM:\n{path}\n\n{e}")
            return
        self.nes = nes
        self.running = True
        self.paused = False
        self.frame_count = 0
        self._hide_splash()
        h = nes.rom.header
        info = (f"{os.path.basename(path)} | mapper {h.mapper}"
                f"{'.' + str(h.submapper) if h.is_nes2 else ''}"
                f" | PRG {h.prg_banks}x16K | CHR {h.chr_banks}x8K"
                f" | {h.mirroring}{' | NES2.0' if h.is_nes2 else ''}")
        self.status_var.set(info)
        self.root.title(f"luigines by ac - {os.path.basename(path)}")

    def _close_rom(self):
        self.nes = None
        self.running = False
        self.status_var.set("No ROM loaded.")
        self.root.title("luigines by ac")
        self._show_splash()

    def _reset(self):
        if self.nes:
            self.nes.cpu.reset()
            self.nes.ppu.scanline = 0

    def _power_cycle(self):
        if self.nes:
            path = self.nes.rom.header.filename
            self._open(path)

    def _toggle_pause(self):
        if not self.nes:
            return
        self.paused = not self.paused
        s = self.status_var.get().replace("  [paused]", "")
        if self.paused:
            s += "  [paused]"
        self.status_var.set(s)

    def _about(self):
        messagebox.showinfo(
            "About luigines",
            "luigines 0.1a by ac\n"
            f"Single-file NES emulator, Python {sys.version.split()[0]}\n\n"
            "FCEUX-style GUI, blue hue, 60 FPS NTSC target.\n"
            "Mappers supported: 0, 1, 2, 3, 4, 7, 11, 66, 71.\n"
            "Unsupported mappers fall back to NROM so the ROM still boots.")

    def _controls_help(self):
        messagebox.showinfo(
            "Controls",
            "D-Pad  : Arrow keys (or WASD)\n"
            "A      : X\n"
            "B      : Z\n"
            "Start  : Enter\n"
            "Select : Shift\n\n"
            "Pause  : P  (or Pause key)\n"
            "Reset  : Ctrl+R\n"
            "Open   : Ctrl+O")

    def _quit(self):
        self.running = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    FRAME_MS = 1000 // 60

    def _schedule_frame(self):
        self.root.after(self.FRAME_MS, self._frame_tick)

    def _frame_tick(self):
        start = time.perf_counter()
        if self.nes and self.running and not self.paused:
            try:
                self.nes.run_frame()
                self._blit()
            except Exception as e:
                self.running = False
                self.status_var.set(f"emulation error: {e}")
        now = time.time()
        self.frame_count += 1
        if now - self.last_fps_t >= 1.0:
            self.fps = self.frame_count / (now - self.last_fps_t)
            self.frame_count = 0
            self.last_fps_t = now
            if self.nes:
                base = self.status_var.get().split("  FPS")[0]
                self.status_var.set(f"{base}  FPS {self.fps:5.1f}")
        elapsed_ms = (time.perf_counter() - start) * 1000
        delay = max(1, int(self.FRAME_MS - elapsed_ms))
        self.root.after(delay, self._frame_tick)

    def _blit(self):
        if self.nes is None:
            return
        fb = self.nes.ppu.framebuffer
        pal = NES_PALETTE_HEX
        rows = []
        append = rows.append
        for y in range(SCREEN_H):
            row_off = y * SCREEN_W
            append("{" + " ".join(pal[fb[row_off + x] & 0x3F] for x in range(SCREEN_W)) + "}")
        data = " ".join(rows)
        try:
            tmp = tk.PhotoImage(width=SCREEN_W, height=SCREEN_H)
            tmp.put(data)
            self.photo = tmp.zoom(SCALE, SCALE)
            self.canvas.itemconfig(self.canvas_img, image=self.photo)
        except tk.TclError:
            pass


def main():
    if sys.version_info < (3, 14):
        print(f"luigines requires Python 3.14+, got {sys.version}", file=sys.stderr)
        return 1
    rom = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    try:
        root.option_add("*Font", "TkFixedFont")
    except tk.TclError:
        pass
    EmuApp(root, rom)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

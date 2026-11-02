"""Bounded ELF64 DT_NEEDED reference parser; never resolve or load libraries.

Only for an already-opened, no-follow, regular ODBC18 vendor ELF file
whose header was checked by the owning OFF-2 operator diagnostic. This
module reads a bounded subset of the same file descriptor via pread;
it does not execute binaries, search system library paths, contact any
service or expose dependency names to output.
"""
from __future__ import annotations

import os
import re
import struct

MAX_PROGRAM_HEADERS = 64
MAX_DYNAMIC_BYTES = 64 * 1024
MAX_STRING_TABLE_BYTES = 64 * 1024
MAX_NEEDED_NAMES = 64
MAX_NEEDED_NAME_BYTES = 128
_PT_LOAD = 1
_PT_DYNAMIC = 2
_DT_NULL = 0
_DT_NEEDED = 1
_DT_STRTAB = 5
_DT_STRSZ = 10
_SONAME = re.compile(rb"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,127}\.so(?:\.[A-Za-z0-9_.+\-]{1,80})?")


class _ELFDynamicInvalid(Exception):
    """Sanitized invalid/unverifiable ELF dynamic metadata."""


def _checked_range(offset: int, length: int, size: int) -> bool:
    return 0 <= offset <= size and 0 <= length <= size - offset


def _read(fd: int, offset: int, n: int, size: int) -> bytes:
    if not _checked_range(offset, n, size):
        raise _ELFDynamicInvalid
    value = os.pread(fd, n, offset)
    if len(value) != n:
        raise _ELFDynamicInvalid
    return value


def inspect_needed(fd: int, size: int, header: bytes) -> int:
    """Return only a count of valid DT_NEEDED strings (no link resolution).

    Fail closed on extended/unsupported ELF program headers, unbounded
    tables, duplicate or unsafe referenced names, missing DT_NULL or
    virtual-string-table addresses not mapped by an on-disk PT_LOAD.
    """
    if len(header) != 64 or header[:6] != b"\x7fELF\x02\x01":
        raise _ELFDynamicInvalid
    phoff = struct.unpack_from("<Q", header, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", header, 54)
    if (phentsize != 56 or not 1 <= phnum <= MAX_PROGRAM_HEADERS
            or phoff < 64):
        raise _ELFDynamicInvalid
    programs_raw = _read(fd, phoff, phnum * 56, size)
    loads: list[tuple[int, int, int]] = []
    dynamic: tuple[int, int] | None = None
    for (typ, _flags, offset, vaddr, _paddr, filesz, memsz, _align) in struct.iter_unpack(
            "<IIQQQQQQ", programs_raw):
        if typ not in (_PT_LOAD, _PT_DYNAMIC):
            continue
        if (filesz > memsz or not _checked_range(offset, filesz, size)
                or memsz == 0):
            raise _ELFDynamicInvalid
        if typ == _PT_LOAD:
            loads.append((offset, vaddr, filesz))
        elif typ == _PT_DYNAMIC:
            if dynamic is not None or not 16 <= filesz <= MAX_DYNAMIC_BYTES or filesz % 16:
                raise _ELFDynamicInvalid
            dynamic = (offset, filesz)
    if not loads or dynamic is None:
        raise _ELFDynamicInvalid

    raw = _read(fd, dynamic[0], dynamic[1], size)
    strtab: int | None = None
    strsz: int | None = None
    offsets: list[int] = []
    saw_end = False
    for tag, value in struct.iter_unpack("<qQ", raw):
        if tag == _DT_NULL:
            saw_end = True
            break
        if tag == _DT_NEEDED:
            if len(offsets) >= MAX_NEEDED_NAMES:
                raise _ELFDynamicInvalid
            offsets.append(value)
        elif tag == _DT_STRTAB:
            if strtab is not None:
                raise _ELFDynamicInvalid
            strtab = value
        elif tag == _DT_STRSZ:
            if strsz is not None:
                raise _ELFDynamicInvalid
            strsz = value

    if (not saw_end or not offsets or strtab is None or strsz is None
            or not 1 <= strsz <= MAX_STRING_TABLE_BYTES):
        raise _ELFDynamicInvalid

    str_offset = None
    for offset, vaddr, length in loads:
        # Need the *whole* string table inside an on-disk PT_LOAD.
        if vaddr <= strtab and strsz <= length and strtab - vaddr <= length - strsz:
            str_offset = offset + strtab - vaddr
            break
    if str_offset is None:
        raise _ELFDynamicInvalid
    data = _read(fd, str_offset, strsz, size)
    seen: set[bytes] = set()
    for item in offsets:
        if item >= len(data):
            raise _ELFDynamicInvalid
        end = data.find(b"\x00", item)
        if end < 0 or not 1 <= end - item <= MAX_NEEDED_NAME_BYTES:
            raise _ELFDynamicInvalid
        name = data[item:end]
        if _SONAME.fullmatch(name) is None or name in seen:
            raise _ELFDynamicInvalid
        seen.add(name)
    return len(offsets)

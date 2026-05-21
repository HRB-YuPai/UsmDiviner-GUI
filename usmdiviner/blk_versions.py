#!/usr/bin/env python3
"""
Extract MiHoYoBinData RawData-like payloads from Genshin Blb3 container files (magic: Blb\x03).

This script ports the key parts of AnimeStudio's Blb3 pipeline:
- BlbUtils.Decrypt
- BlbAES (custom AES variant)
- Blb3File header/block parsing

It also supports loading the Blb3 key tables from AnimeStudio's CryptoHelper.cs so you can
add/update keys without changing this script.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

"""Built-in Blb3 key tables extracted from AnimeStudio CryptoHelper.cs."""

BUILTIN_BLB3_KEYS = {
    "GF256Exp": [1, 3, 5, 15, 17, 51, 85, 255, 26, 46, 114, 150, 161, 248, 19, 53, 95, 225, 56, 72, 216, 115, 149, 164, 247, 2, 6, 10, 30, 34, 102, 170, 229, 52, 92, 228, 55, 89, 235, 38, 106, 190, 217, 112, 144, 171, 230, 49, 83, 245, 4, 12, 20, 60, 68, 204, 79, 209, 104, 184, 211, 110, 178, 205, 76, 212, 103, 169, 224, 59, 77, 215, 98, 166, 241, 8, 24, 40, 120, 136, 131, 158, 185, 208, 107, 189, 220, 127, 129, 152, 179, 206, 73, 219, 118, 154, 181, 196, 87, 249, 16, 48, 80, 240, 11, 29, 39, 105, 187, 214, 97, 163, 254, 25, 43, 125, 135, 146, 173, 236, 47, 113, 147, 174, 233, 32, 96, 160, 251, 22, 58, 78, 210, 109, 183, 194, 93, 231, 50, 86, 250, 21, 63, 65, 195, 94, 226, 61, 71, 201, 64, 192, 91, 237, 44, 116, 156, 191, 218, 117, 159, 186, 213, 100, 172, 239, 42, 126, 130, 157, 188, 223, 122, 142, 137, 128, 155, 182, 193, 88, 232, 35, 101, 175, 234, 37, 111, 177, 200, 67, 197, 84, 252, 31, 33, 99, 165, 244, 7, 9, 27, 45, 119, 153, 176, 203, 70, 202, 69, 207, 74, 222, 121, 139, 134, 145, 168, 227, 62, 66, 198, 81, 243, 14, 18, 54, 90, 238, 41, 123, 141, 140, 143, 138, 133, 148, 167, 242, 13, 23, 57, 75, 221, 124, 132, 151, 162, 253, 28, 36, 108, 180, 199, 82, 246, 1],
    "GF256Log": [0, 0, 25, 1, 50, 2, 26, 198, 75, 199, 27, 104, 51, 238, 223, 3, 100, 4, 224, 14, 52, 141, 129, 239, 76, 113, 8, 200, 248, 105, 28, 193, 125, 194, 29, 181, 249, 185, 39, 106, 77, 228, 166, 114, 154, 201, 9, 120, 101, 47, 138, 5, 33, 15, 225, 36, 18, 240, 130, 69, 53, 147, 218, 142, 150, 143, 219, 189, 54, 208, 206, 148, 19, 92, 210, 241, 64, 70, 131, 56, 102, 221, 253, 48, 191, 6, 139, 98, 179, 37, 226, 152, 34, 136, 145, 16, 126, 110, 72, 195, 163, 182, 30, 66, 58, 107, 40, 84, 250, 133, 61, 186, 43, 121, 10, 21, 155, 159, 94, 202, 78, 212, 172, 229, 243, 115, 167, 87, 175, 88, 168, 80, 244, 234, 214, 116, 79, 174, 233, 213, 231, 230, 173, 232, 44, 215, 117, 122, 235, 22, 11, 245, 89, 203, 95, 176, 156, 169, 81, 160, 127, 12, 246, 111, 23, 196, 73, 236, 216, 67, 31, 45, 164, 118, 123, 183, 204, 187, 62, 90, 251, 96, 177, 134, 59, 82, 161, 108, 170, 85, 41, 157, 151, 178, 135, 144, 97, 190, 220, 252, 188, 149, 207, 205, 55, 63, 91, 209, 83, 57, 132, 60, 65, 162, 109, 71, 20, 42, 158, 93, 86, 242, 211, 171, 68, 17, 146, 217, 35, 32, 46, 137, 180, 124, 184, 38, 119, 153, 227, 165, 103, 74, 237, 222, 197, 49, 254, 24, 13, 99, 140, 128, 192, 247, 112, 7],
    "Blb3AESSBox": [99, 125, 117, 120, 246, 110, 105, 194, 56, 8, 109, 32, 242, 218, 165, 121, 218, 147, 219, 110, 238, 76, 81, 231, 181, 205, 184, 180, 128, 185, 108, 223, 151, 220, 177, 5, 18, 26, 209, 235, 28, 140, 207, 218, 93, 245, 31, 58, 52, 246, 17, 240, 44, 163, 51, 173, 63, 43, 186, 217, 215, 26, 140, 74, 73, 194, 110, 89, 95, 43, 28, 231, 26, 114, 156, 248, 101, 174, 97, 203, 3, 128, 82, 190, 116, 169, 231, 12, 50, 146, 228, 98, 22, 17, 6, 144, 176, 142, 200, 152, 39, 40, 85, 226, 45, 144, 104, 20, 60, 81, 241, 199, 33, 210, 50, 252, 230, 232, 78, 130, 196, 207, 160, 90, 108, 130, 141, 173, 77, 141, 145, 111, 219, 18, 194, 144, 76, 46, 244, 182, 232, 208, 151, 252, 240, 16, 221, 79, 182, 191, 6, 31, 222, 119, 34, 143, 66, 195, 149, 68, 64, 147, 152, 169, 237, 163, 130, 251, 106, 122, 6, 201, 61, 56, 74, 214, 87, 121, 133, 222, 57, 96, 248, 30, 212, 239, 78, 81, 217, 199, 16, 183, 122, 185, 231, 237, 216, 99, 114, 1, 32, 20, 190, 212, 135, 112, 69, 69, 160, 239, 103, 181, 156, 214, 32, 217, 185, 236, 141, 98, 90, 28, 195, 65, 1, 25, 122, 242, 141, 60, 104, 115, 115, 247, 109, 2, 34, 184, 198, 48, 124, 80, 123, 254, 75, 19, 180, 159, 185, 96, 215, 244, 76, 169, 69, 233],
    "Blb3AESShift": [0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15],
    "Blb3RC4Key": [41, 35, 190, 132, 225, 108, 214, 174, 82, 144, 73, 241, 241, 187, 233, 235, 179, 166, 219, 60, 135, 12, 62, 153, 36, 94, 13, 28, 6, 183, 71, 222, 179, 18, 77, 200, 67, 187, 139, 166, 31, 3, 90, 125, 9, 56, 37, 31, 93, 212, 203, 252, 150, 245, 69, 59, 19, 13, 137, 10, 28, 219, 174, 50, 32, 154, 80, 238, 64, 120, 54, 253, 18, 73, 50, 246, 158, 125, 73, 220, 173, 79, 20, 242, 68, 64, 102, 208, 107, 196, 48, 183, 50, 59, 161, 34, 246, 34, 145, 157, 225, 139, 31, 218, 176, 202, 153, 2, 185, 114, 157, 73, 44, 128, 126, 197, 153, 213, 233, 128, 178, 234, 201, 204, 83, 191, 103, 214, 191, 20, 214, 126, 45, 220, 142, 102, 131, 239, 87, 73, 97, 255, 105, 143, 97, 205, 209, 30, 157, 156, 22, 114, 114, 230, 29, 240, 132, 79, 74, 119, 2, 215, 232, 57, 44, 83, 203, 201, 18, 30, 51, 116, 158, 12, 244, 213, 212, 159, 212, 164, 89, 126, 53, 207, 50, 34, 244, 204, 207, 211, 144, 45, 72, 211, 143, 117, 230, 217, 29, 42, 229, 192, 247, 43, 120, 129, 135, 68, 14, 95, 80, 0, 212, 97, 141, 190, 123, 5, 21, 7, 59, 51, 130, 31, 24, 112, 146, 218, 100, 84, 206, 177, 133, 62, 105, 21, 248, 70, 106, 4, 150, 115, 14, 217, 22, 47, 103, 104, 212, 247, 74, 74, 208, 87, 104, 118],
    "Blb3SBox": [208, 32, 65, 74, 162, 122, 206, 102, 33, 124, 142, 69, 244, 135, 49, 221, 216, 53, 194, 9, 234, 96, 56, 210, 180, 190, 16, 118, 127, 183, 15, 253, 203, 2, 14, 91, 46, 155, 177, 225, 245, 94, 64, 77, 136, 152, 111, 55, 171, 238, 83, 121, 112, 36, 108, 103, 230, 60, 73, 6, 89, 186, 207, 8, 138, 172, 160, 139, 61, 191, 19, 115, 67, 145, 0, 43, 161, 34, 147, 58, 204, 76, 68, 20, 40, 247, 237, 54, 79, 228, 252, 144, 10, 158, 214, 119, 5, 189, 87, 63, 150, 95, 75, 188, 141, 62, 114, 254, 78, 167, 195, 169, 59, 7, 137, 47, 184, 255, 29, 182, 101, 109, 196, 97, 57, 106, 163, 100, 193, 174, 178, 151, 41, 159, 242, 50, 52, 26, 88, 39, 81, 113, 21, 3, 236, 71, 30, 92, 179, 24, 125, 233, 72, 110, 85, 25, 42, 218, 37, 128, 17, 241, 149, 229, 226, 131, 165, 130, 28, 90, 205, 212, 116, 157, 51, 181, 213, 202, 22, 227, 35, 132, 44, 222, 27, 148, 232, 82, 1, 18, 123, 99, 80, 154, 104, 246, 215, 140, 98, 224, 23, 219, 143, 12, 192, 13, 70, 223, 248, 4, 235, 117, 166, 209, 164, 251, 93, 200, 31, 243, 220, 176, 120, 170, 45, 201, 86, 156, 134, 249, 198, 231, 129, 146, 168, 239, 84, 107, 126, 153, 197, 217, 199, 250, 211, 38, 48, 185, 240, 11, 66, 173, 133, 105, 187, 175, 11, 226, 194, 41, 255, 221, 230, 42, 217, 151, 48, 94, 115, 149, 72, 5, 86, 38, 15, 210, 162, 154, 60, 174, 20, 189, 249, 146, 35, 97, 116, 49, 225, 195, 122, 229, 240, 138, 50, 170, 145, 27, 121, 231, 84, 12, 129, 208, 213, 8, 14, 152, 159, 108, 191, 172, 89, 237, 24, 135, 220, 133, 105, 246, 130, 1, 167, 131, 32, 215, 16, 185, 33, 30, 66, 216, 177, 74, 161, 102, 157, 13, 113, 91, 26, 183, 45, 164, 7, 101, 51, 6, 245, 103, 207, 168, 18, 222, 95, 63, 53, 19, 111, 2, 107, 209, 166, 29, 199, 90, 64, 179, 248, 144, 165, 155, 148, 160, 0, 96, 104, 80, 218, 67, 56, 123, 55, 79, 244, 88, 197, 100, 34, 61, 201, 252, 10, 58, 186, 120, 106, 250, 92, 140, 224, 119, 136, 65, 205, 81, 158, 163, 76, 31, 202, 22, 110, 40, 241, 254, 142, 153, 200, 251, 25, 126, 127, 69, 77, 228, 223, 117, 87, 109, 47, 187, 70, 227, 234, 219, 83, 52, 54, 128, 239, 247, 124, 28, 176, 156, 71, 98, 178, 181, 137, 23, 9, 206, 198, 193, 68, 203, 99, 139, 214, 132, 180, 238, 243, 85, 143, 212, 73, 62, 43, 150, 232, 253, 4, 141, 82, 188, 147, 112, 171, 233, 78, 235, 46, 118, 169, 134, 204, 211, 196, 175, 57, 44, 242, 75, 173, 114, 93, 190, 236, 39, 192, 21, 3, 36, 182, 125, 59, 17, 184, 37, 221, 47, 251, 6, 177, 91, 242, 165, 140, 201, 202, 199, 21, 179, 252, 124, 235, 220, 80, 145, 131, 128, 130, 83, 211, 228, 217, 115, 100, 39, 194, 160, 103, 238, 84, 13, 170, 119, 151, 133, 197, 117, 35, 167, 55, 1, 25, 209, 121, 248, 81, 169, 73, 58, 233, 247, 240, 92, 212, 116, 26, 185, 29, 148, 40, 19, 244, 10, 144, 108, 250, 149, 112, 59, 159, 227, 226, 78, 4, 188, 163, 33, 210, 94, 219, 48, 68, 44, 118, 225, 60, 105, 28, 192, 79, 75, 11, 154, 253, 111, 216, 102, 183, 126, 23, 37, 195, 200, 243, 222, 150, 62, 98, 255, 223, 76, 45, 16, 232, 70, 246, 205, 36, 230, 193, 97, 143, 74, 139, 95, 122, 234, 101, 134, 49, 32, 213, 113, 241, 72, 190, 64, 14, 57, 67, 7, 155, 104, 204, 63, 96, 42, 189, 54, 181, 86, 66, 206, 114, 65, 69, 127, 123, 158, 3, 9, 152, 157, 0, 214, 153, 27, 176, 93, 109, 99, 198, 196, 30, 132, 182, 15, 17, 172, 229, 175, 184, 191, 61, 174, 85, 164, 180, 24, 50, 31, 249, 147, 129, 46, 239, 5, 34, 20, 38, 135, 237, 254, 141, 236, 178, 207, 53, 203, 231, 110, 90, 125, 41, 8, 18, 82, 161, 89, 88, 156, 208, 43, 162, 187, 77, 166, 136, 171, 106, 51, 168, 138, 2, 173, 142, 22, 137, 215, 52, 224, 186, 245, 56, 218, 146, 120, 107, 71, 87, 12, 117, 189, 92, 251, 193, 171, 71, 72, 114, 15, 70, 16, 60, 234, 205, 46, 192, 146, 2, 29, 111, 160, 204, 172, 80, 82, 213, 11, 221, 6, 33, 208, 59, 187, 195, 181, 229, 137, 184, 27, 26, 220, 63, 110, 222, 159, 57, 104, 178, 124, 36, 168, 100, 254, 79, 206, 207, 241, 93, 40, 246, 243, 253, 41, 182, 167, 140, 165, 73, 235, 156, 238, 28, 196, 186, 215, 106, 101, 67, 109, 198, 143, 122, 216, 127, 150, 99, 54, 242, 223, 98, 176, 170, 225, 105, 123, 108, 69, 61, 180, 81, 34, 125, 88, 217, 96, 86, 194, 95, 65, 1, 255, 84, 7, 166, 237, 32, 52, 38, 200, 148, 19, 76, 212, 18, 37, 158, 128, 183, 102, 49, 48, 12, 64, 8, 201, 230, 244, 142, 197, 130, 113, 118, 126, 85, 239, 233, 236, 25, 152, 9, 214, 177, 218, 94, 188, 210, 3, 116, 134, 10, 91, 23, 83, 121, 44, 219, 14, 120, 4, 90, 249, 157, 133, 139, 131, 209, 77, 162, 39, 179, 20, 132, 173, 97, 174, 21, 144, 149, 30, 175, 107, 35, 228, 22, 145, 47, 153, 250, 0, 31, 51, 202, 226, 151, 42, 103, 169, 13, 231, 43, 74, 68, 135, 45, 66, 155, 50, 138, 62, 245, 211, 141, 147, 24, 129, 55, 136, 252, 112, 247, 199, 161, 56, 203, 78, 164, 163, 87, 17, 185, 53, 115, 232, 224, 227, 89, 58, 119, 190, 240, 5, 75, 191, 154, 248],
    "Blb3ShiftRow": [5, 10, 3, 8, 15, 2, 7, 9, 0, 6, 14, 11, 12, 1, 4, 13, 5, 14, 8, 6, 1, 12, 7, 9, 0, 15, 3, 11, 4, 13, 2, 10, 4, 15, 13, 5, 12, 8, 2, 9, 11, 1, 7, 3, 10, 0, 6, 14],
    "Blb3Key": [169, 133, 87, 77, 139, 249, 129, 51],
    "Blb3Mul": [200, 115, 191, 37, 217, 156, 126, 108],
}

try:
    import lz4.block  # type: ignore
except Exception:  # pragma: no cover
    lz4 = None
else:
    lz4 = lz4.block


# Blb3 compression values used by Unity/AnimeStudio.
COMP_NONE = 0
COMP_LZMA = 1
COMP_LZ4 = 2
COMP_LZ4HC = 3
COMP_OODLE = 4


@dataclass
class Blb3Keys:
    gf256_exp: list[int]
    gf256_log: list[int]
    aes_sbox: list[int]
    aes_shift: list[int]
    rc4_key: list[int]
    sbox: list[int]
    shift_row: list[int]
    key: list[int]
    mul: list[int]


@dataclass
class BlockInfo:
    compressed_size: int
    uncompressed_size: int
    compression: int


@dataclass
class NodeInfo:
    offset: int
    size: int
    flags: int
    path: str


def _read_u8(buf: io.BytesIO) -> int:
    b = buf.read(1)
    if len(b) != 1:
        raise EOFError("Unexpected EOF while reading u8")
    return b[0]


def _read_u32(buf: io.BytesIO) -> int:
    b = buf.read(4)
    if len(b) != 4:
        raise EOFError("Unexpected EOF while reading u32")
    return struct.unpack("<I", b)[0]


def _read_i32(buf: io.BytesIO) -> int:
    b = buf.read(4)
    if len(b) != 4:
        raise EOFError("Unexpected EOF while reading i32")
    return struct.unpack("<i", b)[0]


def _read_i64(buf: io.BytesIO) -> int:
    b = buf.read(8)
    if len(b) != 8:
        raise EOFError("Unexpected EOF while reading i64")
    return struct.unpack("<q", b)[0]


def _read_cstring(buf: io.BytesIO) -> str:
    out = bytearray()
    while True:
        b = buf.read(1)
        if not b:
            break
        if b == b"\x00":
            break
        out += b
    return out.decode("utf-8", errors="replace")


def _align_4(buf: io.BytesIO) -> None:
    pos = buf.tell()
    rem = pos % 4
    if rem:
        buf.seek(4 - rem, io.SEEK_CUR)


def _parse_csharp_byte_array(src: str, name: str) -> list[int]:
    # Matches: public static readonly byte[] Name = new byte[...] { ... };
    pattern = re.compile(
        rf"\b{name}\b\s*=\s*new\s+byte\s*\[[^\]]*\]\s*\{{(.*?)\}}\s*;",
        re.DOTALL,
    )
    m = pattern.search(src)
    if not m:
        raise ValueError(f"Cannot find array '{name}' in CryptoHelper.cs")
    body = m.group(1)
    nums = re.findall(r"0x[0-9A-Fa-f]+|\d+", body)
    return [int(x, 16) if x.lower().startswith("0x") else int(x) for x in nums]


def load_blb3_keys_from_crypthelper(path: Path) -> Blb3Keys:
    src = path.read_text(encoding="utf-8", errors="replace")
    return Blb3Keys(
        gf256_exp=_parse_csharp_byte_array(src, "GF256Exp"),
        gf256_log=_parse_csharp_byte_array(src, "GF256Log"),
        aes_sbox=_parse_csharp_byte_array(src, "Blb3AESSBox"),
        aes_shift=_parse_csharp_byte_array(src, "Blb3AESShift"),
        rc4_key=_parse_csharp_byte_array(src, "Blb3RC4Key"),
        sbox=_parse_csharp_byte_array(src, "Blb3SBox"),
        shift_row=_parse_csharp_byte_array(src, "Blb3ShiftRow"),
        key=_parse_csharp_byte_array(src, "Blb3Key"),
        mul=_parse_csharp_byte_array(src, "Blb3Mul"),
    )


def load_blb3_keys_from_builtin() -> Blb3Keys:
    if not BUILTIN_BLB3_KEYS:
        raise ValueError("Built-in Blb3 key tables are unavailable")
    return Blb3Keys(
        gf256_exp=list(BUILTIN_BLB3_KEYS["GF256Exp"]),
        gf256_log=list(BUILTIN_BLB3_KEYS["GF256Log"]),
        aes_sbox=list(BUILTIN_BLB3_KEYS["Blb3AESSBox"]),
        aes_shift=list(BUILTIN_BLB3_KEYS["Blb3AESShift"]),
        rc4_key=list(BUILTIN_BLB3_KEYS["Blb3RC4Key"]),
        sbox=list(BUILTIN_BLB3_KEYS["Blb3SBox"]),
        shift_row=list(BUILTIN_BLB3_KEYS["Blb3ShiftRow"]),
        key=list(BUILTIN_BLB3_KEYS["Blb3Key"]),
        mul=list(BUILTIN_BLB3_KEYS["Blb3Mul"]),
    )


def _gf256_mul(keys: Blb3Keys, a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return keys.gf256_exp[(keys.gf256_log[a] + keys.gf256_log[b]) % 0xFF]


def _blb_aes_expand(keys: Blb3Keys, key: bytes) -> list[int]:
    shift_rows_table = [0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11]
    power_schedule = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]

    out = [0] * 176
    for i in range(16):
        out[i] = key[keys.aes_shift[i]]

    offset = 0x1F
    for rnd in range(10):
        a = keys.aes_sbox[out[offset - 0x14]]
        b = keys.aes_sbox[out[offset - 0x10]]
        c = (
            keys.aes_sbox[out[offset - 0x18]]
            ^ out[offset - 0x18]
            ^ power_schedule[rnd]
            ^ out[offset - 0x1F]
        )
        d = keys.aes_sbox[out[offset - 0x1C]]

        out[offset - 0x0F] = c & 0xFF
        temp = a ^ out[offset - 0x14] ^ out[offset - 0x1B]
        out[offset - 0x0B] = temp & 0xFF
        a = b ^ out[offset - 0x10] ^ out[offset - 0x17]
        out[offset - 7] = a & 0xFF
        b = d ^ out[offset - 0x1C] ^ out[offset - 0x13]
        out[offset - 3] = b & 0xFF

        c ^= out[offset - 0x1E]
        out[offset - 0x0E] = c & 0xFF
        temp ^= out[offset - 0x1A]
        out[offset - 10] = temp & 0xFF
        a ^= out[offset - 0x16]
        out[offset - 6] = a & 0xFF
        b ^= out[offset - 0x12]
        out[offset - 2] = b & 0xFF

        c ^= out[offset - 0x1D]
        out[offset - 0x0D] = c & 0xFF
        temp ^= out[offset - 0x19]
        out[offset - 9] = temp & 0xFF
        a ^= out[offset - 0x15]
        out[offset - 5] = a & 0xFF
        b ^= out[offset - 0x11]
        out[offset - 1] = b & 0xFF

        out[offset - 0x0C] = (c ^ out[offset - 0x1C]) & 0xFF
        out[offset - 8] = (temp ^ out[offset - 0x18]) & 0xFF
        out[offset - 4] = (a ^ out[offset - 0x14]) & 0xFF
        out[offset] = (b ^ out[offset - 0x10]) & 0xFF

        offset += 0x10

    return out


def _blb_aes_sub_bytes(keys: Blb3Keys, state: bytearray) -> None:
    for i in range(len(state)):
        state[i] ^= keys.aes_sbox[state[i]]


def _blb_aes_shift_rows(state: bytearray) -> None:
    table = [0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11]
    tmp = state[:]
    for i in range(16):
        state[i] = tmp[table[i]]


def _blb_aes_mix_cols(state: bytearray) -> None:
    # Lookup tables are identical to the C# implementation.
    g2 = [
        0x00, 0x02, 0x04, 0x06, 0x08, 0x0A, 0x0C, 0x0E, 0x10, 0x12, 0x14, 0x16, 0x18, 0x1A, 0x1C, 0x1E,
        0x20, 0x22, 0x24, 0x26, 0x28, 0x2A, 0x2C, 0x2E, 0x30, 0x32, 0x34, 0x36, 0x38, 0x3A, 0x3C, 0x3E,
        0x40, 0x42, 0x44, 0x46, 0x48, 0x4A, 0x4C, 0x4E, 0x50, 0x52, 0x54, 0x56, 0x58, 0x5A, 0x5C, 0x5E,
        0x60, 0x62, 0x64, 0x66, 0x68, 0x6A, 0x6C, 0x6E, 0x70, 0x72, 0x74, 0x76, 0x78, 0x7A, 0x7C, 0x7E,
        0x80, 0x82, 0x84, 0x86, 0x88, 0x8A, 0x8C, 0x8E, 0x90, 0x92, 0x94, 0x96, 0x98, 0x9A, 0x9C, 0x9E,
        0xA0, 0xA2, 0xA4, 0xA6, 0xA8, 0xAA, 0xAC, 0xAE, 0xB0, 0xB2, 0xB4, 0xB6, 0xB8, 0xBA, 0xBC, 0xBE,
        0xC0, 0xC2, 0xC4, 0xC6, 0xC8, 0xCA, 0xCC, 0xCE, 0xD0, 0xD2, 0xD4, 0xD6, 0xD8, 0xDA, 0xDC, 0xDE,
        0xE0, 0xE2, 0xE4, 0xE6, 0xE8, 0xEA, 0xEC, 0xEE, 0xF0, 0xF2, 0xF4, 0xF6, 0xF8, 0xFA, 0xFC, 0xFE,
        0x1B, 0x19, 0x1F, 0x1D, 0x13, 0x11, 0x17, 0x15, 0x0B, 0x09, 0x0F, 0x0D, 0x03, 0x01, 0x07, 0x05,
        0x3B, 0x39, 0x3F, 0x3D, 0x33, 0x31, 0x37, 0x35, 0x2B, 0x29, 0x2F, 0x2D, 0x23, 0x21, 0x27, 0x25,
        0x5B, 0x59, 0x5F, 0x5D, 0x53, 0x51, 0x57, 0x55, 0x4B, 0x49, 0x4F, 0x4D, 0x43, 0x41, 0x47, 0x45,
        0x7B, 0x79, 0x7F, 0x7D, 0x73, 0x71, 0x77, 0x75, 0x6B, 0x69, 0x6F, 0x6D, 0x63, 0x61, 0x67, 0x65,
        0x9B, 0x99, 0x9F, 0x9D, 0x93, 0x91, 0x97, 0x95, 0x8B, 0x89, 0x8F, 0x8D, 0x83, 0x81, 0x87, 0x85,
        0xBB, 0xB9, 0xBF, 0xBD, 0xB3, 0xB1, 0xB7, 0xB5, 0xAB, 0xA9, 0xAF, 0xAD, 0xA3, 0xA1, 0xA7, 0xA5,
        0xDB, 0xD9, 0xDF, 0xDD, 0xD3, 0xD1, 0xD7, 0xD5, 0xCB, 0xC9, 0xCF, 0xCD, 0xC3, 0xC1, 0xC7, 0xC5,
        0xFB, 0xF9, 0xFF, 0xFD, 0xF3, 0xF1, 0xF7, 0xF5, 0xEB, 0xE9, 0xEF, 0xED, 0xE3, 0xE1, 0xE7, 0xE5,
    ]
    g3 = [
        0x00, 0x03, 0x06, 0x05, 0x0C, 0x0F, 0x0A, 0x09, 0x18, 0x1B, 0x1E, 0x1D, 0x14, 0x17, 0x12, 0x11,
        0x30, 0x33, 0x36, 0x35, 0x3C, 0x3F, 0x3A, 0x39, 0x28, 0x2B, 0x2E, 0x2D, 0x24, 0x27, 0x22, 0x21,
        0x60, 0x63, 0x66, 0x65, 0x6C, 0x6F, 0x6A, 0x69, 0x78, 0x7B, 0x7E, 0x7D, 0x74, 0x77, 0x72, 0x71,
        0x50, 0x53, 0x56, 0x55, 0x5C, 0x5F, 0x5A, 0x59, 0x48, 0x4B, 0x4E, 0x4D, 0x44, 0x47, 0x42, 0x41,
        0xC0, 0xC3, 0xC6, 0xC5, 0xCC, 0xCF, 0xCA, 0xC9, 0xD8, 0xDB, 0xDE, 0xDD, 0xD4, 0xD7, 0xD2, 0xD1,
        0xF0, 0xF3, 0xF6, 0xF5, 0xFC, 0xFF, 0xFA, 0xF9, 0xE8, 0xEB, 0xEE, 0xED, 0xE4, 0xE7, 0xE2, 0xE1,
        0xA0, 0xA3, 0xA6, 0xA5, 0xAC, 0xAF, 0xAA, 0xA9, 0xB8, 0xBB, 0xBE, 0xBD, 0xB4, 0xB7, 0xB2, 0xB1,
        0x90, 0x93, 0x96, 0x95, 0x9C, 0x9F, 0x9A, 0x99, 0x88, 0x8B, 0x8E, 0x8D, 0x84, 0x87, 0x82, 0x81,
        0x9B, 0x98, 0x9D, 0x9E, 0x97, 0x94, 0x91, 0x92, 0x83, 0x80, 0x85, 0x86, 0x8F, 0x8C, 0x89, 0x8A,
        0xAB, 0xA8, 0xAD, 0xAE, 0xA7, 0xA4, 0xA1, 0xA2, 0xB3, 0xB0, 0xB5, 0xB6, 0xBF, 0xBC, 0xB9, 0xBA,
        0xFB, 0xF8, 0xFD, 0xFE, 0xF7, 0xF4, 0xF1, 0xF2, 0xE3, 0xE0, 0xE5, 0xE6, 0xEF, 0xEC, 0xE9, 0xEA,
        0xCB, 0xC8, 0xCD, 0xCE, 0xC7, 0xC4, 0xC1, 0xC2, 0xD3, 0xD0, 0xD5, 0xD6, 0xDF, 0xDC, 0xD9, 0xDA,
        0x5B, 0x58, 0x5D, 0x5E, 0x57, 0x54, 0x51, 0x52, 0x43, 0x40, 0x45, 0x46, 0x4F, 0x4C, 0x49, 0x4A,
        0x6B, 0x68, 0x6D, 0x6E, 0x67, 0x64, 0x61, 0x62, 0x73, 0x70, 0x75, 0x76, 0x7F, 0x7C, 0x79, 0x7A,
        0x3B, 0x38, 0x3D, 0x3E, 0x37, 0x34, 0x31, 0x32, 0x23, 0x20, 0x25, 0x26, 0x2F, 0x2C, 0x29, 0x2A,
        0x0B, 0x08, 0x0D, 0x0E, 0x07, 0x04, 0x01, 0x02, 0x13, 0x10, 0x15, 0x16, 0x1F, 0x1C, 0x19, 0x1A,
    ]

    def mix_col(off: int) -> None:
        a0 = state[off + 0]
        a1 = state[off + 1]
        a2 = state[off + 2]
        a3 = state[off + 3]
        state[off + 0] = g2[a0] ^ g3[a1] ^ a2 ^ a3
        state[off + 1] = g2[a1] ^ g3[a2] ^ a3 ^ a0
        state[off + 2] = g2[a2] ^ g3[a3] ^ a0 ^ a1
        state[off + 3] = g2[a3] ^ g3[a0] ^ a1 ^ a2

    mix_col(0)
    mix_col(4)
    mix_col(8)
    mix_col(12)


def _blb_aes_xor_round_key(state: bytearray, keys: list[int], rnd: int) -> None:
    for i in range(4):
        for j in range(4):
            state[i * 4 + j] ^= keys[i + j * 4 + rnd * 16]


def blb_aes_encrypt(keys: Blb3Keys, block: bytes, key: bytes) -> bytes:
    rk = _blb_aes_expand(keys, key)
    state = bytearray(block[:16])
    _blb_aes_xor_round_key(state, rk, 0)

    for rnd in range(9):
        _blb_aes_sub_bytes(keys, state)
        _blb_aes_shift_rows(state)
        _blb_aes_mix_cols(state)
        _blb_aes_xor_round_key(state, rk, rnd + 1)

    _blb_aes_sub_bytes(keys, state)
    _blb_aes_shift_rows(state)
    _blb_aes_xor_round_key(state, rk, 10)
    return bytes(state)


def blb_descramble(keys: Blb3Keys, buf: bytearray) -> None:
    vec = bytearray(len(buf))
    for i in range(3):
        for j in range(len(buf)):
            k = keys.shift_row[(2 - i) * 0x10 + j]
            idx = j % 8
            v = _gf256_mul(keys, keys.mul[idx], buf[k % len(buf)])
            vec[j] = keys.key[idx] ^ keys.sbox[((j % 4) * 0x100) | v]
        buf[:] = vec


def blb_rc4(keys: Blb3Keys, buf: bytearray) -> None:
    s = keys.rc4_key[:]
    t = [0] * 256
    for i in range(0, 256, 2):
        t[i] = buf[i & 6]
        t[i + 1] = buf[(i + 1) & 7]

    j = 0
    for i in range(256):
        j = (j + s[i] + t[i]) % 256
        s[i], s[j] = s[j], s[i]

    i = 0
    j = 0
    for iteration in range(len(buf) - 0x10):
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        k = s[(s[j] + s[i]) % 256]
        mode = buf[(i % 8) + 8] % 3
        p = iteration + 0x10
        if mode == 0:
            buf[p] ^= k
        elif mode == 1:
            buf[p] = (buf[p] - k) & 0xFF
        else:
            buf[p] = (buf[p] + k) & 0xFF


def blb_decrypt(keys: Blb3Keys, header16: bytes, payload: bytes) -> bytes:
    out = bytearray(payload)
    n = min(128, len(out))
    if n == 0:
        return bytes(out)

    # AnimeStudio truncates the working span to at most 128 bytes.
    work = bytearray(out[:n])

    count = min(len(work), len(header16))
    for i in range(count):
        work[i] ^= header16[i]

    if len(work) >= 16:
        work[:16] = blb_aes_encrypt(keys, bytes(work[:16]), header16)
        if len(work) > 16:
            blb_rc4(keys, work)
        head = bytearray(work[:16])
        blb_descramble(keys, head)
        work[:16] = head

    out[:n] = work
    return bytes(out)


def parse_blb3(file_bytes: bytes, keys: Blb3Keys) -> tuple[list[tuple[str, bytes]], dict]:
    r = io.BytesIO(file_bytes)
    sig = r.read(4)
    if sig != b"Blb\x03":
        raise ValueError(f"Not Blb3: got {sig!r}")

    comp_header_size = _read_u32(r)
    _ = _read_u32(r)
    header16 = r.read(16)
    if len(header16) != 16:
        raise ValueError("Corrupted Blb3 header: missing 16-byte key header")

    raw_header = r.read(comp_header_size)
    if len(raw_header) != comp_header_size:
        raise ValueError("Corrupted Blb3 header: short compressed blocks info")

    header = blb_decrypt(keys, header16, raw_header)

    h = io.BytesIO(header)
    total_size = _read_u32(h)
    last_uncompressed = _read_u32(h)
    h.seek(4, io.SEEK_CUR)
    blob_offset = _read_i32(h)
    blob_size = _read_u32(h)
    compression_type = _read_u8(h)
    uncompressed_size = 1 << _read_u8(h)
    _align_4(h)
    blocks_count = _read_i32(h)
    nodes_count = _read_i32(h)

    base = h.tell()
    rel = _read_i64(h)
    blocks_info_offset = base + rel
    base = h.tell()
    rel = _read_i64(h)
    nodes_info_offset = base + rel
    base = h.tell()
    rel = _read_i64(h)
    flag_info_offset = base + rel

    blocks: list[BlockInfo] = []
    h.seek(blocks_info_offset)
    for i in range(blocks_count):
        csum = _read_u32(h)
        usz = last_uncompressed if i == blocks_count - 1 else uncompressed_size
        blocks.append(BlockInfo(csum, usz, compression_type))

    for i in range(len(blocks) - 1, 0, -1):
        blocks[i].compressed_size -= blocks[i - 1].compressed_size
        blocks[i].compression = COMP_NONE if blocks[i].compressed_size == blocks[i].uncompressed_size else compression_type

    nodes: list[NodeInfo] = []
    h.seek(nodes_info_offset)
    for i in range(nodes_count):
        noff = _read_i32(h)
        nsize = _read_i32(h)

        pos = h.tell()
        h.seek(flag_info_offset)
        flag = _read_u32(h)
        if i >= 0x20:
            flag = _read_u32(h)
        flags = (flag & (1 << i)) * 4
        h.seek(pos)

        base = h.tell()
        rel_path = _read_i64(h)
        path_pos = base + rel_path
        pos = h.tell()
        h.seek(path_pos)
        path = _read_cstring(h)
        h.seek(pos)

        nodes.append(NodeInfo(noff, nsize, flags, path))

    # Match AnimeStudio behavior: block bytes are read from current stream position
    # immediately after the encrypted header blob. Do not seek by blob_offset here.

    blocks_stream = io.BytesIO()
    for b in blocks:
        comp = b.compression
        if comp == COMP_NONE:
            chunk = r.read(b.uncompressed_size)
            chunk = blb_decrypt(keys, header16, chunk)
            blocks_stream.write(chunk)
            continue

        cdata = bytearray(r.read(b.compressed_size))
        if comp == COMP_OODLE and len(cdata) > 6:
            cdata = bytearray(blb_decrypt(keys, header16, bytes(cdata)))
            raise RuntimeError("Oodle blocks are not supported in this standalone Python script")

        if comp in (COMP_LZ4, COMP_LZ4HC):
            if lz4 is None:
                raise RuntimeError("lz4 package required for Blb3 LZ4 blocks (pip install lz4)")
            cdata = bytearray(blb_decrypt(keys, header16, bytes(cdata)))
            try:
                dec = lz4.decompress(bytes(cdata), uncompressed_size=b.uncompressed_size)
            except Exception as exc:
                # Some lz4 Python builds differ in framing assumptions. Try a raw fallback
                # without explicit size before failing hard.
                try:
                    dec = lz4.decompress(bytes(cdata))
                except Exception:
                    raise RuntimeError(
                        "LZ4 decompress failed "
                        f"(comp_size={b.compressed_size}, uncomp_size={b.uncompressed_size}): {exc}"
                    ) from exc
            if len(dec) != b.uncompressed_size:
                dec = dec[: b.uncompressed_size]
            blocks_stream.write(dec)
            continue

        if comp == COMP_LZMA:
            raise RuntimeError("LZMA Blb3 blocks are not yet supported in this standalone script")

        raise RuntimeError(f"Unsupported Blb3 compression type: {comp}")

    blob = blocks_stream.getvalue()
    files: list[tuple[str, bytes]] = []
    for n in nodes:
        if n.offset < 0 or n.size < 0:
            continue
        files.append((n.path, blob[n.offset : n.offset + n.size]))

    meta = {
        "signature": sig.decode("latin1"),
        "compressed_header_size": comp_header_size,
        "size_from_header": total_size,
        "blob_offset": blob_offset,
        "blob_size": blob_size,
        "compression_type": compression_type,
        "blocks_count": blocks_count,
        "nodes_count": nodes_count,
    }
    return files, meta


def looks_like_b64_ascii(data: bytes, min_len: int = 24) -> bool:
    if len(data) < min_len:
        return False
    t = data.strip()
    if len(t) < min_len or len(t) % 4 != 0:
        return False
    return bool(re.fullmatch(rb"[A-Za-z0-9+/=\r\n]+", t))


def try_decode_json(data: bytes) -> dict | list | None:
    for enc in ("utf-8", "utf-16-le", "utf-16-be", "latin1"):
        try:
            txt = data.decode(enc)
        except Exception:
            continue
        txt = txt.strip().replace("\x00", "")
        if not txt:
            continue
        if txt[0] not in "[{":
            continue
        try:
            return json.loads(txt)
        except Exception:
            continue
    return None


def scan_rawdata_candidates(files: Iterable[tuple[str, bytes]]) -> list[dict]:
    out: list[dict] = []
    b64_pat = re.compile(rb"[A-Za-z0-9+/=]{64,}")
    text_pat = re.compile(rb"[ -~]{32,}")

    for path, data in files:
        # Candidate A: file itself is a base64 blob.
        if looks_like_b64_ascii(data):
            try:
                dec = base64.b64decode(data, validate=False)
            except binascii.Error:
                dec = b""
            parsed = try_decode_json(dec)
            out.append(
                {
                    "source": path,
                    "kind": "file_base64",
                    "raw_b64": data.decode("ascii", errors="replace"),
                    "decoded_json": parsed,
                    "decoded_size": len(dec),
                }
            )

        # Candidate B: embedded long base64 spans.
        for m in b64_pat.finditer(data):
            raw = m.group(0)
            if len(raw) % 4 != 0:
                continue
            try:
                dec = base64.b64decode(raw, validate=False)
            except Exception:
                continue
            parsed = try_decode_json(dec)
            if parsed is None and len(dec) < 16:
                continue
            out.append(
                {
                    "source": path,
                    "kind": "embedded_base64",
                    "offset": m.start(),
                    "raw_b64": raw.decode("ascii", errors="replace"),
                    "decoded_json": parsed,
                    "decoded_size": len(dec),
                }
            )

        # Candidate C: embedded plaintext JSON text (common in Dump output).
        for m in text_pat.finditer(data):
            raw_txt = m.group(0)
            stripped = raw_txt.strip()
            if len(stripped) < 32:
                continue
            if stripped[:1] not in (b"{", b"["):
                continue
            try:
                txt = stripped.decode("utf-8")
            except Exception:
                continue
            try:
                parsed = json.loads(txt)
            except Exception:
                continue
            out.append(
                {
                    "source": path,
                    "kind": "embedded_json_text",
                    "offset": m.start(),
                    "as_string": txt,
                    "as_base64": base64.b64encode(stripped).decode("ascii"),
                    "decoded_json": parsed,
                    "decoded_size": len(stripped),
                }
            )

    return out


def _select_versions_payload(candidates: list[dict]) -> dict[str, Any] | list[Any] | None:
    for candidate in candidates:
        decoded = candidate.get("decoded_json")
        if isinstance(decoded, dict):
            if "list" in decoded:
                return {
                    "source": candidate.get("source"),
                    "kind": candidate.get("kind"),
                    "offset": candidate.get("offset"),
                    "list": decoded.get("list"),
                    "decoded_json": decoded,
                }
            if decoded:
                return {
                    "source": candidate.get("source"),
                    "kind": candidate.get("kind"),
                    "offset": candidate.get("offset"),
                    "list": decoded,
                    "decoded_json": decoded,
                }
        elif isinstance(decoded, list):
            return {
                "source": candidate.get("source"),
                "kind": candidate.get("kind"),
                "offset": candidate.get("offset"),
                "list": decoded,
                "decoded_json": decoded,
            }
    return None


def parse_blk_versions(input_path: str | Path, cryptohelper: str | Path | None = None) -> dict[str, Any]:
    in_path = Path(input_path)
    ch_path = Path(cryptohelper) if cryptohelper else None

    file_bytes = in_path.read_bytes()
    if ch_path is not None:
        keys = load_blb3_keys_from_crypthelper(ch_path)
    else:
        keys = load_blb3_keys_from_builtin()

    files, meta = parse_blb3(file_bytes, keys)
    candidates = scan_rawdata_candidates(files)
    versions = _select_versions_payload(candidates)
    versions_list = versions["list"] if isinstance(versions, dict) else None
    # Use the full original decoded JSON (e.g. {"list": [...]}) to preserve the
    # top-level structure exactly as it appears in the original file.
    versions_decoded = versions["decoded_json"] if isinstance(versions, dict) else None

    return {
        "input": str(in_path),
        "meta": meta,
        "inner_file_count": len(files),
        "inner_files": [path for path, _ in files],
        "rawdata_candidates": candidates,
        "versions": versions,
        "versions_list": versions_list,
        "versions_json": json.dumps(versions_decoded if versions_decoded is not None else None, ensure_ascii=False, indent=2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract RawData-like payloads from Genshin Blb3 files")
    parser.add_argument("input", help="Path to .blk/.blb file (Blb\\x03 format expected)")
    parser.add_argument("-o", "--output", help="Output JSON path", default="blb_rawdata_result.json")
    parser.add_argument(
        "--cryptohelper",
        required=False,
        default=None,
        help="Optional path to AnimeStudio CryptoHelper.cs (overrides built-in Blb3 key tables)",
    )
    parser.add_argument(
        "--dump-files-dir",
        help="Optional directory to dump extracted inner files",
        default=None,
    )
    args = parser.parse_args()

    in_path = Path(args.input)
    ch_path = Path(args.cryptohelper) if args.cryptohelper else None
    out_path = Path(args.output)

    file_bytes = in_path.read_bytes()
    if ch_path is not None:
        keys = load_blb3_keys_from_crypthelper(ch_path)
    else:
        keys = load_blb3_keys_from_builtin()

    files, meta = parse_blb3(file_bytes, keys)

    if args.dump_files_dir:
        dump_dir = Path(args.dump_files_dir)
        dump_dir.mkdir(parents=True, exist_ok=True)
        for rel, data in files:
            safe_rel = rel.replace("\\", "/").lstrip("/")
            target = dump_dir / safe_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    candidates = scan_rawdata_candidates(files)

    result = {
        "input": str(in_path),
        "meta": meta,
        "inner_file_count": len(files),
        "inner_files": [p for p, _ in files],
        "rawdata_candidates": candidates,
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Parsed {len(files)} inner files")
    print(f"[OK] Found {len(candidates)} RawData candidates")
    print(f"[OK] Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

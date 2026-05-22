from __future__ import annotations

import mmap
import struct
from pathlib import Path

from .exceptions import UsmFormatError
from .models import UsmChunk


def parse_usm_chunks(data: bytes | mmap.mmap) -> list[UsmChunk]:
    chunks: list[UsmChunk] = []
    offset = 0
    index = 0
    data_len = len(data)

    while offset + 32 <= data_len:
        header = data[offset:offset + 32]
        try:
            signature, data_size = struct.unpack(">II", header[:8])
            data_offset = header[9]
            padding_size = struct.unpack(">H", header[10:12])[0]
            chno = header[12]
            data_type = header[15]
            frame_time = struct.unpack(">I", header[16:20])[0]
            frame_rate = struct.unpack(">I", header[20:24])[0]
        except (IndexError, struct.error) as exc:
            raise UsmFormatError(f"bad USM header at 0x{offset:X}") from exc

        next_offset = offset + data_size + 8
        if data_size < 0x18 or next_offset > data_len:
            raise UsmFormatError(f"bad USM chunk at 0x{offset:X}: data_size={data_size}")

        payload_start = offset + 8 + data_offset
        payload_size = data_size - data_offset - padding_size
        payload_end = payload_start + payload_size
        if payload_size < 0 or payload_end > data_len:
            raise UsmFormatError(f"bad USM payload at 0x{offset:X}")

        chunks.append(
            UsmChunk(
                index=index,
                offset=offset,
                signature=signature,
                data_size=data_size,
                data_offset=data_offset,
                padding_size=padding_size,
                chno=chno,
                data_type=data_type,
                frame_time=frame_time,
                frame_rate=frame_rate,
                payload_start=payload_start,
                payload_size=payload_size,
            )
        )
        offset = next_offset
        index += 1

    return chunks


def collect_usm_inputs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".usm" else []

    files: list[Path] = []
    for path in input_path.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".usm":
            files.append(path)
    return sorted(files)


def sig_name(sig: int) -> str:
    try:
        return sig.to_bytes(4, "big").decode("ascii")
    except UnicodeDecodeError:
        return f"0x{sig:08X}"

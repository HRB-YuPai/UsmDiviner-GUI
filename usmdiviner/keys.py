from __future__ import annotations

from pathlib import Path

from .constants import KEY_MASK_56, ZERO_RESIDUE_KEY


_FILENAME_KEY_ALIASES = {
    "MDAQ001_OPNew_Part1",
    "MDAQ001_OPNew_Part2_PlayerBoy",
    "MDAQ001_OPNew_Part2_PlayerGirl",
}


def _filename_residue(filename: str | Path) -> int:
    base_name = Path(filename).stem
    if base_name in _FILENAME_KEY_ALIASES:
        base_name = "MDAQ001_OP"

    filename_key = 0
    for ch in base_name:
        filename_key = ord(ch) + 3 * filename_key
    filename_key &= KEY_MASK_56
    return filename_key or ZERO_RESIDUE_KEY


def _residue_56(value: int) -> int:
    return 0 if value == ZERO_RESIDUE_KEY else (value & KEY_MASK_56)


def full_key_int(key1: bytes, key2: bytes) -> int:
    return int.from_bytes(key1 + key2, "little")


def parse_full_key(text: str) -> int:
    value = text.strip().replace("_", "")
    if value.lower().startswith("0x"):
        value = value[2:]
    if not value or len(value) > 16:
        raise ValueError("key must be a 64-bit hexadecimal value")
    try:
        key = int(value, 16)
    except ValueError as exc:
        raise ValueError("key must be a 64-bit hexadecimal value") from exc
    if key < 0 or key > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("key must fit in 64 bits")
    return key


def split_full_key(usm_key: int) -> tuple[bytes, bytes]:
    key_bytes = usm_key.to_bytes(8, "little")
    return key_bytes[:4], key_bytes[4:]


def genshin_like_key(usm_key: int, filename: str | Path) -> int:
    """Recover the external 56-bit key residue implied by a file name."""
    filename_key = _filename_residue(filename)
    usm_residue = _residue_56(usm_key)
    filename_residue = _residue_56(filename_key)
    return (usm_residue - filename_residue) & KEY_MASK_56


def full_key_from_genshin_like_key(genshin_key: int, filename: str | Path) -> int:
    """Recover full USM key residue from external genshin-like key and file name."""
    filename_key = _filename_residue(filename)
    genshin_residue = _residue_56(genshin_key)
    filename_residue = _residue_56(filename_key)
    usm_residue = (genshin_residue + filename_residue) & KEY_MASK_56
    return usm_residue or ZERO_RESIDUE_KEY

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

from .exceptions import ExternalToolError
from .keys import full_key_int

logger = logging.getLogger(__name__)


def _normalize_arch(machine: str) -> str:
    arch = machine.lower().strip()
    if arch in {"x86_64", "amd64"}:
        return "x64"
    if arch in {"aarch64", "arm64"}:
        return "arm64"
    return arch


def _preferred_vgmstream_dirs() -> tuple[Path, ...]:
    system = platform.system().lower()
    arch = _normalize_arch(platform.machine())

    if system == "windows":
        return (
            Path("assets") / "tools" / "vgmstream" / "windows_x64",
            Path("vgmstream") / "windows_x64",
        )
    if system == "darwin":
        return (
            Path("assets") / "tools" / "vgmstream" / "macos",
            Path("vgmstream") / "macos",
        )
    if system == "linux":
        if arch == "arm64":
            return (
                Path("assets") / "tools" / "vgmstream" / "linux_arm64",
                Path("assets") / "tools" / "vgmstream" / "linux_x64",
                Path("vgmstream") / "linux_arm64",
                Path("vgmstream") / "linux_x64",
            )
        return (
            Path("assets") / "tools" / "vgmstream" / "linux_x64",
            Path("assets") / "tools" / "vgmstream" / "linux_arm64",
            Path("vgmstream") / "linux_x64",
            Path("vgmstream") / "linux_arm64",
        )
    return tuple()


def _preferred_ffmpeg_dirs() -> tuple[Path, ...]:
    system = platform.system().lower()
    arch = _normalize_arch(platform.machine())

    if system == "windows":
        return (
            Path("assets") / "tools" / "ffmpeg" / "windows_x64",
            Path("ffmpeg") / "windows_x64",
        )
    if system == "darwin":
        return (
            Path("assets") / "tools" / "ffmpeg" / "macos",
            Path("ffmpeg") / "macos",
        )
    if system == "linux":
        if arch == "arm64":
            return (
                Path("assets") / "tools" / "ffmpeg" / "linux_arm64",
                Path("assets") / "tools" / "ffmpeg" / "linux_x64",
                Path("ffmpeg") / "linux_arm64",
                Path("ffmpeg") / "linux_x64",
            )
        return (
            Path("assets") / "tools" / "ffmpeg" / "linux_x64",
            Path("assets") / "tools" / "ffmpeg" / "linux_arm64",
            Path("ffmpeg") / "linux_x64",
            Path("ffmpeg") / "linux_arm64",
        )
    return tuple()


def _existing_file(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path).expanduser()
    return str(p) if p.is_file() else None


def find_vgmstream(user_path: str | None) -> str | None:
    if user_path:
        return _existing_file(user_path)

    roots = [Path.cwd(), Path(__file__).resolve().parent.parent]
    names = ("vgmstream-cli.exe", "vgmstream-cli", "test.exe", "test", "vgmstream")

    # Prefer bundled binaries that match the current OS/arch.
    preferred_dirs = _preferred_vgmstream_dirs()
    for root in roots:
        for rel in preferred_dirs:
            for name in names:
                hit = _existing_file(root / rel / name)
                if hit:
                    return hit

    # Fallback to PATH for system-wide installations.
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit

    # Backward-compatibility for older project layouts.
    legacy_dirs = (
        Path("assets") / "tools" / "vgmstream",
        Path("vgmstream-win64"),
        Path("vgmstream"),
        Path("bin"),
        Path("tools") / "vgmstream",
    )
    for root in roots:
        for rel in legacy_dirs:
            for name in names:
                hit = _existing_file(root / rel / name)
                if hit:
                    return hit

    if os.name != "nt":
        for path in (
            "/usr/local/bin/vgmstream-cli",
            "/opt/homebrew/bin/vgmstream-cli",
            "/usr/bin/vgmstream-cli",
        ):
            hit = _existing_file(path)
            if hit:
                return hit
    return None


def find_ffmpeg(user_path: str | None) -> str | None:
    if user_path:
        return _existing_file(user_path)

    roots = [Path.cwd(), Path(__file__).resolve().parent.parent]
    names = ("ffmpeg.exe", "ffmpeg")

    # Prefer bundled ffmpeg that matches current OS/arch.
    preferred_dirs = _preferred_ffmpeg_dirs()
    for root in roots:
        for rel in preferred_dirs:
            for sub in (Path("."), Path("bin")):
                for name in names:
                    hit = _existing_file(root / rel / sub / name)
                    if hit:
                        return hit

    # Fallback to PATH for system-wide installations.
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit

    # Backward-compatibility for older layouts.
    legacy_dirs = (
        Path("assets") / "tools" / "ffmpeg",
        Path("ffmpeg"),
        Path("bin"),
        Path("tools") / "ffmpeg",
    )
    for root in roots:
        for rel in legacy_dirs:
            for sub in (Path("."), Path("bin")):
                for name in names:
                    hit = _existing_file(root / rel / sub / name)
                    if hit:
                        return hit

    if os.name != "nt":
        for path in (
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "/usr/bin/ffmpeg",
        ):
            hit = _existing_file(path)
            if hit:
                return hit
    return None


def write_hcakey_file(audio_path: Path, key1: bytes, key2: bytes) -> Path:
    key_bytes = full_key_int(key1, key2).to_bytes(8, "big")
    target = audio_path.with_suffix(audio_path.suffix + "key")
    target.write_bytes(key_bytes)
    return target


def remove_hcakey_files(directory: Path) -> None:
    for pattern in ("*.hcakey", ".hcakey"):
        for key_path in directory.glob(pattern):
            try:
                key_path.unlink()
            except OSError as exc:
                logger.debug("failed to remove %s: %s", key_path, exc)


def decode_with_vgmstream(
    vgmstream: str,
    input_path: Path,
    output_wav: Path,
    timeout: int = 120,
) -> tuple[bool, str]:
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [vgmstream, "-o", str(output_wav), str(input_path)]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExternalToolError(f"vgmstream failed: {exc}") from exc
    ok = proc.returncode == 0 and output_wav.exists() and output_wav.stat().st_size > 44
    return ok, proc.stdout[-4000:]


def mux_to_mkv(
    ffmpeg: str,
    video_path: Path,
    audio_inputs: list[Path],
    output_mkv: Path,
    timeout: int = 300,
) -> tuple[bool, str]:
    if not video_path.exists() or video_path.stat().st_size == 0:
        return False, "video stream does not exist"

    existing_audio = [p for p in audio_inputs if p.exists() and p.stat().st_size > 0]

    output_mkv.parent.mkdir(parents=True, exist_ok=True)
    _safe_unlink(output_mkv)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path)]
    for ap in existing_audio:
        cmd.extend(["-i", str(ap)])
    cmd.extend(["-map", "0:v:0"])
    for i in range(len(existing_audio)):
        cmd.extend(["-map", f"{i + 1}:a:0"])
    cmd.extend(["-c:v", "copy"])
    if existing_audio:
        cmd.extend(["-c:a", "flac"])
    cmd.append(str(output_mkv))

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _safe_unlink(output_mkv)
        raise ExternalToolError(f"ffmpeg failed: {exc}") from exc

    ok = proc.returncode == 0 and output_mkv.exists() and output_mkv.stat().st_size > 0
    if not ok:
        _safe_unlink(output_mkv)
    return ok, proc.stdout[-4000:]


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.debug("failed to remove %s: %s", path, exc)

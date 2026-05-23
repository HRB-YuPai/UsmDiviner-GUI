from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .exceptions import ExternalToolError
from .keys import full_key_int

logger = logging.getLogger(__name__)

ASS_DEFAULT_STYLE_HEADER = """[Script Info]
; This is an Advanced Sub Station Alpha v4+ script.
ScriptType: v4.00+
Collisions: Normal
ScaledBorderAndShadow: Yes
PlayDepth: 0
PlayResX: 384
PlayResY: 288

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,SDK_SC_Web,11.0,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,0,0.5,2,10,10,14,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

_SRT_TIME_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*$"
)


def _subtitle_font_file() -> Path | None:
    base = Path(__file__).resolve().parent.parent
    candidate = base / "assets" / "fonts" / "zh-cn.ttf"
    if candidate.is_file():
        return candidate
    return None


def _to_ass_time(seconds: float) -> str:
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    total -= hours * 3600
    minutes = int(total // 60)
    total -= minutes * 60
    secs = int(total)
    cs = int(round((total - secs) * 100))
    if cs >= 100:
        cs = 0
        secs += 1
    if secs >= 60:
        secs = 0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        hours += 1
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_escape_text(text: str) -> str:
    escaped = text.replace("\\", r"\\")
    escaped = escaped.replace("{", r"\{").replace("}", r"\}")
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    return escaped.replace("\n", r"\N")


def _parse_srt_time(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        return 0.0
    hour = int(parts[0])
    minute = int(parts[1])
    sec = float(parts[2])
    return hour * 3600.0 + minute * 60.0 + sec


def _convert_srt_to_ass(src: Path, dst: Path) -> bool:
    try:
        content = src.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False

    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n"))
    events: list[str] = []
    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if lines and lines[0].isdigit():
            lines = lines[1:]
        if len(lines) < 2:
            continue
        match = _SRT_TIME_RE.match(lines[0])
        if not match:
            continue
        start_raw = f"{match.group(1)}:{match.group(2)}:{match.group(3)}.{match.group(4)}"
        end_raw = f"{match.group(5)}:{match.group(6)}:{match.group(7)}.{match.group(8)}"
        start = _to_ass_time(_parse_srt_time(start_raw))
        end = _to_ass_time(_parse_srt_time(end_raw))
        text = _ass_escape_text("\n".join(lines[1:]))
        if not text:
            continue
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    if not events:
        return False

    try:
        dst.write_text(ASS_DEFAULT_STYLE_HEADER + "\n".join(events) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _convert_txt_to_ass(src: Path, dst: Path) -> bool:
    try:
        content = src.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False

    lines = [line.strip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return False

    events: list[str] = []
    per_line_seconds = 3.0
    for idx, line in enumerate(lines):
        start = _to_ass_time(idx * per_line_seconds)
        end = _to_ass_time((idx + 1) * per_line_seconds)
        text = _ass_escape_text(line)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    try:
        dst.write_text(ASS_DEFAULT_STYLE_HEADER + "\n".join(events) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _ensure_ass_subtitle(src: Path, work_dir: Path) -> Path | None:
    ext = src.suffix.lower()
    if ext == ".ass":
        return src
    target = work_dir / f"{src.stem}.converted.ass"
    if ext == ".srt":
        return target if _convert_srt_to_ass(src, target) else None
    if ext == ".txt":
        return target if _convert_txt_to_ass(src, target) else None
    return None


def _subtitle_codec_for_path(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == ".ass":
        return "ass"
    if ext == ".srt":
        return "srt"
    return None


def _escape_sub_filter_path(path: Path) -> str:
    text = str(path)
    text = text.replace("\\", "\\\\")
    text = text.replace(":", r"\:")
    text = text.replace("'", r"\'")
    text = text.replace(",", r"\,")
    return text


def _subtitle_burn_filter(subtitle_ass: Path, font_file: Path) -> str:
    subtitle_expr = _escape_sub_filter_path(subtitle_ass)
    fontsdir_expr = _escape_sub_filter_path(font_file.parent)
    return f"subtitles='{subtitle_expr}':fontsdir='{fontsdir_expr}':force_style='Fontname=SDK_SC_Web'"


def _video_input_ffmpeg_args(video_path: Path) -> list[str]:
    ext = video_path.suffix.lower()
    if ext in {".264", ".h264"}:
        return ["-f", "h264"]
    if ext == ".m1v":
        return ["-f", "mpegvideo"]
    if ext == ".ivf":
        return ["-f", "ivf"]
    return []


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


def _run_ffmpeg_command(
    ffmpeg: str,
    cmd: list[str],
    output_path: Path,
    timeout: int,
    error_prefix: str,
) -> tuple[bool, str]:
    ffmpeg_cwd = None
    env = os.environ.copy()
    try:
        ffmpeg_dir = Path(ffmpeg).resolve().parent
        ffmpeg_cwd = str(ffmpeg_dir)
        runtime_dirs = [ffmpeg_dir]

        parent_lib = ffmpeg_dir.parent / "lib"
        if parent_lib.is_dir():
            runtime_dirs.append(parent_lib)

        if os.name == "nt":
            env["PATH"] = os.pathsep.join([str(path) for path in runtime_dirs] + [env.get("PATH", "")])
        elif sys.platform == "darwin":
            env["DYLD_LIBRARY_PATH"] = os.pathsep.join(
                [str(path) for path in runtime_dirs] + ([env["DYLD_LIBRARY_PATH"]] if env.get("DYLD_LIBRARY_PATH") else [])
            )
        else:
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                [str(path) for path in runtime_dirs] + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else [])
            )
    except OSError:
        ffmpeg_cwd = None

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            cwd=ffmpeg_cwd,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _safe_unlink(output_path)
        raise ExternalToolError(f"{error_prefix}: {exc}") from exc

    ok = proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
    if not ok:
        _safe_unlink(output_path)
    return ok, proc.stdout[-4000:]


def mux_to_mkv(
    ffmpeg: str,
    video_path: Path,
    audio_inputs: list[Path],
    subtitle_inputs: list[tuple[Path, str]] | None,
    output_mkv: Path,
    convert_subtitles_to_ass: bool = True,
    timeout: int = 300,
) -> tuple[bool, str]:
    if not video_path.exists() or video_path.stat().st_size == 0:
        return False, "video stream does not exist"

    existing_audio = [p for p in audio_inputs if p.exists() and p.stat().st_size > 0]
    existing_subtitles = [
        (p, str(lang or "").strip())
        for p, lang in (subtitle_inputs or [])
        if p.exists() and p.stat().st_size > 0
    ]

    output_mkv.parent.mkdir(parents=True, exist_ok=True)
    _safe_unlink(output_mkv)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    cmd.extend(_video_input_ffmpeg_args(video_path))
    cmd.extend(["-i", str(video_path)])
    for ap in existing_audio:
        cmd.extend(["-i", str(ap)])
    cmd.extend(["-map", "0:v:0"])
    for i in range(len(existing_audio)):
        cmd.extend(["-map", f"{i + 1}:a:0"])

    # Burn one subtitle track using libass + bundled font for deterministic rendering.
    subtitle_path = existing_subtitles[0][0] if existing_subtitles else None
    if subtitle_path is not None:
        font_file = _subtitle_font_file()
        if font_file is None:
            return False, "required subtitle font not found: assets/fonts/zh-cn.ttf"
        if convert_subtitles_to_ass:
            with tempfile.TemporaryDirectory(prefix="usmdiviner_ass_") as tmp:
                ass_path = _ensure_ass_subtitle(subtitle_path, Path(tmp))
                if ass_path is None:
                    return False, f"failed to convert subtitle to ASS: {subtitle_path.name}"
                cmd.extend(["-vf", _subtitle_burn_filter(ass_path, font_file)])
                cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
                if existing_audio:
                    cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
                cmd.append(str(output_mkv))
                return _run_ffmpeg_command(ffmpeg, cmd, output_mkv, timeout, "ffmpeg failed")

        cmd.extend(["-vf", _subtitle_burn_filter(subtitle_path, font_file)])
        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
        if existing_audio:
            cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
        cmd.append(str(output_mkv))
        return _run_ffmpeg_command(ffmpeg, cmd, output_mkv, timeout, "ffmpeg failed")

    cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
    if existing_audio:
        cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
    cmd.append(str(output_mkv))

    return _run_ffmpeg_command(ffmpeg, cmd, output_mkv, timeout, "ffmpeg failed")


def mux_to_mkv_soft(
    ffmpeg: str,
    video_path: Path,
    audio_inputs: list[Path],
    subtitle_inputs: list[tuple[Path, str]] | None,
    output_mkv: Path,
    default_sub_lang: str = "",
    convert_subtitles_to_ass: bool = True,
    timeout: int = 300,
) -> tuple[bool, str]:
    if not video_path.exists() or video_path.stat().st_size == 0:
        return False, "video stream does not exist"

    existing_audio = [p for p in audio_inputs if p.exists() and p.stat().st_size > 0]
    existing_subtitles = [
        (p, str(lang or "").strip().upper())
        for p, lang in (subtitle_inputs or [])
        if p.exists() and p.stat().st_size > 0
    ]

    output_mkv.parent.mkdir(parents=True, exist_ok=True)
    _safe_unlink(output_mkv)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    cmd.extend(_video_input_ffmpeg_args(video_path))
    cmd.extend(["-i", str(video_path)])
    for ap in existing_audio:
        cmd.extend(["-i", str(ap)])

    with tempfile.TemporaryDirectory(prefix="usmdiviner_softass_") as tmp:
        tmp_dir = Path(tmp)
        prepared_subs: list[tuple[Path, str, str | None]] = []
        for src, lang in existing_subtitles:
            if convert_subtitles_to_ass:
                ass_path = _ensure_ass_subtitle(src, tmp_dir)
                if ass_path is not None and ass_path.exists():
                    prepared_subs.append((ass_path, lang, "ass"))
            else:
                prepared_subs.append((src, lang, _subtitle_codec_for_path(src)))

        for sub_path, _, _ in prepared_subs:
            cmd.extend(["-i", str(sub_path)])

        cmd.extend(["-map", "0:v:0"])
        for i in range(len(existing_audio)):
            cmd.extend(["-map", f"{i + 1}:a:0"])
        subtitle_start = 1 + len(existing_audio)
        for i in range(len(prepared_subs)):
            cmd.extend(["-map", f"{subtitle_start + i}:s:0"])

        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
        if existing_audio:
            cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
        if prepared_subs:
            if convert_subtitles_to_ass:
                cmd.extend(["-c:s", "ass"])
            else:
                for idx, (_, _, codec) in enumerate(prepared_subs):
                    if codec:
                        cmd.extend([f"-c:s:{idx}", codec])
            wanted = str(default_sub_lang or "").strip().upper()
            for idx, (_, lang, _) in enumerate(prepared_subs):
                if lang:
                    cmd.extend([f"-metadata:s:s:{idx}", f"language={lang.lower()}"])
                default_flag = "1" if wanted and lang == wanted else "0"
                cmd.extend([f"-disposition:s:{idx}", f"default={default_flag}"])
            font_file = _subtitle_font_file()
            if font_file and font_file.exists() and (convert_subtitles_to_ass or any(codec == "ass" for _, _, codec in prepared_subs)):
                cmd.extend(["-attach", str(font_file), "-metadata:s:t:0", "mimetype=application/x-truetype-font"])

        cmd.append(str(output_mkv))
        return _run_ffmpeg_command(ffmpeg, cmd, output_mkv, timeout, "ffmpeg failed")


def transcode_mkv_to_mp4(
    ffmpeg: str,
    input_mkv: Path,
    output_mp4: Path,
    subtitle_input: Path | None = None,
    timeout: int = 600,
) -> tuple[bool, str]:
    if not input_mkv.exists() or input_mkv.stat().st_size == 0:
        return False, "mkv input does not exist"

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    _safe_unlink(output_mp4)

    def _build_cmd(subtitle_filter: str | None) -> list[str]:
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_mkv),
        ]
        if subtitle_filter:
            cmd.extend(["-vf", subtitle_filter])
        cmd.extend([
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "10",
            "-c:a",
            "mp3",
            "-b:a",
            "1411k",
            str(output_mp4),
        ])
        return cmd

    if subtitle_input is not None:
        if not subtitle_input.exists() or subtitle_input.stat().st_size <= 0:
            return False, "subtitle input does not exist"
        font_file = _subtitle_font_file()
        if font_file is None:
            return False, "required subtitle font not found: assets/fonts/zh-cn.ttf"
        with tempfile.TemporaryDirectory(prefix="usmdiviner_ass_") as tmp:
            ass_path = _ensure_ass_subtitle(subtitle_input, Path(tmp))
            if ass_path is None:
                return False, f"failed to convert subtitle to ASS: {subtitle_input.name}"
            cmd = _build_cmd(_subtitle_burn_filter(ass_path, font_file))
            return _run_ffmpeg_command(ffmpeg, cmd, output_mp4, timeout, "ffmpeg mp4 transcode failed")

    return _run_ffmpeg_command(ffmpeg, _build_cmd(None), output_mp4, timeout, "ffmpeg mp4 transcode failed")


def transcode_ivf_to_mp4(
    ffmpeg: str,
    video_path: Path,
    audio_inputs: list[Path],
    subtitle_inputs: list[tuple[Path, str]] | None,
    output_mp4: Path,
    convert_subtitles_to_ass: bool = True,
    timeout: int = 600,
) -> tuple[bool, str]:
    if not video_path.exists() or video_path.stat().st_size == 0:
        return False, "video stream does not exist"

    existing_audio = [p for p in audio_inputs if p.exists() and p.stat().st_size > 0]
    existing_subtitles = [
        (p, str(lang or "").strip())
        for p, lang in (subtitle_inputs or [])
        if p.exists() and p.stat().st_size > 0
    ]

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    _safe_unlink(output_mp4)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    cmd.extend(_video_input_ffmpeg_args(video_path))
    cmd.extend(["-i", str(video_path)])
    for ap in existing_audio:
        cmd.extend(["-i", str(ap)])
    cmd.extend(["-map", "0:v:0"])
    for i in range(len(existing_audio)):
        cmd.extend(["-map", f"{i + 1}:a:0"])

    subtitle_path = existing_subtitles[0][0] if existing_subtitles else None
    if subtitle_path is not None:
        font_file = _subtitle_font_file()
        if font_file is None:
            return False, "required subtitle font not found: assets/fonts/zh-cn.ttf"
        if convert_subtitles_to_ass:
            with tempfile.TemporaryDirectory(prefix="usmdiviner_ass_") as tmp:
                ass_path = _ensure_ass_subtitle(subtitle_path, Path(tmp))
                if ass_path is None:
                    return False, f"failed to convert subtitle to ASS: {subtitle_path.name}"
                cmd.extend(["-vf", _subtitle_burn_filter(ass_path, font_file)])
                cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
                if existing_audio:
                    cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
                cmd.append(str(output_mp4))
                return _run_ffmpeg_command(ffmpeg, cmd, output_mp4, timeout, "ffmpeg mp4 transcode failed")

        cmd.extend(["-vf", _subtitle_burn_filter(subtitle_path, font_file)])
        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
        if existing_audio:
            cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
        cmd.append(str(output_mp4))
        return _run_ffmpeg_command(ffmpeg, cmd, output_mp4, timeout, "ffmpeg mp4 transcode failed")

    cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
    if existing_audio:
        cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
    cmd.append(str(output_mp4))
    return _run_ffmpeg_command(ffmpeg, cmd, output_mp4, timeout, "ffmpeg mp4 transcode failed")


def transcode_ivf_to_mp4_soft(
    ffmpeg: str,
    video_path: Path,
    audio_inputs: list[Path],
    subtitle_inputs: list[tuple[Path, str]] | None,
    output_mp4: Path,
    default_sub_lang: str = "",
    convert_subtitles_to_ass: bool = True,
    timeout: int = 600,
) -> tuple[bool, str]:
    if not video_path.exists() or video_path.stat().st_size == 0:
        return False, "video stream does not exist"

    existing_audio = [p for p in audio_inputs if p.exists() and p.stat().st_size > 0]
    existing_subtitles = [
        (p, str(lang or "").strip().upper())
        for p, lang in (subtitle_inputs or [])
        if p.exists() and p.stat().st_size > 0
    ]

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    _safe_unlink(output_mp4)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    cmd.extend(_video_input_ffmpeg_args(video_path))
    cmd.extend(["-i", str(video_path)])
    for ap in existing_audio:
        cmd.extend(["-i", str(ap)])

    with tempfile.TemporaryDirectory(prefix="usmdiviner_movtext_") as tmp:
        tmp_dir = Path(tmp)
        prepared_subs: list[tuple[Path, str]] = []
        for src, lang in existing_subtitles:
            if convert_subtitles_to_ass:
                ass_path = _ensure_ass_subtitle(src, tmp_dir)
                if ass_path is not None and ass_path.exists():
                    prepared_subs.append((ass_path, lang))
            else:
                prepared_subs.append((src, lang))

        for sp, _ in prepared_subs:
            cmd.extend(["-i", str(sp)])

        cmd.extend(["-map", "0:v:0"])
        for i in range(len(existing_audio)):
            cmd.extend(["-map", f"{i + 1}:a:0"])
        subtitle_start = 1 + len(existing_audio)
        for i in range(len(prepared_subs)):
            cmd.extend(["-map", f"{subtitle_start + i}:s:0"])

        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "10"])
        if existing_audio:
            cmd.extend(["-c:a", "mp3", "-b:a", "1411k"])
        if prepared_subs:
            cmd.extend(["-c:s", "mov_text"])
            wanted = str(default_sub_lang or "").strip().upper()
            for idx, (_, lang) in enumerate(prepared_subs):
                if lang:
                    cmd.extend([f"-metadata:s:s:{idx}", f"language={lang.lower()}"])
                default_flag = "1" if wanted and lang == wanted else "0"
                cmd.extend([f"-disposition:s:{idx}", f"default={default_flag}"])

        cmd.append(str(output_mp4))
        return _run_ffmpeg_command(ffmpeg, cmd, output_mp4, timeout, "ffmpeg mp4 transcode failed")


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.debug("failed to remove %s: %s", path, exc)

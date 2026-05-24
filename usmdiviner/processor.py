from __future__ import annotations

import json
import logging
import mmap
from collections import defaultdict
from pathlib import Path

from .audio import decide_audio_for_channel
from .constants import (
    AUDIO_PROBE_BYTES_PER_CHANNEL,
    SOLVER_BEAM,
    SOLVER_L1_BEAM,
    FAST_CRACK_VIDEO_BYTES,
    SIG_SFA,
    SIG_SFV,
)
from .crack import crack_keys_from_usm
from .exceptions import ExternalToolError, KeyCrackError
from .formats import classify_audio, detect_video_stream
from .keys import full_key_int, genshin_like_key, split_full_key
from .masks import make_masks, unmask_audio_payload, unmask_video_payload
from .models import AudioDecision, ProcessOptions, UsmChunk
from .tools import (
    decode_with_vgmstream,
    find_ffmpeg,
    find_vgmstream,
    mux_to_mkv,
    remove_hcakey_files,
    transcode_ivf_to_mp4,
    write_hcakey_file,
)
from .usm import parse_usm_chunks

logger = logging.getLogger(__name__)

_REPORT_FOLDER_BY_LANG = {
    "zh-cn": "USM_解密报告",
    "zh-tw": "USM_解密報告",
    "en": "USM_Decryption_Reports",
}


def _should_write_report(usm_path: Path, opt: ProcessOptions) -> bool:
    if opt.write_report:
        return True
    selected = opt.report_selected_files or ()
    if not selected:
        return False
    path_key = str(usm_path.resolve())
    return path_key in selected


def process_one(
    usm_path_str: str,
    opt: ProcessOptions,
    progress_callback=None,
) -> dict:
    usm_path = Path(usm_path_str)
    base = usm_path.stem
    out_dir = _make_output_dir(usm_path, opt)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("[%s] start process_one: extract_only=%s fast=%s mux_mkv=%s output=%s", usm_path.name, opt.extract_only, opt.fast, opt.mux_mkv, out_dir)
    _emit_progress(progress_callback, 4)

    if usm_path.stat().st_size == 0:
        raise KeyCrackError({"reason": "empty USM file"})

    if opt.extract_only:
        logger.debug("[%s] extract-only mode enabled", usm_path.name)
        _emit_progress(progress_callback, 12)
        with usm_path.open("rb") as fp, mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ) as data:
            chunks = parse_usm_chunks(data)
            logger.debug("[%s] parsed chunks: total=%s", usm_path.name, len(chunks))
            video_path, video_info, audio_paths, audio_info = _demux_raw_streams(
                data,
                chunks,
                out_dir,
                base,
            )
        logger.debug("[%s] raw demux done: video=%s audio_channels=%s", usm_path.name, video_path, len(audio_paths))
        _emit_progress(progress_callback, 70)
        report = _build_extract_report(
            usm_path,
            out_dir,
            chunks,
            video_path,
            video_info,
            audio_paths,
            audio_info,
        )
        if _should_write_report(usm_path, opt):
            report_path = _resolve_report_path(usm_path, opt)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            report["report_written"] = True
            report["report_path"] = str(report_path)
        else:
            report["report_written"] = False
            report["report_path"] = None
        _emit_progress(progress_callback, 100)
        return report

    if opt.manual_key is not None:
        key1, key2 = split_full_key(opt.manual_key)
        crack_stats = {"skipped": True, "reason": "manual key supplied"}
        logger.debug("[%s] using manual key", usm_path.name)
        _emit_progress(progress_callback, 28)
    else:
        _emit_progress(progress_callback, 18)
        try:
            key1, key2, crack_stats = _crack_key(usm_path, opt.fast)
        except KeyCrackError as exc:
            logger.debug("[%s] key crack skipped: %s", usm_path.name, exc.args[0])
            _emit_progress(progress_callback, 100)
            return _skip_report(usm_path, out_dir, crack_stats=exc.args[0], opt=opt)
        logger.debug("[%s] key crack done: key1=%s key2=%s stats=%s", usm_path.name, key1.hex().upper(), key2.hex().upper(), crack_stats)
        _emit_progress(progress_callback, 38)

    video_mask1, video_mask2, audio_mask = make_masks(key1, key2)

    with usm_path.open("rb") as fp, mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ) as data:
        chunks = parse_usm_chunks(data)
        logger.debug("[%s] parsed chunks: total=%s video=%s audio=%s", usm_path.name, len(chunks), sum(1 for c in chunks if c.signature == SIG_SFV and c.data_type == 0), sum(1 for c in chunks if c.signature == SIG_SFA and c.data_type == 0))
        audio_payloads = _collect_audio_probe_payloads(data, chunks)
        logger.debug("[%s] collected probe payloads for channels=%s", usm_path.name, sorted(audio_payloads.keys()))

        vgmstream = find_vgmstream(opt.vgmstream)
        logger.debug("[%s] vgmstream resolved: %s", usm_path.name, vgmstream)
        audio_decisions: dict[int, AudioDecision] = {}
        for ch, payloads in audio_payloads.items():
            decision, _ = decide_audio_for_channel(
                ch,
                payloads,
                audio_mask,
                key1,
                key2,
                vgmstream,
                opt.adx_audio_mask,
            )
            audio_decisions[ch] = decision
            logger.debug("[%s] audio decision ch%s: format=%s use_mask=%s confidence=%s reason=%s", usm_path.name, ch, decision.format, decision.use_audio_mask, decision.confidence, decision.reason)

        video_path, video_info, audio_paths = _demux_streams(
            data,
            chunks,
            out_dir,
            base,
            video_mask1,
            video_mask2,
            audio_mask,
            audio_decisions,
        )
    logger.debug("[%s] demux done: video=%s video_fmt=%s audio_files=%s", usm_path.name, video_path, video_info.get("format"), len(audio_paths))
    _emit_progress(progress_callback, 62)

    decoded = _decode_audio(audio_paths, audio_decisions, vgmstream, key1, key2)
    logger.debug("[%s] decode summary: decoded_channels=%s", usm_path.name, sum(1 for d in decoded.values() if d.get("ok")))
    _emit_progress(progress_callback, 78)
    mkv_path = _make_mkv_path(usm_path, opt)
    mp4_path = _make_mp4_path(usm_path, opt)
    mux_report, mux_success = _maybe_mux(
        opt,
        video_path,
        audio_paths,
        audio_decisions,
        decoded,
        mkv_path,
        mp4_path,
    )
    logger.debug("[%s] mux summary: success=%s report=%s", usm_path.name, mux_success, mux_report)
    # Do not auto-clean extracted artifacts during processing.
    # Files are cleaned in one explicit exit-time cleanup flow from the GUI.
    logger.debug("[%s] auto cleanup skipped: mux_success=%s keep_audio=%s", usm_path.name, mux_success, opt.keep_intermediate_audio)
    _emit_progress(progress_callback, 90)

    report = _build_report(
        usm_path,
        out_dir,
        key1,
        key2,
        crack_stats,
        chunks,
        video_path,
        video_info,
        audio_paths,
        audio_decisions,
        decoded,
        mux_report,
    )
    if opt.manual_key is not None:
        report["manual_key"] = True
    if _should_write_report(usm_path, opt):
        report_path = _resolve_report_path(usm_path, opt)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report["report_written"] = True
        report["report_path"] = str(report_path)
        logger.debug("[%s] report written: %s", usm_path.name, report_path)
    else:
        report["report_written"] = False
        report["report_path"] = None
    logger.debug("[%s] process_one done", usm_path.name)
    _emit_progress(progress_callback, 100)
    return report


def _emit_progress(callback, value: int) -> None:
    if callback is None:
        return
    try:
        callback(int(max(0, min(100, value))))
    except Exception:
        # Progress reporting should never break processing.
        return


def _make_mkv_path(usm_path: Path, opt: ProcessOptions) -> Path:
    output_root = Path(opt.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    base = usm_path.stem
    rel_hint = ""
    if opt.input_root:
        try:
            rel = usm_path.resolve().relative_to(Path(opt.input_root).resolve())
            rel_parent = rel.parent
            if rel_parent.parts:
                rel_hint = "__".join(rel_parent.parts)
        except ValueError:
            rel_hint = ""

    file_name = f"{base}.mkv" if not rel_hint else f"{base}__{rel_hint}.mkv"
    return output_root / file_name


def _make_mp4_path(usm_path: Path, opt: ProcessOptions) -> Path:
    output_root = Path(opt.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    base = usm_path.stem
    rel_hint = ""
    if opt.input_root:
        try:
            rel = usm_path.resolve().relative_to(Path(opt.input_root).resolve())
            rel_parent = rel.parent
            if rel_parent.parts:
                rel_hint = "__".join(rel_parent.parts)
        except ValueError:
            rel_hint = ""

    file_name = f"{base}.mp4" if not rel_hint else f"{base}__{rel_hint}.mp4"
    return output_root / file_name


def _make_output_dir(usm_path: Path, opt: ProcessOptions) -> Path:
    output_root = Path(opt.output_dir)
    if not opt.input_root:
        return output_root / usm_path.stem

    try:
        rel = usm_path.resolve().relative_to(Path(opt.input_root).resolve())
    except ValueError:
        rel = Path(usm_path.name)
    return output_root / rel.with_suffix("")


def _crack_key(usm_path: Path, fast: bool) -> tuple[bytes, bytes, dict]:
    logger.debug("[%s] crack start: fast=%s beam=%s l1_beam=%s", usm_path.name, fast, SOLVER_BEAM, SOLVER_L1_BEAM)
    key1, key2, crack_stats = crack_keys_from_usm(
        usm_path,
        max_video_bytes=FAST_CRACK_VIDEO_BYTES if fast else None,
        beam_size=SOLVER_BEAM,
        l1_beam_size=SOLVER_L1_BEAM,
    )
    if key1 is None or key2 is None:
        raise KeyCrackError(crack_stats)
    return key1, key2, crack_stats


def _skip_report(usm_path: Path, out_dir: Path, crack_stats: dict, opt: ProcessOptions) -> dict:
    report = {
        "file": str(usm_path),
        "status": "skipped",
        "output_dir": str(out_dir),
        "reason": crack_stats.get("reason", "key recovery failed"),
        "crack": crack_stats,
    }
    if _should_write_report(usm_path, opt):
        report_path = _resolve_report_path(usm_path, opt=opt)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report["report_written"] = True
        report["report_path"] = str(report_path)
    else:
        report["report_written"] = False
        report["report_path"] = None
    return report


def _resolve_report_path(usm_path: Path, opt: ProcessOptions | None) -> Path:
    custom_dir = opt.report_dir if opt else None
    if custom_dir:
        report_root = Path(custom_dir)
    else:
        lang = opt.report_language if opt else "en"
        folder_name = _REPORT_FOLDER_BY_LANG.get(lang.lower(), _REPORT_FOLDER_BY_LANG["en"])
        report_root = usm_path.parent / folder_name

    report_root.mkdir(parents=True, exist_ok=True)
    candidate = report_root / f"{usm_path.stem}_Report.json"
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        numbered = report_root / f"{usm_path.stem}_Report_{index}.json"
        if not numbered.exists():
            return numbered
        index += 1


def _collect_audio_probe_payloads(data, chunks: list[UsmChunk]) -> dict[int, list[bytes]]:
    payloads: dict[int, list[bytes]] = defaultdict(list)
    remaining: dict[int, int] = defaultdict(lambda: AUDIO_PROBE_BYTES_PER_CHANNEL)

    for chunk in chunks:
        if chunk.signature != SIG_SFA or chunk.data_type != 0 or chunk.payload_size <= 0:
            continue
        left = remaining[chunk.chno]
        if left <= 0:
            continue
        take = min(chunk.payload_size, left)
        payloads[chunk.chno].append(data[chunk.payload_start:chunk.payload_start + take])
        remaining[chunk.chno] -= take
    return payloads


def _demux_streams(
    data,
    chunks: list[UsmChunk],
    out_dir: Path,
    base: str,
    video_mask1: bytes,
    video_mask2: bytes,
    audio_mask: bytes,
    audio_decisions: dict[int, AudioDecision],
) -> tuple[Path | None, dict, dict[int, Path]]:
    logger.debug("demux start: out_dir=%s base=%s decisions=%s", out_dir, base, {ch: {"format": d.format, "mask": d.use_audio_mask} for ch, d in audio_decisions.items()})
    temp_video_path = out_dir / f"{base}.video.tmp"
    audio_fps: dict[int, object] = {}
    audio_paths: dict[int, Path] = {}

    with temp_video_path.open("wb") as video_fp:
        try:
            for chunk in chunks:
                payload = data[chunk.payload_start:chunk.payload_end]
                if chunk.signature == SIG_SFV and chunk.data_type == 0:
                    video_fp.write(unmask_video_payload(payload, video_mask1, video_mask2))
                elif chunk.signature == SIG_SFA and chunk.data_type == 0:
                    decision = audio_decisions.get(chunk.chno)
                    if not decision:
                        continue
                    out_payload = (
                        unmask_audio_payload(payload, audio_mask)
                        if decision.use_audio_mask
                        else payload
                    )
                    ext = decision.format if decision.format in ("hca", "adx") else "bin"
                    if chunk.chno not in audio_fps:
                        audio_path = out_dir / f"{base}_ch{chunk.chno}.{ext}"
                        audio_paths[chunk.chno] = audio_path
                        audio_fps[chunk.chno] = audio_path.open("wb")
                    audio_fps[chunk.chno].write(out_payload)
        finally:
            for fp in audio_fps.values():
                fp.close()

    video_path, video_info = _finalize_video_temp(temp_video_path, out_dir, base)
    logger.debug("demux end: video=%s info=%s audio_channels=%s", video_path, video_info, len(audio_paths))
    return video_path, video_info, audio_paths


def _demux_raw_streams(
    data,
    chunks: list[UsmChunk],
    out_dir: Path,
    base: str,
) -> tuple[Path | None, dict, dict[int, Path], dict[int, dict]]:
    temp_video_path = out_dir / f"{base}.video.tmp"
    audio_fps: dict[int, object] = {}
    temp_audio_paths: dict[int, Path] = {}

    with temp_video_path.open("wb") as video_fp:
        try:
            for chunk in chunks:
                payload = data[chunk.payload_start:chunk.payload_end]
                if chunk.signature == SIG_SFV and chunk.data_type == 0:
                    video_fp.write(payload)
                elif chunk.signature == SIG_SFA and chunk.data_type == 0:
                    if chunk.chno not in audio_fps:
                        audio_path = out_dir / f"{base}_ch{chunk.chno}.audio.tmp"
                        temp_audio_paths[chunk.chno] = audio_path
                        audio_fps[chunk.chno] = audio_path.open("wb")
                    audio_fps[chunk.chno].write(payload)
        finally:
            for fp in audio_fps.values():
                fp.close()

    video_path, video_info = _finalize_video_temp(temp_video_path, out_dir, base)
    audio_paths: dict[int, Path] = {}
    audio_info: dict[int, dict] = {}
    for ch, temp_path in sorted(temp_audio_paths.items()):
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            _safe_unlink(temp_path)
            continue
        with temp_path.open("rb") as fp:
            cls = classify_audio(fp.read(4096))
        fmt = cls.get("format") or "unknown"
        ext = fmt if fmt in ("hca", "adx") else "bin"
        audio_path = out_dir / f"{base}_ch{ch}.{ext}"
        if audio_path.exists():
            audio_path.unlink()
        temp_path.rename(audio_path)
        audio_paths[ch] = audio_path
        audio_info[ch] = {"format": fmt, "path": str(audio_path), "raw": True}
    return video_path, video_info, audio_paths, audio_info


def _finalize_video_temp(
    temp_video_path: Path,
    out_dir: Path,
    base: str,
) -> tuple[Path | None, dict]:
    if not temp_video_path.exists() or temp_video_path.stat().st_size == 0:
        _safe_unlink(temp_video_path)
        return None, {"format": "none", "extension": None, "codec": None, "magic": ""}

    with temp_video_path.open("rb") as fp:
        video_info = detect_video_stream(fp.read(4096))
    ext = video_info.get("extension") or "bin"
    video_path = out_dir / f"{base}.{ext}"
    if video_path.exists():
        video_path.unlink()
    temp_video_path.rename(video_path)
    return video_path, video_info


def _decode_audio(
    audio_paths: dict[int, Path],
    audio_decisions: dict[int, AudioDecision],
    vgmstream: str | None,
    key1: bytes,
    key2: bytes,
) -> dict[int, dict]:
    decoded: dict[int, dict] = {}
    for ch, audio_path in audio_paths.items():
        decision = audio_decisions[ch]
        logger.debug("decode start ch%s: path=%s format=%s", ch, audio_path, decision.format)
        if decision.format == "hca":
            write_hcakey_file(audio_path, key1, key2)
            logger.debug("decode ch%s: wrote hcakey file", ch)
        if not vgmstream:
            logger.debug("decode ch%s: skipped, vgmstream missing", ch)
            continue
        wav_path = audio_path.with_suffix(".wav")
        try:
            ok, log = decode_with_vgmstream(vgmstream, audio_path, wav_path)
        except ExternalToolError as exc:
            logger.warning("audio decode failed for %s: %s", audio_path.name, exc)
            decoded[ch] = {"ok": False, "wav": None, "log_tail": str(exc)}
            continue
        decoded[ch] = {"ok": ok, "wav": str(wav_path) if ok else None, "log_tail": log[-1000:]}
        logger.debug("decode end ch%s: ok=%s wav=%s", ch, ok, decoded[ch].get("wav"))
    return decoded


def _maybe_mux(
    opt: ProcessOptions,
    video_path: Path | None,
    audio_paths: dict[int, Path],
    audio_decisions: dict[int, AudioDecision],
    decoded: dict[int, dict],
    mkv_path: Path,
    mp4_path: Path,
) -> tuple[dict | None, bool]:
    logger.debug("mux start: enabled=%s video=%s", opt.mux_mkv, video_path)
    if not opt.mux_mkv:
        return None, False
    if not video_path:
        return {
            "ok": False,
            "mkv": None,
            "mp4": None,
            "log_tail": "video stream not found; MP4 not created",
        }, False

    mux_audio_inputs: list[Path] = []
    for ch, audio_path in sorted(audio_paths.items()):
        dec = decoded.get(ch) or {}
        if dec.get("ok") and dec.get("wav"):
            mux_audio_inputs.append(Path(dec["wav"]))
        elif audio_decisions[ch].format == "adx":
            mux_audio_inputs.append(audio_path)

    ffmpeg = find_ffmpeg(opt.ffmpeg)
    logger.debug("mux ffmpeg=%s audio_inputs=%s", ffmpeg, [str(p) for p in mux_audio_inputs])
    if not ffmpeg:
        return {"ok": False, "mkv": None, "mp4": None, "log_tail": "ffmpeg not found"}, False

    try:
        mp4_ok, mp4_log = transcode_ivf_to_mp4(ffmpeg, video_path, mux_audio_inputs, None, mp4_path)
    except ExternalToolError as exc:
        logger.warning("mp4 direct export failed for %s: %s", video_path.name, exc)
        mp4_ok = False
        mp4_log = str(exc)

    if mp4_ok:
        return {
            "ok": True,
            "mkv": None,
            "mp4": str(mp4_path),
            "mp4_ok": True,
            "mp4_log_tail": mp4_log[-1000:],
            "log_tail": mp4_log[-1000:],
        }, True

    # Final fallback path: if direct MP4 export fails, keep an MKV output.
    try:
        mkv_ok, mkv_log = mux_to_mkv(ffmpeg, video_path, mux_audio_inputs, None, mkv_path)
    except ExternalToolError as exc:
        logger.warning("mkv fallback mux failed for %s: %s", video_path.name, exc)
        message = "mp4 export failed and mkv fallback failed; extracted streams were kept"
        return {
            "ok": False,
            "mkv": None,
            "mp4": None,
            "mp4_ok": False,
            "mp4_message": "direct mp4 export failed; trying mkv fallback",
            "mp4_log_tail": mp4_log[-1000:],
            "message": message,
            "log_tail": str(exc),
            "streams_kept": True,
        }, False

    if not mkv_ok:
        message = _mux_failure_message(video_path, mkv_log)
        logger.warning("mkv fallback skipped for %s: %s", video_path.name, message)
        return {
            "ok": False,
            "mkv": None,
            "mp4": None,
            "mp4_ok": False,
            "mp4_message": "direct mp4 export failed; trying mkv fallback",
            "mp4_log_tail": mp4_log[-1000:],
            "message": message,
            "log_tail": mkv_log[-1000:],
            "streams_kept": True,
        }, False

    return {
        "ok": True,
        "mkv": str(mkv_path),
        "mp4": None,
        "mp4_ok": False,
        "mp4_message": "direct mp4 export failed; MKV was kept as fallback",
        "mp4_log_tail": mp4_log[-1000:],
        "log_tail": mkv_log[-1000:],
    }, True


def _mux_failure_message(video_path: Path, log: str) -> str:
    text = log.lower()
    if "unknown timestamp" in text:
        return (
            "ffmpeg could not mux the video stream because timestamps are missing; "
            "extracted streams were kept"
        )
    return "ffmpeg mux failed; extracted streams were kept"


def _cleanup_outputs(
    mux_success: bool,
    keep_intermediate_audio: bool,
    out_dir: Path,
    video_path: Path | None,
    audio_paths: dict[int, Path],
    decoded: dict[int, dict],
) -> None:
    if mux_success:
        stream_paths = set(audio_paths.values())
        stream_paths.update(
            Path(dec["wav"])
            for dec in decoded.values()
            if dec.get("ok") and dec.get("wav")
        )
        if video_path:
            stream_paths.add(video_path)
        for path in stream_paths:
            _safe_unlink(path)
        remove_hcakey_files(out_dir)
        return

    if not keep_intermediate_audio:
        for ch, audio_path in audio_paths.items():
            if bool((decoded.get(ch) or {}).get("ok")):
                _safe_unlink(audio_path)
                _safe_unlink(audio_path.with_suffix(audio_path.suffix + "key"))


def _clear_removed_paths(
    mux_success: bool,
    keep_intermediate_audio: bool,
    decoded: dict[int, dict],
) -> None:
    for dec in decoded.values():
        wav = dec.get("wav")
        if wav and not Path(wav).exists():
            dec["wav"] = None
            if mux_success:
                dec["removed_after_mux"] = True
            elif not keep_intermediate_audio:
                dec["removed_after_decode"] = True


def _cleanup_empty_mux_dir(opt: ProcessOptions, mux_success: bool, out_dir: Path) -> None:
    if not opt.mux_mkv or not mux_success:
        return
    try:
        out_dir.rmdir()
    except OSError:
        # Keep non-empty or inaccessible directories.
        return


def _build_report(
    usm_path: Path,
    out_dir: Path,
    key1: bytes,
    key2: bytes,
    crack_stats: dict,
    chunks: list[UsmChunk],
    video_path: Path | None,
    video_info: dict,
    audio_paths: dict[int, Path],
    audio_decisions: dict[int, AudioDecision],
    decoded: dict[int, dict],
    mux_report: dict | None,
) -> dict:
    full_key = full_key_int(key1, key2)
    return {
        "file": str(usm_path),
        "status": "ok",
        "output_dir": str(out_dir),
        "key1_hex_little": key1.hex().upper(),
        "key2_hex_little": key2.hex().upper(),
        "full_key_hex": f"{full_key:016X}",
        "full_key_decimal": str(full_key),
        "usm_decrypt_key": genshin_like_key(full_key, usm_path.name),
        "crack": crack_stats,
        "chunks": {
            "total": len(chunks),
            "video": sum(1 for c in chunks if c.signature == SIG_SFV and c.data_type == 0),
            "audio": sum(1 for c in chunks if c.signature == SIG_SFA and c.data_type == 0),
        },
        "video": {
            "path": str(video_path) if video_path and video_path.exists() else None,
            "format": video_info.get("format"),
            "codec": video_info.get("codec"),
            "magic": video_info.get("magic"),
        },
        "audio": {
            str(ch): {
                "path": (
                    str(audio_paths[ch])
                    if ch in audio_paths and audio_paths[ch].exists()
                    else None
                ),
                "format": decision.format,
                "use_audio_mask": decision.use_audio_mask,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "hca": decision.hca,
                "decode": decoded.get(ch),
            }
            for ch, decision in sorted(audio_decisions.items())
        },
        "mux": mux_report,
    }


def _build_extract_report(
    usm_path: Path,
    out_dir: Path,
    chunks: list[UsmChunk],
    video_path: Path | None,
    video_info: dict,
    audio_paths: dict[int, Path],
    audio_info: dict[int, dict],
) -> dict:
    return {
        "file": str(usm_path),
        "status": "ok",
        "output_dir": str(out_dir),
        "extract_only": True,
        "chunks": {
            "total": len(chunks),
            "video": sum(1 for c in chunks if c.signature == SIG_SFV and c.data_type == 0),
            "audio": sum(1 for c in chunks if c.signature == SIG_SFA and c.data_type == 0),
        },
        "video": {
            "path": str(video_path) if video_path and video_path.exists() else None,
            "format": video_info.get("format"),
            "codec": video_info.get("codec"),
            "magic": video_info.get("magic"),
            "raw": True,
        },
        "audio": {
            str(ch): {
                "path": str(path) if path.exists() else None,
                "format": audio_info.get(ch, {}).get("format", "unknown"),
                "raw": True,
            }
            for ch, path in sorted(audio_paths.items())
        },
        "mux": None,
    }


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.debug("failed to remove %s: %s", path, exc)

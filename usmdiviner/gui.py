from __future__ import annotations

import concurrent.futures as futures
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog

from .blk_versions import parse_blk_versions
from .exceptions import UsmDivinerError
from .keys import parse_full_key
from .models import ProcessOptions
from .processor import process_one
from .tools import find_ffmpeg, find_vgmstream
from .usm import collect_usm_inputs

logger = logging.getLogger(__name__)
DEFAULT_LANGUAGE = "zh-CN"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LANG_DIR = ASSETS_DIR / "i18n"
FONT_PATH = ASSETS_DIR / "fonts" / "zh-cn.ttf"
SUPPORTED_LANGUAGES = ("zh-CN", "zh-TW", "en")
SYNC_TEMPLATE_CANDIDATES = (
    ASSETS_DIR / "usm_template" / "versions_template.json",
    ASSETS_DIR / "versions_reference.json",
    ASSETS_DIR / "versions_template.json",
    ASSETS_DIR / "key_template_versions.json",
    Path.cwd() / "versions_reference.json",
    Path.cwd() / "versions_template.json",
)


def _load_translations() -> dict[str, dict[str, str]]:
    translations: dict[str, dict[str, str]] = {}
    for lang in SUPPORTED_LANGUAGES:
        path = LANG_DIR / f"{lang}.json"
        with path.open("r", encoding="utf-8") as fp:
            translations[lang] = json.load(fp)
    return translations


TRANSLATIONS = _load_translations()


def _t(lang: str, key: str, **kwargs) -> str:
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANGUAGE]
    text = table.get(key) or TRANSLATIONS[DEFAULT_LANGUAGE].get(key) or key
    return text.format(**kwargs) if kwargs else text


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>UsmDiviner</title>
    <style>
        @font-face {
            font-family: "UsmDivinerZh";
            src: url("__FONT_URL__") format("truetype");
            font-weight: normal;
            font-style: normal;
        }

        html, body {
            width: 100%;
            height: 100%;
            overflow: hidden;
        }

        :root {

            --bg0: #1e1e1e;
            --bg1: #252525;
            --bg2: #2d2d2d;
            --aura1: #ffffff0a;
            --aura2: #ffffff06;
            --panel0: #1f1f1f;
            --panel1: #161616;
            --surface: #0d0d0d;
            --surface-2: #151515;
            --fg: #e0e0e0;
            --muted: #888888;
            --ok: #6ab983;
            --warn: #dab66d;
            --err: #d88d8d;
            --line: #3e3e3e;
            --acc: #858585;
            --input-bg: #1a1a1a;
            --input-border: #505050;
            --btn-fg: #e0e0e0;
            --btn-bg-0: #3a3a3a;
            --btn-bg-1: #2a2a2a;
            --btn-border: #555555;
            --run-bg-0: #2f7d42;
            --run-bg-1: #1e5a2f;
            --run-fg: #ffffff;
            --scroll-track: #1a1a1a;
            --scroll-thumb: #555555;
            --focus-ring: #85858533;
            --flash-bg: #85858533;
            --meter-bg: #3e3e3e33;
            --modal-overlay: #00000088;
        }

        [data-theme="light"] {
            --bg0: #f4efe6;
            --bg1: #ece3d6;
            --bg2: #f3eadf;
            --aura1: #d8c4a355;
            --aura2: #b9d8c355;
            --panel0: #f8f2e8;
            --panel1: #efe6d9;
            --surface: #fdf9f2;
            --surface-2: #f4ecdf;
            --fg: #3b3126;
            --muted: #7a6b59;
            --ok: #1f8f5c;
            --warn: #9a6a14;
            --err: #b23a3a;
            --line: #d7c9b5;
            --acc: #2f8f7a;
            --input-bg: #fffdf8;
            --input-border: #d8cab6;
            --btn-fg: #3b3126;
            --btn-bg-0: #fffaf1;
            --btn-bg-1: #f4eadc;
            --btn-border: #cdbca7;
            --run-bg-0: #5aa884;
            --run-bg-1: #438f70;
            --run-fg: #ffffff;
            --scroll-track: #efe4d4;
            --scroll-thumb: #c4ad8f;
            --focus-ring: #2f8f7a22;
            --flash-bg: #2f8f7a22;
            --meter-bg: #c9baa733;
            --modal-overlay: #3d2d1f44;
        }

        * { box-sizing: border-box; }

        body {
            margin: 0;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            color: var(--fg);
            background:
                radial-gradient(1200px 500px at 10% -10%, var(--aura1), transparent),
                radial-gradient(900px 500px at 110% -20%, var(--aura2), transparent),
                linear-gradient(180deg, var(--bg0), var(--bg1));
            transition: background 680ms cubic-bezier(0.22, 1, 0.36, 1), color 320ms ease;
        }

        body, .panel, .btn, input[type="text"], .control select, .table-wrap, .log-box, .modal-card {
            transition: background-color 280ms ease, color 240ms ease, border-color 280ms ease, box-shadow 280ms ease;
        }

        .wrap {
            max-width: 1180px;
            height: 100%;
            margin: 0 auto;
            padding: 8px 12px;
        }

        .panel {
            height: 100%;
            display: flex;
            flex-direction: column;
            background: linear-gradient(180deg, var(--panel0), var(--panel1));
            border: 1px solid var(--line);
            border-radius: 14px;
            box-shadow: 0 12px 28px #00000055;
        }

        .head {
            padding: 10px 18px 9px;
            border-bottom: 1px solid var(--line);
        }

        .head-top {
            display: flex;
            gap: 12px;
            justify-content: space-between;
            align-items: center;
        }

        .title {
            margin: 0;
            font-size: 22px;
            line-height: 1.1;
            letter-spacing: 0.2px;
        }

        .sub {
            margin-top: 2px;
            color: var(--muted);
            font-size: 11px;
        }

        .toolbar-controls {
            display: flex;
            gap: 8px;
            align-items: flex-end;
            justify-content: flex-end;
        }

        .control {
            display: flex;
            flex-direction: column;
            gap: 3px;
            min-width: 145px;
        }

        .control label {
            color: var(--muted);
            font-size: 11px;
        }

        .control select {
            width: 100%;
            border-radius: 8px;
            border: 1px solid var(--input-border);
            background: var(--input-bg);
            color: var(--fg);
            padding: 6px 8px;
            font-size: 12px;
            outline: none;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr;
            grid-template-rows: auto 1fr auto auto;
            gap: 10px;
            padding: 10px 14px;
            flex: 1;
            overflow: hidden;
            min-height: 0;
        }

        .top-pane,
        .table-pane,
        .footer-pane {
            border: 1px solid var(--line);
            border-radius: 10px;
            background: linear-gradient(180deg, #ffffff05, #00000010);
        }

        .top-pane {
            padding: 10px;
        }

        .table-pane {
            min-height: 0;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 8px;
        }

        .footer-pane {
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
            padding: 8px;
        }

        .actions-bar {
            margin-top: -2px;
        }

        /* Two-column form layout: left and right 50/50 */
        .form-cols {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 7px 18px;
        }

        .form-col {
            display: flex;
            flex-direction: column;
            gap: 7px;
        }

        /* Full-width mode row above form-cols */
        /* Wraps mode-row + form-cols with tighter internal spacing */
        .form-block {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .mode-row {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 0;
        }

        .mode-row > label:first-child {
            color: var(--muted);
            font-size: 12px;
            white-space: nowrap;
            min-width: 5em;
        }

        .row {
            display: grid;
            grid-template-columns: 5em 1fr auto;
            gap: 7px;
            align-items: center;
        }

        .row.small {
            grid-template-columns: 5em 1fr;
        }

        .mode {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .mode label {
            display: flex;
            gap: 6px;
            align-items: center;
            color: var(--fg);
            font-size: 12px;
        }

        label {
            color: var(--muted);
            font-size: 12px;
            white-space: nowrap;
        }

        input[type="text"] {
            width: 100%;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid var(--input-border);
            background: var(--input-bg);
            color: var(--fg);
            font-size: 12px;
            outline: none;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        input[type="text"]:focus {
            border-color: var(--acc);
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        input[type="text"]::placeholder {
            color: var(--muted);
            opacity: 0.78;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        .btn {
            cursor: pointer;
            border: 1px solid var(--btn-border);
            border-radius: 8px;
            color: var(--btn-fg);
            background: linear-gradient(180deg, var(--btn-bg-0), var(--btn-bg-1));
            padding: 7px 11px;
            font-size: 12px;
            font-weight: 600;
            white-space: nowrap;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        .btn:hover { filter: brightness(1.08); }
        .btn:disabled { opacity: 0.6; cursor: not-allowed; }

        .opts {
            display: grid;
            grid-template-columns: repeat(3, minmax(180px, 1fr));
            gap: 6px 10px;
            background: var(--bg2);
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 8px 10px;
        }

        .opt {
            display: flex;
            gap: 6px;
            align-items: center;
            font-size: 12px;
            color: var(--fg);
        }

        .section-title {
            margin: 0;
            padding: 0 2px;
            color: var(--muted);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.3px;
            text-transform: uppercase;
        }

        .table-wrap {
            position: relative;
            border: 1px solid var(--line);
            border-radius: 10px;
            background: var(--surface);
            overflow: auto;
            min-height: 0;
            max-height: none;
            flex: 1;
        }

        table.file-table {
            width: 100%;
            min-width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 11px;
            color: var(--fg);
        }

        .file-table th,
        .file-table td {
            border-bottom: 1px solid var(--line);
            padding: 6px 7px;
            text-align: left;
            vertical-align: top;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .file-table th {
            position: sticky;
            top: 0;
            background: var(--surface-2);
            color: var(--muted);
            font-weight: 700;
            z-index: 1;
            min-width: 80px;
            text-align: center;
        }

        .file-table th {
            position: sticky;
        }

        .resizer {
            position: absolute;
            top: 0;
            right: 0;
            width: 6px;
            height: 100%;
            cursor: col-resize;
            user-select: none;
            touch-action: none;
            opacity: 0;
        }

        .file-table th:hover .resizer {
            opacity: 0.7;
            background: linear-gradient(180deg, transparent, var(--acc), transparent);
        }

        .file-table tr.pending { opacity: 0.8; }
        .file-table tr.ok { background: #163524; }
        .file-table tr.warn { background: #3a3115; }
        .file-table tr.err { background: #3a1d1d; }

        [data-theme="light"] .file-table tr.ok { background: #def5ea; }
        [data-theme="light"] .file-table tr.warn { background: #fdf3db; }
        [data-theme="light"] .file-table tr.err { background: #fde2e2; }

        .table-empty-overlay {
            position: absolute;
            left: 0;
            right: 0;
            top: 36px;
            bottom: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: var(--muted);
            letter-spacing: 0.2px;
            pointer-events: none;
            padding: 8px 12px;
        }

        .table-empty-overlay.hidden {
            display: none;
        }

        .file-table td.empty-state {
            text-align: center;
            vertical-align: middle;
            color: var(--muted);
            padding: 0;
            letter-spacing: 0.2px;
        }

        /* Center selected columns: name, size, Mask_1, Mask_2, USM key */
        .file-table td:nth-child(2),
        .file-table td:nth-child(3),
        .file-table td:nth-child(5),
        .file-table td:nth-child(6),
        .file-table td:nth-child(7) {
            text-align: center;
        }

        .mono { font-family: Consolas, Courier New, monospace; }

        .actions {
            display: flex;
            gap: 8px;
            justify-content: flex-end;
            align-items: center;
        }

        .actions .btn {
            padding: 7px 14px;
            font-size: 12px;
            min-width: 80px;
        }

        /* BLK row: 4-column grid — label | textbox (1fr) | Load btn | View btn (collapses when hidden) */
        .blk-row {
            grid-template-columns: 5em 1fr auto auto;
        }

        .run {
            background: linear-gradient(180deg, var(--run-bg-0), var(--run-bg-1));
            border-color: var(--run-bg-0);
            color: var(--run-fg);
        }

        .progress-wrap {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
            align-items: center;
            padding: 0;
        }

        .progress-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }

        .progress-head label {
            color: var(--muted);
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.2px;
        }

        .progress-track {
            width: 100%;
            height: 10px;
            border-radius: 999px;
            overflow: hidden;
            background: #ffffff12;
        }

        .progress-fill {
            height: 100%;
            width: 0%;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--acc), #69d89f);
            transition: width 260ms ease;
        }

        .progress-text {
            text-align: right;
            color: var(--muted);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.2px;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        .cell-progress {
            width: 120px;
        }

        .report-pick {
            text-align: center;
            width: 82px;
        }

        .row-action {
            text-align: center;
        }

        .mini-btn {
            padding: 4px 7px;
            font-size: 11px;
            border-radius: 8px;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            line-height: 1;
        }

        .btn-ico {
            font-size: 12px;
            opacity: 0.92;
        }

        .copied-flash {
            animation: copiedFlash 680ms ease;
        }

        .copy-toast {
            position: fixed;
            left: 50%;
            bottom: 22px;
            transform: translateX(-50%) translateY(10px);
            background: var(--surface-2);
            color: var(--fg);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 12px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 180ms ease, transform 180ms ease;
            z-index: 80;
            box-shadow: 0 8px 20px #00000055;
        }

        .copy-toast.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }

        @keyframes copiedFlash {
            0% { background: var(--flash-bg); }
            100% { background: transparent; }
        }

        .table-wrap::-webkit-scrollbar,
        .log-box::-webkit-scrollbar,
        .blk-preview::-webkit-scrollbar,
        .sync-result-text::-webkit-scrollbar {
            width: 12px;
            height: 12px;
        }

        .table-wrap::-webkit-scrollbar-track,
        .log-box::-webkit-scrollbar-track,
        .blk-preview::-webkit-scrollbar-track,
        .sync-result-text::-webkit-scrollbar-track {
            background: var(--scroll-track);
            border-radius: 999px;
        }

        .table-wrap::-webkit-scrollbar-thumb,
        .log-box::-webkit-scrollbar-thumb,
        .blk-preview::-webkit-scrollbar-thumb,
        .sync-result-text::-webkit-scrollbar-thumb {
            background: var(--scroll-thumb);
            border-radius: 999px;
            border: 2px solid var(--scroll-track);
        }

        .table-wrap::-webkit-scrollbar-button,
        .log-box::-webkit-scrollbar-button,
        .blk-preview::-webkit-scrollbar-button,
        .sync-result-text::-webkit-scrollbar-button {
            width: 0;
            height: 0;
            display: none;
        }

        .mini-track {
            width: 100%;
            height: 8px;
            border-radius: 999px;
            overflow: hidden;
            background: var(--meter-bg);
            border: 1px solid var(--line);
        }

        .mini-fill {
            height: 100%;
            width: 0%;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--acc), #69d89f);
            transition: width 220ms ease;
        }

        .mini-label {
            margin-top: 4px;
            color: var(--muted);
            font-size: 10px;
            text-align: right;
            font-family: Consolas, Courier New, monospace;
        }

        .modal {
            position: fixed;
            inset: 0;
            background: var(--modal-overlay);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 14px;
            z-index: 50;
        }

        .hidden {
            display: none !important;
        }

        .modal-card {
            width: min(980px, 96vw);
            height: min(620px, 84vh);
            background: linear-gradient(180deg, var(--panel0), var(--panel1));
            border: 1px solid var(--line);
            border-radius: 14px;
            box-shadow: 0 16px 36px #00000066;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .modal-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            padding: 12px 14px;
            border-bottom: 1px solid var(--line);
            color: var(--fg);
            font-weight: 700;
        }

        .log-box {
            flex: 1;
            margin: 12px 14px;
            border-radius: 10px;
            border: 1px solid var(--line);
            background: var(--surface);
            color: var(--fg);
            padding: 10px;
            white-space: pre-wrap;
            overflow: auto;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            font-size: 12px;
            line-height: 1.4;
        }

        .sync-result-card {
            width: min(860px, 92vw);
            height: min(560px, 78vh);
        }

        #sync_result_modal .modal-head {
            justify-content: center;
        }

        #sync_result_modal .modal-head > span {
            width: 100%;
            text-align: center;
        }

        .sync-result-body {
            flex: 1;
            padding: 12px 14px;
            min-height: 0;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .sync-result-note {
            color: var(--muted);
            font-size: 12px;
        }

        .sync-result-text {
            width: 100%;
            flex: 1;
            min-height: 0;
            resize: none;
            border-radius: 10px;
            border: 1px solid var(--line);
            background: var(--surface);
            color: var(--fg);
            padding: 10px;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            font-size: 12px;
            line-height: 1.45;
            outline: none;
        }

        .log-box.empty {
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: var(--muted);
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            font-size: 13px;
            line-height: 1.5;
        }

        .modal-actions {
            display: flex;
            gap: 8px;
            justify-content: flex-end;
            padding: 0 14px 12px;
        }

        .blk-modal-card {
            width: min(1100px, 96vw);
            height: min(720px, 88vh);
        }

        .blk-modal-body {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding: 12px 14px;
            min-height: 0;
        }

        .blk-summary-row {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 8px;
        }

        .blk-search {
            display: flex;
            align-items: center;
            gap: 0;
            flex-shrink: 0;
        }

        .blk-search-input-wrap {
            position: relative;
            display: inline-flex;
            align-items: center;
            flex-shrink: 0;
            border: 1px solid var(--input-border);
            border-radius: 8px;
            background: var(--input-bg);
            overflow: visible;
        }

        .blk-search-input {
            flex: 1;
            min-width: 80px;
            padding: 6px 8px;
            border: none;
            background: transparent;
            color: var(--fg);
            font-size: 12px;
            outline: none;
        }

        .blk-search-input:focus {
            box-shadow: none;
        }

        .blk-search-input-wrap:focus-within {
            border-color: var(--acc);
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        .blk-search-input::placeholder {
            color: var(--muted);
            opacity: 0.78;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        .blk-search-btn {
            padding: 6px 10px;
            font-size: 11px;
            min-width: 58px;
        }

        .blk-search-nav-btn {
            padding: 5px 8px;
            font-size: 11px;
            min-width: 30px;
            border: none;
            border-radius: 0;
            border-left: 1px solid var(--line);
            background: transparent;
            font-weight: 700;
        }

        .blk-search-status {
            min-width: 64px;
            text-align: center;
            color: var(--muted);
            font-size: 11px;
            font-family: Consolas, Courier New, monospace;
        }

        .blk-search-status-inline {
            flex-shrink: 0;
            min-width: 44px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: var(--muted);
            font-size: 11px;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            font-variant-numeric: tabular-nums;
            padding: 0 6px;
            white-space: nowrap;
            pointer-events: none;
            border-left: 1px solid var(--line);
        }

        .blk-search-controls {
            display: inline-flex;
            align-items: stretch;
            flex-shrink: 0;
            background: transparent;
        }

        .blk-search-toggle-btn {
            padding: 5px 8px;
            min-width: 32px;
            border: none;
            border-left: 1px solid var(--line);
            border-radius: 0;
            background: transparent;
            font-size: 11px;
            font-weight: 700;
        }

        .blk-search-toggle-btn.active {
            background: var(--focus-ring);
            color: var(--fg);
        }

        .blk-search-clear-btn {
            padding: 5px 8px;
            min-width: 30px;
            border: none;
            border-left: 1px solid var(--line);
            border-radius: 0;
            background: transparent;
            font-size: 13px;
            font-weight: 700;
            line-height: 1;
        }

        .blk-search-hit {
            background: #c99a2a44;
            color: var(--fg);
            border-radius: 3px;
            padding: 0 1px;
        }

        .blk-search-hit-active {
            background: #e3b74988;
            outline: 1px solid #e3b749;
        }

        #blk_versions_modal .modal-head {
            justify-content: center;
            flex-direction: column;
            align-items: center;
            gap: 2px;
        }

        #blk_versions_modal .modal-head > span {
            width: 100%;
            text-align: center;
        }

        .blk-head-line {
            width: 100%;
            color: var(--muted);
            font-size: 12px;
            line-height: 1.35;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            user-select: none;
            -webkit-user-select: none;
            -ms-user-select: none;
        }

        #blk_versions_summary {
            margin-top: 6px;
        }

        .blk-preview {
            flex: 1;
            margin: 0;
            border-radius: 10px;
            border: 1px solid var(--line);
            background: var(--surface);
            color: var(--fg);
            padding: 12px;
            white-space: pre;
            overflow: auto;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            font-size: 12px;
            line-height: 1.45;
            min-height: 0;
        }

        .ok { color: var(--ok); }
        .warn { color: var(--warn); }
        .err { color: var(--err); }

        /* Tooltip styles - using data-tooltip attribute */
        [data-tooltip] {
            position: relative;
        }

        [data-tooltip]:hover::after {
            content: attr(data-tooltip);
            position: absolute;
            bottom: 115%;
            left: 50%;
            transform: translateX(-50%);
            background: var(--panel0);
            color: var(--fg);
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 11px;
            text-align: center;
            white-space: nowrap;
            pointer-events: none;
            opacity: 1;
            visibility: visible;
            z-index: 100;
            box-shadow: 0 4px 12px #00000044;
            animation: tooltipFadeIn 150ms ease;
        }

        @keyframes tooltipFadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        /* Toggle switch styles */
        .toggle-switch {
            position: relative;
            display: inline-block;
            width: 48px;
            height: 24px;
        }

        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: var(--input-border);
            border-radius: 24px;
            transition: background-color 280ms ease;
            border: 1px solid var(--line);
        }

        .toggle-slider:before {
            position: absolute;
            content: '';
            height: 18px;
            width: 18px;
            left: 2px;
            bottom: 2px;
            background-color: var(--fg);
            border-radius: 50%;
            transition: transform 280ms ease;
        }

        .toggle-switch input:checked + .toggle-slider {
            background-color: var(--ok);
            border-color: var(--ok);
        }

        .toggle-switch input:checked + .toggle-slider:before {
            transform: translateX(24px);
        }

        /* Settings Modal Styles */
        .modal-head {
            text-align: center;
            font-size: 16px;
            font-weight: 700;
        }

        #settings_modal .modal-head {
            background: linear-gradient(180deg, var(--panel0), var(--panel1));
            padding: 16px 14px;
            border: none;
        }

        .settings-content {
            flex: 1;
            padding: 20px 16px;
            overflow-y: auto;
        }

        #settings_modal .modal-card {
            height: min(760px, 92vh);
        }

        .settings-content::-webkit-scrollbar {
            width: 12px;
        }

        .settings-content::-webkit-scrollbar-track {
            background: var(--scroll-track);
            border-radius: 999px;
        }

        .settings-content::-webkit-scrollbar-thumb {
            background: var(--scroll-thumb);
            border-radius: 999px;
            border: 2px solid var(--scroll-track);
        }

        .settings-content {
            scrollbar-color: var(--scroll-thumb) var(--scroll-track);
            scrollbar-width: thin;
        }

        #log_modal .modal-head {
            justify-content: center;
            text-align: center;
        }

        .settings-group {
            margin-bottom: 0;
            padding-bottom: 0;
            border-bottom: none;
        }

        .settings-group:last-child {
            border-bottom: none;
        }

        .setting-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 14px;
            padding: 12px 0;
            border-bottom: 1px solid var(--line);
        }

        .setting-item:last-child {
            border-bottom: none;
        }

        .setting-label {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 3px;
        }

        .setting-label .label-text {
            display: block;
            color: var(--fg);
            font-size: 13px;
            font-weight: 500;
            line-height: 1.3;
        }

        .setting-label .label-desc {
            display: block;
            color: var(--muted);
            font-size: 10px;
            line-height: 1.4;
        }

        .setting-key-input {
            width: 100%;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid var(--input-border);
            background: var(--input-bg);
            color: var(--fg);
            font-size: 12px;
            outline: none;
        }

        .setting-key-input:focus {
            border-color: var(--acc);
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        .modal-actions {
            display: flex;
            gap: 10px;
            justify-content: center;
            padding: 14px 16px;
            border-top: 1px solid var(--line);
            background: var(--panel1);
            border-bottom-left-radius: 14px;
            border-bottom-right-radius: 14px;
        }

        .modal-actions .btn {
            padding: 8px 24px;
            font-size: 12px;
            min-width: 80px;
        }

        #settings_modal .modal-head {
            justify-content: center;
        }

        @media (max-width: 900px) {
            .head-top { flex-direction: column; }
            .toolbar-controls { width: 100%; }
            .control { flex: 1; min-width: 0; }
            .grid { grid-template-rows: auto auto auto auto; overflow: auto; }
            .form-cols { grid-template-columns: 1fr; }
            .row { grid-template-columns: 1fr; }
            .blk-row { grid-template-columns: 1fr; }
            .opts { grid-template-columns: 1fr; }
            .actions { justify-content: flex-end; flex-wrap: wrap; }
            .actions .btn { width: auto; }

        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="panel">
            <div class="head">
                <div class="head-top">
                    <div>
                        <h1 class="title" id="title_text">UsmDiviner GUI</h1>
                        <div class="sub" id="subtitle_text">USM key recovery, extraction, MKV mux, and BLB versions viewer</div>
                    </div>
                    <div class="toolbar-controls">
                        <div class="control">
                            <label for="lang_select" id="lang_label_text">Language</label>
                            <select id="lang_select" onchange="setLanguage(this.value)">
                                <option id="lang_opt_zh_cn" value="zh-CN">Simplified Chinese</option>
                                <option id="lang_opt_zh_tw" value="zh-TW">Traditional Chinese</option>
                                <option id="lang_opt_en" value="en">English</option>
                            </select>
                        </div>
                        <div class="control">
                            <label for="theme_select" id="theme_label_text">Theme</label>
                            <select id="theme_select" onchange="setTheme(this.value)">
                                <option id="theme_opt_dark" value="dark">Dark</option>
                                <option id="theme_opt_light" value="light">Light</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>
            <div class="grid">
                <div class="top-pane">
                    <div class="form-block">
                        <div class="mode-row">
                            <label id="analysis_mode_text">Mode</label>
                            <div class="mode">
                                <label><input type="radio" name="input_mode" id="mode_single" value="single" checked onchange="syncInputMode()" /> <span id="single_file_text">Single file</span></label>
                                <label><input type="radio" name="input_mode" id="mode_batch" value="batch" onchange="syncInputMode()" /> <span id="batch_folder_text">Batch</span></label>
                            </div>
                        </div>
                        <div class="form-cols">
                            <div class="form-col">
                                <div class="row">
                                    <label id="input_label" for="input">Input</label>
                                    <input id="input" type="text" placeholder="" onchange="previewInput()" />
                                    <button class="btn" id="input_pick_btn" data-tooltip="Browse to select input" onclick="pickInput()">Browse</button>
                                </div>
                                <div class="row">
                                    <label id="output_label" for="output">Output</label>
                                    <input id="output" type="text" placeholder="" />
                                    <button class="btn" id="output_pick_btn" data-tooltip="Browse to select output folder" onclick="bridge.pickOutput()">Browse</button>
                                </div>
                                <div class="row" id="report_path_row" style="display:none;">
                                    <label id="report_path_label" for="report_output">Report</label>
                                    <input id="report_output" type="text" placeholder="" />
                                    <button class="btn" id="report_pick_btn" data-tooltip="Select report output folder" onclick="bridge.pickReportOutput()">Pick</button>
                                </div>
                            </div>
                            <div class="form-col">
                                <div class="row blk-row">
                                    <label id="blk_label" for="blk_input">Load BLK</label>
                                    <input id="blk_input" type="text" readonly placeholder="" />
                                    <button class="btn" id="blk_pick_btn" data-tooltip="Select BLK file" onclick="pickBlkInput()">Load</button>
                                    <button class="btn hidden" id="open_versions_btn" onclick="openBlkVersionsModal()">View</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="table-pane">
                    <div class="section-title" id="file_list_title">USM file list</div>
                    <div class="table-wrap">
                    <table class="file-table">
                        <colgroup>
                            <col id="col_progress" style="width:12%;" />
                            <col id="col_name" style="width:24%;" />
                            <col id="col_size" style="width:9%;" />
                            <col id="col_created" style="width:13%;" />
                            <col id="col_key1" style="width:11%;" />
                            <col id="col_key2" style="width:11%;" />
                            <col id="col_genshin" style="width:14%;" />
                            <col id="col_action" style="width:7%;" />
                        </colgroup>
                        <thead>
                            <tr>
                                <th id="th_progress" data-min="140">Progress</th>
                                <th id="th_name" data-min="220">Name</th>
                                <th id="th_size" data-min="110">Size</th>
                                <th id="th_created" data-min="170">Created</th>
                                <th id="th_key1" data-min="150">key1_hex_little</th>
                                <th id="th_key2" data-min="150">key2_hex_little</th>
                                <th id="th_genshin" data-min="220">genshin_like_key</th>
                                <th id="th_action" data-min="96"></th>
                            </tr>
                        </thead>
                        <tbody id="file_table_body">
                            <tr class="pending"><td class="empty-state" colspan="8"></td></tr>
                        </tbody>
                    </table>
                    <div id="file_table_empty" class="table-empty-overlay">No files loaded.</div>
                </div>
                </div>

                <div class="footer-pane">
                    <div class="progress-wrap">
                        <div class="progress-head">
                            <label id="overall_progress_text">Overall progress</label>
                            <div id="overall_progress_value" class="progress-text">0%</div>
                        </div>
                        <div class="progress-track"><div id="overall_progress_fill" class="progress-fill"></div></div>
                    </div>

                    <div class="opts" style="display:none;">
                        <label class="opt"><input id="no_parallel" type="checkbox" /> <span id="opt_no_parallel_text">Disable multiprocessing</span></label>
                        <label class="opt"><input id="report" type="checkbox" onchange="syncRules()" /> <span id="opt_report_text">Write report.json</span></label>
                        <label class="opt"><input id="fast" type="checkbox" /> <span id="opt_fast_text">Fast key crack</span></label>
                        <label class="opt"><input id="extract_only" type="checkbox" onchange="syncRules()" /> <span id="opt_extract_only_text">Extract only</span></label>
                        <label class="opt"><input id="keep_audio" type="checkbox" /> <span id="opt_keep_audio_text">Keep intermediate audio</span></label>
                        <label class="opt"><input id="no_adx_mask" type="checkbox" /> <span id="opt_no_adx_mask_text">Disable ADX AudioMask</span></label>
                        <label class="opt"><input id="mux_mkv" type="checkbox" onchange="syncRules()" /> <span id="opt_mux_mkv_text">Mux MKV</span></label>
                    </div>
                </div>

                <div class="actions actions-bar">
                    <button class="btn" id="open_settings_btn" data-tooltip="Settings" onclick="openSettingsModal()">Settings</button>
                    <button class="btn" id="open_log_btn" data-tooltip="View output logs" onclick="openLogModal()">Logs</button>
                    <button id="run" class="btn run" data-tooltip="Start extraction" onclick="runTask()">Run</button>
                </div>
            </div>
        </div>
    </div>

    <div id="log_modal" class="modal hidden">
        <div class="modal-card">
            <div class="modal-head">
                <span id="log_window_title">Run logs</span>
            </div>
            <div id="log_box" class="log-box"></div>
            <div class="modal-actions">
                <button class="btn" id="export_log_btn" onclick="exportLog()" disabled>Export</button>
                <button class="btn" id="clear_log_btn" onclick="clearLog()" disabled>Clear log</button>
                <button class="btn" id="close_log_btn" onclick="closeLogModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="settings_modal" class="modal hidden">
        <div class="modal-card">
            <div class="modal-head">
                <span id="settings_title">Settings</span>
            </div>
            <div class="settings-content">
                <div class="settings-group">
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_no_parallel_text">Disable multiprocessing</span>
                            <span class="label-desc" id="opt_disable_multiprocessing_tooltip">Disable parallel processing, use single process only</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="no_parallel_toggle" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_report_text">Generate reports</span>
                            <span class="label-desc" id="opt_write_report_tooltip">Generate detailed JSON report</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="report_toggle" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_fast_text">Fast key crack</span>
                            <span class="label-desc" id="opt_fast_key_crack_tooltip">Use fast algorithm for key recovery</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="fast_toggle" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_extract_only_text">Extract only</span>
                            <span class="label-desc" id="opt_extract_only_tooltip">Extract audio only, skip key recovery</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="extract_only_toggle" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_keep_audio_text">Keep intermediate audio</span>
                            <span class="label-desc" id="opt_keep_intermediate_audio_tooltip">Keep intermediate audio files during extraction</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="keep_audio_toggle" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_no_adx_mask_text">Disable ADX AudioMask</span>
                            <span class="label-desc" id="opt_disable_adx_mask_tooltip">Skip ADX audio mask processing</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="no_adx_mask_toggle" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_mux_mkv_text">Mux MKV</span>
                            <span class="label-desc" id="opt_mux_mkv_tooltip">Mux extracted audio and video into MKV file</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="mux_mkv_toggle" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_manual_key_text">Custom USM Key</span>
                            <span class="label-desc" id="opt_manual_key_tooltip">Enable manual USM key input</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="manual_key_toggle" onchange="updateManualKeyVisibility()" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="setting-item hidden" id="manual_key_row">
                        <div class="setting-label" style="width:100%;">
                            <span class="label-text" id="manual_key_text">Custom USM Key</span>
                            <input id="key" type="text" class="setting-key-input" />
                        </div>
                    </div>
                </div>
            </div>
            <div class="modal-actions">
                <button class="btn" id="settings_ok_btn" onclick="closeSettingsModal(true)">OK</button>
                <button class="btn" id="settings_cancel_btn" onclick="closeSettingsModal(false)">Cancel</button>
            </div>
        </div>
    </div>

    <div id="blk_versions_modal" class="modal hidden">
        <div class="modal-card blk-modal-card">
            <div class="modal-head">
                <span id="blk_versions_title">versions.json</span>
                <div class="blk-head-line" id="blk_versions_summary">No versions.json data available.</div>
                <div class="blk-head-line" id="blk_versions_path">BLK path: —</div>
            </div>
            <div class="blk-modal-body">
                <div class="blk-summary-row">
                    <div class="blk-search">
                        <div class="blk-search-input-wrap">
                            <input id="blk_search_input" class="blk-search-input" type="text" placeholder="Search text" oninput="onBlkSearchInput()" onkeydown="handleBlkSearchKey(event)" />
                            <span class="blk-search-status-inline" id="blk_search_status">0/0</span>
                            <div class="blk-search-controls">
                                <button class="btn blk-search-toggle-btn" id="blk_search_case_btn" onclick="toggleBlkSearchCase()" data-tooltip="Match case">Aa</button>
                                <button class="btn blk-search-toggle-btn" id="blk_search_word_btn" onclick="toggleBlkSearchWholeWord()" data-tooltip="Match whole word">W</button>
                                <button class="btn blk-search-nav-btn" id="blk_search_prev_btn" onclick="focusPrevBlkSearchHit()" data-tooltip="Previous match">↑</button>
                                <button class="btn blk-search-nav-btn" id="blk_search_next_btn" onclick="focusNextBlkSearchHit()" data-tooltip="Next match">↓</button>
                                <button class="btn blk-search-clear-btn" id="blk_search_clear_btn" onclick="resetBlkSearch()" data-tooltip="Clear search">×</button>
                            </div>
                        </div>
                    </div>
                </div>
                <pre id="blk_versions_box" class="blk-preview"></pre>
            </div>
            <div class="modal-actions">
                <button class="btn" id="blk_versions_copy_btn" onclick="copyBlkVersions()">Copy</button>
                <button class="btn" id="blk_versions_sync_btn" onclick="syncBlkKeysFromUsmRows()">Sync Keys</button>
                <button class="btn" id="blk_versions_close_btn" onclick="closeBlkVersionsModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="copy_toast" class="copy-toast"></div>

    <div id="sync_result_modal" class="modal hidden">
        <div class="modal-card sync-result-card">
            <div class="modal-head">
                <span id="sync_result_title">Sync Result</span>
            </div>
            <div class="sync-result-body">
                <div id="sync_result_note" class="sync-result-note"></div>
                <textarea id="sync_result_text" class="sync-result-text" readonly></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" id="sync_result_close_btn" onclick="closeSyncResultModal()">Close</button>
            </div>
        </div>
    </div>

    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script>
        const I18N = JSON.parse(__TRANSLATIONS_JSON__);
        let bridge = null;
        let fileRows = new Map();
        let logLines = [];
        let blkVersionsData = null;
        let blkSearchQuery = "";
        let blkSearchCaseSensitive = false;
        let blkSearchWholeWord = false;
        let blkSearchMatches = [];
        let blkSearchIndex = -1;
        let blkParsePending = false;
        let copyToastTimer = null;
        let lastLogLine = null;
        let lastLogTs = 0;

        function byId(id) { return document.getElementById(id); }

        function t(lang) {
            return I18N[lang] || I18N["en"];
        }

        function currentLang() {
            return byId("lang_select").value || "zh-CN";
        }

        function currentTheme() {
            return byId("theme_select").value || "dark";
        }

        function setText(id, text) {
            const el = byId(id);
            if (el) el.textContent = text;
        }

        function setPlaceholder(id, text) {
            const el = byId(id);
            if (el) el.placeholder = text;
        }

        function setTooltip(id, text) {
            const el = byId(id);
            if (!el) return;
            el.setAttribute("data-tooltip", text || "");
            el.setAttribute("aria-label", text || "");
            el.removeAttribute("title");
        }

        function blkEntryCount(value) {
            if (Array.isArray(value)) return value.length;
            if (value && typeof value === "object") return Object.keys(value).length;
            return 0;
        }

        function extractBlkGameVersion() {
            const normalizeVersion = (value) => {
                const raw = String(value || "").trim();
                if (!raw) return "";
                const parts = raw.split(".").filter((p) => p.length > 0);
                if (parts.length === 2) return `${parts[0]}.${parts[1]}.0`;
                return raw;
            };

            const list = Array.isArray(blkVersionsData && blkVersionsData.versions_list)
                ? blkVersionsData.versions_list
                : [];
            for (let i = list.length - 1; i >= 0; i -= 1) {
                const item = list[i];
                if (!item || typeof item !== "object") continue;
                const versionValue = String(item.version || "").trim();
                if (versionValue) return normalizeVersion(versionValue);
            }

            // Fallback: parse the full JSON payload and scan recursively.
            const raw = String(blkVersionsData && blkVersionsData.versions_json || "");
            if (!raw || raw === "null") return "—";
            try {
                const decoded = JSON.parse(raw);
                let lastVersion = "";
                const walk = (node) => {
                    if (!node) return;
                    if (Array.isArray(node)) {
                        for (const entry of node) walk(entry);
                        return;
                    }
                    if (typeof node !== "object") return;
                    if (Object.prototype.hasOwnProperty.call(node, "version")) {
                        const v = String(node.version || "").trim();
                        if (v) lastVersion = v;
                    }
                    for (const key of Object.keys(node)) {
                        walk(node[key]);
                    }
                };
                walk(decoded);
                if (lastVersion) return normalizeVersion(lastVersion);
                return "—";
            } catch (_) {
                return "—";
            }
        }

        function formatBytes(bytes) {
            const n = Number(bytes || 0);
            const units = ["B", "KB", "MB", "GB", "TB"];
            let value = n;
            let unit = 0;
            while (value >= 1024 && unit < units.length - 1) {
                value /= 1024;
                unit += 1;
            }
            return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
        }

        function formatDate(ts) {
            if (!ts) return "—";
            const lang = currentLang();
            const locale = lang === "zh-CN" ? "zh-CN" : lang === "zh-TW" ? "zh-TW" : "en-US";
            return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "medium" }).format(new Date(ts * 1000));
        }

        function renderFileList(rows) {
            const body = byId("file_table_body");
            const emptyOverlay = byId("file_table_empty");
            fileRows.clear();
            body.innerHTML = "";
            if (!rows || !rows.length) {
                const dict = t(currentLang());
                body.innerHTML = `<tr class="pending"><td class="empty-state" colspan="8"></td></tr>`;
                if (emptyOverlay) {
                    emptyOverlay.textContent = dict.table_empty;
                    emptyOverlay.classList.remove("hidden");
                }
                return;
            }
            if (emptyOverlay) {
                emptyOverlay.classList.add("hidden");
            }
            rows.forEach((row) => {
                row.progress = Number(row.progress || 0);
                fileRows.set(row.id, row);
                const tr = document.createElement("tr");
                tr.id = `row_${row.id}`;
                tr.className = row.status === "ok" ? "ok" : row.status === "skipped" ? "warn" : row.status === "error" ? "err" : "pending";
                const cells = [
                    {
                        html: `<div class="cell-progress"><div class="mini-track"><div id="${row.id}_progress_fill" class="mini-fill" style="width:${row.progress}%"></div></div><div id="${row.id}_progress_text" class="mini-label">${row.progress}%</div></div>`,
                    },
                    { text: row.name, title: row.path },
                    { text: formatBytes(row.size_bytes) },
                    { text: formatDate(row.created_ts) },
                    { id: `${row.id}_key1`, text: row.key1_hex_little || "—" },
                    { id: `${row.id}_key2`, text: row.key2_hex_little || "—" },
                    { id: `${row.id}_genshin`, text: row.genshin_like_key ?? "—" },
                    {
                        id: `${row.id}_action`,
                        html: "—",
                    },
                ];
                cells.forEach((cell) => {
                    const td = document.createElement("td");
                    td.className = "mono";
                    if (cell.html) {
                        td.className = cell.id && cell.id.endsWith("_action") ? "row-action" : "";
                        td.innerHTML = cell.html;
                    } else {
                        td.textContent = cell.text;
                    }
                    if (cell.title) td.title = cell.title;
                    if (cell.id) td.id = cell.id;
                    if (cell.id && (cell.id.endsWith("_key1") || cell.id.endsWith("_key2") || cell.id.endsWith("_genshin"))) {
                        td.ondblclick = () => copyCellText(td);
                        td.title = t(currentLang()).cell_copy_hint;
                    }
                    tr.appendChild(td);
                });
                updateReportAction(row.id, row.status || "pending");
                body.appendChild(tr);
            });
        }

        function updateReportAction(id, status) {
            const cell = byId(`${id}_action`);
            if (!cell) return;
            const globalReport = byId("report").checked;
            if (globalReport) {
                const dict = t(currentLang());
                cell.textContent = dict.report_all_enabled;
                return;
            }
            if (status === "ok" || status === "skipped" || status === "error") {
                const dict = t(currentLang());
                cell.innerHTML = `<button class="btn mini-btn" data-tooltip="${dict.save_report_tooltip}" aria-label="${dict.save_report_tooltip}" onclick="saveReportForRow('${id}')">${dict.save_report}</button>`;
            } else {
                cell.textContent = "—";
            }
        }

        function saveReportForRow(id) {
            if (!bridge) return;
            if (byId("report").checked) return;
            bridge.saveReportForRow(id);
        }

        async function copyCellText(cell) {
            const text = (cell.textContent || "").trim();
            if (!text || text === "—") return;
            const dict = t(currentLang());
            try {
                if (bridge && bridge.copyText) {
                    bridge.copyText(text);
                } else if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(text);
                } else {
                    const ta = document.createElement("textarea");
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand("copy");
                    ta.remove();
                }
                cell.classList.remove("copied-flash");
                void cell.offsetWidth;
                cell.classList.add("copied-flash");
                showCopyToast(dict.cell_copied);
            } catch (_) {
                showCopyToast(dict.cell_copy_failed);
            }
        }

        function showCopyToast(message) {
            const el = byId("copy_toast");
            if (!el || !message) return;
            el.textContent = message;
            el.classList.add("show");
            if (copyToastTimer) {
                clearTimeout(copyToastTimer);
            }
            copyToastTimer = setTimeout(() => {
                el.classList.remove("show");
                copyToastTimer = null;
            }, 1200);
        }

        function openSyncResultModal(note, text) {
            const noteEl = byId("sync_result_note");
            const textEl = byId("sync_result_text");
            if (noteEl) noteEl.textContent = String(note || "");
            if (textEl) textEl.value = String(text || "");
            byId("sync_result_modal").classList.remove("hidden");
        }

        function closeSyncResultModal() {
            byId("sync_result_modal").classList.add("hidden");
        }

        function onSyncResultReady(content) {
            const dict = t(currentLang());
            openSyncResultModal(dict.blk_sync_popup_note || "", content || dict.blk_sync_popup_empty || "");
        }

        function initColumnResizers() {
            const headers = Array.from(document.querySelectorAll(".file-table thead th"));
            const cols = Array.from(document.querySelectorAll(".file-table colgroup col"));
            headers.forEach((th, index) => {
                if (th.id === "th_action") return;
                if (th.querySelector(".resizer")) return;
                const col = cols[index];
                if (!col) return;
                const grip = document.createElement("span");
                grip.className = "resizer";
                th.style.position = "sticky";
                th.appendChild(grip);
                let startX = 0;
                let startW = 0;
                const minW = Number(th.dataset.min || 80);
                const freezeCurrentWidths = () => {
                    cols.forEach((c) => {
                        const w = Math.max(1, Math.round(c.getBoundingClientRect().width || 1));
                        c.style.width = `${w}px`;
                    });
                };
                const syncTableWidth = () => {
                    const wrap = document.querySelector(".table-wrap");
                    const table = document.querySelector(".file-table");
                    if (!wrap || !table) return;
                    const total = cols.reduce((sum, c) => sum + (parseFloat(c.style.width) || c.getBoundingClientRect().width || 0), 0);
                    const next = Math.max(total, wrap.clientWidth || 0);
                    table.style.width = `${Math.max(1, Math.round(next))}px`;
                    table.style.minWidth = `${Math.max(1, Math.round(next))}px`;
                };
                const onMove = (e) => {
                    const dx = e.clientX - startX;
                    const next = Math.max(minW, startW + dx);
                    col.style.width = `${next}px`;
                    syncTableWidth();
                };
                const onUp = () => {
                    window.removeEventListener("mousemove", onMove);
                    window.removeEventListener("mouseup", onUp);
                    syncTableWidth();
                };
                grip.addEventListener("mousedown", (e) => {
                    e.preventDefault();
                    freezeCurrentWidths();
                    startX = e.clientX;
                    startW = col.getBoundingClientRect().width || th.getBoundingClientRect().width;
                    window.addEventListener("mousemove", onMove);
                    window.addEventListener("mouseup", onUp);
                });
            });
        }

        function setFileRow(id, data) {
            const tr = byId(`row_${id}`);
            if (!tr) return;
            const merged = Object.assign({}, fileRows.get(id) || {}, data, { id });
            fileRows.set(id, merged);
            const cells = {
                key1: byId(`${id}_key1`),
                key2: byId(`${id}_key2`),
                genshin: byId(`${id}_genshin`),
            };
            if (data.status) {
                tr.className = data.status === "ok" ? "ok" : data.status === "skipped" ? "warn" : data.status === "error" ? "err" : "pending";
                updateReportAction(id, data.status);
            }
            if (data.key1_hex_little !== undefined && cells.key1) cells.key1.textContent = data.key1_hex_little || "—";
            if (data.key2_hex_little !== undefined && cells.key2) cells.key2.textContent = data.key2_hex_little || "—";
            if (data.genshin_like_key !== undefined && cells.genshin) cells.genshin.textContent = data.genshin_like_key ?? "—";
        }

        function setFileProgress(id, progress) {
            const value = Math.max(0, Math.min(100, Number(progress || 0)));
            const fill = byId(`${id}_progress_fill`);
            const text = byId(`${id}_progress_text`);
            if (fill) fill.style.width = `${value}%`;
            if (text) text.textContent = `${value}%`;
            const row = fileRows.get(id);
            if (row) {
                row.progress = value;
                fileRows.set(id, row);
            }
        }

        function setOverallProgress(done, total) {
            const t = Math.max(0, Number(total || 0));
            const d = Math.max(0, Math.min(t, Number(done || 0)));
            const pct = t > 0 ? Math.round((d * 100) / t) : 0;
            byId("overall_progress_fill").style.width = `${pct}%`;
            byId("overall_progress_value").textContent = `${pct}%`;
        }

        function refreshFileList() {
            if (!fileRows.size) return;
            renderFileList(Array.from(fileRows.values()));
        }

        function applyLanguage(lang) {
            const dict = t(lang);
            document.documentElement.lang = lang;
            document.title = dict.app_title;
            setText("title_text", dict.app_title);
            setText("subtitle_text", dict.app_subtitle);
            setText("lang_label_text", dict.lang_label);
            setText("lang_opt_zh_cn", dict.lang_zh_cn);
            setText("lang_opt_zh_tw", dict.lang_zh_tw);
            setText("lang_opt_en", dict.lang_en);
            setText("theme_label_text", dict.theme_label);
            setText("theme_opt_dark", dict.theme_dark);
            setText("theme_opt_light", dict.theme_light);
            setText("analysis_mode_text", dict.analysis_mode);
            setText("single_file_text", dict.single_file);
            setText("batch_folder_text", dict.batch_folder);
            setText("output_label", dict.output_folder);
            setText("output_pick_btn", dict.browse);
            setText("manual_key_text", dict.manual_key);
            setText("file_list_title", dict.file_list);
            setText("overall_progress_text", dict.overall_progress);
            setText("th_progress", dict.table_progress);
            setText("th_action", dict.table_action);
            setText("th_name", dict.table_name);
            setText("th_size", dict.table_size);
            setText("th_created", dict.table_created);
            setText("th_key1", dict.table_key1);
            setText("th_key2", dict.table_key2);
            setText("th_genshin", dict.table_genshin_key);
            setText("file_table_empty", dict.table_empty);
            setText("opt_no_parallel_text", dict.disable_multiprocessing);
            setText("opt_report_text", dict.write_report);
            setText("settings_opt_no_parallel_text", dict.disable_multiprocessing);
            setText("settings_opt_report_text", dict.write_report);
            setText("report_path_label", dict.report_custom_path);
            setText("report_pick_btn", dict.pick_report_folder);
            setText("opt_fast_text", dict.fast_key_crack);
            setText("opt_extract_only_text", dict.extract_only);
            setText("opt_keep_audio_text", dict.keep_intermediate_audio);
            setText("opt_no_adx_mask_text", dict.disable_adx_mask);
            setText("opt_mux_mkv_text", dict.mux_mkv);
            setText("settings_opt_fast_text", dict.fast_key_crack);
            setText("settings_opt_extract_only_text", dict.extract_only);
            setText("settings_opt_keep_audio_text", dict.keep_intermediate_audio);
            setText("settings_opt_no_adx_mask_text", dict.disable_adx_mask);
            setText("settings_opt_mux_mkv_text", dict.mux_mkv);
            setText("settings_opt_manual_key_text", dict.manual_key);
            setText("open_log_btn", dict.open_log);
            setText("log_window_title", dict.log_window);
            setText("export_log_btn", dict.export_log);
            setText("clear_log_btn", dict.clear_log);
            setText("close_log_btn", dict.close);
            setText("run", dict.run);
            setText("blk_label", dict.blk_file_label);
            setText("blk_pick_btn", dict.btn_blk_load);
            setText("open_versions_btn", dict.btn_view_versions);
            setText("blk_versions_title", dict.blk_versions_title);
            setText("blk_versions_copy_btn", dict.blk_versions_copy);
            setText("blk_versions_sync_btn", dict.blk_versions_sync);
            setText("blk_versions_close_btn", dict.close);
            setText("sync_result_title", dict.blk_sync_popup_title || dict.blk_versions_sync);
            setText("sync_result_close_btn", dict.close);
            setText("sync_result_note", dict.blk_sync_popup_note || "");
            setPlaceholder("output", dict.placeholder_output);
            setPlaceholder("report_output", dict.placeholder_report_output);
            setPlaceholder("blk_input", dict.placeholder_blk_input);
            setPlaceholder("blk_search_input", dict.blk_search_placeholder);
            setTooltip("blk_search_case_btn", dict.blk_search_match_case);
            setTooltip("blk_search_word_btn", dict.blk_search_match_whole);
            setTooltip("blk_search_prev_btn", dict.blk_search_prev_tooltip);
            setTooltip("blk_search_next_btn", dict.blk_search_next_tooltip);
            setTooltip("blk_search_clear_btn", dict.blk_search_clear_tooltip);
            setTooltip("input_pick_btn", dict.btn_input_pick_tooltip);
            setTooltip("output_pick_btn", dict.btn_output_pick_tooltip);
            setTooltip("report_pick_btn", dict.btn_report_pick_tooltip);
            setTooltip("blk_pick_btn", dict.btn_blk_pick_tooltip);
            setTooltip("open_versions_btn", dict.btn_view_versions_tooltip);
            setText("settings_title", dict.settings_title);
            setText("settings_ok_btn", dict.settings_ok);
            setText("settings_cancel_btn", dict.settings_cancel);
            setTooltip("open_settings_btn", dict.btn_settings_tooltip);
            setTooltip("open_log_btn", dict.btn_logs_tooltip);
            setTooltip("run", dict.btn_run_tooltip);
            setTooltip("export_log_btn", dict.btn_export_log_tooltip);
            setTooltip("clear_log_btn", dict.btn_clear_log_tooltip);
            setTooltip("close_log_btn", dict.btn_close_log_tooltip);
            setTooltip("settings_ok_btn", dict.btn_settings_ok_tooltip);
            setTooltip("settings_cancel_btn", dict.btn_settings_cancel_tooltip);
            setTooltip("blk_versions_copy_btn", dict.btn_blk_versions_copy_tooltip);
            setTooltip("blk_versions_sync_btn", dict.btn_blk_versions_sync_tooltip);
            setTooltip("blk_versions_close_btn", dict.btn_blk_versions_close_tooltip);
            byId("open_settings_btn").textContent = dict.settings_title;
            byId("open_log_btn").textContent = dict.open_log;
            byId("run").textContent = dict.run;
            document.getElementById("opt_disable_multiprocessing_tooltip").textContent = dict.opt_disable_multiprocessing_tooltip;
            document.getElementById("opt_write_report_tooltip").textContent = dict.opt_write_report_tooltip;
            document.getElementById("opt_fast_key_crack_tooltip").textContent = dict.opt_fast_key_crack_tooltip;
            document.getElementById("opt_extract_only_tooltip").textContent = dict.opt_extract_only_tooltip;
            document.getElementById("opt_keep_intermediate_audio_tooltip").textContent = dict.opt_keep_intermediate_audio_tooltip;
            document.getElementById("opt_disable_adx_mask_tooltip").textContent = dict.opt_disable_adx_mask_tooltip;
            document.getElementById("opt_mux_mkv_tooltip").textContent = dict.opt_mux_mkv_tooltip;
            document.getElementById("opt_manual_key_tooltip").textContent = dict.opt_manual_key_tooltip;
            refreshFileList();
            syncInputMode(true);
            syncRules();
            updateManualKeyVisibility();
            renderBlkStatus();
            renderBlkModal();
            updateBlkSearchStatus();
            renderLogBox();
            initColumnResizers();
        }

        function appendLog(line) {
            if ((line || "").trim().length === 0) {
                return;
            }
            lastLogLine = line;
            lastLogTs = Date.now();
            logLines.push(line);
            renderLogBox();
        }

        function hasUsableLogs() {
            return logLines.some((line) => (line || "").trim().length > 0);
        }

        function updateLogUiState() {
            const exportBtn = byId("export_log_btn");
            const clearBtn = byId("clear_log_btn");
            const hasLogs = hasUsableLogs();
            if (exportBtn) exportBtn.disabled = !hasLogs;
            if (clearBtn) clearBtn.disabled = !hasLogs;
        }

        function renderLogBox() {
            const box = byId("log_box");
            if (!box) return;
            if (!hasUsableLogs()) {
                box.classList.add("empty");
                box.textContent = t(currentLang()).log_empty_placeholder;
            } else {
                box.classList.remove("empty");
                box.textContent = logLines.join("\\n");
                box.scrollTop = box.scrollHeight;
            }
            updateLogUiState();
        }

        function clearLog() {
            if (!hasUsableLogs()) {
                updateLogUiState();
                return;
            }
            logLines = [];
            lastLogLine = null;
            lastLogTs = 0;
            renderLogBox();
        }

        function exportLog() {
            if (!bridge || !hasUsableLogs()) return;
            const content = logLines.join("\\n");
            const ts = new Date().toISOString().replace(/[.:]/g, "-");
            const name = "usmdiviner-log-" + ts + ".txt";
            bridge.exportLog(content, name);
        }

        function openLogModal() {
            byId("log_modal").classList.remove("hidden");
            renderLogBox();
        }

        function closeLogModal() {
            byId("log_modal").classList.add("hidden");
        }

        function openSettingsModal() {
            syncCheckboxesToToggles();
            updateManualKeyVisibility();
            byId("settings_modal").classList.remove("hidden");
        }

        function closeSettingsModal(apply) {
            if (apply) {
                syncTogglesToCheckboxes();
                syncRules();
            } else {
                syncCheckboxesToToggles();
            }
            updateManualKeyVisibility();
            byId("settings_modal").classList.add("hidden");
        }

        function updateManualKeyVisibility() {
            const toggle = byId("manual_key_toggle");
            const row = byId("manual_key_row");
            if (!toggle || !row) return;
            row.classList.toggle("hidden", !toggle.checked);
        }

        function syncCheckboxesToToggles() {
            byId("no_parallel_toggle").checked = byId("no_parallel").checked;
            byId("report_toggle").checked = byId("report").checked;
            byId("fast_toggle").checked = byId("fast").checked;
            byId("extract_only_toggle").checked = byId("extract_only").checked;
            byId("keep_audio_toggle").checked = byId("keep_audio").checked;
            byId("no_adx_mask_toggle").checked = byId("no_adx_mask").checked;
            byId("mux_mkv_toggle").checked = byId("mux_mkv").checked;
            byId("manual_key_toggle").checked = !!(byId("key") && byId("key").value.trim());
        }

        function syncTogglesToCheckboxes() {
            byId("no_parallel").checked = byId("no_parallel_toggle").checked;
            byId("report").checked = byId("report_toggle").checked;
            byId("fast").checked = byId("fast_toggle").checked;
            byId("extract_only").checked = byId("extract_only_toggle").checked;
            byId("keep_audio").checked = byId("keep_audio_toggle").checked;
            byId("no_adx_mask").checked = byId("no_adx_mask_toggle").checked;
            byId("mux_mkv").checked = byId("mux_mkv_toggle").checked;
            if (!byId("manual_key_toggle").checked && byId("key")) {
                byId("key").value = "";
            }
        }

        function setRunning(running) {
            const run = byId("run");
            const dict = t(currentLang());
            run.disabled = running;
            run.textContent = running ? dict.running : dict.run;
        }

        function setField(field, value) {
            const el = byId(field);
            if (el) el.value = value;
            if (field === "input") {
                previewInput();
            } else if (field === "blk_input") {
                blkParsePending = true;
                blkVersionsData = null;
                renderBlkStatus();
                renderBlkModal();
            }
        }

        function renderBlkStatus() {
            const btn = byId("open_versions_btn");
            if (!btn) return;
            const hasVersions = !!(blkVersionsData && !blkVersionsData.error &&
                blkVersionsData.versions_json && blkVersionsData.versions_json !== "null");
            if (hasVersions) {
                btn.classList.remove("hidden");
            } else {
                btn.classList.add("hidden");
            }
        }

        function renderBlkModal() {
            const summary = byId("blk_versions_summary");
            const summaryPath = byId("blk_versions_path");
            const box = byId("blk_versions_box");
            const dict = t(currentLang());
            const blkPathEl = byId("blk_input");
            const blkPath = blkPathEl ? blkPathEl.value : "";
            if (!summary || !summaryPath || !box) return;
            if (!blkVersionsData || !blkVersionsData.versions_json || blkVersionsData.versions_json === "null") {
                summary.textContent = dict.blk_versions_modal_empty;
                summaryPath.textContent = dict.blk_versions_modal_path
                    .replace("{path}", String(blkPath || "—"));
                box.textContent = "";
                blkSearchMatches = [];
                blkSearchIndex = -1;
                updateBlkSearchStatus();
                return;
            }
            const count = blkEntryCount(blkVersionsData.versions_list);
            const source = blkVersionsData.versions ? blkVersionsData.versions.source : null;
            const kind = blkVersionsData.versions ? blkVersionsData.versions.kind : null;
            const offset = blkVersionsData.versions ? blkVersionsData.versions.offset : null;
            const gameVersion = extractBlkGameVersion();
            summary.textContent = dict.blk_versions_modal_summary
                .replace("{count}", String(count))
                .replace("{source}", String(source || "—"))
                .replace("{kind}", String(kind || "—"))
                .replace("{offset}", String(offset === null || offset === undefined ? "—" : offset))
                .replace("{game_version}", String(gameVersion || "—"));
            summaryPath.textContent = dict.blk_versions_modal_path
                .replace("{path}", String(blkPath || "—"));
            const raw = String(blkVersionsData.versions_json || "");
            if (!blkSearchQuery) {
                box.textContent = raw;
                blkSearchMatches = [];
                blkSearchIndex = -1;
                updateBlkSearchStatus();
                return;
            }
            const highlighted = highlightMatches(raw, blkSearchQuery);
            box.innerHTML = highlighted.html;
            blkSearchMatches = Array.from(box.querySelectorAll("mark.blk-search-hit"));
            if (blkSearchMatches.length <= 0) {
                blkSearchIndex = -1;
                updateBlkSearchStatus();
                return;
            }
            if (blkSearchIndex < 0 || blkSearchIndex >= blkSearchMatches.length) {
                blkSearchIndex = 0;
            }
            focusBlkSearchHit(blkSearchIndex);
        }

        function updateBlkSearchStatus() {
            const status = byId("blk_search_status");
            const prevBtn = byId("blk_search_prev_btn");
            const nextBtn = byId("blk_search_next_btn");
            const clearBtn = byId("blk_search_clear_btn");
            const caseBtn = byId("blk_search_case_btn");
            const wordBtn = byId("blk_search_word_btn");
            const input = byId("blk_search_input");
            const hasQueryText = String(input ? input.value : (blkSearchQuery || "")).length > 0;
            if (status) {
                if (!blkSearchQuery || blkSearchMatches.length <= 0 || blkSearchIndex < 0) {
                    status.textContent = "0/0";
                } else {
                    status.textContent = `${blkSearchIndex + 1}/${blkSearchMatches.length}`;
                }
            }
            const hasHits = blkSearchMatches.length > 0 && blkSearchIndex >= 0;
            if (prevBtn) prevBtn.disabled = !hasHits;
            if (nextBtn) nextBtn.disabled = !hasHits;
            if (clearBtn) clearBtn.disabled = !hasQueryText;
            if (caseBtn) caseBtn.classList.toggle("active", blkSearchCaseSensitive);
            if (wordBtn) wordBtn.classList.toggle("active", blkSearchWholeWord);
        }

        function focusBlkSearchHit(index) {
            if (blkSearchMatches.length <= 0) {
                blkSearchIndex = -1;
                updateBlkSearchStatus();
                return;
            }
            const safeIndex = ((index % blkSearchMatches.length) + blkSearchMatches.length) % blkSearchMatches.length;
            blkSearchIndex = safeIndex;
            blkSearchMatches.forEach((el) => el.classList.remove("blk-search-hit-active"));
            const active = blkSearchMatches[safeIndex];
            if (active) {
                active.classList.add("blk-search-hit-active");
                active.scrollIntoView({ block: "center" });
            }
            updateBlkSearchStatus();
        }

        function escapeHtml(text) {
            return String(text || "")
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#39;");
        }

        function isBlkWordChar(ch) {
            return /[0-9A-Za-z_]/.test(String(ch || ""));
        }

        function findBlkSearchMatches(source, query) {
            const text = String(source || "");
            const needleRaw = String(query || "");
            if (!needleRaw) return [];

            const haystack = blkSearchCaseSensitive ? text : text.toLowerCase();
            const needle = blkSearchCaseSensitive ? needleRaw : needleRaw.toLowerCase();
            const matches = [];
            let cursor = 0;

            while (cursor <= haystack.length - needle.length) {
                const found = haystack.indexOf(needle, cursor);
                if (found < 0) break;
                const end = found + needle.length;

                if (blkSearchWholeWord) {
                    const left = found <= 0 ? "" : text.charAt(found - 1);
                    const right = end >= text.length ? "" : text.charAt(end);
                    const leftOk = !isBlkWordChar(left);
                    const rightOk = !isBlkWordChar(right);
                    if (!leftOk || !rightOk) {
                        cursor = found + 1;
                        continue;
                    }
                }

                matches.push({ start: found, end });
                cursor = found + Math.max(needle.length, 1);
            }

            return matches;
        }

        function highlightMatches(raw, query) {
            const source = String(raw || "");
            const ranges = findBlkSearchMatches(source, query);
            if (ranges.length <= 0) {
                return { html: escapeHtml(source), count: 0 };
            }
            const parts = [];
            let cursor = 0;
            for (const range of ranges) {
                parts.push(escapeHtml(source.slice(cursor, range.start)));
                parts.push(`<mark class="blk-search-hit">${escapeHtml(source.slice(range.start, range.end))}</mark>`);
                cursor = range.end;
            }
            parts.push(escapeHtml(source.slice(cursor)));
            return { html: parts.join(""), count: ranges.length };
        }

        function onBlkSearchInput() {
            const input = byId("blk_search_input");
            blkSearchQuery = (input ? input.value : "");
            blkSearchIndex = -1;
            renderBlkModal();
        }

        function handleBlkSearchKey(event) {
            if (!event || event.key !== "Enter") return;
            event.preventDefault();
            if (blkSearchMatches.length <= 0) {
                onBlkSearchInput();
                return;
            }
            if (event.shiftKey) {
                focusPrevBlkSearchHit();
            } else {
                focusNextBlkSearchHit();
            }
        }

        function toggleBlkSearchCase() {
            blkSearchCaseSensitive = !blkSearchCaseSensitive;
            blkSearchIndex = -1;
            renderBlkModal();
        }

        function toggleBlkSearchWholeWord() {
            blkSearchWholeWord = !blkSearchWholeWord;
            blkSearchIndex = -1;
            renderBlkModal();
        }

        function applyBlkSearch() {
            const input = byId("blk_search_input");
            blkSearchQuery = (input ? input.value : "");
            blkSearchIndex = -1;
            renderBlkModal();
        }

        function resetBlkSearch() {
            blkSearchQuery = "";
            blkSearchMatches = [];
            blkSearchIndex = -1;
            const input = byId("blk_search_input");
            if (input) input.value = "";
            renderBlkModal();
        }

        function focusPrevBlkSearchHit() {
            if (blkSearchMatches.length <= 0) return;
            focusBlkSearchHit(blkSearchIndex - 1);
        }

        function focusNextBlkSearchHit() {
            if (blkSearchMatches.length <= 0) return;
            focusBlkSearchHit(blkSearchIndex + 1);
        }

        function setBlkVersions(payloadJson) {
            blkParsePending = false;
            try {
                blkVersionsData = JSON.parse(payloadJson);
            } catch (_) {
                blkVersionsData = { error: payloadJson };
            }
            renderBlkStatus();
            renderBlkModal();
        }

        function pickBlkInput() {
            if (!bridge) return;
            bridge.pickBlkFile();
        }

        function openBlkVersionsModal() {
            renderBlkModal();
            byId("blk_versions_modal").classList.remove("hidden");
            const searchInput = byId("blk_search_input");
            if (searchInput) searchInput.focus();
        }

        function closeBlkVersionsModal() {
            byId("blk_versions_modal").classList.add("hidden");
        }

        async function copyBlkVersions() {
            if (!blkVersionsData || !blkVersionsData.versions_json || blkVersionsData.versions_json === "null") return;
            const text = blkVersionsData.versions_json;
            const dict = t(currentLang());
            try {
                if (bridge && bridge.copyText) {
                    bridge.copyText(text);
                } else if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(text);
                } else {
                    const ta = document.createElement("textarea");
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand("copy");
                    ta.remove();
                }
                showCopyToast(dict.blk_versions_copied);
            } catch (_) {
                showCopyToast(dict.blk_versions_copy_failed || dict.cell_copy_failed);
            }
        }

        function syncBlkKeysFromUsmRows() {
            const dict = t(currentLang());
            if (!blkVersionsData || !blkVersionsData.versions_json || blkVersionsData.versions_json === "null") {
                showCopyToast(dict.blk_versions_sync_no_data);
                return;
            }
            if (!bridge || !bridge.syncBlkKeysFromRows) {
                showCopyToast(dict.blk_versions_sync_no_bridge);
                return;
            }
            openSyncResultModal(
                dict.blk_sync_popup_note || "",
                dict.blk_sync_dialog_waiting || dict.blk_sync_started_toast || dict.blk_versions_sync
            );
            const rows = Array.from(fileRows.values() || []);
            bridge.syncBlkKeysFromRows(JSON.stringify(rows));
        }

        function getInputMode() {
            return byId("mode_batch").checked ? "batch" : "single";
        }

        function syncInputMode(preserveState = false) {
            const mode = getInputMode();
            const dict = t(currentLang());
            byId("input_label").textContent = mode === "batch" ? dict.input_usm_folder : dict.input_usm_file;
            byId("input_pick_btn").textContent = mode === "batch" ? dict.pick : dict.browse;
            byId("input").placeholder = mode === "batch" ? dict.placeholder_input_folder : dict.placeholder_input_file;
            if (preserveState) {
                return;
            }
            byId("input").value = "";
            renderFileList([]);
            setOverallProgress(0, 0);
        }

        function previewInput() {
            if (!bridge) return;
            bridge.previewInput(getInputMode(), byId("input").value);
        }

        function pickInput() {
            if (!bridge) return;
            bridge.pickInput(getInputMode());
        }

        function loadFileList(rowsJson) {
            const rows = JSON.parse(rowsJson);
            renderFileList(rows);
        }

        function updateFileRow(rowJson) {
            const row = JSON.parse(rowJson);
            setFileRow(row.id, row);
        }

        function updateFileProgress(progressJson) {
            const data = JSON.parse(progressJson);
            setFileProgress(data.id, data.progress);
        }

        function updateOverallProgress(progressJson) {
            const data = JSON.parse(progressJson);
            setOverallProgress(data.done, data.total);
        }

        function syncRules() {
            const extractOnly = byId("extract_only").checked;
            const mux = byId("mux_mkv");
            const fast = byId("fast");
            const report = byId("report");
            const reportRow = byId("report_path_row");
            if (extractOnly) {
                mux.checked = false;
                fast.checked = false;
            }
            mux.disabled = extractOnly;
            fast.disabled = false;
            reportRow.style.display = report.checked ? "grid" : "none";
            fileRows.forEach((row, id) => updateReportAction(id, row.status || "pending"));
        }

        function setLanguage(lang) {
            if (bridge) {
                bridge.setLanguage(lang);
            }
            applyLanguage(lang);
        }

        function applyTheme(theme) {
            const mode = theme === "light" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", mode);
            byId("theme_select").value = mode;
            try {
                localStorage.setItem("usmdiviner_theme", mode);
            } catch (_) {
                // Ignore storage errors in restricted runtime.
            }
        }

        function setTheme(theme) {
            applyTheme(theme);
        }

        function runTask() {
            if (!bridge) return;
            setOverallProgress(0, 0);
            const payload = {
                language: currentLang(),
                input_mode: getInputMode(),
                input: byId("input").value,
                output: byId("output").value,
                report_output: byId("report_output").value,
                key: byId("manual_key_toggle").checked ? byId("key").value : "",
                no_parallel: byId("no_parallel").checked,
                report: byId("report").checked,
                fast: byId("fast").checked,
                extract_only: byId("extract_only").checked,
                keep_audio: byId("keep_audio").checked,
                no_adx_mask: byId("no_adx_mask").checked,
                mux_mkv: byId("mux_mkv").checked,
            };
            bridge.runTask(JSON.stringify(payload));
        }

        new QWebChannel(qt.webChannelTransport, function(channel) {
            if (window.__usmBridgeBound) {
                return;
            }
            window.__usmBridgeBound = true;
            bridge = channel.objects.bridge;
            bridge.logMessage.connect(appendLog);
            bridge.uiToast.connect(showCopyToast);
            bridge.syncResultReady.connect(onSyncResultReady);
            bridge.runStateChanged.connect(setRunning);
            bridge.fieldChosen.connect(setField);
            bridge.fileListReady.connect(loadFileList);
            bridge.fileRowUpdate.connect(updateFileRow);
            bridge.fileProgressUpdate.connect(updateFileProgress);
            bridge.overallProgressUpdate.connect(updateOverallProgress);
            bridge.blkVersionsReady.connect(setBlkVersions);
            try {
                const storedTheme = localStorage.getItem("usmdiviner_theme") || "dark";
                applyTheme(storedTheme);
            } catch (_) {
                applyTheme("dark");
            }
            const lang = byId("lang_select").value || "zh-CN";
            bridge.setLanguage(lang);
            applyLanguage(lang);
        });
    </script>
</body>
</html>
"""


def _render_html() -> str:
    font_url = "assets/fonts/zh-cn.ttf" if FONT_PATH.exists() else ""
    # Embed translations as a JSON string literal to avoid accidental script parse errors.
    translations_json = json.dumps(TRANSLATIONS, ensure_ascii=False)
    translations_js_string = json.dumps(translations_json)
    html = HTML_TEMPLATE.replace("__TRANSLATIONS_JSON__", translations_js_string)
    return html.replace("__FONT_URL__", font_url)


class _QtLogHandler(logging.Handler):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._callback(msg)
        except Exception:
            self.handleError(record)


class WebBridge(QObject):
    logMessage = Signal(str)
    uiToast = Signal(str)
    syncResultReady = Signal(str)
    runStateChanged = Signal(bool)
    windowTitleChanged = Signal(str)
    fieldChosen = Signal(str, str)
    blkVersionsReady = Signal(str)
    fileListReady = Signal(str)
    fileRowUpdate = Signal(str)
    fileProgressUpdate = Signal(str)
    overallProgressUpdate = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._worker: threading.Thread | None = None
        self._blk_worker: threading.Thread | None = None
        self._blk_result_lock = threading.Lock()
        self._last_blk_result: dict | None = None
        self._language = DEFAULT_LANGUAGE
        self._language_lock = threading.Lock()
        self._reports_by_id: dict[str, dict] = {}
        self._reports_lock = threading.Lock()

    def _set_language(self, language: str) -> None:
        lang = language if language in TRANSLATIONS else DEFAULT_LANGUAGE
        with self._language_lock:
            self._language = lang

    def _get_language(self) -> str:
        with self._language_lock:
            return self._language

    def _t(self, key: str, **kwargs) -> str:
        return _t(self._get_language(), key, **kwargs)

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        self._set_language(language)
        self.windowTitleChanged.emit(self._t("app_title"))

    @Slot(str)
    def copyText(self, text: str) -> None:
        QApplication.clipboard().setText(str(text or ""))

    @Slot(str)
    def pickInput(self, mode: str) -> None:
        if mode == "batch":
            picked_dir = QFileDialog.getExistingDirectory(None, self._t("select_usm_folder"))
            if picked_dir:
                self.fieldChosen.emit("input", picked_dir)
                self._emit_preview_list(mode, picked_dir)
            return

        picked_file, _ = QFileDialog.getOpenFileName(
            None,
            self._t("select_usm_file"),
            "",
            "USM (*.usm);;All files (*.*)",
        )
        if picked_file:
            self.fieldChosen.emit("input", picked_file)
            self._emit_preview_list(mode, picked_file)

    @Slot()
    def pickBlkFile(self) -> None:
        picked_file, _ = QFileDialog.getOpenFileName(
            None,
            self._t("select_blk_file"),
            "",
            "BLK (*.blk);;BLB (*.blb);;All files (*.*)",
        )
        if not picked_file:
            return
        self.fieldChosen.emit("blk_input", picked_file)
        self._start_blk_parse(Path(picked_file))

    def _start_blk_parse(self, input_path: Path) -> None:
        if self._blk_worker and self._blk_worker.is_alive():
            self.logMessage.emit(self._t("blk_parse_running"))
            return
        self.logMessage.emit(self._t("blk_parse_started", path=input_path.name))
        self._blk_worker = threading.Thread(target=self._run_blk_job, args=(input_path,), daemon=True)
        self._blk_worker.start()

    def _run_blk_job(self, input_path: Path) -> None:
        try:
            result = parse_blk_versions(input_path)
        except Exception as exc:
            with self._blk_result_lock:
                self._last_blk_result = None
            self.blkVersionsReady.emit(
                json.dumps(
                    {
                        "input": str(input_path),
                        "error": self._t("blk_parse_failed", reason=exc),
                        "versions": None,
                        "versions_list": None,
                        "versions_json": None,
                    },
                    ensure_ascii=False,
                )
            )
            self.logMessage.emit(self._t("blk_parse_failed", reason=exc))
            return

        count = int(result.get("inner_file_count") or 0)
        candidates = result.get("rawdata_candidates") or []
        versions = result.get("versions")
        versions_list = result.get("versions_list")
        with self._blk_result_lock:
            self._last_blk_result = result
        self.blkVersionsReady.emit(json.dumps(result, ensure_ascii=False))
        if versions_list:
            self.logMessage.emit(
                self._t("blk_parse_success", count=count, candidates=len(candidates), entries=len(versions_list))
            )
        else:
            self.logMessage.emit(
                self._t("blk_parse_no_versions", count=count, candidates=len(candidates))
            )

    @staticmethod
    def _norm_video_name(name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            return ""
        lowered = raw.lower()
        if lowered.endswith(".usm"):
            lowered = lowered[:-4]
        return lowered

    @staticmethod
    def _parse_sync_key(value) -> int | None:
        text = str(value or "").strip()
        if not text or text in {"—", "-", "None", "null"}:
            return None
        if text.startswith("0x") or text.startswith("0X"):
            try:
                return int(text, 16)
            except ValueError:
                return None
        try:
            return int(text)
        except ValueError:
            return None

    @staticmethod
    def _key_first_dict(data: dict[str, Any]) -> dict[str, Any]:
        ordered: dict[str, Any] = {}
        if "key" in data:
            ordered["key"] = data["key"]
        if "version" in data:
            ordered["version"] = data["version"]
        for key, value in data.items():
            if key in {"key", "version"}:
                continue
            ordered[key] = value
        return ordered

    @staticmethod
    def _short_sync_videos(videos: Any) -> str:
        if not isinstance(videos, list):
            return "—"
        items = [str(v or "").strip() for v in videos if str(v or "").strip()]
        if not items:
            return "—"
        return ", ".join(items)

    @staticmethod
    def _is_ignored_test_video(name: str) -> bool:
        return "test" in str(name or "").lower()

    def _describe_sync_target(
        self,
        item: dict[str, Any],
        group: dict[str, Any] | None = None,
        videos: Any | None = None,
    ) -> str:
        parent_version = str(item.get("version") or "").strip() or "—"
        item_videos = item.get("videos") if videos is None else videos
        if group is None:
            return f"version={parent_version}, videos={self._short_sync_videos(item_videos)}"
        group_version = str(group.get("version") or "").strip() or "—"
        group_videos = group.get("videos") if videos is None else videos
        return (
            f"version={parent_version}, group={group_version}, "
            f"videos={self._short_sync_videos(group_videos)}"
        )

    def _build_sync_popup_text(self, unresolved_details: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for detail in unresolved_details:
            game_version = str(detail.get("game_version") or "—")
            owner_version = str(detail.get("owner_version") or "—")
            for usm in detail.get("videos") or []:
                lines.append(
                    self._t(
                        "blk_sync_popup_item",
                        usm=str(usm or "").strip() or "—",
                        owner_version=owner_version,
                        game_version=game_version,
                    )
                )
        if not lines:
            return self._t("blk_sync_popup_empty")
        return "\n".join(lines)

    def _build_template_key_map(self) -> tuple[dict[str, int], str | None]:
        def add_videos(mapping: dict[str, int], videos: Any, key_val: int | None) -> None:
            if key_val is None or not isinstance(videos, list):
                return
            for video_name in videos:
                normalized = self._norm_video_name(str(video_name or ""))
                if normalized:
                    mapping[normalized] = key_val

        for template_path in SYNC_TEMPLATE_CANDIDATES:
            if not template_path.exists() or not template_path.is_file():
                continue
            try:
                decoded = json.loads(template_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if isinstance(decoded, dict):
                versions_list = decoded.get("list")
            elif isinstance(decoded, list):
                versions_list = decoded
            else:
                versions_list = None

            if not isinstance(versions_list, list):
                continue

            mapping: dict[str, int] = {}
            for item in versions_list:
                if not isinstance(item, dict):
                    continue
                add_videos(mapping, item.get("videos"), self._parse_sync_key(item.get("key")))
                groups = item.get("videoGroups")
                if isinstance(groups, list):
                    for group in groups:
                        if not isinstance(group, dict):
                            continue
                        add_videos(mapping, group.get("videos"), self._parse_sync_key(group.get("key")))

            if mapping:
                return mapping, str(template_path)

        return {}, None

    @Slot(str)
    def syncBlkKeysFromRows(self, rows_json: str) -> None:
        with self._blk_result_lock:
            if not self._last_blk_result:
                self.logMessage.emit(self._t("blk_sync_no_data"))
                return
            result = json.loads(json.dumps(self._last_blk_result, ensure_ascii=False))

        versions_json = result.get("versions_json")
        if not versions_json or versions_json == "null":
            self.logMessage.emit(self._t("blk_sync_no_data"))
            return

        try:
            rows = json.loads(rows_json or "[]")
        except json.JSONDecodeError:
            rows = []

        name_to_key, template_path = self._build_template_key_map()
        if template_path:
            self.logMessage.emit(
                self._t("blk_sync_template_loaded", path=template_path, count=len(name_to_key))
            )
        else:
            self.logMessage.emit(self._t("blk_sync_template_missing"))

        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            key_val = self._parse_sync_key(row.get("genshin_like_key"))
            if key_val is None:
                continue
            row_name = str(row.get("name") or "").strip()
            row_path = str(row.get("path") or "").strip()
            candidates: set[str] = set()
            if row_name:
                candidates.add(self._norm_video_name(row_name))
            if row_path:
                candidates.add(self._norm_video_name(Path(row_path).name))
                candidates.add(self._norm_video_name(Path(row_path).stem))
            for c in candidates:
                if c:
                    # Current USM results override template mapping.
                    name_to_key[c] = key_val

        if not name_to_key:
            self.logMessage.emit(self._t("blk_sync_no_usm_keys"))
            return

        try:
            versions_decoded = json.loads(versions_json)
        except json.JSONDecodeError:
            self.logMessage.emit(self._t("blk_sync_no_data"))
            return

        if not isinstance(versions_decoded, dict):
            self.logMessage.emit(self._t("blk_sync_no_data"))
            return

        versions_list = versions_decoded.get("list")
        if not isinstance(versions_list, list):
            self.logMessage.emit(self._t("blk_sync_no_data"))
            return

        updated_groups = 0
        skipped_groups = 0
        unresolved_details: list[dict[str, Any]] = []
        ignored_test_details: list[dict[str, str]] = []

        for item in versions_list:
            if not isinstance(item, dict):
                continue

            groups = item.get("videoGroups")
            if isinstance(groups, list):
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    if group.get("key") not in (None, "", "—"):
                        continue
                    videos = group.get("videos")
                    if not isinstance(videos, list):
                        continue
                    non_test_videos = [
                        str(v or "").strip()
                        for v in videos
                        if str(v or "").strip() and not self._is_ignored_test_video(str(v or ""))
                    ]
                    if not non_test_videos:
                        skipped_groups += 1
                        ignored_test_details.append(
                            {"label": self._describe_sync_target(item, group, videos=videos)}
                        )
                        continue
                    matched_key = None
                    for v in non_test_videos:
                        norm = self._norm_video_name(str(v or ""))
                        if not norm:
                            continue
                        key_val = name_to_key.get(norm)
                        if key_val is None:
                            continue
                        matched_key = key_val
                        break
                    if matched_key is not None:
                        group["key"] = matched_key
                        updated_groups += 1
                    else:
                        unresolved_details.append(
                            {
                                "label": self._describe_sync_target(item, group, videos=non_test_videos),
                                "game_version": str(item.get("version") or "").strip() or "—",
                                "owner_version": str(group.get("version") or "").strip() or "—",
                                "videos": non_test_videos,
                            }
                        )
                continue

            # Legacy versions format: version entry has videos + single key.
            if item.get("key") not in (None, "", "—"):
                continue
            videos = item.get("videos")
            if not isinstance(videos, list):
                continue
            non_test_videos = [
                str(v or "").strip()
                for v in videos
                if str(v or "").strip() and not self._is_ignored_test_video(str(v or ""))
            ]
            if not non_test_videos:
                skipped_groups += 1
                ignored_test_details.append(
                    {"label": self._describe_sync_target(item, videos=videos)}
                )
                continue
            matched_key = None
            for v in non_test_videos:
                norm = self._norm_video_name(str(v or ""))
                if not norm:
                    continue
                key_val = name_to_key.get(norm)
                if key_val is None:
                    continue
                matched_key = key_val
                break
            if matched_key is not None:
                item["key"] = matched_key
                updated_groups += 1
            else:
                unresolved_details.append(
                    {
                        "label": self._describe_sync_target(item, videos=non_test_videos),
                        "game_version": str(item.get("version") or "").strip() or "—",
                        "owner_version": str(item.get("version") or "").strip() or "—",
                        "videos": non_test_videos,
                    }
                )

        unresolved_groups = len(unresolved_details)

        # Keep stable field order: key must appear before version.
        normalized_list: list[dict[str, Any]] = []
        for item in versions_list:
            if not isinstance(item, dict):
                continue
            groups = item.get("videoGroups")
            if isinstance(groups, list):
                normalized_groups: list[dict[str, Any]] = []
                for group in groups:
                    if isinstance(group, dict):
                        normalized_groups.append(self._key_first_dict(group))
                item["videoGroups"] = normalized_groups
            normalized_list.append(self._key_first_dict(item))
        versions_list = normalized_list
        versions_decoded["list"] = versions_list

        result["versions_list"] = versions_list
        result["versions_json"] = json.dumps(versions_decoded, ensure_ascii=False, indent=2)
        if isinstance(result.get("versions"), dict):
            result["versions"]["list"] = versions_list
            result["versions"]["decoded_json"] = versions_decoded

        with self._blk_result_lock:
            self._last_blk_result = result

        self.blkVersionsReady.emit(json.dumps(result, ensure_ascii=False))
        self.logMessage.emit(
            self._t(
                "blk_sync_done",
                updated=updated_groups,
                unresolved=unresolved_groups,
                skipped=skipped_groups,
            )
        )
        self.syncResultReady.emit(self._build_sync_popup_text(unresolved_details))
        if unresolved_details:
            self.logMessage.emit(self._t("blk_sync_unresolved_header", count=len(unresolved_details)))
            for detail in unresolved_details:
                self.logMessage.emit(self._t("blk_sync_detail_item", label=detail["label"]))
        if ignored_test_details:
            self.logMessage.emit(self._t("blk_sync_ignored_test_header", count=len(ignored_test_details)))
            for detail in ignored_test_details:
                self.logMessage.emit(self._t("blk_sync_detail_item", label=detail["label"]))

    @Slot(str, str)
    def previewInput(self, mode: str, raw_input: str) -> None:
        self._emit_preview_list(mode, raw_input)

    def _emit_preview_list(self, mode: str, raw_input: str) -> None:
        input_text = str(raw_input or "").strip()
        if not input_text:
            self.fileListReady.emit(json.dumps([], ensure_ascii=False))
            self.overallProgressUpdate.emit(json.dumps({"done": 0, "total": 0}, ensure_ascii=False))
            return

        input_path = Path(input_text)
        files: list[Path] = []
        normalized_mode = str(mode or "single").strip().lower()
        if normalized_mode == "batch":
            if input_path.exists() and input_path.is_dir():
                files = collect_usm_inputs(input_path)
        else:
            if (
                input_path.exists()
                and input_path.is_file()
                and input_path.suffix.lower() == ".usm"
            ):
                files = [input_path]

        rows, _ = self._build_file_rows(files)
        self.fileListReady.emit(json.dumps(rows, ensure_ascii=False))
        self.overallProgressUpdate.emit(
            json.dumps({"done": 0, "total": len(files)}, ensure_ascii=False)
        )

    @Slot()
    def pickOutput(self) -> None:
        picked_dir = QFileDialog.getExistingDirectory(None, self._t("select_output_folder"))
        if picked_dir:
            self.fieldChosen.emit("output", picked_dir)

    @Slot()
    def pickReportOutput(self) -> None:
        picked_dir = QFileDialog.getExistingDirectory(None, self._t("pick_report_folder"))
        if picked_dir:
            self.fieldChosen.emit("report_output", picked_dir)

    @Slot(str)
    def saveReportForRow(self, row_id: str) -> None:
        with self._reports_lock:
            report = self._reports_by_id.get(str(row_id))
        if not report:
            self.logMessage.emit(self._t("report_not_ready"))
            return

        source = Path(str(report.get("file") or "report"))
        default_name = f"{source.stem}_Report.json" if source.stem else "USM_Report.json"
        default_dir = str(source.parent) if source.parent.exists() else os.getcwd()
        default_path = str(Path(default_dir) / default_name)

        target_path, _ = QFileDialog.getSaveFileName(
            None,
            self._t("select_report_save_file"),
            default_path,
            "JSON (*.json);;All files (*.*)",
        )
        if not target_path:
            return

        try:
            Path(target_path).write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self.logMessage.emit(self._t("error_line", file=source.name, reason=exc))
            return
        self.logMessage.emit(self._t("report_saved_to", path=target_path))

    @Slot(str, str)
    def exportLog(self, content: str, suggested_name: str) -> None:
        base_dir = ASSETS_DIR.parent.resolve()
        fallback_name = Path(str(suggested_name or "").strip() or "usmdiviner-log.txt").name
        default_path = str(base_dir / fallback_name)

        target_path, _ = QFileDialog.getSaveFileName(
            None,
            self._t("select_log_save_file"),
            default_path,
            "Text (*.txt);;All files (*.*)",
        )
        if not target_path:
            target_path = default_path

        try:
            Path(target_path).write_text(str(content or ""), encoding="utf-8")
        except OSError as exc:
            self.logMessage.emit(self._t("log_export_failed", reason=exc))
            return

        self.logMessage.emit(self._t("log_exported", path=target_path))

    @Slot(str)
    def runTask(self, payload_json: str) -> None:
        if self._worker and self._worker.is_alive():
            return
        try:
            payload = json.loads(payload_json)
            language = str(payload.get("language") or self._get_language())
            self._set_language(language)
            config = self._collect_config(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            self.logMessage.emit(self._t("invalid_options", reason=exc))
            return

        self.runStateChanged.emit(True)
        self.logMessage.emit(self._t("start"))
        self._worker = threading.Thread(target=self._run_job, args=(config,), daemon=True)
        self._worker.start()

    def _collect_config(self, payload: dict) -> dict:
        input_mode = str(payload.get("input_mode") or "single").strip().lower()
        input_text = str(payload.get("input") or "").strip()
        output_text = str(payload.get("output") or "output").strip() or "output"
        report_output_text = str(payload.get("report_output") or "").strip()
        key_text = str(payload.get("key") or "").strip()

        no_parallel = bool(payload.get("no_parallel"))
        report = bool(payload.get("report"))
        fast = bool(payload.get("fast"))
        extract_only = bool(payload.get("extract_only"))
        keep_audio = bool(payload.get("keep_audio"))
        no_adx_mask = bool(payload.get("no_adx_mask"))
        mux_mkv = bool(payload.get("mux_mkv"))

        if not input_text:
            raise ValueError(self._t("input_required"))

        input_path = Path(input_text)
        if not input_path.exists():
            raise ValueError(self._t("input_not_found", path=input_path))
        if input_mode == "batch":
            if not input_path.is_dir():
                raise ValueError(self._t("batch_requires_folder"))
        else:
            if not input_path.is_file():
                raise ValueError(self._t("single_requires_file"))
            if input_path.suffix.lower() != ".usm":
                raise ValueError(self._t("single_requires_usm"))

        report_dir = None
        if report_output_text:
            report_dir_path = Path(report_output_text)
            if report_dir_path.exists() and not report_dir_path.is_dir():
                raise ValueError(self._t("invalid_options", reason="report output must be a folder"))
            report_dir = str(report_dir_path)

        manual_key = None
        if key_text:
            try:
                manual_key = parse_full_key(key_text)
            except ValueError as exc:
                raise ValueError(self._t("manual_key_invalid", reason=exc)) from exc

        if manual_key is not None and fast:
            raise ValueError(self._t("key_cannot_fast"))
        if extract_only and manual_key is not None:
            raise ValueError(self._t("extract_only_cannot_key"))
        if extract_only and fast:
            raise ValueError(self._t("extract_only_cannot_fast"))
        if extract_only and mux_mkv:
            raise ValueError(self._t("extract_only_cannot_mux"))

        opt = ProcessOptions(
            output_dir=output_text,
            input_root=str(input_path) if input_path.is_dir() else None,
            vgmstream=None,
            keep_intermediate_audio=keep_audio,
            adx_audio_mask=not no_adx_mask,
            mux_mkv=mux_mkv,
            ffmpeg=None,
            write_report=report,
            report_dir=report_dir,
            report_language=self._get_language(),
            report_selected_files=None,
            fast=fast,
            manual_key=manual_key,
            extract_only=extract_only,
        )

        return {
            "input_path": input_path,
            "opt": opt,
            "no_parallel": no_parallel,
        }

    def _build_file_rows(self, files: list[Path]) -> tuple[list[dict], dict[str, str]]:
        rows: list[dict] = []
        path_to_id: dict[str, str] = {}
        for idx, path in enumerate(files):
            row_id = f"row_{idx}"
            stat = path.stat()
            rows.append(
                {
                    "id": row_id,
                    "path": str(path),
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "created_ts": stat.st_ctime,
                    "progress": 0,
                    "status": "pending",
                }
            )
            path_to_id[str(path)] = row_id
        return rows, path_to_id

    def _stage_plan(self, opt: ProcessOptions) -> list[tuple[int, str]]:
        if opt.extract_only:
            return [
                (4, "process_stage_prepare"),
                (12, "process_stage_demux"),
                (70, "process_stage_finalize"),
                (100, "process_stage_done"),
            ]
        plan: list[tuple[int, str]] = [
            (4, "process_stage_prepare"),
            (18, "process_stage_key_recovery"),
            (38, "process_stage_demux"),
            (62, "process_stage_decode"),
        ]
        if opt.mux_mkv:
            plan.append((78, "process_stage_mux"))
        plan.extend(
            [
                (90, "process_stage_finalize"),
                (100, "process_stage_done"),
            ]
        )
        return plan

    def _emit_progress_stage_logs(
        self,
        file_name: str,
        value: int,
        stage_plan: list[tuple[int, str]],
        announced: set[str],
    ) -> None:
        for threshold, key in stage_plan:
            if value >= threshold and key not in announced:
                self.logMessage.emit(self._t(key, file=file_name))
                announced.add(key)

    def _run_job(self, config: dict) -> None:
        handler = _QtLogHandler(self.logMessage.emit)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        root_logger = logging.getLogger()
        old_level = root_logger.level
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

        try:
            input_path: Path = config["input_path"]
            opt: ProcessOptions = config["opt"]
            no_parallel: bool = config["no_parallel"]
            with self._reports_lock:
                self._reports_by_id.clear()

            files = collect_usm_inputs(input_path)
            if not files:
                self.logMessage.emit(self._t("no_usm_files_found"))
                return

            rows, path_to_id = self._build_file_rows(files)
            opt.report_selected_files = None
            self.fileListReady.emit(json.dumps(rows, ensure_ascii=False))
            self.overallProgressUpdate.emit(
                json.dumps({"done": 0, "total": len(files)}, ensure_ascii=False)
            )

            Path(opt.output_dir).mkdir(parents=True, exist_ok=True)
            max_workers = max(os.cpu_count() or 1, 1)
            use_parallel = (not no_parallel) and max_workers > 1 and len(files) > 1

            self.logMessage.emit(
                self._t(
                    "files_summary",
                    count=len(files),
                    parallel=self._t("yes") if use_parallel else self._t("no"),
                    workers=max_workers if use_parallel else 1,
                )
            )
            if opt.manual_key is not None:
                self.logMessage.emit(f"[INFO] manual key: {opt.manual_key:016X}")
            if not opt.extract_only:
                self.logMessage.emit(
                    "[INFO] vgmstream: "
                    + (find_vgmstream(opt.vgmstream) or "not found; audio will be extracted only")
                )
            if opt.mux_mkv:
                self.logMessage.emit(
                    "[INFO] ffmpeg: "
                    + (find_ffmpeg(opt.ffmpeg) or "not found; MKV mux will be skipped")
                )

            reports: list[dict] = []
            done_count = 0
            if use_parallel:
                for path in files:
                    self.logMessage.emit(self._t("process_queued", file=path.name))
                with futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    fut_map = {executor.submit(process_one, str(path), opt): path for path in files}
                    for fut in futures.as_completed(fut_map):
                        path = fut_map[fut]
                        self.logMessage.emit(self._t("process_completed", file=path.name))
                        try:
                            report = fut.result()
                        except UsmDivinerError as exc:
                            report = {"file": str(path), "status": "error", "reason": str(exc)}
                        except Exception as exc:
                            report = {"file": str(path), "status": "error", "reason": repr(exc)}
                        report["id"] = path_to_id.get(str(path), "")
                        if report.get("id"):
                            with self._reports_lock:
                                self._reports_by_id[str(report["id"])] = dict(report)
                        reports.append(report)
                        if report["id"]:
                            self.fileProgressUpdate.emit(
                                json.dumps(
                                    {"id": report["id"], "progress": 100},
                                    ensure_ascii=False,
                                )
                            )
                        self.fileRowUpdate.emit(json.dumps(report, ensure_ascii=False))
                        done_count += 1
                        self.overallProgressUpdate.emit(
                            json.dumps(
                                {"done": done_count, "total": len(files)},
                                ensure_ascii=False,
                            )
                        )
                        self.logMessage.emit(_summary_line(self._get_language(), report))
                        for detail in _report_detail_lines(report):
                            self.logMessage.emit(detail)
            else:
                for path in files:
                    row_id = path_to_id.get(str(path), "")
                    self.logMessage.emit(self._t("process_start_line", file=path.name))
                    stage_plan = self._stage_plan(opt)
                    announced_stage_logs: set[str] = set()
                    if row_id:
                        self.fileProgressUpdate.emit(
                            json.dumps({"id": row_id, "progress": 12}, ensure_ascii=False)
                        )
                    try:
                        report = process_one(
                            str(path),
                            opt,
                            progress_callback=(
                                lambda value, _row_id=row_id, _file_name=path.name: (
                                    self.fileProgressUpdate.emit(
                                        json.dumps(
                                            {"id": _row_id, "progress": int(value)},
                                            ensure_ascii=False,
                                        )
                                    ),
                                    self._emit_progress_stage_logs(
                                        _file_name,
                                        int(value),
                                        stage_plan,
                                        announced_stage_logs,
                                    ),
                                )
                            )
                            if row_id
                            else None,
                        )
                    except UsmDivinerError as exc:
                        report = {"file": str(path), "status": "error", "reason": str(exc)}
                    except Exception as exc:
                        report = {"file": str(path), "status": "error", "reason": repr(exc)}
                    report["id"] = path_to_id.get(str(path), "")
                    if report.get("id"):
                        with self._reports_lock:
                            self._reports_by_id[str(report["id"])] = dict(report)
                    reports.append(report)
                    if report["id"]:
                        self.fileProgressUpdate.emit(
                            json.dumps(
                                {"id": report["id"], "progress": 100},
                                ensure_ascii=False,
                            )
                        )
                    self.fileRowUpdate.emit(json.dumps(report, ensure_ascii=False))
                    done_count += 1
                    self.overallProgressUpdate.emit(
                        json.dumps(
                            {"done": done_count, "total": len(files)},
                            ensure_ascii=False,
                        )
                    )
                    self.logMessage.emit(_summary_line(self._get_language(), report))
                    for detail in _report_detail_lines(report):
                        self.logMessage.emit(detail)

            ok = sum(1 for r in reports if r.get("status") == "ok")
            skipped = sum(1 for r in reports if r.get("status") == "skipped")
            errors = sum(1 for r in reports if r.get("status") == "error")
            self.logMessage.emit(
                self._t("done_summary", ok=ok, skipped=skipped, errors=errors)
            )
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(old_level)
            self.runStateChanged.emit(False)
            self.logMessage.emit(self._t("end"))


def _summary_line(lang: str, report: dict) -> str:
    file_name = Path(report.get("file", "?")).name
    status = report.get("status")
    if status == "ok":
        mux = report.get("mux") or {}
        if mux.get("ok") and mux.get("mkv"):
            return _t(lang, "ok_mux_line", file=file_name, mkv=mux["mkv"])
        return _t(lang, "ok_line", file=file_name)
    reason = report.get("reason") or "unknown"
    if status == "skipped":
        return _t(lang, "skip_line", file=file_name, reason=reason)
    return _t(lang, "error_line", file=file_name, reason=reason)


def _report_detail_lines(report: dict) -> list[str]:
    lines: list[str] = []
    status = report.get("status")

    crack = report.get("crack") or {}
    if crack:
        crack_items: list[str] = []
        for key in ("reason", "bytes_scanned", "beam_size", "l1_beam_size", "candidates", "elapsed_ms"):
            value = crack.get(key)
            if value is not None and value != "":
                crack_items.append(f"{key}={value}")
        if crack_items:
            lines.append("     crack: " + ", ".join(crack_items))

    chunks = report.get("chunks") or {}
    if chunks:
        lines.append(
            "     chunks: total={total}, video={video}, audio={audio}".format(
                total=chunks.get("total", 0),
                video=chunks.get("video", 0),
                audio=chunks.get("audio", 0),
            )
        )

    if status != "ok":
        return lines

    if report.get("extract_only"):
        lines.append("     mode: extract-only")
    else:
        lines.append(
            "     key: {full}  key1={k1} key2={k2}".format(
                full=report.get("full_key_hex") or "-",
                k1=report.get("key1_hex_little") or "-",
                k2=report.get("key2_hex_little") or "-",
            )
        )

    video = report.get("video") or {}
    if video.get("path"):
        lines.append("     video: {path} ({fmt})".format(path=video["path"], fmt=video.get("format") or "unknown"))

    audio_map = report.get("audio") or {}
    for ch, audio in sorted(audio_map.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else str(item[0])):
        if audio.get("raw"):
            lines.append("     audio ch{ch}: {fmt} (raw)".format(ch=ch, fmt=audio.get("format") or "unknown"))
            continue

        hca = audio.get("hca") or {}
        hca_str = ""
        if audio.get("format") == "hca":
            ciph_type = hca.get("ciph_type")
            ciph_map = {0: "none", 1: "keyless", 56: "keyed"}
            hca_str = f", hca_ciph={ciph_type}({ciph_map.get(ciph_type, 'unknown')})"

        dec = audio.get("decode") or {}
        wav = f", wav={dec.get('wav')}" if dec.get("ok") else ""
        lines.append(
            "     audio ch{ch}: {fmt}, audiomask={mask} ({conf}){hca}{wav}".format(
                ch=ch,
                fmt=audio.get("format") or "unknown",
                mask=audio.get("use_audio_mask"),
                conf=audio.get("confidence") or "unknown",
                hca=hca_str,
                wav=wav,
            )
        )

    mux = report.get("mux")
    if mux:
        if mux.get("ok"):
            lines.append("     mkv: {mkv}".format(mkv=mux.get("mkv")))
        else:
            lines.append("     mkv: skipped ({msg})".format(msg=mux.get("message") or mux.get("log_tail") or "unknown"))

    if report.get("report_written"):
        lines.append("     report: {path}".format(path=report.get("report_path") or "(unknown)"))

    return lines


def main() -> int:
    app = QApplication([])
    view = QWebEngineView()
    view.setWindowTitle(_t(DEFAULT_LANGUAGE, "app_title"))
    view.setFixedSize(1180, 850)

    bridge = WebBridge()
    channel = QWebChannel(view.page())
    channel.registerObject("bridge", bridge)
    view.page().setWebChannel(channel)

    bridge.windowTitleChanged.connect(view.setWindowTitle)

    html = _render_html()
    # Use local workspace root as base URL so relative asset paths can be loaded.
    base_dir = ASSETS_DIR.parent.resolve()
    view.setHtml(html, QUrl.fromLocalFile(str(base_dir) + os.sep))
    view.show()
    return app.exec()

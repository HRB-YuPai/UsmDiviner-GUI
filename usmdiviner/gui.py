from __future__ import annotations

import concurrent.futures as futures
import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
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
from .tools import mux_to_mkv, transcode_ivf_to_mp4
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

        * {
            box-sizing: border-box;
        }

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

        .native-select-hidden {
            display: none !important;
        }

        .select-shell {
            position: relative;
            width: 100%;
        }

        .select-trigger {
            width: 100%;
            min-height: 34px;
            border-radius: 12px;
            border: 1px solid var(--input-border);
            background:
                linear-gradient(180deg, color-mix(in srgb, var(--input-bg) 94%, #ffffff 6%), color-mix(in srgb, var(--input-bg) 90%, #000000 10%));
            color: var(--fg);
            padding: 8px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            font-size: 12px;
            line-height: 1.2;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            box-shadow: inset 0 1px 0 #ffffff12, 0 8px 18px #00000014;
            cursor: pointer;
            transition:
                border-color 260ms ease,
                box-shadow 320ms ease,
                transform 260ms ease,
                background 320ms ease;
        }

        .select-trigger:hover {
            border-color: var(--acc);
            box-shadow: inset 0 1px 0 #ffffff18, 0 12px 24px #0000001c;
            transform: translateY(-1px);
        }

        .select-trigger:focus-visible {
            outline: none;
            border-color: var(--acc);
            box-shadow: 0 0 0 4px var(--focus-ring), 0 12px 28px #00000020;
        }

        .select-trigger-label {
            min-width: 0;
            overflow: hidden;
            white-space: nowrap;
            text-overflow: ellipsis;
            text-align: left;
        }

        .select-trigger-icon {
            width: 10px;
            height: 10px;
            flex: 0 0 auto;
            border-right: 2px solid currentColor;
            border-bottom: 2px solid currentColor;
            transform: rotate(45deg) translateY(-1px);
            opacity: 0.72;
            transition: transform 420ms cubic-bezier(0.22, 1, 0.36, 1), opacity 240ms ease;
        }

        .select-shell.open .select-trigger {
            border-color: var(--acc);
            box-shadow: 0 0 0 4px var(--focus-ring), 0 14px 30px #00000022;
            transform: translateY(-1px);
        }

        .select-shell.open .select-trigger-icon {
            transform: rotate(225deg) translateY(1px);
            opacity: 0.95;
        }

        .select-menu {
            position: absolute;
            top: calc(100% + 8px);
            left: 0;
            right: 0;
            padding: 8px;
            border-radius: 14px;
            border: 1px solid var(--line);
            background: linear-gradient(180deg, var(--panel0), var(--panel1));
            box-shadow: 0 22px 38px #00000026;
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transform: translateY(-10px) scale(0.96);
            transform-origin: top center;
            transition:
                opacity 700ms cubic-bezier(0.22, 1, 0.36, 1),
                transform 880ms cubic-bezier(0.18, 0.9, 0.22, 1),
                visibility 700ms ease;
            z-index: 80;
        }

        .select-shell.open .select-menu {
            opacity: 1;
            visibility: visible;
            pointer-events: auto;
            transform: translateY(0) scale(1);
        }

        .select-option {
            width: 100%;
            border: 1px solid transparent;
            background: transparent;
            color: var(--fg);
            border-radius: 10px;
            padding: 9px 11px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            text-align: left;
            font-size: 12px;
            font-family: inherit;
            cursor: pointer;
            transition: background 240ms ease, border-color 240ms ease, transform 240ms ease, color 240ms ease;
        }

        .select-option:hover,
        .select-option:focus-visible {
            outline: none;
            background: color-mix(in srgb, var(--surface-2) 84%, var(--acc) 16%);
            border-color: color-mix(in srgb, var(--acc) 50%, var(--line) 50%);
            transform: translateX(2px);
        }

        .select-option.active {
            background: color-mix(in srgb, var(--surface-2) 70%, var(--acc) 30%);
            border-color: var(--acc);
            box-shadow: inset 0 1px 0 #ffffff14;
        }

        .select-option-check {
            opacity: 0;
            color: var(--acc);
            font-weight: 700;
            transition: opacity 200ms ease;
        }

        .select-option.active .select-option-check {
            opacity: 1;
        }

        .toolbar-select-shell .select-trigger {
            min-height: 32px;
            padding: 7px 11px;
            border-radius: 10px;
        }

        .video-export-shell .select-trigger {
            min-height: 36px;
            border-radius: 11px;
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
            min-width: max-content;
        }

        .row {
            display: grid;
            grid-template-columns: max-content 1fr auto;
            gap: 7px;
            align-items: center;
        }

        .row.small {
            grid-template-columns: max-content 1fr;
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

        input[type="text"][readonly] {
            cursor: default;
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
            min-width: 0;
            max-width: 100%;
        }

        table.file-table {
            width: max-content;
            min-width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 11px;
            font-family: inherit;
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

        .resizer { display: none; }

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
            grid-template-columns: max-content 1fr auto auto;
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
            width: min(160px, 100%);
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            align-items: stretch;
            gap: 4px;
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

        .table-wrap,
        .log-box,
        .blk-preview,
        .sync-result-text,
        .save-success-path {
            cursor: default;
            user-select: none;
        }

        .table-wrap::-webkit-scrollbar,
        .log-box::-webkit-scrollbar,
        .blk-preview::-webkit-scrollbar,
        .sync-result-text::-webkit-scrollbar,
        .save-success-path::-webkit-scrollbar {
            width: 12px;
            height: 12px;
            cursor: default;
        }

        .table-wrap::-webkit-scrollbar-track,
        .log-box::-webkit-scrollbar-track,
        .blk-preview::-webkit-scrollbar-track,
        .sync-result-text::-webkit-scrollbar-track,
        .save-success-path::-webkit-scrollbar-track {
            background: var(--scroll-track);
            border-radius: 999px;
            cursor: default;
        }

        .table-wrap::-webkit-scrollbar-thumb,
        .log-box::-webkit-scrollbar-thumb,
        .blk-preview::-webkit-scrollbar-thumb,
        .sync-result-text::-webkit-scrollbar-thumb,
        .save-success-path::-webkit-scrollbar-thumb {
            background: var(--scroll-thumb);
            border-radius: 999px;
            border: 2px solid var(--scroll-track);
            cursor: default;
        }

        .table-wrap::-webkit-scrollbar-button,
        .log-box::-webkit-scrollbar-button,
        .blk-preview::-webkit-scrollbar-button,
        .sync-result-text::-webkit-scrollbar-button,
        .save-success-path::-webkit-scrollbar-button {
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
            color: var(--muted);
            font-size: 12px;
            font-weight: 500;
            text-align: right;
            width: 100%;
        }

        .file-table td:first-child {
            text-align: center;
            vertical-align: middle;
        }

        .video-export-card {
            width: min(980px, 96vw);
            height: min(680px, 86vh);
        }

        .video-export-body {
            flex: 1;
            min-height: 0;
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding: 12px 14px;
        }

        .video-export-config {
            display: grid;
            grid-template-columns: 120px 1fr;
            gap: 8px 10px;
            align-items: center;
        }

        .video-export-config .field-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 8px;
            align-items: center;
        }

        .video-export-select {
            width: 100%;
            border-radius: 8px;
            border: 1px solid var(--input-border);
            background: var(--input-bg);
            color: var(--fg);
            padding: 7px 9px;
            font-size: 12px;
            outline: none;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        .video-export-list {
            border: 1px solid var(--line);
            border-radius: 10px;
            background: var(--surface);
            min-height: 0;
            flex: 1;
            overflow: auto;
        }

        .video-export-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 12px;
        }

        .video-export-table th,
        .video-export-table td {
            border-bottom: 1px solid var(--line);
            padding: 8px;
            text-align: left;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .video-export-table th {
            position: sticky;
            top: 0;
            background: var(--surface-2);
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.2px;
        }

        .video-export-progress {
            width: min(180px, 100%);
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
            opacity: 1;
            visibility: visible;
            pointer-events: auto;
            transition: opacity 910ms cubic-bezier(0.22, 1, 0.36, 1), visibility 910ms ease;
        }

        .hidden {
            display: none !important;
        }

        /* Keep modal nodes mounted so both show and hide can animate smoothly. */
        .modal.hidden {
            display: flex !important;
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transition: opacity 1170ms cubic-bezier(0.22, 1, 0.36, 1), visibility 1170ms ease;
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
            opacity: 1;
            transform: translateY(0) scale(1);
            transition: transform 1190ms cubic-bezier(0.18, 0.9, 0.22, 1), opacity 910ms ease;
            transform-origin: 50% 45%;
        }

        .modal.hidden .modal-card {
            opacity: 0;
            transform: translateY(26px) scale(0.94);
            transition: transform 1530ms cubic-bezier(0.18, 0.9, 0.22, 1), opacity 1170ms ease;
        }

        @media (prefers-reduced-motion: reduce) {
            .modal,
            .modal-card,
            .select-trigger,
            .select-trigger-icon,
            .select-menu,
            .select-option,
            .context-menu,
            .context-menu-item {
                transition: none !important;
            }
        }

        .context-menu {
            position: fixed;
            top: 0;
            left: 0;
            background: var(--panel0);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 4px 0;
            z-index: 999;
            min-width: 140px;
            box-shadow: 0 4px 12px #00000044;
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transform: translateY(26px) scale(0.94);
            transform-origin: 50% 45%;
            transition: opacity 1170ms cubic-bezier(0.22, 1, 0.36, 1), visibility 1170ms ease, transform 1530ms cubic-bezier(0.18, 0.9, 0.22, 1);
        }

        .context-menu.show {
            opacity: 1;
            visibility: visible;
            pointer-events: auto;
            transform: translateY(0) scale(1);
            transition: opacity 910ms cubic-bezier(0.22, 1, 0.36, 1), visibility 910ms ease, transform 1190ms cubic-bezier(0.18, 0.9, 0.22, 1);
        }

        .context-menu-item {
            padding: 6px 12px;
            cursor: pointer;
            color: var(--fg);
            font-size: 12px;
            user-select: none;
            transition: background 120ms ease;
        }

        .context-menu-item:hover {
            background: var(--surface-2);
        }

        .context-menu-item.disabled {
            color: var(--muted);
            cursor: not-allowed;
            opacity: 0.5;
        }

        .context-menu-item.disabled:hover {
            background: transparent;
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

        .confirm-save-card {
            width: min(640px, 92vw);
            height: auto;
            min-height: 0;
        }

        .save-success-card {
            width: min(760px, 92vw);
            height: auto;
            min-height: 0;
        }

        #sync_result_modal .modal-head {
            justify-content: center;
        }

        #blk_save_confirm_modal .modal-head,
        #blk_save_success_modal .modal-head {
            justify-content: center;
        }

        #blk_sync_success_modal .modal-head {
            justify-content: center;
        }

        #sync_result_modal .modal-head > span {
            width: 100%;
            text-align: center;
        }

        #blk_save_confirm_modal .modal-head > span,
        #blk_save_success_modal .modal-head > span {
            width: 100%;
            text-align: center;
        }

        #blk_sync_success_modal .modal-head > span {
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

        .confirm-save-body,
        .save-success-body {
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        #blk_sync_success_modal .save-success-body {
            align-items: center;
            text-align: center;
        }

        .confirm-save-message,
        .save-success-message {
            color: var(--fg);
            font-size: 13px;
            line-height: 1.55;
            white-space: pre-wrap;
        }

        #blk_sync_success_modal .save-success-message {
            text-align: center;
        }

        .save-success-path {
            width: 100%;
            min-height: 92px;
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
            resize: none;
            outline: none;
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
            padding: 12px 12px;
            border: none;
        }

        .settings-content {
            flex: 1;
            padding: 12px 12px;
            overflow-y: auto;
        }

        #settings_modal .modal-card {
            width: min(680px, 92vw);
            height: min(520px, 76vh);
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
            padding: 9px 0;
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
                        <div class="sub" id="subtitle_text">USM key recovery, extraction, post-export video workflow, and BLB versions viewer</div>
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
                                <label><input type="radio" name="input_mode" id="mode_single" value="single" checked onchange="syncInputMode()" /> <span id="single_file_text">File selection</span></label>
                                <label><input type="radio" name="input_mode" id="mode_batch" value="batch" onchange="syncInputMode()" /> <span id="batch_folder_text">Folder selection</span></label>
                            </div>
                        </div>
                        <div class="form-cols">
                            <div class="form-col">
                                <div class="row">
                                    <label id="input_label" for="input">Input</label>
                                    <input id="input" type="text" placeholder="" readonly />
                                    <button class="btn" id="input_pick_btn" data-tooltip="Browse to select input" onclick="pickInput()">Browse</button>
                                </div>
                                <div class="row hidden" id="output_row">
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
                                <th id="th_progress" data-min="140"></th>
                                <th id="th_name" data-min="220"></th>
                                <th id="th_size" data-min="110"></th>
                                <th id="th_created" data-min="170"></th>
                                <th id="th_key1" data-min="150"></th>
                                <th id="th_key2" data-min="150"></th>
                                <th id="th_genshin" data-min="220"></th>
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
                        <label class="opt hidden"><input id="report" type="checkbox" onchange="syncRules()" /> <span id="opt_report_text">Write report.json</span></label>
                        <label class="opt"><input id="fast" type="checkbox" /> <span id="opt_fast_text">Fast key crack</span></label>
                        <label class="opt"><input id="extract_only" type="checkbox" onchange="syncRules()" /> <span id="opt_extract_only_text">Extract only</span></label>
                        <label class="opt"><input id="keep_audio" type="checkbox" /> <span id="opt_keep_audio_text">Keep intermediate audio</span></label>
                        <label class="opt"><input id="no_adx_mask" type="checkbox" /> <span id="opt_no_adx_mask_text">Disable ADX AudioMask</span></label>
                        <label class="opt hidden"><input id="mux_mkv" type="checkbox" onchange="syncRules()" /> <span id="opt_mux_mkv_text">MP4 (Keep MKV Fallback)</span></label>
                    </div>
                </div>

                <div class="actions actions-bar">
                    <button class="btn" id="open_settings_btn" data-tooltip="Settings" onclick="openSettingsModal()">Settings</button>
                    <button class="btn" id="open_log_btn" data-tooltip="View output logs" onclick="openLogModal()">Logs</button>
                    <button class="btn hidden" id="open_video_export_btn" data-tooltip="Export videos from extracted IVF/WAV" onclick="openVideoExportModal()">Export Video</button>
                    <button class="btn hidden" id="export_all_reports_btn" data-tooltip="Export all reports" onclick="exportAllReports()">Export All Reports</button>
                    <button class="btn hidden" id="export_index_btn" data-tooltip="Export processed index JSON" onclick="exportIndexJson()">Export Index</button>
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
                    <div class="setting-item hidden">
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
                    <div class="setting-item hidden">
                        <div class="setting-label">
                            <span class="label-text" id="settings_opt_mux_mkv_text">MP4 (Keep MKV Fallback)</span>
                            <span class="label-desc" id="opt_mux_mkv_tooltip">Create MKV from extracted streams and transcode MP4 as primary output</span>
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
                <textarea id="blk_versions_box" class="blk-preview" spellcheck="false" oninput="onBlkVersionsEditorInput()"></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" id="blk_versions_copy_btn" onclick="copyBlkVersions()">Copy</button>
                <button class="btn" id="blk_versions_save_btn" onclick="requestSaveBlkVersions()">Save</button>
                <button class="btn" id="blk_versions_sync_btn" onclick="syncBlkKeysFromUsmRows()">Sync Keys</button>
                <button class="btn" id="blk_versions_close_btn" onclick="closeBlkVersionsModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="video_export_modal" class="modal hidden">
        <div class="modal-card video-export-card">
            <div class="modal-head">
                <span id="video_export_title">Export Video</span>
            </div>
            <div class="video-export-body">
                <div class="video-export-config">
                    <label id="video_export_format_label" for="video_export_format">Format</label>
                    <select id="video_export_format" class="video-export-select">
                        <option value="mp4">MP4</option>
                        <option value="mkv">MKV</option>
                    </select>

                    <label id="video_export_output_label" for="video_export_output">Output</label>
                    <div class="field-row">
                        <input id="video_export_output" type="text" placeholder="" />
                        <button class="btn" id="video_export_output_pick_btn" onclick="pickVideoExportOutput()">Browse</button>
                    </div>
                </div>

                <div class="video-export-list">
                    <table class="video-export-table">
                        <thead>
                            <tr>
                                <th id="video_export_th_name">Name</th>
                                <th id="video_export_th_status">Status</th>
                                <th id="video_export_th_progress">Progress</th>
                            </tr>
                        </thead>
                        <tbody id="video_export_table_body"></tbody>
                    </table>
                </div>

                <div class="progress-wrap">
                    <div class="progress-head">
                        <label id="video_export_overall_label">Overall progress</label>
                        <div id="video_export_overall_value" class="progress-text">0%</div>
                    </div>
                    <div class="progress-track"><div id="video_export_overall_fill" class="progress-fill"></div></div>
                </div>
            </div>
            <div class="modal-actions">
                <button class="btn" id="video_export_start_btn" onclick="startVideoExport()">Start Export</button>
                <button class="btn" id="video_export_close_btn" onclick="closeVideoExportModal()">Close</button>
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

    <div id="blk_sync_success_modal" class="modal hidden">
        <div class="modal-card save-success-card">
            <div class="modal-head">
                <span id="blk_sync_success_title">BLK Key Sync Complete</span>
            </div>
            <div class="save-success-body">
                <div id="blk_sync_success_message" class="save-success-message"></div>
            </div>
            <div class="modal-actions">
                <button class="btn" id="blk_sync_success_ok_btn" onclick="closeBlkSyncSuccessModal()">OK</button>
            </div>
        </div>
    </div>

    <div id="blk_save_confirm_modal" class="modal hidden">
        <div class="modal-card confirm-save-card">
            <div class="modal-head">
                <span id="blk_save_confirm_title">Continue Save?</span>
            </div>
            <div class="confirm-save-body">
                <div id="blk_save_confirm_message" class="confirm-save-message"></div>
            </div>
            <div class="modal-actions">
                <button class="btn" id="blk_save_confirm_yes_btn" onclick="confirmSaveBlkVersions()">Yes</button>
                <button class="btn" id="blk_save_confirm_no_btn" onclick="closeBlkSaveConfirmModal()">No</button>
            </div>
        </div>
    </div>

    <div id="blk_save_success_modal" class="modal hidden">
        <div class="modal-card save-success-card">
            <div class="modal-head">
                <span id="blk_save_success_title">versions.json Saved</span>
            </div>
            <div class="save-success-body">
                <div id="blk_save_success_message" class="save-success-message"></div>
                <textarea id="blk_save_success_path" class="save-success-path" readonly></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" id="blk_save_reveal_btn" onclick="revealBlkSavedPath()">Open Save Path</button>
                <button class="btn" id="blk_save_success_ok_btn" onclick="closeBlkSaveSuccessModal()">OK</button>
            </div>
        </div>
    </div>

    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script>
        const I18N = JSON.parse(__TRANSLATIONS_JSON__);
        let bridge = null;
        let fileRows = new Map();
        let logLines = [];
        let selectedInputFiles = [];
        let blkVersionsData = null;
        let blkVersionsEditorText = "";
        let blkSearchQuery = "";
        let blkSearchCaseSensitive = false;
        let blkSearchWholeWord = false;
        let blkSearchMatches = [];
        let blkSearchIndex = -1;
        let blkParsePending = false;
        let blkSaveSuccessPath = "";
        let blkSaveCanReveal = false;
        let videoExportCandidates = [];
        let videoExportRows = new Map();
        let videoExportRunning = false;
        let progressPumpTimer = null;
        let overallProgressCurrent = 0;
        let overallProgressTarget = 0;
        let overallLastTick = 0;
        let rowProgressModel = new Map();
        let isTaskRunning = false;
        let copyToastTimer = null;
        let lastLogLine = null;
        let lastLogTs = 0;
        let customSelectInstances = new Map();

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

        function closeCustomSelects(exceptId = null) {
            customSelectInstances.forEach((instance, selectId) => {
                if (!instance || !instance.shell) return;
                instance.shell.classList.toggle("open", !!exceptId && selectId === exceptId);
                instance.trigger.setAttribute("aria-expanded", instance.shell.classList.contains("open") ? "true" : "false");
            });
        }

        function refreshCustomSelect(selectId) {
            const instance = customSelectInstances.get(selectId);
            if (!instance) return;
            const { select, label, menu } = instance;
            const options = Array.from(select.options || []);
            const selected = options.find((option) => option.value === select.value) || options[select.selectedIndex] || null;
            label.textContent = selected ? String(selected.textContent || "") : "";
            menu.innerHTML = "";
            options.forEach((option) => {
                const item = document.createElement("button");
                item.type = "button";
                item.className = "select-option" + (option.value === select.value ? " active" : "");
                item.setAttribute("role", "option");
                item.setAttribute("aria-selected", option.value === select.value ? "true" : "false");
                item.innerHTML = `<span>${escapeHtml(option.textContent || "")}</span><span class="select-option-check">✓</span>`;
                item.addEventListener("click", () => {
                    select.value = option.value;
                    refreshCustomSelect(selectId);
                    closeCustomSelects();
                    select.dispatchEvent(new Event("change", { bubbles: true }));
                });
                menu.appendChild(item);
            });
        }

        function refreshAllCustomSelects() {
            customSelectInstances.forEach((_, selectId) => refreshCustomSelect(selectId));
        }

        function setupCustomSelect(selectId) {
            const select = byId(selectId);
            if (!select || customSelectInstances.has(selectId)) return;

            const shell = document.createElement("div");
            shell.className = "select-shell";
            if (select.classList.contains("video-export-select")) {
                shell.classList.add("video-export-shell");
            } else {
                shell.classList.add("toolbar-select-shell");
            }

            const trigger = document.createElement("button");
            trigger.type = "button";
            trigger.className = "select-trigger";
            trigger.setAttribute("aria-haspopup", "listbox");
            trigger.setAttribute("aria-expanded", "false");

            const label = document.createElement("span");
            label.className = "select-trigger-label";
            const icon = document.createElement("span");
            icon.className = "select-trigger-icon";
            trigger.appendChild(label);
            trigger.appendChild(icon);

            const menu = document.createElement("div");
            menu.className = "select-menu";
            menu.setAttribute("role", "listbox");

            select.parentNode.insertBefore(shell, select);
            shell.appendChild(select);
            shell.appendChild(trigger);
            shell.appendChild(menu);
            select.classList.add("native-select-hidden");

            customSelectInstances.set(selectId, { select, shell, trigger, label, menu });

            trigger.addEventListener("click", (event) => {
                event.preventDefault();
                const willOpen = !shell.classList.contains("open");
                closeCustomSelects(willOpen ? selectId : null);
            });

            refreshCustomSelect(selectId);
        }

        function setupCustomSelects() {
            ["lang_select", "theme_select", "video_export_format"].forEach(setupCustomSelect);
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
            rowProgressModel.clear();
            if (progressPumpTimer !== null) {
                window.clearTimeout(progressPumpTimer);
                progressPumpTimer = null;
            }
            overallProgressCurrent = 0;
            overallProgressTarget = 0;
            overallLastTick = 0;
            body.innerHTML = "";
            if (!rows || !rows.length) {
                const dict = t(currentLang());
                body.innerHTML = `<tr class="pending"><td class="empty-state" colspan="8"></td></tr>`;
                if (emptyOverlay) {
                    emptyOverlay.textContent = dict.table_empty;
                    emptyOverlay.classList.remove("hidden");
                }
                renderPostProcessButtons();
                return;
            }
            if (emptyOverlay) {
                emptyOverlay.classList.add("hidden");
            }
            rows.forEach((row) => {
                row.progress = Number(row.progress || 0);
                row.progressDisplay = Number(row.progress || 0);
                row.progressTarget = Number(row.progress || 0);
                fileRows.set(row.id, row);
                rowProgressModel.set(row.id, {
                    display: Number(row.progress || 0),
                    target: Number(row.progress || 0),
                    lastTick: 0,
                });
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
                    { id: `${row.id}_key1`, text: row.key1_hex_little || "" },
                    { id: `${row.id}_key2`, text: row.key2_hex_little || "" },
                    { id: `${row.id}_genshin`, text: (row.usm_decrypt_key ?? row.genshin_like_key ?? "") },
                    {
                        id: `${row.id}_action`,
                        html: "",
                    },
                ];
                cells.forEach((cell) => {
                    const td = document.createElement("td");
                    if (cell.html) {
                        td.className = cell.id && cell.id.endsWith("_action") ? "row-action" : "";
                        td.innerHTML = cell.html;
                    } else {
                        if (cell.mono) td.className = "mono";
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
            renderPostProcessButtons();
        }

        function hasFinishedProcessingRows() {
            if (!fileRows || fileRows.size <= 0) return false;
            for (const row of fileRows.values()) {
                const status = String(row && row.status || "pending");
                if (!(status === "ok" || status === "skipped" || status === "error")) {
                    return false;
                }
            }
            return true;
        }

        function renderPostProcessButtons() {
            const show = !isTaskRunning && hasFinishedProcessingRows();
            const exportReportsBtn = byId("export_all_reports_btn");
            const exportIndexBtn = byId("export_index_btn");
            if (exportReportsBtn) exportReportsBtn.classList.toggle("hidden", !show);
            if (exportIndexBtn) exportIndexBtn.classList.toggle("hidden", !show);
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
                cell.innerHTML = `<button class="btn mini-btn" onclick="saveReportForRow('${id}')">${dict.save_report}</button>`;
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

        function getBlkVersionsText() {
            const box = byId("blk_versions_box");
            if (box) {
                blkVersionsEditorText = String(box.value || "");
            }
            return String(blkVersionsEditorText || "");
        }

        function onBlkVersionsEditorInput() {
            blkVersionsEditorText = getBlkVersionsText();
            if (blkSearchQuery) {
                updateBlkSearchMatches();
            }
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

        function openBlkSyncSuccessModal(message) {
            setText("blk_sync_success_message", message || "");
            byId("blk_sync_success_modal").classList.remove("hidden");
        }

        function closeBlkSyncSuccessModal() {
            byId("blk_sync_success_modal").classList.add("hidden");
        }

        function openBlkSaveConfirmModal(title, message) {
            setText("blk_save_confirm_title", title || "");
            setText("blk_save_confirm_message", message || "");
            byId("blk_save_confirm_modal").classList.remove("hidden");
        }

        function closeBlkSaveConfirmModal() {
            byId("blk_save_confirm_modal").classList.add("hidden");
        }

        function openBlkSaveSuccessModal(message, path, canReveal, title = null) {
            blkSaveSuccessPath = String(path || "");
            blkSaveCanReveal = !!canReveal;
            if (title) {
                setText("blk_save_success_title", title);
            }
            setText("blk_save_success_message", message || "");
            const pathEl = byId("blk_save_success_path");
            if (pathEl) {
                pathEl.value = blkSaveSuccessPath;
                pathEl.classList.toggle("hidden", !blkSaveSuccessPath);
            }
            const revealBtn = byId("blk_save_reveal_btn");
            if (revealBtn) {
                revealBtn.classList.toggle("hidden", !blkSaveCanReveal);
            }
            byId("blk_save_success_modal").classList.remove("hidden");
        }

        function closeBlkSaveSuccessModal() {
            byId("blk_save_success_modal").classList.add("hidden");
        }

        function onBlkSavePromptReady(payloadJson) {
            try {
                const payload = JSON.parse(payloadJson || "{}");
                openBlkSaveConfirmModal(payload.title || "", payload.message || "");
            } catch (_) {
                openBlkSaveConfirmModal("", payloadJson || "");
            }
        }

        function onBlkSaveCompleted(payloadJson) {
            const dict = t(currentLang());
            try {
                const payload = JSON.parse(payloadJson || "{}");
                closeBlkSaveConfirmModal();
                openBlkSaveSuccessModal(
                    payload.message || dict.blk_versions_saved_message || "",
                    payload.path || "",
                    !!payload.can_reveal,
                    payload.title || dict.blk_versions_saved_title || ""
                );
            } catch (_) {
                closeBlkSaveConfirmModal();
                openBlkSaveSuccessModal(
                    dict.blk_versions_saved_message || "",
                    "",
                    false,
                    dict.blk_versions_saved_title || ""
                );
            }
        }

        function onIndexExportResult(payloadJson) {
            const dict = t(currentLang());
            try {
                const payload = JSON.parse(payloadJson || "{}");
                openBlkSaveSuccessModal(
                    payload.message || dict.index_no_data || "",
                    payload.path || "",
                    !!payload.can_reveal,
                    payload.title || dict.index_export_result_title || ""
                );
            } catch (_) {
                openBlkSaveSuccessModal(
                    dict.index_no_data || "",
                    "",
                    false,
                    dict.index_export_failed_title || ""
                );
            }
        }

        function requestSaveBlkVersions() {
            const dict = t(currentLang());
            const text = getBlkVersionsText();
            if (!text.trim()) {
                showCopyToast(dict.blk_versions_modal_empty);
                return;
            }
            if (!bridge || !bridge.requestSaveBlkVersions) {
                showCopyToast(dict.blk_versions_sync_no_bridge);
                return;
            }
            bridge.requestSaveBlkVersions(text);
        }

        function confirmSaveBlkVersions() {
            if (!bridge || !bridge.confirmSaveBlkVersions) return;
            bridge.confirmSaveBlkVersions(getBlkVersionsText());
        }

        function revealBlkSavedPath() {
            if (!blkSaveCanReveal || !blkSaveSuccessPath || !bridge || !bridge.revealSavedPath) {
                return;
            }
            bridge.revealSavedPath(blkSaveSuccessPath);
        }

        function onSyncResultReady(content) {
            const dict = t(currentLang());
            let payload = null;
            try {
                payload = JSON.parse(content || "{}");
            } catch (_) {
                payload = null;
            }

            if (!payload || typeof payload !== "object") {
                openSyncResultModal(dict.blk_sync_popup_note || "", content || dict.blk_sync_popup_empty || "");
                return;
            }

            const unresolvedCount = Number(payload.unresolved_count || 0);
            const detailsText = String(payload.details_text || "");
            const successMessage = String(payload.success_message || dict.blk_sync_all_resolved_message || "");

            if (unresolvedCount > 0) {
                closeBlkSyncSuccessModal();
                openSyncResultModal(dict.blk_sync_popup_note || "", detailsText || dict.blk_sync_popup_empty || "");
                return;
            }

            closeSyncResultModal();
            openBlkSyncSuccessModal(successMessage);
        }

        function initColumnResizers() {
            const headers = Array.from(document.querySelectorAll(".file-table thead th"));
            const cols = Array.from(document.querySelectorAll(".file-table colgroup col"));
            headers.forEach((th, index) => {
                if (th.id === "th_action" || th.id === "th_progress") return;
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
                    table.style.minWidth = `${Math.max(1, Math.round(wrap.clientWidth || 1))}px`;
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
            if (data.key1_hex_little !== undefined && cells.key1) cells.key1.textContent = data.key1_hex_little || "";
            if (data.key2_hex_little !== undefined && cells.key2) cells.key2.textContent = data.key2_hex_little || "";
            if (cells.genshin) {
                const hasNew = data.usm_decrypt_key !== undefined;
                const hasLegacy = data.genshin_like_key !== undefined;
                if (hasNew || hasLegacy) {
                    cells.genshin.textContent = data.usm_decrypt_key ?? data.genshin_like_key ?? "";
                }
            }
            renderPostProcessButtons();
        }

        function _advanceProgress(current, target, dtSec, urgency = 1) {
            const delta = target - current;
            if (Math.abs(delta) < 0.15) {
                return target;
            }
            const speed = (12 + Math.min(60, Math.abs(delta) * 0.95)) * urgency;
            const maxStep = Math.max(0.2, speed * dtSec);
            if (delta > 0) {
                return Math.min(target, current + maxStep);
            }
            return Math.max(target, current - maxStep);
        }

        function _renderProgressImmediate(id, value) {
            const safe = Math.max(0, Math.min(100, Number(value || 0)));
            const fill = byId(`${id}_progress_fill`);
            const text = byId(`${id}_progress_text`);
            if (fill) fill.style.width = `${safe}%`;
            if (text) text.textContent = `${Math.round(safe)}%`;
        }

        function _ensureProgressPump() {
            if (progressPumpTimer !== null) {
                return;
            }
            progressPumpTimer = window.setTimeout(_pumpProgress, 33);
        }

        function _pumpProgress() {
            progressPumpTimer = null;
            const now = Date.now();
            let pendingRows = false;

            fileRows.forEach((row, id) => {
                const model = rowProgressModel.get(id) || { display: Number(row.progress || 0), target: Number(row.progressTarget || row.progress || 0), lastTick: now };
                const dtSec = Math.max(0.016, Math.min(0.2, (now - (model.lastTick || now)) / 1000));
                const urgency = model.target >= 99 ? 3.2 : 1.0;
                const next = _advanceProgress(Number(model.display || 0), Number(model.target || 0), dtSec, urgency);

                model.display = next;
                model.lastTick = now;
                rowProgressModel.set(id, model);

                row.progressDisplay = next;
                row.progress = Number(model.target || 0);
                fileRows.set(id, row);
                _renderProgressImmediate(id, next);

                if (Math.abs(Number(model.target || 0) - next) >= 0.15) {
                    pendingRows = true;
                }
            });

            const overallDtSec = Math.max(0.016, Math.min(0.2, (now - (overallLastTick || now)) / 1000));
            overallLastTick = now;
            const overallUrgency = overallProgressTarget >= 99 ? 3.0 : 1.25;
            overallProgressCurrent = _advanceProgress(overallProgressCurrent, overallProgressTarget, overallDtSec, overallUrgency);
            byId("overall_progress_fill").style.width = `${overallProgressCurrent}%`;
            byId("overall_progress_value").textContent = `${Math.round(overallProgressCurrent)}%`;

            const overallPending = Math.abs(overallProgressTarget - overallProgressCurrent) >= 0.15;
            if (pendingRows || overallPending) {
                _ensureProgressPump();
            }
        }

        function setFileProgress(id, progress) {
            const value = Math.max(0, Math.min(100, Number(progress || 0)));
            const row = fileRows.get(id);
            if (!row) return;

            row.progressTarget = value;
            if (row.progressDisplay === undefined || row.progressDisplay === null) {
                row.progressDisplay = Number(row.progress || 0);
            }
            fileRows.set(id, row);

            const model = rowProgressModel.get(id) || {
                display: Number(row.progressDisplay || 0),
                target: value,
                lastTick: Date.now(),
            };
            model.target = value;
            rowProgressModel.set(id, model);

            if (value >= 100) {
                model.display = 100;
                _renderProgressImmediate(id, 100);
            }
            _ensureProgressPump();
        }

        function setOverallProgress(done, total) {
            const t = Math.max(0, Number(total || 0));
            const d = Math.max(0, Math.min(t, Number(done || 0)));
            overallProgressTarget = t > 0 ? (d * 100) / t : 0;
            if (overallProgressTarget >= 100) {
                overallProgressCurrent = 100;
                byId("overall_progress_fill").style.width = "100%";
                byId("overall_progress_value").textContent = "100%";
            }
            _ensureProgressPump();
        }

        function renderVideoExportButton() {
            const btn = byId("open_video_export_btn");
            if (!btn) return;
            btn.classList.toggle("hidden", !(videoExportCandidates.length > 0));
        }

        function renderVideoExportRows() {
            const dict = t(currentLang());
            const body = byId("video_export_table_body");
            if (!body) return;
            body.innerHTML = "";
            videoExportRows.clear();
            for (const item of videoExportCandidates) {
                const id = String(item.id || item.name || Math.random());
                videoExportRows.set(id, { id, progress: 0, status: dict.video_export_status_pending || "Pending" });
                const tr = document.createElement("tr");
                tr.id = `video_export_row_${id}`;
                tr.innerHTML = `
                    <td title="${String(item.file || item.name || "")}">${String(item.name || "—")}</td>
                    <td id="video_export_status_${id}">${dict.video_export_status_pending || "Pending"}</td>
                    <td>
                        <div class="cell-progress video-export-progress">
                            <div class="mini-track"><div id="video_export_fill_${id}" class="mini-fill" style="width:0%"></div></div>
                            <div id="video_export_text_${id}" class="mini-label">0%</div>
                        </div>
                    </td>
                `;
                body.appendChild(tr);
            }
            setVideoExportOverallProgress(0, Math.max(videoExportCandidates.length, 1));
        }

        function setVideoExportOverallProgress(done, total) {
            const t = Math.max(1, Number(total || 1));
            const d = Math.max(0, Math.min(t, Number(done || 0)));
            const pct = Math.round((d * 100) / t);
            const fill = byId("video_export_overall_fill");
            const text = byId("video_export_overall_value");
            if (fill) fill.style.width = `${pct}%`;
            if (text) text.textContent = `${pct}%`;
        }

        function updateVideoExportRowProgress(id, progress, status) {
            const value = Math.max(0, Math.min(100, Number(progress || 0)));
            const fill = byId(`video_export_fill_${id}`);
            const text = byId(`video_export_text_${id}`);
            const statusEl = byId(`video_export_status_${id}`);
            if (fill) fill.style.width = `${value}%`;
            if (text) text.textContent = `${Math.round(value)}%`;
            if (statusEl && status) statusEl.textContent = String(status);
        }

        function openVideoExportModal() {
            renderVideoExportRows();
            byId("video_export_modal").classList.remove("hidden");
        }

        function closeVideoExportModal() {
            if (videoExportRunning) return;
            byId("video_export_modal").classList.add("hidden");
        }

        function pickVideoExportOutput() {
            if (!bridge || !bridge.pickVideoExportOutput) return;
            bridge.pickVideoExportOutput();
        }

        function startVideoExport() {
            if (!bridge || !bridge.startVideoExport || videoExportRunning) return;
            const out = String(byId("video_export_output").value || "").trim();
            if (!out) {
                showCopyToast(t(currentLang()).video_export_output_required || "");
                return;
            }
            videoExportRunning = true;
            byId("video_export_start_btn").disabled = true;
            const payload = {
                format: byId("video_export_format").value,
                output_dir: out,
                candidates: videoExportCandidates,
            };
            bridge.startVideoExport(JSON.stringify(payload));
        }

        function onVideoExportReady(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            videoExportCandidates = Array.isArray(payload.candidates) ? payload.candidates : [];
            const out = String(payload.default_output_dir || "");
            if (byId("video_export_output") && out) {
                byId("video_export_output").value = out;
            }
            renderVideoExportButton();
        }

        function onVideoExportProgress(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            updateVideoExportRowProgress(payload.id, payload.progress, payload.status);
            setVideoExportOverallProgress(payload.done || 0, payload.total || 1);
        }

        function onVideoExportFinished(payloadJson) {
            const dict = t(currentLang());
            videoExportRunning = false;
            byId("video_export_start_btn").disabled = false;
            try {
                const payload = JSON.parse(payloadJson || "{}");
                closeVideoExportModal();
                openBlkSaveSuccessModal(
                    payload.message || "",
                    payload.path || "",
                    !!payload.can_reveal,
                    payload.title || dict.video_export_result_title || ""
                );
            } catch (_) {
                closeVideoExportModal();
                openBlkSaveSuccessModal(
                    dict.video_export_failed || "",
                    "",
                    false,
                    dict.video_export_result_title || ""
                );
            }
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
            setText("open_video_export_btn", dict.export_video || "Export Video");
            setText("export_all_reports_btn", dict.export_all_reports || "Export All Reports");
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
            setText("blk_versions_save_btn", dict.blk_versions_save || dict.save_report);
            setText("blk_versions_sync_btn", dict.blk_versions_sync);
            setText("blk_versions_close_btn", dict.close);
            setText("sync_result_title", dict.blk_sync_popup_title || dict.blk_versions_sync);
            setText("sync_result_close_btn", dict.close);
            setText("sync_result_note", dict.blk_sync_popup_note || "");
            setText("blk_sync_success_title", dict.blk_sync_success_title || dict.blk_versions_sync);
            setText("blk_sync_success_ok_btn", dict.settings_ok || "OK");
            setText("blk_save_confirm_title", dict.blk_versions_save_confirm_title || dict.blk_versions_title);
            setText("blk_save_confirm_yes_btn", dict.yes);
            setText("blk_save_confirm_no_btn", dict.no);
            setText("blk_save_success_title", dict.blk_versions_saved_title || dict.blk_versions_title);
            setText("blk_save_reveal_btn", dict.blk_versions_saved_reveal || dict.browse);
            setText("blk_save_success_ok_btn", dict.settings_ok || "OK");
            setText("video_export_title", dict.video_export_title || "Export Video");
            setText("video_export_format_label", dict.video_export_format_label || "Format");
            setText("video_export_output_label", dict.video_export_output_label || "Output");
            setText("video_export_output_pick_btn", dict.browse || "Browse");
            setText("video_export_th_name", dict.table_name || "Name");
            setText("video_export_th_status", dict.video_export_status || "Status");
            setText("video_export_th_progress", dict.table_progress || "Progress");
            setText("video_export_overall_label", dict.overall_progress || "Overall progress");
            setText("video_export_start_btn", dict.video_export_start || "Start Export");
            setText("video_export_close_btn", dict.close || "Close");
            setPlaceholder("output", dict.placeholder_output);
            setPlaceholder("report_output", dict.placeholder_report_output);
            setPlaceholder("blk_input", dict.placeholder_blk_input);
            setPlaceholder("video_export_output", dict.video_export_output_placeholder || "");
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
            setTooltip("open_video_export_btn", dict.btn_export_video_tooltip || dict.export_video);
            setTooltip("export_all_reports_btn", dict.btn_export_all_reports_tooltip || dict.export_all_reports);
            setTooltip("export_index_btn", dict.btn_export_index_tooltip || dict.export_index);
            setTooltip("run", dict.btn_run_tooltip);
            setTooltip("export_log_btn", dict.btn_export_log_tooltip);
            setTooltip("clear_log_btn", dict.btn_clear_log_tooltip);
            setTooltip("close_log_btn", dict.btn_close_log_tooltip);
            setTooltip("settings_ok_btn", dict.btn_settings_ok_tooltip);
            setTooltip("settings_cancel_btn", dict.btn_settings_cancel_tooltip);
            setTooltip("blk_versions_copy_btn", dict.btn_blk_versions_copy_tooltip);
            setTooltip("blk_versions_save_btn", dict.btn_blk_versions_save_tooltip || dict.save_report_tooltip);
            setTooltip("blk_versions_sync_btn", dict.btn_blk_versions_sync_tooltip);
            setTooltip("blk_versions_close_btn", dict.btn_blk_versions_close_tooltip);
            byId("open_settings_btn").textContent = dict.settings_title;
            byId("open_log_btn").textContent = dict.open_log;
            byId("open_video_export_btn").textContent = dict.export_video || "Export Video";
            byId("export_all_reports_btn").textContent = dict.export_all_reports || "Export All Reports";
            byId("export_index_btn").textContent = dict.export_index || "Export Index";
            byId("run").textContent = dict.run;
            document.getElementById("opt_disable_multiprocessing_tooltip").textContent = dict.opt_disable_multiprocessing_tooltip;
            document.getElementById("opt_write_report_tooltip").textContent = dict.opt_write_report_tooltip;
            document.getElementById("opt_fast_key_crack_tooltip").textContent = dict.opt_fast_key_crack_tooltip;
            document.getElementById("opt_extract_only_tooltip").textContent = dict.opt_extract_only_tooltip;
            document.getElementById("opt_keep_intermediate_audio_tooltip").textContent = dict.opt_keep_intermediate_audio_tooltip;
            document.getElementById("opt_disable_adx_mask_tooltip").textContent = dict.opt_disable_adx_mask_tooltip;
            document.getElementById("opt_mux_mkv_tooltip").textContent = dict.opt_mux_mkv_tooltip;
            document.getElementById("opt_manual_key_tooltip").textContent = dict.opt_manual_key_tooltip;
            if (selectedInputFiles.length > 0) {
                applyInputSelection(selectedInputFiles, "");
            }
            refreshContextMenuLanguage();
            refreshAllCustomSelects();
            refreshFileList();
            syncInputMode(true);
            syncRules();
            updateManualKeyVisibility();
            renderBlkStatus();
            renderBlkModal();
            updateBlkSearchStatus();
            renderLogBox();
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

        function exportIndexJson() {
            if (!bridge || !bridge.exportIndexJson) return;
            bridge.exportIndexJson();
        }

        function exportAllReports() {
            if (!bridge || !bridge.exportAllReports) return;
            bridge.exportAllReports();
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
            if (byId("no_parallel_toggle") && byId("no_parallel")) byId("no_parallel_toggle").checked = byId("no_parallel").checked;
            if (byId("fast_toggle") && byId("fast")) byId("fast_toggle").checked = byId("fast").checked;
            if (byId("extract_only_toggle") && byId("extract_only")) byId("extract_only_toggle").checked = byId("extract_only").checked;
            if (byId("keep_audio_toggle") && byId("keep_audio")) byId("keep_audio_toggle").checked = byId("keep_audio").checked;
            if (byId("no_adx_mask_toggle") && byId("no_adx_mask")) byId("no_adx_mask_toggle").checked = byId("no_adx_mask").checked;
            byId("manual_key_toggle").checked = !!(byId("key") && byId("key").value.trim());
        }

        function syncTogglesToCheckboxes() {
            if (byId("no_parallel") && byId("no_parallel_toggle")) byId("no_parallel").checked = byId("no_parallel_toggle").checked;
            if (byId("fast") && byId("fast_toggle")) byId("fast").checked = byId("fast_toggle").checked;
            if (byId("extract_only") && byId("extract_only_toggle")) byId("extract_only").checked = byId("extract_only_toggle").checked;
            if (byId("keep_audio") && byId("keep_audio_toggle")) byId("keep_audio").checked = byId("keep_audio_toggle").checked;
            if (byId("no_adx_mask") && byId("no_adx_mask_toggle")) byId("no_adx_mask").checked = byId("no_adx_mask_toggle").checked;
            if (!byId("manual_key_toggle").checked && byId("key")) {
                byId("key").value = "";
            }
        }

        function setRunning(running) {
            isTaskRunning = !!running;
            const run = byId("run");
            const dict = t(currentLang());
            run.disabled = running;
            run.textContent = running ? dict.running : dict.run;
            renderPostProcessButtons();
        }

        function setField(field, value) {
            const el = byId(field);
            if (field === "input") {
                const text = String(value || "");
                let parsed = null;
                if (text.trim().startsWith("{")) {
                    try {
                        parsed = JSON.parse(text);
                    } catch (_) {
                        parsed = null;
                    }
                }
                if (parsed && Array.isArray(parsed.files)) {
                    applyInputSelection(parsed.files, parsed.display || "");
                } else if (el) {
                    selectedInputFiles = [];
                    el.value = text;
                    el.title = text;
                }
            } else if (el) {
                el.value = value;
            }
            if (field === "input") {
                previewInput();
            } else if (field === "blk_input") {
                blkParsePending = true;
                blkVersionsData = null;
                blkVersionsEditorText = "";
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
                blkVersionsEditorText = "";
                box.value = "";
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
            const raw = blkVersionsEditorText || String(blkVersionsData.versions_json || "");
            if (box.value !== raw) {
                box.value = raw;
            }
            blkVersionsEditorText = raw;
            updateBlkSearchMatches();
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
            const active = blkSearchMatches[safeIndex];
            const box = byId("blk_versions_box");
            if (active && box) {
                box.focus();
                box.setSelectionRange(active.start, active.end);
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

        function updateBlkSearchMatches() {
            const source = getBlkVersionsText();
            if (!blkSearchQuery) {
                blkSearchMatches = [];
                blkSearchIndex = -1;
                updateBlkSearchStatus();
                return;
            }
            blkSearchMatches = findBlkSearchMatches(source, blkSearchQuery);
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

        function onBlkSearchInput() {
            const input = byId("blk_search_input");
            blkSearchQuery = (input ? input.value : "");
            blkSearchIndex = -1;
            updateBlkSearchMatches();
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
            updateBlkSearchMatches();
        }

        function toggleBlkSearchWholeWord() {
            blkSearchWholeWord = !blkSearchWholeWord;
            blkSearchIndex = -1;
            updateBlkSearchMatches();
        }

        function applyBlkSearch() {
            const input = byId("blk_search_input");
            blkSearchQuery = (input ? input.value : "");
            blkSearchIndex = -1;
            updateBlkSearchMatches();
        }

        function resetBlkSearch() {
            blkSearchQuery = "";
            blkSearchMatches = [];
            blkSearchIndex = -1;
            const input = byId("blk_search_input");
            if (input) input.value = "";
            updateBlkSearchStatus();
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
                blkVersionsEditorText = String((blkVersionsData && blkVersionsData.versions_json) || "");
            } catch (_) {
                blkVersionsData = { error: payloadJson };
                blkVersionsEditorText = "";
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
            const text = getBlkVersionsText();
            if (!text) return;
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
            closeSyncResultModal();
            closeBlkSyncSuccessModal();
            showCopyToast(dict.blk_sync_dialog_waiting || dict.blk_sync_started_toast || dict.blk_versions_sync);
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
            selectedInputFiles = [];
            byId("input").value = "";
            byId("input").title = "";
            renderFileList([]);
            setOverallProgress(0, 0);
        }

        function formatInputSelectionLabel(files) {
            const list = Array.isArray(files) ? files.map((file) => String(file || "").trim()).filter(Boolean) : [];
            if (list.length <= 0) return "";
            if (list.length === 1) return list[0];
            const lang = currentLang();
            if (lang === "zh-CN") return `已选择 ${list.length} 个文件`;
            if (lang === "zh-TW") return `已選擇 ${list.length} 個檔案`;
            return `${list.length} files selected`;
        }

        function applyInputSelection(files, displayText) {
            selectedInputFiles = Array.isArray(files) ? files.map((file) => String(file || "").trim()).filter(Boolean) : [];
            const input = byId("input");
            if (!input) return;
            const label = String(displayText || "").trim() || formatInputSelectionLabel(selectedInputFiles);
            input.value = label;
            input.title = selectedInputFiles.join("\\n");
        }

        function previewInput() {
            if (!bridge) return;
            const mode = getInputMode();
            if (mode === "batch") {
                bridge.previewInput(mode, byId("input").value);
                return;
            }
            const payload = selectedInputFiles.length > 0 ? selectedInputFiles : [byId("input").value];
            bridge.previewInput(mode, JSON.stringify(payload));
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
            const fast = byId("fast");
            const reportRow = byId("report_path_row");
            if (extractOnly) {
                fast.checked = false;
            }
            fast.disabled = false;
            reportRow.style.display = "none";
            if (byId("report")) byId("report").checked = false;
            if (byId("mux_mkv")) byId("mux_mkv").checked = false;
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
            refreshCustomSelect("theme_select");
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
            const inputFiles = selectedInputFiles.length > 0 ? selectedInputFiles : (byId("input").value ? [byId("input").value] : []);
            const mode = getInputMode();
            const payload = {
                language: currentLang(),
                input_mode: mode,
                input: byId("input").value,
                input_files: mode === "single" ? inputFiles : [],
                output: byId("output").value,
                report_output: byId("report_output").value,
                key: byId("manual_key_toggle").checked ? byId("key").value : "",
                no_parallel: byId("no_parallel").checked,
                report: false,
                fast: byId("fast").checked,
                extract_only: byId("extract_only").checked,
                keep_audio: byId("keep_audio").checked,
                no_adx_mask: byId("no_adx_mask").checked,
                mux_mkv: false,
            };
            bridge.runTask(JSON.stringify(payload));
        }

        new QWebChannel(qt.webChannelTransport, function(channel) {
            if (window.__usmBridgeBound) {
                return;
            }
            window.__usmBridgeBound = true;
            bridge = channel.objects.bridge;
            setupCustomSelects();
            bridge.logMessage.connect(appendLog);
            bridge.uiToast.connect(showCopyToast);
            bridge.syncResultReady.connect(onSyncResultReady);
            bridge.blkSavePromptReady.connect(onBlkSavePromptReady);
            bridge.blkSaveCompleted.connect(onBlkSaveCompleted);
            bridge.indexExportResultReady.connect(onIndexExportResult);
            bridge.videoExportReady.connect(onVideoExportReady);
            bridge.videoExportProgress.connect(onVideoExportProgress);
            bridge.videoExportFinished.connect(onVideoExportFinished);
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

        document.addEventListener("click", (event) => {
            const target = event.target;
            if (target instanceof Element && target.closest(".select-shell")) {
                return;
            }
            closeCustomSelects();
        });


        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeCustomSelects();
                hideContextMenu();
            }
        });

        let contextMenu = null;
        let contextMenuCopy = null;
        let contextMenuTarget = null;

        function resolveContextCopyText(target) {
            const selected = (window.getSelection && window.getSelection().toString()) || "";
            if ((selected || "").trim()) return selected.trim();
            if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
                const val = String(target.value || "").trim();
                return val;
            }
            if (!(target instanceof Element)) return "";
            const textHost = target.closest("td, th, .mini-label, .progress-text, .select-trigger-label, .log-box, .blk-preview, .sync-result-text, .save-success-path, .sub, label, button");
            const text = textHost ? String(textHost.textContent || "").trim() : "";
            return text;
        }

        function copyTextToClipboard(text) {
            const value = String(text || "").trim();
            if (!value) return;
            if (bridge && bridge.copyText) {
                bridge.copyText(value);
                return;
            }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(value).catch(() => {});
            }
        }

        function refreshContextMenuLanguage() {
            if (!contextMenuCopy) return;
            const dict = t(currentLang());
            contextMenuCopy.textContent = dict.context_menu_copy || dict.blk_versions_copy || "Copy";
        }

        function initContextMenu() {
            contextMenu = document.createElement("div");
            contextMenu.className = "context-menu";
            contextMenu.innerHTML = `
                <div class="context-menu-item" id="context-menu-copy"></div>
            `;
            document.body.appendChild(contextMenu);
            contextMenuCopy = contextMenu.querySelector("#context-menu-copy");
            refreshContextMenuLanguage();
            
            contextMenuCopy.addEventListener("click", () => {
                if (contextMenuCopy.classList.contains("disabled")) return;
                copyTextToClipboard(resolveContextCopyText(contextMenuTarget));
                hideContextMenu();
            });
        }

        function hideContextMenu() {
            if (contextMenu) {
                contextMenu.classList.remove("show");
            }
        }

        function showContextMenu(event) {
            const target = event.target;
            if (!contextMenu) initContextMenu();
            contextMenuTarget = target;
            const copyText = resolveContextCopyText(target);
            contextMenuCopy.classList.toggle("disabled", !copyText);

            const menuWidth = contextMenu.offsetWidth || 140;
            const menuHeight = contextMenu.offsetHeight || 34;
            const maxLeft = Math.max(8, window.innerWidth - menuWidth - 8);
            const maxTop = Math.max(8, window.innerHeight - menuHeight - 8);
            const left = Math.max(8, Math.min(event.clientX, maxLeft));
            const top = Math.max(8, Math.min(event.clientY, maxTop));
            
            contextMenu.classList.add("show");
            contextMenu.style.left = left + "px";
            contextMenu.style.top = top + "px";
        }

        document.addEventListener("contextmenu", (event) => {
            event.preventDefault();
            showContextMenu(event);
            return false;
        });

        document.addEventListener("click", (event) => {
            if (contextMenu && !contextMenu.contains(event.target)) {
                hideContextMenu();
            }
        });

        document.addEventListener("scroll", () => {
            hideContextMenu();
        }, true);
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
    blkSavePromptReady = Signal(str)
    blkSaveCompleted = Signal(str)
    indexExportResultReady = Signal(str)
    videoExportReady = Signal(str)
    videoExportProgress = Signal(str)
    videoExportFinished = Signal(str)
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
        self._video_export_worker: threading.Thread | None = None
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

    @staticmethod
    def _parse_input_file_selection(raw_input: str) -> list[str]:
        text = str(raw_input or "").strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except Exception:
            decoded = None

        files: Any = None
        if isinstance(decoded, dict):
            files = decoded.get("files")
        elif isinstance(decoded, list):
            files = decoded
        if isinstance(files, list):
            return [str(item).strip() for item in files if str(item).strip()]

        if "\n" in text:
            return [line.strip() for line in text.splitlines() if line.strip()]

        return [text]

    @Slot(str)
    def pickInput(self, mode: str) -> None:
        if mode == "batch":
            picked_dir = QFileDialog.getExistingDirectory(None, self._t("select_usm_folder"))
            if picked_dir:
                self.fieldChosen.emit("input", picked_dir)
            return

        picked_files, _ = QFileDialog.getOpenFileNames(
            None,
            self._t("select_usm_files"),
            "",
            "USM (*.usm);;All files (*.*)",
        )
        if picked_files:
            files = [str(Path(p)) for p in picked_files if str(p).strip()]
            if files:
                self.fieldChosen.emit(
                    "input",
                    json.dumps({"files": files, "display": files[0] if len(files) == 1 else ""}, ensure_ascii=False),
                )

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

    @staticmethod
    def _load_versions_list_from_payload(payload: Any) -> list[dict[str, Any]] | None:
        if isinstance(payload, dict):
            versions_list = payload.get("list")
        elif isinstance(payload, list):
            versions_list = payload
        else:
            versions_list = None
        return versions_list if isinstance(versions_list, list) else None

    def _load_versions_template_payload(self) -> tuple[Any | None, str | None]:
        for template_path in SYNC_TEMPLATE_CANDIDATES:
            if not template_path.exists() or not template_path.is_file():
                continue
            try:
                payload = json.loads(template_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if self._load_versions_list_from_payload(payload) is None:
                continue
            return payload, str(template_path)
        return None, None

    def _collect_versions_key_state(self, payload: Any) -> dict[str, Any]:
        versions_list = self._load_versions_list_from_payload(payload) or []
        nodes: dict[tuple[str, str, str], dict[str, Any]] = {}
        missing_group_versions = 0
        keyed_game_versions: set[str] = set()
        ordered_versions: list[str] = []

        for item in versions_list:
            if not isinstance(item, dict):
                continue
            game_version = str(item.get("version") or "").strip() or "—"
            ordered_versions.append(game_version)
            groups = item.get("videoGroups")
            if isinstance(groups, list):
                for index, group in enumerate(groups):
                    if not isinstance(group, dict):
                        continue
                    owner_version_raw = str(group.get("version") or "").strip()
                    owner_version = owner_version_raw or f"#{index}"
                    has_key = self._parse_sync_key(group.get("key")) is not None
                    if has_key:
                        keyed_game_versions.add(game_version)
                    elif owner_version_raw:
                        missing_group_versions += 1
                    nodes[("group", game_version, owner_version)] = {
                        "kind": "group",
                        "game_version": game_version,
                        "owner_version": owner_version,
                        "has_key": has_key,
                    }
                continue

            has_key = self._parse_sync_key(item.get("key")) is not None
            if has_key:
                keyed_game_versions.add(game_version)
            nodes[("item", game_version, "")] = {
                "kind": "item",
                "game_version": game_version,
                "owner_version": game_version,
                "has_key": has_key,
            }

        missing_nodes = [node for node in nodes.values() if not node["has_key"]]
        return {
            "nodes": nodes,
            "missing_nodes": missing_nodes,
            "missing_versions": {node["game_version"] for node in missing_nodes},
            "missing_group_versions": missing_group_versions,
            "keyed_game_versions": keyed_game_versions,
            "latest_game_version": ordered_versions[-1] if ordered_versions else "",
        }

    @staticmethod
    def _default_versions_save_path(source_path: str) -> str:
        source = Path(str(source_path or "").strip())
        if source.is_file():
            return str(source.with_name("versions.json"))
        if source.exists() and source.is_dir():
            return str(source / "versions.json")
        return str(Path.cwd() / "versions.json")

    @staticmethod
    def _linux_has_desktop_environment() -> bool:
        return bool(
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("XDG_CURRENT_DESKTOP")
            or os.environ.get("DESKTOP_SESSION")
        )

    def _can_reveal_saved_path(self) -> bool:
        if sys.platform.startswith("linux"):
            return self._linux_has_desktop_environment()
        return True

    def _analyze_blk_save_state(self, content: str) -> tuple[dict[str, Any] | None, str | None]:
        try:
            decoded = json.loads(str(content or ""))
        except json.JSONDecodeError as exc:
            return None, self._t("blk_versions_save_invalid_json", reason=exc)

        if not isinstance(decoded, dict):
            return None, self._t("blk_versions_save_invalid_root")

        current_state = self._collect_versions_key_state(decoded)
        missing_nodes = current_state["missing_nodes"]
        latest_game_version = str(current_state["latest_game_version"] or "")
        missing_versions = set(current_state["missing_versions"])
        missing_group_versions = int(current_state["missing_group_versions"] or 0)
        early_versions = {"common", "2.0", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6"}
        keyed_versions = set(current_state["keyed_game_versions"])
        has_later_missing = any(v not in early_versions for v in missing_versions)
        legacy_only_pattern = bool(keyed_versions) and keyed_versions.issubset(early_versions) and has_later_missing

        template_payload, _ = self._load_versions_template_payload()
        same_as_template = False
        if template_payload is not None:
            template_state = self._collect_versions_key_state(template_payload)
            current_missing_ids = {node_id for node_id, node in current_state["nodes"].items() if not node["has_key"]}
            template_missing_ids = {node_id for node_id, node in template_state["nodes"].items() if not node["has_key"]}
            same_as_template = current_missing_ids == template_missing_ids

        if not missing_nodes:
            return {
                "requires_confirmation": False,
                "severity": "direct",
                "missing_count": 0,
                "missing_group_versions": 0,
                "latest_game_version": latest_game_version,
                "same_as_template": same_as_template,
            }, None

        only_latest_missing = bool(missing_nodes) and missing_versions == {latest_game_version}
        if legacy_only_pattern or missing_group_versions >= 4 or not only_latest_missing:
            return {
                "requires_confirmation": True,
                "severity": "severe",
                "missing_count": len(missing_nodes),
                "missing_group_versions": missing_group_versions,
                "latest_game_version": latest_game_version,
                "same_as_template": same_as_template,
            }, None

        return {
            "requires_confirmation": True,
            "severity": "latest-only",
            "missing_count": len(missing_nodes),
            "missing_group_versions": missing_group_versions,
            "latest_game_version": latest_game_version,
            "same_as_template": same_as_template,
        }, None

    def _build_blk_save_prompt_payload(self, analysis: dict[str, Any]) -> dict[str, str]:
        severity = str(analysis.get("severity") or "")
        latest_game_version = str(analysis.get("latest_game_version") or "—")
        missing_count = int(analysis.get("missing_count") or 0)
        missing_group_versions = int(analysis.get("missing_group_versions") or 0)
        if severity == "severe":
            message = self._t(
                "blk_versions_save_confirm_severe",
                missing=missing_count,
                group_missing=missing_group_versions,
                latest=latest_game_version,
            )
        else:
            message = self._t(
                "blk_versions_save_confirm_latest_only",
                missing=missing_count,
                latest=latest_game_version,
            )
        return {
            "title": self._t("blk_versions_save_confirm_title"),
            "message": message,
        }

    def _save_blk_versions_to_path(self, content: str) -> str | None:
        with self._blk_result_lock:
            result = dict(self._last_blk_result or {})
        default_path = self._default_versions_save_path(str(result.get("input") or ""))
        target_path, _ = QFileDialog.getSaveFileName(
            None,
            self._t("select_versions_save_file"),
            default_path,
            "JSON (*.json);;All files (*.*)",
        )
        if not target_path:
            return None
        try:
            Path(target_path).write_text(str(content or ""), encoding="utf-8")
        except OSError as exc:
            self.logMessage.emit(self._t("error_line", file="versions.json", reason=exc))
            self.uiToast.emit(self._t("blk_versions_save_failed", reason=exc))
            return None
        return target_path

    @Slot(str)
    def requestSaveBlkVersions(self, content: str) -> None:
        analysis, error = self._analyze_blk_save_state(content)
        if error:
            self.uiToast.emit(error)
            self.logMessage.emit(error)
            return
        if not analysis:
            self.uiToast.emit(self._t("blk_versions_save_failed_unknown"))
            return
        if analysis.get("requires_confirmation"):
            self.blkSavePromptReady.emit(
                json.dumps(self._build_blk_save_prompt_payload(analysis), ensure_ascii=False)
            )
            return

        saved_path = self._save_blk_versions_to_path(content)
        if not saved_path:
            return
        self.blkSaveCompleted.emit(
            json.dumps(
                {
                    "message": self._t("blk_versions_saved_message"),
                    "path": saved_path,
                    "can_reveal": self._can_reveal_saved_path(),
                },
                ensure_ascii=False,
            )
        )
        self.logMessage.emit(self._t("blk_versions_saved_log", path=saved_path))

    @Slot(str)
    def confirmSaveBlkVersions(self, content: str) -> None:
        analysis, error = self._analyze_blk_save_state(content)
        if error:
            self.uiToast.emit(error)
            self.logMessage.emit(error)
            return
        if not analysis:
            self.uiToast.emit(self._t("blk_versions_save_failed_unknown"))
            return

        saved_path = self._save_blk_versions_to_path(content)
        if not saved_path:
            return
        self.blkSaveCompleted.emit(
            json.dumps(
                {
                    "message": self._t("blk_versions_saved_message"),
                    "path": saved_path,
                    "can_reveal": self._can_reveal_saved_path(),
                },
                ensure_ascii=False,
            )
        )
        self.logMessage.emit(self._t("blk_versions_saved_log", path=saved_path))

    @Slot(str)
    def revealSavedPath(self, target_path: str) -> None:
        path = Path(str(target_path or "").strip())
        if not path.exists():
            self.uiToast.emit(self._t("blk_versions_reveal_failed"))
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", f"/select,{path}"])
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
                return
            if not self._linux_has_desktop_environment():
                return

            uri = path.resolve().as_uri()
            parent = path.resolve().parent
            for command in (
                ["nautilus", "--select", str(path)],
                ["dolphin", "--select", str(path)],
                ["nemo", str(path)],
                [
                    "dbus-send",
                    "--session",
                    "--dest=org.freedesktop.FileManager1",
                    "--type=method_call",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:{uri}",
                    "string:",
                ],
                ["xdg-open", str(parent)],
            ):
                if command[0] != "dbus-send" and shutil.which(command[0]) is None:
                    continue
                try:
                    subprocess.Popen(command)
                    return
                except OSError:
                    continue
            self.uiToast.emit(self._t("blk_versions_reveal_failed"))
        except OSError:
            self.uiToast.emit(self._t("blk_versions_reveal_failed"))

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
            key_val = self._parse_sync_key(row.get("usm_decrypt_key"))
            if key_val is None:
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
        self.syncResultReady.emit(
            json.dumps(
                {
                    "unresolved_count": unresolved_groups,
                    "details_text": self._build_sync_popup_text(unresolved_details),
                    "success_message": self._t(
                        "blk_sync_all_resolved_message",
                        updated=updated_groups,
                        skipped=skipped_groups,
                    ),
                },
                ensure_ascii=False,
            )
        )
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

        files: list[Path] = []
        normalized_mode = str(mode or "single").strip().lower()
        if normalized_mode == "batch":
            input_path = Path(input_text)
            if input_path.exists() and input_path.is_dir():
                files = collect_usm_inputs(input_path)
        else:
            for item in self._parse_input_file_selection(input_text):
                input_path = Path(item)
                if (
                    input_path.exists()
                    and input_path.is_file()
                    and input_path.suffix.lower() == ".usm"
                ):
                    files.append(input_path)

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

    @staticmethod
    def _build_index_item(report: dict[str, Any]) -> dict[str, Any]:
        item: dict[str, Any] = {
            "file": report.get("file"),
            "status": report.get("status"),
            "reason": report.get("reason"),
            "extract_only": bool(report.get("extract_only")),
            "key1_hex_little": report.get("key1_hex_little"),
            "key2_hex_little": report.get("key2_hex_little"),
            "usm_decrypt_key": report.get("usm_decrypt_key")
            if report.get("usm_decrypt_key") is not None
            else report.get("genshin_like_key"),
            "full_key_hex": report.get("full_key_hex"),
            "report_path": report.get("report_path"),
            "report_written": bool(report.get("report_written")),
        }
        video = report.get("video") or {}
        mux = report.get("mux") or {}
        if isinstance(video, dict):
            item["video"] = {
                "path": video.get("path"),
                "format": video.get("format"),
            }
        if isinstance(mux, dict):
            item["mux"] = {
                "ok": bool(mux.get("ok")),
                "mp4": mux.get("mp4"),
                "mkv": mux.get("mkv"),
            }
        return item

    @Slot()
    def exportIndexJson(self) -> None:
        with self._reports_lock:
            reports = [dict(v) for v in self._reports_by_id.values()]

        if not reports:
            msg = self._t("index_no_data")
            self.logMessage.emit(msg)
            self.indexExportResultReady.emit(
                json.dumps(
                    {
                        "title": self._t("index_export_failed_title"),
                        "message": msg,
                        "path": "",
                        "can_reveal": False,
                    },
                    ensure_ascii=False,
                )
            )
            return

        reports.sort(key=lambda x: str(x.get("file") or ""))
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "total": len(reports),
            "ok": sum(1 for r in reports if r.get("status") == "ok"),
            "skipped": sum(1 for r in reports if r.get("status") == "skipped"),
            "error": sum(1 for r in reports if r.get("status") == "error"),
            "items": [self._build_index_item(r) for r in reports],
        }

        default_path = str(Path.cwd() / "usm_processed_index.json")
        target_path, _ = QFileDialog.getSaveFileName(
            None,
            self._t("select_index_save_file"),
            default_path,
            "JSON (*.json);;All files (*.*)",
        )
        if not target_path:
            return

        try:
            Path(target_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            msg = self._t("index_export_failed", reason=exc)
            self.logMessage.emit(msg)
            self.indexExportResultReady.emit(
                json.dumps(
                    {
                        "title": self._t("index_export_failed_title"),
                        "message": msg,
                        "path": "",
                        "can_reveal": False,
                    },
                    ensure_ascii=False,
                )
            )
            return

        msg = self._t("index_exported", path=target_path)
        self.logMessage.emit(msg)
        self.indexExportResultReady.emit(
            json.dumps(
                {
                    "title": self._t("index_export_success_title"),
                    "message": msg,
                    "path": target_path,
                    "can_reveal": self._can_reveal_saved_path(),
                },
                ensure_ascii=False,
            )
        )

    @Slot()
    def exportAllReports(self) -> None:
        with self._reports_lock:
            reports = [dict(v) for v in self._reports_by_id.values()]

        if not reports:
            msg = self._t("report_not_ready")
            self.indexExportResultReady.emit(
                json.dumps(
                    {
                        "title": self._t("export_all_reports_title"),
                        "message": msg,
                        "path": "",
                        "can_reveal": False,
                    },
                    ensure_ascii=False,
                )
            )
            return

        first_file = Path(str(reports[0].get("file") or Path.cwd()))
        folder_by_lang = {
            "zh-cn": "USM_解密报告",
            "zh-tw": "USM_解密報告",
            "en": "USM_Decryption_Reports",
        }
        folder_name = folder_by_lang.get(self._get_language().lower(), folder_by_lang["en"])
        default_root = first_file.parent / folder_name
        target_dir = QFileDialog.getExistingDirectory(
            None,
            self._t("select_report_export_folder"),
            str(default_root),
        )
        if not target_dir:
            return

        target_root = Path(target_dir)
        target_root.mkdir(parents=True, exist_ok=True)
        ok_count = 0
        fail_count = 0
        for report in reports:
            src = Path(str(report.get("file") or "report"))
            base = f"{src.stem}_Report.json" if src.stem else "USM_Report.json"
            out = target_root / base
            if out.exists():
                idx = 2
                while True:
                    cand = target_root / f"{src.stem}_Report_{idx}.json"
                    if not cand.exists():
                        out = cand
                        break
                    idx += 1
            try:
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                ok_count += 1
            except OSError:
                fail_count += 1

        message = self._t("export_all_reports_done", ok=ok_count, failed=fail_count)
        self.logMessage.emit(message)
        self.indexExportResultReady.emit(
            json.dumps(
                {
                    "title": self._t("export_all_reports_title"),
                    "message": message,
                    "path": str(target_root),
                    "can_reveal": self._can_reveal_saved_path(),
                },
                ensure_ascii=False,
            )
        )

    @Slot()
    def pickVideoExportOutput(self) -> None:
        picked_dir = QFileDialog.getExistingDirectory(None, self._t("select_video_export_folder"))
        if picked_dir:
            self.fieldChosen.emit("video_export_output", picked_dir)

    @Slot(str)
    def startVideoExport(self, payload_json: str) -> None:
        if self._video_export_worker and self._video_export_worker.is_alive():
            return
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}

        fmt = str(payload.get("format") or "mp4").lower()
        output_text = str(payload.get("output_dir") or "").strip()
        if not output_text:
            self.videoExportFinished.emit(
                json.dumps(
                    {
                        "title": self._t("video_export_result_title"),
                        "message": self._t("video_export_output_required"),
                        "path": "",
                        "can_reveal": False,
                    },
                    ensure_ascii=False,
                )
            )
            return
        output_dir = Path(output_text)

        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        ffmpeg = find_ffmpeg(None)
        if not ffmpeg:
            self.videoExportFinished.emit(
                json.dumps(
                    {
                        "title": self._t("video_export_result_title"),
                        "message": self._t("video_export_ffmpeg_missing"),
                        "path": "",
                        "can_reveal": False,
                    },
                    ensure_ascii=False,
                )
            )
            return

        self._video_export_worker = threading.Thread(
            target=self._run_video_export,
            args=(fmt, output_dir, candidates, ffmpeg),
            daemon=True,
        )
        self._video_export_worker.start()

    def _run_video_export(self, fmt: str, output_dir: Path, candidates: list[Any], ffmpeg: str) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, len(candidates))
        done = 0
        success = 0
        failed = 0

        for item in candidates:
            row_id = str((item or {}).get("id") or "")
            name = str((item or {}).get("name") or row_id or "video")
            ivf = Path(str((item or {}).get("ivf") or ""))
            wavs = [Path(str(p)) for p in ((item or {}).get("wavs") or []) if str(p or "").strip()]
            self.videoExportProgress.emit(
                json.dumps(
                    {
                        "id": row_id,
                        "progress": 10,
                        "status": self._t("video_export_status_running"),
                        "done": done,
                        "total": total,
                    },
                    ensure_ascii=False,
                )
            )

            ok = False
            if ivf.exists() and ivf.is_file():
                stem = Path(name).stem if name else ivf.stem
                if fmt == "mkv":
                    out = output_dir / f"{stem}.mkv"
                    ok, _ = mux_to_mkv(ffmpeg, ivf, wavs, out)
                else:
                    out = output_dir / f"{stem}.mp4"
                    ok, _ = transcode_ivf_to_mp4(ffmpeg, ivf, wavs, out)

            done += 1
            if ok:
                success += 1
            else:
                failed += 1
            self.videoExportProgress.emit(
                json.dumps(
                    {
                        "id": row_id,
                        "progress": 100,
                        "status": self._t("video_export_status_done") if ok else self._t("video_export_status_failed"),
                        "done": done,
                        "total": total,
                    },
                    ensure_ascii=False,
                )
            )

        self.videoExportFinished.emit(
            json.dumps(
                {
                    "title": self._t("video_export_result_title"),
                    "message": self._t("video_export_done", ok=success, failed=failed),
                    "path": str(output_dir),
                    "can_reveal": self._can_reveal_saved_path(),
                },
                ensure_ascii=False,
            )
        )

    def _collect_video_export_candidates(self, reports: list[dict]) -> tuple[list[dict[str, Any]], str]:
        if not reports:
            return [], ""
        if any(str(r.get("status") or "") != "ok" for r in reports):
            return [], ""
        ok_reports = reports

        candidates: list[dict[str, Any]] = []
        all_have_ivf = True
        default_parent = ""
        for report in ok_reports:
            video = report.get("video") or {}
            ivf_text = str(video.get("path") or "").strip()
            ivf = Path(ivf_text) if ivf_text else None
            if not ivf or not ivf.exists() or ivf.suffix.lower() != ".ivf":
                all_have_ivf = False
                continue
            if not default_parent:
                default_parent = str(ivf.parent)

            wavs: list[str] = []
            audio = report.get("audio") or {}
            if isinstance(audio, dict):
                for item in audio.values():
                    info = item if isinstance(item, dict) else {}
                    decode = info.get("decode") if isinstance(info.get("decode"), dict) else {}
                    wav_text = str(decode.get("wav") or "").strip()
                    if wav_text and Path(wav_text).exists():
                        wavs.append(wav_text)

            file_name = Path(str(report.get("file") or ivf.name)).name
            row_id = str(report.get("id") or "")
            candidates.append(
                {
                    "id": row_id,
                    "name": file_name,
                    "file": str(report.get("file") or ""),
                    "ivf": str(ivf),
                    "wavs": wavs,
                }
            )

        if not all_have_ivf or len(candidates) != len(ok_reports):
            return [], ""
        return candidates, default_parent

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
        input_files_payload = payload.get("input_files") if isinstance(payload.get("input_files"), list) else []
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

        input_path = Path(input_text) if input_text else Path.cwd()
        input_root: str | None = None

        if input_mode == "batch":
            if not input_path.exists():
                raise ValueError(self._t("input_not_found", path=input_path))
            if not input_path.is_dir():
                raise ValueError(self._t("batch_requires_folder"))
            input_files: list[Path] = []
            input_root = str(input_path)
        else:
            if input_files_payload:
                input_files = []
                for item in input_files_payload:
                    path = Path(str(item or "").strip())
                    if not path.exists():
                        raise ValueError(self._t("input_not_found", path=path))
                    if not path.is_file():
                        raise ValueError(self._t("single_requires_file"))
                    if path.suffix.lower() != ".usm":
                        raise ValueError(self._t("single_requires_usm"))
                    input_files.append(path)
                if input_files:
                    try:
                        parents = {str(path.resolve().parent) for path in input_files}
                    except OSError:
                        parents = set()
                    if len(parents) == 1:
                        input_root = next(iter(parents))
                    input_path = input_files[0]
            else:
                if not input_path.exists():
                    raise ValueError(self._t("input_not_found", path=input_path))
                if not input_path.is_file():
                    raise ValueError(self._t("single_requires_file"))
                if input_path.suffix.lower() != ".usm":
                    raise ValueError(self._t("single_requires_usm"))
                input_files = [input_path]
                input_root = str(input_path.parent)

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
            input_root=input_root,
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
            "input_path": input_path if input_mode == "batch" else input_files[0],
            "input_files": input_files if input_mode == "single" else None,
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
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s][%(name)s] %(message)s", datefmt="%H:%M:%S"))
        package_logger = logging.getLogger("usmdiviner")
        old_package_level = package_logger.level
        package_logger.setLevel(logging.DEBUG)
        package_logger.addHandler(handler)

        try:
            input_path: Path = config["input_path"]
            input_files: list[Path] | None = config.get("input_files")
            opt: ProcessOptions = config["opt"]
            no_parallel: bool = config["no_parallel"]
            with self._reports_lock:
                self._reports_by_id.clear()
            self.videoExportReady.emit(
                json.dumps(
                    {
                        "candidates": [],
                        "default_output_dir": "",
                    },
                    ensure_ascii=False,
                )
            )

            files = input_files if input_files else collect_usm_inputs(input_path)
            if not files and input_path.exists() and input_path.is_file() and input_path.suffix.lower() == ".usm":
                files = [input_path]
            if not files:
                self.logMessage.emit(self._t("no_usm_files_found"))
                self.videoExportReady.emit(
                    json.dumps(
                        {
                            "candidates": [],
                            "default_output_dir": "",
                        },
                        ensure_ascii=False,
                    )
                )
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
                    + (find_ffmpeg(opt.ffmpeg) or "not found; MP4/MKV output will be skipped")
                )

            reports: list[dict] = []
            progress_by_id = {row["id"]: 0 for row in rows}
            progress_lock = threading.Lock()
            progress_marks: dict[str, int] = {}

            def emit_overall_from_rows() -> None:
                with progress_lock:
                    total_progress = sum(progress_by_id.values())
                self.overallProgressUpdate.emit(
                    json.dumps(
                        {"done": total_progress / 100, "total": len(files)},
                        ensure_ascii=False,
                    )
                )

            def emit_row_progress(row_id: str, file_name: str, value: int) -> None:
                safe_value = int(max(0, min(100, value)))
                self.fileProgressUpdate.emit(
                    json.dumps({"id": row_id, "progress": safe_value}, ensure_ascii=False)
                )
                with progress_lock:
                    progress_by_id[row_id] = safe_value
                mark = safe_value // 10
                prev_mark = progress_marks.get(row_id, -1)
                if mark > prev_mark:
                    progress_marks[row_id] = mark
                    self.logMessage.emit(f"[DEBUG] [{file_name}] progress={safe_value}%")
                emit_overall_from_rows()

            def make_progress_callback(
                row_id: str,
                file_name: str,
                stage_plan: list[tuple[int, str]],
                announced_stage_logs: set[str],
            ):
                def _callback(value: int) -> None:
                    emit_row_progress(row_id, file_name, int(value))
                    self._emit_progress_stage_logs(
                        file_name,
                        int(value),
                        stage_plan,
                        announced_stage_logs,
                    )

                return _callback

            if use_parallel:
                for path in files:
                    self.logMessage.emit(self._t("process_queued", file=path.name))
                with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    fut_map = {}
                    for path in files:
                        row_id = path_to_id.get(str(path), "")
                        stage_plan = self._stage_plan(opt)
                        announced_stage_logs: set[str] = set()
                        if row_id:
                            emit_row_progress(row_id, path.name, 6)
                        self.logMessage.emit(self._t("process_start_line", file=path.name))
                        fut = executor.submit(
                            process_one,
                            str(path),
                            opt,
                            make_progress_callback(row_id, path.name, stage_plan, announced_stage_logs)
                            if row_id
                            else None,
                        )
                        fut_map[fut] = path
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
                            emit_row_progress(report["id"], path.name, 100)
                        self.fileRowUpdate.emit(json.dumps(report, ensure_ascii=False))
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
                        emit_row_progress(row_id, path.name, 8)
                    try:
                        report = process_one(
                            str(path),
                            opt,
                            progress_callback=make_progress_callback(row_id, path.name, stage_plan, announced_stage_logs)
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
                        emit_row_progress(report["id"], path.name, 100)
                    self.fileRowUpdate.emit(json.dumps(report, ensure_ascii=False))
                    self.logMessage.emit(_summary_line(self._get_language(), report))
                    for detail in _report_detail_lines(report):
                        self.logMessage.emit(detail)

            self.overallProgressUpdate.emit(
                json.dumps({"done": len(files), "total": len(files)}, ensure_ascii=False)
            )

            ok = sum(1 for r in reports if r.get("status") == "ok")
            skipped = sum(1 for r in reports if r.get("status") == "skipped")
            errors = sum(1 for r in reports if r.get("status") == "error")
            self.logMessage.emit(
                self._t("done_summary", ok=ok, skipped=skipped, errors=errors)
            )
            candidates, default_output_dir = self._collect_video_export_candidates(reports)
            self.videoExportReady.emit(
                json.dumps(
                    {
                        "candidates": candidates,
                        "default_output_dir": default_output_dir,
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            package_logger.removeHandler(handler)
            package_logger.setLevel(old_package_level)
            self.runStateChanged.emit(False)
            self.logMessage.emit(self._t("end"))


def _summary_line(lang: str, report: dict) -> str:
    file_name = Path(report.get("file", "?")).name
    status = report.get("status")
    if status == "ok":
        mux = report.get("mux") or {}
        if mux.get("ok"):
            primary = mux.get("mp4") or mux.get("mkv")
            if primary:
                return _t(lang, "ok_mux_line", file=file_name, mkv=primary)
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
            if mux.get("mp4"):
                lines.append("     mp4: {mp4} (primary)".format(mp4=mux.get("mp4")))
            if mux.get("mkv"):
                lines.append("     mkv: {mkv} (fallback)".format(mkv=mux.get("mkv")))
            if mux.get("mp4_ok") is False:
                lines.append(
                    "     mp4: skipped ({msg})".format(
                        msg=mux.get("mp4_message") or mux.get("mp4_log_tail") or "unknown"
                    )
                )
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

from __future__ import annotations

import concurrent.futures as futures
import json
import logging
import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog

from .blk_versions import parse_blk_versions
from .exceptions import UsmDivinerError
from .keys import parse_full_key
from .models import ProcessOptions
from .processor import process_one
from .usm import collect_usm_inputs

logger = logging.getLogger(__name__)
DEFAULT_LANGUAGE = "zh-CN"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LANG_DIR = ASSETS_DIR / "i18n"
FONT_PATH = ASSETS_DIR / "fonts" / "zh-cn.ttf"
SUPPORTED_LANGUAGES = ("zh-CN", "zh-TW", "en")


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
        }

        input[type="text"]:focus {
            border-color: var(--acc);
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        input[type="text"]::placeholder {
            color: var(--muted);
            opacity: 0.78;
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
            font-family: Consolas, Courier New, monospace;
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

        @keyframes copiedFlash {
            0% { background: var(--flash-bg); }
            100% { background: transparent; }
        }

        .table-wrap::-webkit-scrollbar,
        .log-box::-webkit-scrollbar {
            width: 12px;
            height: 12px;
        }

        .table-wrap::-webkit-scrollbar-track,
        .log-box::-webkit-scrollbar-track {
            background: var(--scroll-track);
            border-radius: 999px;
        }

        .table-wrap::-webkit-scrollbar-thumb,
        .log-box::-webkit-scrollbar-thumb {
            background: var(--scroll-thumb);
            border-radius: 999px;
            border: 2px solid var(--scroll-track);
        }

        .table-wrap::-webkit-scrollbar-button,
        .log-box::-webkit-scrollbar-button {
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
            font-family: Consolas, Courier New, monospace;
            font-size: 12px;
            line-height: 1.4;
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

        .blk-summary {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.45;
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
            font-family: Consolas, Courier New, monospace;
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
                <button class="btn" id="export_log_btn" onclick="exportLog()">Export</button>
                <button class="btn" id="clear_log_btn" onclick="clearLog()">Clear log</button>
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
                <button class="btn" id="blk_versions_close_x" onclick="closeBlkVersionsModal()">Close</button>
            </div>
            <div class="blk-modal-body">
                <div class="blk-summary" id="blk_versions_summary">No versions.json data available.</div>
                <pre id="blk_versions_box" class="blk-preview"></pre>
            </div>
            <div class="modal-actions">
                <button class="btn" id="blk_versions_copy_btn" onclick="copyBlkVersions()">Copy</button>
                <button class="btn" id="blk_versions_close_btn" onclick="closeBlkVersionsModal()">Close</button>
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
        let blkParsePending = false;

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

        function blkEntryCount(value) {
            if (Array.isArray(value)) return value.length;
            if (value && typeof value === "object") return Object.keys(value).length;
            return 0;
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
                    { id: `${row.id}_key1`, text: "—" },
                    { id: `${row.id}_key2`, text: "—" },
                    { id: `${row.id}_genshin`, text: "—" },
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
                        td.title = "Double-click to copy";
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
                cell.innerHTML = `<button class="btn mini-btn" title="${dict.save_report_tooltip}" onclick="saveReportForRow('${id}')">${dict.save_report}</button>`;
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
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
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
            } catch (_) {
                // ignore clipboard failure in restricted environment
            }
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
            setText("blk_versions_close_x", dict.close);
            setText("blk_versions_copy_btn", dict.blk_versions_copy);
            setText("blk_versions_close_btn", dict.close);
            setPlaceholder("output", dict.placeholder_output);
            setPlaceholder("report_output", dict.placeholder_report_output);
            setPlaceholder("blk_input", dict.placeholder_blk_input);
            byId("input_pick_btn").setAttribute("data-tooltip", dict.btn_input_pick_tooltip);
            byId("output_pick_btn").setAttribute("data-tooltip", dict.btn_output_pick_tooltip);
            byId("report_pick_btn").setAttribute("data-tooltip", dict.btn_report_pick_tooltip);
            byId("blk_pick_btn").setAttribute("data-tooltip", dict.btn_blk_pick_tooltip);
            setText("settings_title", dict.settings_title);
            setText("settings_ok_btn", dict.settings_ok);
            setText("settings_cancel_btn", dict.settings_cancel);
            byId("open_settings_btn").setAttribute("data-tooltip", dict.settings_title);
            byId("open_log_btn").setAttribute("data-tooltip", dict.btn_logs_tooltip);
            byId("run").setAttribute("data-tooltip", dict.btn_run_tooltip);
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
            syncInputMode();
            syncRules();
            updateManualKeyVisibility();
            renderBlkStatus();
            renderBlkModal();
            initColumnResizers();
        }

        function appendLog(line) {
            logLines.push(line);
            renderLogBox();
        }

        function renderLogBox() {
            const box = byId("log_box");
            if (!box) return;
            box.textContent = logLines.join("\\n");
            box.scrollTop = box.scrollHeight;
        }

        function clearLog() {
            logLines = [];
            renderLogBox();
        }

        function exportLog() {
            const dict = t(currentLang());
            const content = logLines.join("\\n");
            const ts = new Date().toISOString().replace(/[.:]/g, "-");
            const name = "usmdiviner-log-" + ts + ".txt";
            const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = name;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            appendLog(dict.log_exported.replace("{name}", name));
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
            const box = byId("blk_versions_box");
            const dict = t(currentLang());
            if (!summary || !box) return;
            if (!blkVersionsData || !blkVersionsData.versions_json || blkVersionsData.versions_json === "null") {
                summary.textContent = dict.blk_versions_modal_empty;
                box.textContent = "";
                return;
            }
            const count = blkEntryCount(blkVersionsData.versions_list);
            const source = blkVersionsData.versions ? blkVersionsData.versions.source : null;
            const kind = blkVersionsData.versions ? blkVersionsData.versions.kind : null;
            const offset = blkVersionsData.versions ? blkVersionsData.versions.offset : null;
            summary.textContent = dict.blk_versions_modal_summary
                .replace("{count}", String(count))
                .replace("{source}", String(source || "—"))
                .replace("{kind}", String(kind || "—"))
                .replace("{offset}", String(offset === null || offset === undefined ? "—" : offset));
            box.textContent = blkVersionsData.versions_json;
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
        }

        function closeBlkVersionsModal() {
            byId("blk_versions_modal").classList.add("hidden");
        }

        async function copyBlkVersions() {
            if (!blkVersionsData || !blkVersionsData.versions_json || blkVersionsData.versions_json === "null") return;
            const text = blkVersionsData.versions_json;
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(text);
                } else {
                    const ta = document.createElement("textarea");
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand("copy");
                    ta.remove();
                }
            } catch (_) {
                // ignore clipboard failure in restricted environment
            }
        }

        function getInputMode() {
            return byId("mode_batch").checked ? "batch" : "single";
        }

        function syncInputMode() {
            const mode = getInputMode();
            const dict = t(currentLang());
            byId("input").value = "";
            byId("input_label").textContent = mode === "batch" ? dict.input_usm_folder : dict.input_usm_file;
            byId("input_pick_btn").textContent = mode === "batch" ? dict.pick : dict.browse;
            byId("input").placeholder = mode === "batch" ? dict.placeholder_input_folder : dict.placeholder_input_file;
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
            bridge = channel.objects.bridge;
            bridge.logMessage.connect(appendLog);
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
        self.blkVersionsReady.emit(json.dumps(result, ensure_ascii=False))
        if versions_list:
            self.logMessage.emit(
                self._t("blk_parse_success", count=count, candidates=len(candidates), entries=len(versions_list))
            )
        else:
            self.logMessage.emit(
                self._t("blk_parse_no_versions", count=count, candidates=len(candidates))
            )

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

            reports: list[dict] = []
            done_count = 0
            if use_parallel:
                with futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    fut_map = {executor.submit(process_one, str(path), opt): path for path in files}
                    for fut in futures.as_completed(fut_map):
                        path = fut_map[fut]
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
            else:
                for path in files:
                    row_id = path_to_id.get(str(path), "")
                    if row_id:
                        self.fileProgressUpdate.emit(
                            json.dumps({"id": row_id, "progress": 12}, ensure_ascii=False)
                        )
                    try:
                        report = process_one(
                            str(path),
                            opt,
                            progress_callback=(
                                lambda value, _row_id=row_id: self.fileProgressUpdate.emit(
                                    json.dumps(
                                        {"id": _row_id, "progress": int(value)},
                                        ensure_ascii=False,
                                    )
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


def main() -> int:
    app = QApplication([])
    view = QWebEngineView()
    view.setWindowTitle(_t(DEFAULT_LANGUAGE, "app_title"))
    view.setFixedSize(1180, 850)

    bridge = WebBridge()
    channel = QWebChannel(view.page())
    channel.registerObject("bridge", bridge)
    view.page().setWebChannel(channel)

    bridge.logMessage.connect(
        lambda line: view.page().runJavaScript(f"appendLog({json.dumps(line)});")
    )
    bridge.runStateChanged.connect(
        lambda running: view.page().runJavaScript(
            f"setRunning({'true' if running else 'false'});"
        )
    )
    bridge.windowTitleChanged.connect(view.setWindowTitle)
    bridge.fieldChosen.connect(
        lambda field, value: view.page().runJavaScript(
            f"setField({json.dumps(field)}, {json.dumps(value)});"
        )
    )

    html = _render_html()
    # Use local workspace root as base URL so relative asset paths can be loaded.
    base_dir = ASSETS_DIR.parent.resolve()
    view.setHtml(html, QUrl.fromLocalFile(str(base_dir) + os.sep))
    view.show()
    return app.exec()

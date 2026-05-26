from __future__ import annotations

import concurrent.futures as futures
import dataclasses
import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainterPath, QResizeEvent, QRegion
from PySide6.QtCore import QObject, Qt, Signal, Slot, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QDialog, QHBoxLayout, QLabel, QPushButton, QProgressBar, QVBoxLayout

from .blk_versions import parse_blk_versions
from .exceptions import UsmDivinerError
from .keys import full_key_from_genshin_like_key, parse_full_key
from .models import ProcessOptions
from .processor import process_one
from .tools import detect_video_export_hardware, find_ffmpeg, find_vgmstream
from .tools import mux_to_mkv, mux_to_mkv_soft, transcode_ivf_to_mp4, transcode_ivf_to_mp4_soft
from .usm import collect_usm_inputs
from .path_utils import get_resource_path, get_user_data_path, get_external_tool_path

logger = logging.getLogger(__name__)
DEFAULT_LANGUAGE = "zh-CN"
ASSETS_DIR = get_resource_path("assets")
LANG_DIR = get_resource_path("assets/i18n")
FONT_PATH = get_resource_path("assets/fonts/zh-cn.ttf")
APP_ICON_PATH = get_resource_path("assets/icon/wolf_favicon.png")
SUPPORTED_LANGUAGES = ("zh-CN", "zh-TW", "en")
SUBTITLE_LANG_CODES = (
    "CHS",
    "CHT",
    "DE",
    "EN",
    "ES",
    "FR",
    "ID",
    "IT",
    "JP",
    "KR",
    "PT",
    "RU",
    "TH",
    "TR",
    "VI",
)
ONLINE_SUBTITLE_RAW_URL = "https://gitlab.com/Dimbreath/AnimeGameData/-/raw/master/Subtitle/{lang}/{name}.srt"
SUPPORTED_GAMES: tuple[str, ...] = (
    "honkai_star_rail",
    "genshin_impact",
    "zenless_zone_zero",
    "honkai_impact_3rd",
    "petit_planet",
)
DEFAULT_GAME = "genshin_impact"
GENSHIN_GAME_ID = "genshin_impact"

# Backward-compatibility source files used for first-time migration into
# per-game folders, especially for existing Genshin-only installs.
LEGACY_SYNC_TEMPLATE_CANDIDATES = (
    get_resource_path("assets/usm_data/genshin_impact/usm_key_base.json"),
    get_resource_path("assets/versions_reference.json"),
    get_resource_path("assets/usm_key_base.json"),
    get_resource_path("assets/key_template_versions.json"),
    get_user_data_path() / "versions_reference.json",
    get_user_data_path() / "usm_key_base.json",
)
LEGACY_USM_KEY_INCREMENT_CANDIDATES = (
    get_user_data_path() / "usm_data/usm_key_increment.json",
    get_resource_path("assets/usm_data/genshin_impact/usm_key_increment.json"),
)


def _load_translations() -> dict[str, dict[str, str]]:
    translations: dict[str, dict[str, str]] = {}
    for lang in SUPPORTED_LANGUAGES:
        path = LANG_DIR / f"{lang}.json"
        with path.open("r", encoding="utf-8-sig") as fp:
            translations[lang] = json.load(fp)
    return translations


TRANSLATIONS = _load_translations()
QT_DIALOG_FONT_FAMILY = ""


def _t(lang: str, key: str, **kwargs) -> str:
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANGUAGE]
    text = table.get(key) or TRANSLATIONS[DEFAULT_LANGUAGE].get(key) or key
    return text.format(**kwargs) if kwargs else text


HTML_TEMPLATE = r"""<!doctype html>
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

        /* Keep text static across pages: no drag-select, no I-beam cursor on non-editable content. */
        :not(input):not(textarea):not([contenteditable="true"]) {
            user-select: none;
            -webkit-user-select: none;
            cursor: default;
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
            height: 100vh;
            overflow: hidden;
        }

        body, .panel, .btn, input[type="text"], .control select, .table-wrap, .log-box, .modal-card {
            transition: background-color 280ms ease, color 240ms ease, border-color 280ms ease, box-shadow 280ms ease;
        }

        .wrap {
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
        }

        .window-titlebar {
            height: 38px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 8px 0 10px;
            border-bottom: 1px solid var(--line);
            background: linear-gradient(180deg, var(--panel0), var(--panel1));
            user-select: none;
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
        }

        .window-title-left {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
            cursor: move;
        }

        .window-title-text {
            font-size: 12px;
            color: var(--muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .window-title-actions {
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .window-btn {
            width: 34px;
            height: 26px;
            border: 1px solid var(--btn-border);
            border-radius: 7px;
            background: linear-gradient(180deg, var(--btn-bg-0), var(--btn-bg-1));
            color: var(--btn-fg);
            font-size: 14px;
            line-height: 1;
            cursor: pointer;
        }

        .window-btn:hover {
            filter: brightness(1.06);
        }

        #window_min_btn:hover {
            background: linear-gradient(180deg, #4e7dd1, #355a9b);
            border-color: #2e4c81;
            color: #ffffff;
        }

        .window-btn-close:hover {
            background: linear-gradient(180deg, #cf4a4a, #a73636);
            border-color: #9c2c2c;
            color: #ffffff;
        }

        .app-icon {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            object-fit: cover;
            flex: 0 0 16px;
        }

        #title_icon {
            width: 42px;
            height: 42px;
            flex: 0 0 42px;
            border-radius: 7px;
        }

        .panel {
            height: 100%;
            display: flex;
            flex-direction: column;
            background: linear-gradient(180deg, var(--panel0), var(--panel1));
            border: 1px solid var(--line);
            border-radius: 16px;
            box-shadow: 0 6px 18px #00000033;
            overflow: hidden;
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

        .brand {
            display: flex;
            align-items: center;
            gap: 9px;
            min-width: 0;
        }

        .brand-text {
            min-width: 0;
        }

        .title {
            margin: 0;
            font-size: 22px;
            line-height: 1.1;
            letter-spacing: 0.2px;
            cursor: default;
            user-select: none;
            -webkit-user-select: none;
        }

        .sub {
            margin-top: 2px;
            color: var(--muted);
            font-size: 11px;
            cursor: default;
            user-select: none;
            -webkit-user-select: none;
        }

        .sub-meta {
            margin-top: 4px;
            color: var(--muted);
            font-size: 11px;
            line-height: 1.35;
            cursor: default;
            user-select: none;
            -webkit-user-select: none;
        }

        .sub-meta-repo {
            white-space: normal;
            word-break: break-all;
        }

        .sub-meta a {
            color: var(--acc);
            text-decoration: none;
            border-bottom: none;
        }

        .sub-meta a:hover {
            color: color-mix(in srgb, var(--acc) 70%, #ffffff 30%);
            border-bottom: none;
        }

        label {
            user-select: none;
            -webkit-user-select: none;
        }

        button {
            user-select: none;
            -webkit-user-select: none;
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

        .select-shell,
        .select-shell * {
            user-select: none;
            -webkit-user-select: none;
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

        .select-trigger:disabled,
        .select-trigger:disabled:hover {
            cursor: not-allowed;
            opacity: 0.58;
            transform: none;
            border-color: var(--line);
            box-shadow: inset 0 1px 0 #ffffff10;
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


        .compat-summary {
            font-size: 11px;
            color: var(--muted);
            line-height: 1.4;
            padding: 0 10px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .top-pane {
            padding: 10px;
        }

        .table-pane {
            min-height: 0;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 8px 0 0;
        }

        .footer-pane {
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
            padding: 0;
            overflow: hidden;
        }

        .actions-bar {
            margin-top: -2px;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .status-strip {
            margin-right: auto;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            min-height: 34px;
            padding: 0 10px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: color-mix(in srgb, var(--surface-2) 72%, transparent);
            color: var(--muted);
            font-size: 11px;
            white-space: nowrap;
            max-width: min(560px, 100%);
            overflow: hidden;
            text-overflow: ellipsis;
            cursor: default;
            user-select: none;
            -webkit-user-select: none;
        }

        .status-strip strong {
            color: var(--fg);
            font-weight: 700;
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
            flex-wrap: wrap;
        }

        .mode-row > label:first-child {
            color: var(--muted);
            font-size: 12px;
            white-space: nowrap;
            min-width: max-content;
        }

        .mode-inline {
            display: inline-flex;
            align-items: center;
            gap: 7px;
        }

        .mode-inline > label:first-child {
            color: var(--muted);
            font-size: 12px;
            white-space: nowrap;
            min-width: max-content;
        }

        .game-warning-box {
            width: 100%;
            padding: 6px 10px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: linear-gradient(180deg, var(--panel0), var(--panel1));
            color: #d04040;
            font-size: 16px;
            font-weight: 700;
            line-height: 1.3;
            cursor: default;
            user-select: none;
            -webkit-user-select: none;
            white-space: normal;
        }

        .game-warning-standalone {
            padding: 10px 14px 0;
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
            gap: 8px;
            align-items: center;
        }

        .mode input[type="radio"] {
            position: absolute;
            opacity: 0;
            pointer-events: none;
        }

        .mode-toggle {
            border: 0;
            border-radius: 0;
            background: transparent;
            color: var(--fg);
            min-height: 30px;
            padding: 0;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            cursor: pointer;
            font-size: 12px;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            box-shadow: none;
        }

        .mode-toggle:focus-visible {
            outline: none;
            box-shadow: 0 0 0 4px var(--focus-ring);
            border-radius: 8px;
        }

        .mode-toggle-text {
            color: var(--muted);
            white-space: nowrap;
            transition: color 200ms ease, opacity 200ms ease;
        }

        .mode-toggle-track {
            width: 48px;
            height: 24px;
            border-radius: 999px;
            border: 1px solid var(--line);
            background: color-mix(in srgb, var(--surface-2) 80%, transparent);
            position: relative;
            flex: 0 0 auto;
            transition: background 220ms ease, border-color 220ms ease;
        }

        .mode-toggle-thumb {
            position: absolute;
            top: 2px;
            left: 2px;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: linear-gradient(180deg, #ffffff, color-mix(in srgb, #ffffff 78%, var(--acc) 22%));
            box-shadow: 0 1px 3px #00000055;
            transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1), background 220ms ease;
        }

        .mode[data-mode="single"] .mode-toggle-text-single,
        .mode[data-mode="batch"] .mode-toggle-text-batch {
            color: var(--fg);
        }

        .mode[data-mode="single"] .mode-toggle-text-batch,
        .mode[data-mode="batch"] .mode-toggle-text-single {
            opacity: 0.72;
        }

        .mode[data-mode="batch"] .mode-toggle-thumb {
            transform: translateX(26px);
            background: linear-gradient(180deg, color-mix(in srgb, #ffffff 70%, var(--acc) 30%), var(--acc));
        }

        .mode[data-mode="single"] .mode-toggle-track {
            border-color: color-mix(in srgb, #2f89ff 55%, var(--line) 45%);
            background: linear-gradient(90deg, color-mix(in srgb, #2f89ff 54%, transparent), color-mix(in srgb, #6ec3ff 42%, transparent));
        }

        .mode[data-mode="batch"] .mode-toggle-track {
            border-color: color-mix(in srgb, #ff7a2f 55%, var(--line) 45%);
            background: linear-gradient(90deg, color-mix(in srgb, #ff7a2f 54%, transparent), color-mix(in srgb, #ffb347 44%, transparent));
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
            padding: 0 10px;
            color: var(--muted);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.3px;
            text-transform: uppercase;
        }

        .table-wrap {
            position: relative;
            border-top: 1px solid var(--line);
            border-left: 0;
            border-right: 0;
            border-bottom: 0;
            border-radius: 0 0 10px 10px;
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

        /* BLK row: label | textbox | action group */
        .blk-row {
            grid-template-columns: max-content minmax(0, 1fr) auto;
        }

        .blk-row #blk_input {
            min-width: 0;
        }

        .blk-actions {
            display: flex;
            align-items: center;
            gap: 7px;
            flex-wrap: nowrap;
            justify-content: flex-start;
        }

        .blk-actions .btn {
            flex: 0 0 auto;
        }

        .run {
            background: linear-gradient(180deg, var(--run-bg-0), var(--run-bg-1));
            border-color: var(--run-bg-0);
            color: var(--run-fg);
        }

        .progress-wrap {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 12px 14px;
            background: var(--panel1);
            border: 0;
            min-height: 100%;
        }

        .progress-head {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 10px;
        }

        .progress-head label {
            color: var(--muted);
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.2px;
            line-height: 1;
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
            line-height: 1;
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
        .blk-preview,
        .sync-result-text,
        .save-success-path {
            cursor: default;
            user-select: none;
        }

        .log-box {
            cursor: text;
            user-select: text;
            -webkit-user-select: text;
            -moz-user-select: text;
            white-space: pre-wrap;
            word-wrap: break-word;
        }

        .table-wrap::-webkit-scrollbar,
        .log-box::-webkit-scrollbar,
        .blk-preview::-webkit-scrollbar,
        .sync-result-text::-webkit-scrollbar,
        .save-success-path::-webkit-scrollbar,
        .usage-body::-webkit-scrollbar,
        .settings-content::-webkit-scrollbar,
        .video-export-list::-webkit-scrollbar {
            width: 12px;
            height: 12px;
            cursor: default;
        }

        .table-wrap::-webkit-scrollbar-track,
        .log-box::-webkit-scrollbar-track,
        .blk-preview::-webkit-scrollbar-track,
        .sync-result-text::-webkit-scrollbar-track,
        .save-success-path::-webkit-scrollbar-track,
        .usage-body::-webkit-scrollbar-track,
        .settings-content::-webkit-scrollbar-track,
        .video-export-list::-webkit-scrollbar-track {
            background: var(--scroll-track);
            border-radius: 999px;
            cursor: default;
        }

        .table-wrap::-webkit-scrollbar-thumb,
        .log-box::-webkit-scrollbar-thumb,
        .blk-preview::-webkit-scrollbar-thumb,
        .sync-result-text::-webkit-scrollbar-thumb,
        .save-success-path::-webkit-scrollbar-thumb,
        .usage-body::-webkit-scrollbar-thumb,
        .settings-content::-webkit-scrollbar-thumb,
        .video-export-list::-webkit-scrollbar-thumb {
            background: var(--scroll-thumb);
            border-radius: 999px;
            border: 2px solid var(--scroll-track);
            cursor: default;
        }

        .table-wrap::-webkit-scrollbar-button,
        .log-box::-webkit-scrollbar-button,
        .blk-preview::-webkit-scrollbar-button,
        .sync-result-text::-webkit-scrollbar-button,
        .save-success-path::-webkit-scrollbar-button,
        .usage-body::-webkit-scrollbar-button,
        .settings-content::-webkit-scrollbar-button,
        .video-export-list::-webkit-scrollbar-button {
            width: 0;
            height: 0;
            display: none;
        }

        .table-wrap,
        .log-box,
        .blk-preview,
        .sync-result-text,
        .save-success-path,
        .usage-body,
        .settings-content,
        .video-export-list {
            scrollbar-color: var(--scroll-thumb) var(--scroll-track);
            scrollbar-width: thin;
        }

        .hover-tooltip {
            position: fixed;
            left: 0;
            top: 0;
            transform: translate3d(-9999px, -9999px, 0);
            background: var(--panel0);
            color: var(--fg);
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 11px;
            line-height: 1.25;
            white-space: nowrap;
            word-break: normal;
            pointer-events: none;
            opacity: 0;
            visibility: hidden;
            z-index: 160;
            box-shadow: 0 4px 12px #00000044;
            transition: opacity 120ms ease;
            user-select: none;
            -webkit-user-select: none;
        }

        .hover-tooltip.show {
            opacity: 1;
            visibility: visible;
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
            width: min(1040px, 96vw);
            height: min(760px, 92vh);
        }

        #video_export_modal .modal-head {
            justify-content: center;
        }

        #video_export_modal .modal-head > span {
            width: 100%;
            text-align: center;
        }

        .video-export-body {
            flex: 1;
            min-height: 0;
            display: grid;
            grid-template-rows: auto minmax(0, 1fr) auto;
            gap: 12px;
            padding: 12px 14px;
        }

        .video-export-sections {
            min-width: 0;
        }

        .video-export-section {
            border: 1px solid var(--line);
            border-radius: 12px;
            background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, #ffffff 6%), color-mix(in srgb, var(--surface) 97%, #000000 3%));
            padding: 12px;
            display: grid;
            gap: 10px;
            min-width: 0;
        }

        .video-export-config,
        .video-export-subtitle-row {
            display: flex;
            gap: 10px 12px;
            align-items: stretch;
            flex-wrap: nowrap;
            min-width: 0;
        }

        .video-export-inline-group {
            display: grid;
            align-items: center;
            gap: 7px;
            min-width: 0;
        }

        .video-export-inline-group label {
            white-space: nowrap;
            color: var(--muted);
            font-size: 12px;
            font-weight: 500;
        }

        .video-export-format-group {
            flex: 0 1 200px;
            grid-template-columns: max-content minmax(86px, 1fr);
        }

        .video-export-output-group {
            flex: 1 1 340px;
            grid-template-columns: max-content minmax(180px, 1fr) auto;
        }

        .video-export-audio-group {
            flex: 1 1 260px;
            grid-template-columns: max-content minmax(170px, 1fr);
        }

        .video-export-subtitle-source-group {
            flex: 0 1 200px;
            grid-template-columns: max-content minmax(100px, 1fr);
        }

        .video-export-subtitle-lang-group,
        .video-export-mode-group {
            flex: 1 1 240px;
            grid-template-columns: max-content minmax(140px, 1fr);
        }

        .video-export-subtitle-local-group {
            flex: 1 1 300px;
            grid-template-columns: max-content minmax(0, 1fr);
        }

        .video-export-hybrid-group {
            flex: 0 1 220px;
            grid-template-columns: max-content minmax(84px, 1fr);
        }

        .video-export-hw-group {
            flex: 1 1 300px;
            grid-template-columns: max-content auto;
        }

        .video-export-hw-header {
            display: inline-flex;
            align-items: center;
            justify-content: flex-start;
            gap: 6px;
            width: auto;
        }

        .video-export-hw-header label[for="video_export_hw_toggle"] {
            flex-shrink: 0;
        }

        .video-export-hw-info {
            grid-column: 1 / -1;
            font-size: 10px;
            color: var(--muted);
            line-height: 1.3;
            white-space: normal;
            overflow: hidden;
            text-overflow: ellipsis;
            padding: 2px 0;
            word-break: break-word;
        }

        #video_export_hw_toggle_shell.toggle-switch {
            width: 36px;
            height: 18px;
            border-radius: 9px;
        }

        #video_export_hw_toggle_shell.toggle-switch .toggle-slider {
            border-radius: 9px;
        }

        #video_export_hw_toggle_shell.toggle-switch .toggle-slider:before {
            height: 14px;
            width: 14px;
            left: 2px;
            bottom: 2px;
        }

        #video_export_hw_toggle_shell.toggle-switch input:checked + .toggle-slider:before {
            transform: translateX(18px);
        }

        .video-export-config input[type="text"],
        .video-export-config select,
        .video-export-subtitle-row input[type="text"],
        .video-export-subtitle-row select {
            min-width: 0;
        }

        .video-export-config input[type="text"],
        .video-export-select,
        #video_export_hybrid_limit {
            height: 34px;
            box-sizing: border-box;
            min-width: 0;
        }

        #video_export_output_pick_btn {
            min-height: 34px;
            padding: 6px 14px;
            white-space: nowrap;
        }

        .video-export-config .video-export-format-select {
            width: 100%;
        }

        .video-export-audio-shell {
            min-width: 0;
        }

        .video-export-audio-shell .select-trigger {
            min-height: 34px;
            border-radius: 10px;
        }

        .multi-select-menu {
            min-width: 260px;
            max-width: min(560px, calc(100vw - 72px));
        }

        .video-export-audio-shell .multi-select-menu,
        #video_export_subtitle_lang_shell .multi-select-menu {
            left: auto;
            right: 0;
            width: max(100%, 260px);
            max-width: min(520px, calc(100vw - 24px));
        }

        .multi-select-actions {
            display: flex;
            gap: 8px;
            padding: 2px 2px 8px;
        }

        .multi-select-action {
            flex: 1;
            border: 1px solid var(--input-border);
            border-radius: 8px;
            background: var(--input-bg);
            color: var(--fg);
            padding: 6px 8px;
            font-size: 11px;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            cursor: pointer;
        }

        .multi-select-action:hover,
        .multi-select-action:focus-visible {
            outline: none;
            border-color: var(--acc);
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        .multi-select-options {
            display: grid;
            gap: 6px;
        }

        .multi-select-options.two-col {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 6px 8px;
        }

        .multi-select-option {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 8px;
            border: 1px solid transparent;
            border-radius: 8px;
            background: transparent;
            color: var(--fg);
            cursor: pointer;
            font-size: 12px;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
            min-width: 0;
        }

        .multi-select-option:hover {
            background: transparent;
            border-color: transparent;
        }

        .multi-select-option input[type="checkbox"] {
            appearance: auto;
            -webkit-appearance: auto;
            width: 16px;
            height: 16px;
            margin: 0;
            accent-color: var(--acc);
            flex: 0 0 auto;
        }

        .multi-select-option input[type="checkbox"]:focus-visible {
            outline: none;
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        .multi-select-option span {
            min-width: 0;
            overflow: hidden;
            white-space: nowrap;
            text-overflow: ellipsis;
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

        .video-export-select:focus,
        #video_export_hybrid_limit:focus,
        #video_export_output:focus {
            border-color: var(--acc);
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        #video_export_hybrid_limit {
            min-width: 0;
            border-radius: 8px;
            border: 1px solid var(--input-border);
            background: var(--input-bg);
            color: var(--fg);
            padding: 7px 9px;
            font-size: 12px;
            outline: none;
            font-family: "UsmDivinerZh", "Segoe UI", "Noto Sans", "Microsoft YaHei", "PingFang TC", sans-serif;
        }

        .video-export-subtitle-row {
            padding-top: 8px;
            margin-top: 8px;
            border-top: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
        }

        .video-export-strategy-row {
            display: none;
        }

        .video-export-subtitle-row .actions {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            align-items: center;
            gap: 8px;
            min-width: 0;
        }

        #video_export_subtitle_pick_btn {
            min-height: 34px;
            padding: 6px 14px;
            white-space: nowrap;
        }

        .video-export-subtitle-row .sub-local-info {
            min-width: 0;
            font-size: 11px;
            color: var(--muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            padding: 0 6px;
            line-height: 32px;
            border: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
            border-radius: 8px;
            background: color-mix(in srgb, var(--input-bg) 90%, transparent);
        }

        .video-export-list {
            border: 1px solid var(--line);
            border-radius: 12px;
            background: var(--surface);
            min-height: 0;
            flex: 1;
            overflow: auto;
            min-width: 0;
        }

        .video-export-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
        }

        .video-export-table th,
        .video-export-table td {
            border-bottom: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
            padding: 8px 10px;
            text-align: center;
            vertical-align: middle;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            font-size: 12px;
            cursor: default;
            user-select: none;
            -webkit-user-select: none;
        }

        .video-export-table th {
            position: sticky;
            top: 0;
            background: var(--surface-2);
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.2px;
            z-index: 1;
        }

        .video-export-table th:nth-child(1),
        .video-export-table td:nth-child(1) {
            width: 36%;
        }

        .video-export-table th:nth-child(2),
        .video-export-table td:nth-child(2) {
            width: 14%;
            text-align: center;
        }

        .video-export-table th:nth-child(3),
        .video-export-table td:nth-child(3) {
            width: 31%;
            text-align: center;
        }

        .video-export-table th:nth-child(4),
        .video-export-table td:nth-child(4) {
            width: 19%;
        }

        .video-export-table tbody tr:hover {
            background: color-mix(in srgb, var(--surface-2) 78%, transparent);
        }

        .video-export-audio-cell {
            color: var(--muted);
        }

        .video-export-audio-cell.has-audio {
            color: var(--fg);
        }

        .video-export-audio-cell .audio-track-list {
            display: block;
            overflow: hidden;
            white-space: nowrap;
            text-overflow: ellipsis;
            text-align: center;
        }

        .video-export-progress {
            width: min(102px, 100%);
            margin: 0 auto;
        }

        .video-export-progress .mini-label {
            text-align: right;
        }

        #video_export_modal .progress-wrap {
            margin-top: 0;
            border: 1px solid var(--line);
            border-radius: 12px;
            background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 92%, #ffffff 8%), color-mix(in srgb, var(--surface) 95%, #000000 5%));
            padding: 10px 12px;
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
            justify-content: center;
            gap: 8px;
            padding: 12px 14px;
            border-bottom: 1px solid var(--line);
            color: var(--fg);
            font-weight: 700;
            text-align: center;
        }

        .modal-head > span {
            width: 100%;
            text-align: center;
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

        @keyframes video-export-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }

        .video-export-online-check-body {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 12px;
            padding: 12px 0;
        }

        .video-export-online-check-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--line);
            border-top-color: var(--acc);
            border-radius: 50%;
            animation: video-export-spin 760ms linear infinite;
        }

        .video-export-online-check-progress {
            color: var(--muted);
            font-size: 11px;
            text-align: center;
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

        #exit_confirm_modal_message {
            text-align: center;
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

        #input_selection_modal .modal-card {
            width: min(840px, 94vw);
            height: min(430px, 56vh);
        }

        #input_selection_modal .save-success-body {
            flex: 1;
            min-height: 0;
        }

        #input_selection_list {
            flex: 1;
            min-height: 240px;
        }

        .usage-card {
            width: min(980px, 95vw);
            height: min(680px, 88vh);
        }

        .usage-body {
            flex: 1;
            min-height: 0;
            margin: 12px 14px;
            border: 1px solid var(--line);
            border-radius: 10px;
            background: var(--surface);
            color: var(--fg);
            padding: 12px;
            overflow: auto;
            white-space: pre-wrap;
            font-size: 12px;
            line-height: 1.6;
        }

        .usage-body a {
            color: var(--acc);
            text-decoration: underline;
            cursor: pointer;
            word-break: break-all;
        }

        .usage-body a:hover {
            filter: brightness(1.08);
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

        #versions_patch_modal .modal-head {
            justify-content: center;
            flex-direction: column;
            align-items: center;
            gap: 2px;
        }

        #versions_patch_modal .modal-head > span {
            width: 100%;
            text-align: center;
        }

        #versions_patch_summary {
            margin-top: 8px;
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
            word-break: normal;
            pointer-events: none;
            opacity: 1;
            visibility: visible;
            z-index: 100;
            box-shadow: 0 4px 12px #00000044;
            animation: tooltipFadeIn 150ms ease;
            user-select: none;
            -webkit-user-select: none;
        }

        #input.clickable {
            cursor: default;
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

        #blk_parse_toggle_shell .toggle-slider {
            border-color: color-mix(in srgb, #2f89ff 55%, var(--line) 45%);
            background: linear-gradient(90deg, color-mix(in srgb, #2f89ff 54%, transparent), color-mix(in srgb, #6ec3ff 42%, transparent));
        }

        #blk_parse_toggle_shell input:checked + .toggle-slider {
            border-color: color-mix(in srgb, #c77dff 55%, var(--line) 45%);
            background: linear-gradient(90deg, color-mix(in srgb, #c77dff 54%, transparent), color-mix(in srgb, #e0aaff 42%, transparent));
        }

        #versions_patch_toggle_shell .toggle-slider {
            border-color: color-mix(in srgb, #2f89ff 55%, var(--line) 45%);
            background: linear-gradient(90deg, color-mix(in srgb, #2f89ff 54%, transparent), color-mix(in srgb, #6ec3ff 42%, transparent));
        }

        #versions_patch_toggle_shell input:checked + .toggle-slider {
            border-color: color-mix(in srgb, #ff7a2f 55%, var(--line) 45%);
            background: linear-gradient(90deg, color-mix(in srgb, #ff7a2f 54%, transparent), color-mix(in srgb, #ffb347 44%, transparent));
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

        #log_modal .modal-head {
            justify-content: center;
            text-align: center;
        }

        /* FFMPEG Log Modal CSS */
        .ffmpeg-log-card {
            width: min(800px, 92vw);
            max-height: min(600px, 88vh);
            display: flex;
            flex-direction: column;
        }

        .ffmpeg-log-card .modal-head {
            justify-content: center;
            text-align: center;
        }

        .ffmpeg-log-card #ffmpeg_log_box {
            flex: 1;
            overflow-y: auto;
            min-height: 200px;
        }

        .ffmpeg-log-card .modal-actions {
            margin-top: 10px;
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
            .window-titlebar {
                padding: 0 6px 0 8px;
            }

            .window-btn {
                width: 32px;
            }

            .head-top { flex-direction: column; }
            .toolbar-controls { width: 100%; }
            .control { flex: 1; min-width: 0; }
            .grid { grid-template-rows: auto auto auto auto; overflow: auto; }
            .form-cols { grid-template-columns: 1fr; }
            .row { grid-template-columns: 1fr; }
            .blk-row { grid-template-columns: 1fr; }
            .opts { grid-template-columns: 1fr; }
            .video-export-config,
            .video-export-subtitle-row { flex-direction: column; }
            .video-export-inline-group { width: 100%; }
            .video-export-strategy-row { grid-template-columns: 1fr; }
            .video-export-section { padding: 9px 10px; }
            #video_export_modal .progress-wrap { padding: 9px 10px; }
            .video-export-format-group,
            .video-export-output-group,
            .video-export-audio-group,
            .video-export-subtitle-source-group,
            .video-export-subtitle-lang-group,
            .video-export-mode-group,
            .video-export-subtitle-local-group,
            .video-export-hybrid-group { grid-template-columns: 1fr; }
            .video-export-subtitle-row .actions {
                grid-template-columns: 1fr;
            }
            .multi-select-options.two-col { grid-template-columns: 1fr; }
            .actions { justify-content: flex-end; flex-wrap: wrap; }
            .actions .btn { width: auto; }

        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="panel">
            <div class="window-titlebar" id="window_titlebar" onmousedown="beginWindowDrag(event)">
                <div class="window-title-left">
                    <img class="app-icon" id="window_icon" src="assets/icon/wolf_favicon.png" alt="App icon" onerror="this.style.display='none'" />
                    <span class="window-title-text" id="window_title_text">UsmDiviner GUI</span>
                </div>
                <div class="window-title-actions">
                    <button type="button" class="window-btn" id="window_min_btn" onclick="windowMinimize()" aria-label="Minimize">-</button>
                    <button type="button" class="window-btn window-btn-close" id="window_close_btn" onclick="windowClose()" aria-label="Close">x</button>
                </div>
            </div>
            <div class="head">
                <div class="head-top">
                    <div class="brand">
                        <img class="app-icon" id="title_icon" src="assets/icon/wolf_favicon.png" alt="App icon" onerror="this.style.display='none'" />
                        <div class="brand-text">
                            <h1 class="title" id="title_text">UsmDiviner GUI</h1>
                            <div class="sub" id="subtitle_text">USM key recovery and extraction with MHY multi-game support</div>
                            <div class="sub-meta" id="project_author_text">Author: Chinese @独行者 | English @LoneOne-HRB</div>
                            <div class="sub-meta sub-meta-repo" id="project_repo_text">Project repo: https://github.com/HRB-YuPai/UsmDiviner-GUI</div>
                        </div>
                    </div>
                    <div class="toolbar-controls">
                        <div class="control">
                            <label for="game_select" id="game_label_text">Game</label>
                            <select id="game_select" onchange="setGame(this.value)">
                                <option id="game_opt_genshin_impact" value="genshin_impact" selected>Genshin Impact</option>
                                <option id="game_opt_honkai_star_rail" value="honkai_star_rail">Honkai: Star Rail</option>
                                <option id="game_opt_zenless_zone_zero" value="zenless_zone_zero">Zenless Zone Zero</option>
                                <option id="game_opt_honkai_impact_3rd" value="honkai_impact_3rd">Honkai Impact 3rd</option>
                                <option id="game_opt_petit_planet" value="petit_planet">Petit Planet</option>
                            </select>
                        </div>
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
            <div class="game-warning-standalone">
                <div class="game-warning-box" id="game_warning_text">Safety warning</div>
            </div>
            <div class="grid">
                <div class="top-pane">
                    <div class="form-block">
                        <div class="mode-row">
                            <label id="analysis_mode_text">Mode</label>
                            <div class="mode" id="mode_switch" data-mode="single">
                                <input type="radio" name="input_mode" id="mode_single" value="single" checked onchange="syncInputMode()" />
                                <input type="radio" name="input_mode" id="mode_batch" value="batch" onchange="syncInputMode()" />
                                <button type="button" id="mode_toggle_btn" class="mode-toggle" onclick="toggleInputMode()" aria-label="Toggle analysis mode">
                                    <span id="single_file_text" class="mode-toggle-text mode-toggle-text-single">File selection</span>
                                    <span class="mode-toggle-track" aria-hidden="true"><span class="mode-toggle-thumb"></span></span>
                                    <span id="batch_folder_text" class="mode-toggle-text mode-toggle-text-batch">Folder selection</span>
                                </button>
                            </div>
                            <div class="mode-inline hidden" id="blk_parse_mode_row">
                                <label id="blk_parse_mode_text" for="blk_parse_toggle">Parse blk</label>
                                <label class="toggle-switch" id="blk_parse_toggle_shell" data-tooltip="原神 26236578.blk 解析">
                                    <input type="checkbox" id="blk_parse_toggle" onchange="syncBlkParseToggle()" />
                                    <span class="toggle-slider"></span>
                                </label>
                            </div>
                            <div class="mode-inline hidden" id="versions_patch_mode_row">
                                <label id="versions_patch_mode_text" for="versions_patch_toggle">versions.json patch</label>
                                <label class="toggle-switch" id="versions_patch_toggle_shell" data-tooltip="Patch versions.json from BLK data">
                                    <input type="checkbox" id="versions_patch_toggle" onchange="syncVersionsPatchToggle()" />
                                    <span class="toggle-slider"></span>
                                </label>
                            </div>
                        </div>
                        <div class="form-cols">
                            <div class="form-col">
                                <div class="row" id="input_row">
                                    <label id="input_label" for="input">Input</label>
                                    <input id="input" type="text" placeholder="" readonly onclick="openInputSelectionModal()" onkeydown="handleInputSelectionKeydown(event)" />
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
                                <div class="row blk-row hidden" id="blk_row">
                                    <label id="blk_label" for="blk_input">Load BLK</label>
                                    <input id="blk_input" type="text" readonly placeholder="" />
                                    <div class="blk-actions" id="blk_actions_group">
                                        <button class="btn" id="blk_pick_btn" data-tooltip="Select BLK file" onclick="pickBlkInput()">Load</button>
                                        <button class="btn hidden" id="pick_versions_patch_base_btn" onclick="pickVersionsPatchBase()">Base JSON</button>
                                        <button class="btn hidden" id="open_versions_btn" onclick="openBlkVersionsModal()">View</button>
                                        <button class="btn hidden" id="open_versions_patch_btn" onclick="openVersionsPatchModal()">Patch</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="table-pane">
                    <div class="section-title" id="file_list_title">USM file list</div>
                    <div class="compat-summary" id="file_compat_summary"></div>
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
                    <div id="status_strip" class="status-strip"></div>
                    <button class="btn" id="open_settings_btn" data-tooltip="Settings" onclick="openSettingsModal()">Settings</button>
                    <button class="btn" id="open_log_btn" data-tooltip="View output logs" onclick="openLogModal()">Logs</button>
                    <button class="btn" id="open_usage_btn" data-tooltip="Open usage guide" onclick="openUsageModal()">Usage</button>
                    <button class="btn" id="open_credits_btn" data-tooltip="Open source acknowledgements" onclick="openCreditsModal()">Credits</button>
                    <button class="btn hidden" id="open_video_export_btn" data-tooltip="Export videos from extracted IVF/WAV" onclick="openVideoExportModal()">Export Video</button>
                    <button class="btn hidden" id="export_all_reports_btn" data-tooltip="Export all reports" onclick="exportAllReports()">Export All Reports</button>
                    <button class="btn hidden" id="export_index_btn" data-tooltip="Export processed index JSON" onclick="exportIndexJson()">Export Index</button>
                    <button class="btn" id="export_game_keys_btn" data-tooltip="Export merged key JSON for selected game" onclick="exportGameKeys()">Export Game Keys</button>
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
                <button class="btn" id="copy_log_btn" onclick="copyLogSelectionOrAll()" disabled>Copy</button>
                <button class="btn" id="export_log_btn" onclick="exportLog()" disabled>Export</button>
                <button class="btn" id="clear_log_btn" onclick="clearLog()" disabled>Clear log</button>
                <button class="btn" id="close_log_btn" onclick="closeLogModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="usage_modal" class="modal hidden">
        <div class="modal-card usage-card">
            <div class="modal-head">
                <span id="usage_title">Usage Guide</span>
            </div>
            <div id="usage_content" class="usage-body"></div>
            <div class="modal-actions">
                <button class="btn" id="usage_close_btn" onclick="closeUsageModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="credits_modal" class="modal hidden">
        <div class="modal-card usage-card">
            <div class="modal-head">
                <span id="credits_title">Open Source Acknowledgements</span>
            </div>
            <div id="credits_content" class="usage-body"></div>
            <div class="modal-actions">
                <button class="btn" id="credits_close_btn" onclick="closeCreditsModal()">Close</button>
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

    <div id="versions_patch_modal" class="modal hidden">
        <div class="modal-card blk-modal-card">
            <div class="modal-head">
                <span id="versions_patch_title">versions.json patch</span>
                <div class="blk-head-line" id="versions_patch_summary">No patch preview available.</div>
                <div class="blk-head-line" id="versions_patch_source">Source BLK: —</div>
                <div class="blk-head-line" id="versions_patch_base_line"></div>
                <div class="blk-head-line" id="versions_patch_warning"></div>
            </div>
            <div class="blk-modal-body">
                <textarea id="versions_patch_box" class="blk-preview" spellcheck="false" readonly></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" id="versions_patch_copy_btn" onclick="copyVersionsPatch()">Copy</button>
                <button class="btn" id="versions_patch_save_btn" onclick="saveVersionsPatch()">Save</button>
                <button class="btn" id="versions_patch_close_btn" onclick="closeVersionsPatchModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="video_export_modal" class="modal hidden">
        <div class="modal-card video-export-card">
            <div class="modal-head">
                <span id="video_export_title">Export Video</span>
            </div>
            <div class="video-export-body">
                <div class="video-export-sections">
                    <div class="video-export-section">
                        <div class="video-export-config">
                            <div class="video-export-inline-group video-export-format-group">
                                <label id="video_export_format_label" for="video_export_format">Format</label>
                                <select id="video_export_format" class="video-export-select video-export-format-select">
                                    <option value="mp4">MP4</option>
                                    <option value="mkv">MKV</option>
                                </select>
                            </div>

                            <div class="video-export-inline-group video-export-output-group">
                                <label id="video_export_output_label" for="video_export_output">Output</label>
                                <input id="video_export_output" type="text" placeholder="" readonly aria-readonly="true" />
                                <button class="btn" id="video_export_output_pick_btn" onclick="pickVideoExportOutput()">Browse</button>
                            </div>

                            <div class="video-export-inline-group video-export-audio-group">
                                <label id="video_export_audio_label" for="video_export_audio_trigger">Audio</label>
                                <div id="video_export_audio_shell" class="select-shell video-export-shell video-export-audio-shell">
                                    <button type="button" id="video_export_audio_trigger" class="select-trigger" aria-haspopup="listbox" aria-expanded="false">
                                        <span id="video_export_audio_summary" class="select-trigger-label">All audio tracks</span>
                                        <span class="select-trigger-icon"></span>
                                    </button>
                                    <div id="video_export_audio_menu" class="select-menu multi-select-menu" role="listbox" aria-multiselectable="true">
                                        <div class="multi-select-actions">
                                            <button type="button" class="multi-select-action" id="video_export_audio_all_btn">All</button>
                                            <button type="button" class="multi-select-action" id="video_export_audio_none_btn">None</button>
                                        </div>
                                        <div class="multi-select-options two-col">
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_audio_ch0" checked /><span id="video_export_audio_ch0_label">Chinese</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_audio_ch1" checked /><span id="video_export_audio_ch1_label">English</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_audio_ch2" checked /><span id="video_export_audio_ch2_label">Japanese</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_audio_ch3" checked /><span id="video_export_audio_ch3_label">Korean</span></label>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="video-export-subtitle-row">
                            <div class="video-export-inline-group video-export-subtitle-source-group">
                                <label id="video_export_subtitle_source_label" for="video_export_subtitle_source">Subtitles</label>
                                <select id="video_export_subtitle_source" class="video-export-select video-export-subtitle-source-select" onchange="updateVideoExportSubtitleSourceUi()">
                                    <option value="off">Off</option>
                                    <option value="local">Local Files</option>
                                    <option value="online">Online</option>
                                </select>
                            </div>

                            <div class="video-export-inline-group video-export-subtitle-lang-group">
                                <label id="video_export_subtitle_lang_label" for="video_export_subtitle_lang_trigger">Languages</label>
                                <div id="video_export_subtitle_lang_shell" class="select-shell video-export-shell video-export-audio-shell">
                                    <button type="button" id="video_export_subtitle_lang_trigger" class="select-trigger" aria-haspopup="listbox" aria-expanded="false">
                                        <span id="video_export_subtitle_lang_summary" class="select-trigger-label">All languages</span>
                                        <span class="select-trigger-icon"></span>
                                    </button>
                                    <div id="video_export_subtitle_lang_menu" class="select-menu multi-select-menu" role="listbox" aria-multiselectable="true">
                                        <div class="multi-select-actions">
                                            <button type="button" class="multi-select-action" id="video_export_subtitle_lang_all_btn">All</button>
                                            <button type="button" class="multi-select-action" id="video_export_subtitle_lang_none_btn">None</button>
                                        </div>
                                        <div class="multi-select-options two-col">
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_CHS" checked /><span id="video_export_subtitle_lang_CHS_label">Simplified Chinese</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_CHT" checked /><span id="video_export_subtitle_lang_CHT_label">Traditional Chinese</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_DE" checked /><span id="video_export_subtitle_lang_DE_label">German</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_EN" checked /><span id="video_export_subtitle_lang_EN_label">English</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_ES" checked /><span id="video_export_subtitle_lang_ES_label">Spanish</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_FR" checked /><span id="video_export_subtitle_lang_FR_label">French</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_ID" checked /><span id="video_export_subtitle_lang_ID_label">Indonesian</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_IT" checked /><span id="video_export_subtitle_lang_IT_label">Italian</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_JP" checked /><span id="video_export_subtitle_lang_JP_label">Japanese</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_KR" checked /><span id="video_export_subtitle_lang_KR_label">Korean</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_PT" checked /><span id="video_export_subtitle_lang_PT_label">Portuguese</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_RU" checked /><span id="video_export_subtitle_lang_RU_label">Russian</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_TH" checked /><span id="video_export_subtitle_lang_TH_label">Thai</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_TR" checked /><span id="video_export_subtitle_lang_TR_label">Turkish</span></label>
                                            <label class="multi-select-option"><input type="checkbox" id="video_export_subtitle_lang_VI" checked /><span id="video_export_subtitle_lang_VI_label">Vietnamese</span></label>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div class="video-export-inline-group video-export-mode-group">
                                <label id="video_export_mode_label" for="video_export_mode">Export Strategy</label>
                                <select id="video_export_mode" class="video-export-select" onchange="updateVideoExportModeUi()">
                                    <option value="container">Container (multi audio + multi subtitles)</option>
                                    <option value="burn">Hard Subtitle (multiple files)</option>
                                    <option value="hybrid">Hybrid (container + hard subtitle)</option>
                                </select>
                            </div>

                            <div id="video_export_subtitle_local_group" class="video-export-inline-group video-export-subtitle-local-group">
                                <label id="video_export_subtitle_local_label" for="video_export_subtitle_pick_btn">Local</label>
                                <div id="video_export_subtitle_local_actions" class="actions" style="justify-content:flex-start;gap:8px;min-width:0;">
                                    <button class="btn" id="video_export_subtitle_pick_btn" onclick="pickVideoExportSubtitles()">Pick</button>
                                    <span id="video_export_subtitle_local_info" class="sub-local-info">No subtitle file selected</span>
                                </div>
                            </div>

                            <div id="video_export_hybrid_group" class="video-export-inline-group video-export-hybrid-group">
                                <label id="video_export_hybrid_limit_label" for="video_export_hybrid_limit">Hybrid hard-sub count</label>
                                <input id="video_export_hybrid_limit" type="number" min="1" max="8" step="1" value="2" />
                            </div>

                            <div id="video_export_hw_group" class="video-export-inline-group video-export-hw-group hidden">
                                <div class="video-export-hw-header">
                                    <label id="video_export_hw_label" for="video_export_hw_toggle">Hardware</label>
                                    <label class="toggle-switch" id="video_export_hw_toggle_shell">
                                        <input id="video_export_hw_toggle" type="checkbox" checked />
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <span id="video_export_hw_info" class="video-export-hw-info"></span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="video-export-list">
                    <table class="video-export-table">
                        <thead>
                            <tr>
                                <th id="video_export_th_name">Name</th>
                                <th id="video_export_th_status">Status</th>
                                <th id="video_export_th_audio">Audio</th>
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
                <button class="btn" id="video_export_ffmpeg_log_btn" onclick="openFfmpegLogModal()"></button>
                <button class="btn" id="video_export_start_btn" onclick="startVideoExport()">Start Export</button>
                <button class="btn" id="video_export_close_btn" onclick="closeVideoExportModal()">Close</button>
            </div>
        </div>
    </div>

    <!-- FFMPEG 日志模态框 -->
    <div id="ffmpeg_log_modal" class="modal hidden">
        <div class="modal-card ffmpeg-log-card">
            <div class="modal-head">
                <span id="ffmpeg_log_window_title">FFMPEG Log</span>
            </div>
            <div id="ffmpeg_log_box" class="log-box"></div>
            <div class="modal-actions">
                <button class="btn" id="ffmpeg_copy_log_btn" onclick="copyFfmpegLogSelectionOrAll()" disabled>Copy</button>
                <button class="btn" id="ffmpeg_export_log_btn" onclick="exportFfmpegLog()" disabled>Export</button>
                <button class="btn" id="ffmpeg_clear_log_btn" onclick="clearFfmpegLog()" disabled>Clear log</button>
                <button class="btn" id="ffmpeg_close_log_btn" onclick="closeFfmpegLogModal()">Close</button>
            </div>
        </div>
    </div>

    <div id="copy_toast" class="copy-toast"></div>
    <div id="hover_tooltip" class="hover-tooltip" aria-hidden="true"></div>

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

    <div id="video_export_subtitle_convert_modal" class="modal hidden">
        <div class="modal-card confirm-save-card">
            <div class="modal-head">
                <span id="video_export_subtitle_convert_title">Convert subtitles to ASS?</span>
            </div>
            <div class="confirm-save-body">
                <div id="video_export_subtitle_convert_message" class="confirm-save-message"></div>
            </div>
            <div class="modal-actions">
                <button class="btn" id="video_export_subtitle_convert_yes_btn" onclick="confirmVideoExportSubtitleConversion('ass')">Convert to ASS</button>
                <button class="btn" id="video_export_subtitle_convert_no_btn" onclick="confirmVideoExportSubtitleConversion('original')">Use Original</button>
                <button class="btn" id="video_export_subtitle_convert_cancel_btn" onclick="closeVideoExportSubtitleConvertModal()">Cancel</button>
            </div>
        </div>
    </div>

    <div id="video_export_subtitle_missing_confirm_modal" class="modal hidden">
        <div class="modal-card confirm-save-card">
            <div class="modal-head">
                <span id="video_export_subtitle_missing_confirm_title">Online Subtitles Not Found</span>
            </div>
            <div class="confirm-save-body">
                <div id="video_export_subtitle_missing_confirm_message" class="confirm-save-message" style="max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;"></div>
            </div>
            <div class="modal-actions">
                <button class="btn" id="video_export_subtitle_missing_confirm_yes_btn" onclick="confirmVideoExportSubtitleMissing()">Continue Export</button>
                <button class="btn" id="video_export_subtitle_missing_confirm_no_btn" onclick="cancelVideoExportSubtitleMissing()">Cancel</button>
            </div>
        </div>
    </div>

    <div id="input_selection_modal" class="modal hidden">
        <div class="modal-card save-success-card">
            <div class="modal-head">
                <span id="input_selection_modal_title">Selected USM Files</span>
            </div>
            <div class="save-success-body">
                <textarea id="input_selection_list" class="save-success-path" readonly></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" id="input_selection_close_btn" onclick="closeInputSelectionModal()">Close</button>
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

    <div id="exit_confirm_modal" class="modal hidden">
        <div class="modal-card confirm-save-card">
            <div class="modal-head">
                <span id="exit_confirm_modal_title">Confirm Exit</span>
            </div>
            <div class="confirm-save-body">
                <div id="exit_confirm_modal_message" class="confirm-save-message"></div>
            </div>
            <div class="modal-actions">
                <button class="btn" id="exit_confirm_modal_yes_btn" onclick="confirmExitFromModal()">Yes</button>
                <button class="btn" id="exit_confirm_modal_no_btn" onclick="closeExitConfirmModal()">No</button>
            </div>
        </div>
    </div>

    <div id="cleanup_progress_modal" class="modal hidden">
        <div class="modal-card save-success-card" style="max-width: 480px;">
            <div class="modal-head">
                <span id="cleanup_progress_modal_title">Cleaning generated files...</span>
            </div>
            <div class="save-success-body" style="gap: 8px; padding: 14px 16px;">
                <div style="display: flex; flex-direction: column; gap: 3px; font-size: 12px;">
                    <div id="cleanup_progress_status" style="color: var(--muted); font-weight: 500;"></div>
                    <div id="cleanup_progress_file" style="color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 11px; opacity: 0.85;"></div>
                    <div id="cleanup_progress_stats" style="color: var(--muted); font-size: 10px; margin-top: 2px;"></div>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div class="progress-track" style="flex: 1; height: 8px; margin: 0; border-radius: 2px; background: var(--bg2);"><div id="cleanup_progress_fill" class="progress-fill" style="width: 0%; height: 100%; background: linear-gradient(90deg, #3edc81, #69d89f); transition: width 150ms cubic-bezier(0.4, 0.2, 0.2, 1); border-radius: 2px;"></div></div>
                    <div id="cleanup_progress_percentage" style="color: var(--muted); font-size: 12px; font-weight: 500; min-width: 40px; text-align: right;">0%</div>
                </div>
            </div>
        </div>
    </div>

    <div id="video_export_online_check_modal" class="modal hidden">
        <div class="modal-card save-success-card" style="max-width: 440px;">
            <div class="modal-head">
                <span id="video_export_online_check_title">Checking Online Subtitles</span>
            </div>
            <div class="save-success-body">
                <div class="video-export-online-check-body">
                    <div class="video-export-online-check-spinner" aria-hidden="true"></div>
                    <div id="video_export_online_check_message" class="save-success-message">...</div>
                    <div id="video_export_online_check_progress" class="video-export-online-check-progress">Checking... (0/0)</div>
                </div>
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
        let blkParseEnabled = false;
        let versionsPatchEnabled = false;
        let versionsPatchBasePath = "";
        let versionsPatchPreviewText = "";
        let versionsPatchPreviewMeta = null;
        let blkSaveSuccessPath = "";
        let blkSaveCanReveal = false;
        let videoExportCandidates = [];
        let videoExportRows = new Map();
        let videoExportRunning = false;
        let videoExportLocalSubtitleFiles = [];
        let videoExportProgressModel = new Map();
        let videoExportPumpTimer = null;
        let videoExportOverallCurrent = 0;
        let videoExportOverallTarget = 0;
        let videoExportOverallLastTick = 0;
        let pendingVideoExportPayload = null;
        let pendingVideoExportCoveragePayload = null;
        let pendingVideoExportSubtitlePromptInfo = null;
        let videoExportHardwareProfile = null;
        let videoExportHardwareProbePending = false;
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
        let hoverTooltipVisible = false;
        // FFMPEG 日志专用容器
        let ffmpegLogLines = [];
        let lastFfmpegLogLine = null;
        let lastFfmpegLogTs = 0;
        let ffmpegLoggingActive = false;

        function byId(id) { return document.getElementById(id); }

        function t(lang) {
            return I18N[lang] || I18N["en"];
        }

        function hideHoverTooltip() {
            const el = byId("hover_tooltip");
            if (!el) return;
            el.classList.remove("show");
            el.setAttribute("aria-hidden", "true");
            hoverTooltipVisible = false;
        }

        function showHoverTooltip(message, clientX, clientY) {
            const el = byId("hover_tooltip");
            const text = String(message || "").trim();
            if (!el || !text) {
                hideHoverTooltip();
                return;
            }

            el.textContent = text;
            el.classList.add("show");
            el.setAttribute("aria-hidden", "false");
            hoverTooltipVisible = true;

            const offsetX = 12;
            const offsetY = 18;
            const margin = 8;
            const rect = el.getBoundingClientRect();
            let x = Number(clientX || 0) + offsetX;
            let y = Number(clientY || 0) + offsetY;

            if (x + rect.width + margin > window.innerWidth) {
                x = window.innerWidth - rect.width - margin;
            }
            if (y + rect.height + margin > window.innerHeight) {
                y = Number(clientY || 0) - rect.height - 10;
            }
            if (x < margin) x = margin;
            if (y < margin) y = margin;

            el.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`;
        }

        function currentLang() {
            return byId("lang_select").value || "zh-CN";
        }

        function currentGame() {
            return byId("game_select").value || "genshin_impact";
        }

        function isGenshinSelected() {
            return currentGame() === "genshin_impact";
        }

        function currentTheme() {
            return byId("theme_select").value || "dark";
        }

        function formatProgressText(value) {
            const safe = Math.max(0, Math.min(100, Number(value || 0)));
            if (safe >= 100) return "100%";
            if (safe <= 0) return "0%";
            return `${safe.toFixed(1)}%`;
        }

        function updateStatusStrip() {
            const el = byId("status_strip");
            if (!el) return;
            const dict = t(currentLang());
            const runText = isTaskRunning ? (dict.running || "Running") : (dict.status_idle || "Idle");
            const themeText = currentTheme() === "light" ? (dict.theme_light || "Light") : (dict.theme_dark || "Dark");
            el.innerHTML = (dict.status_strip_template || "Status: <strong>{state}</strong> | Theme: {theme} | Language: {lang}")
                .replace("{state}", runText)
                .replace("{theme}", themeText)
                .replace("{lang}", currentLang());
        }

        function videoExportAudioShell() {
            return byId("video_export_audio_shell");
        }

        function videoExportSubtitleLangShell() {
            return byId("video_export_subtitle_lang_shell");
        }

        function videoExportAudioSummary() {
            return byId("video_export_audio_summary");
        }

        function videoExportSelectedChannels() {
            const channels = [];
            for (let ch = 0; ch < 4; ch++) {
                const el = byId(`video_export_audio_ch${ch}`);
                if (el && el.checked) channels.push(ch);
            }
            return channels;
        }

        function refreshVideoExportAudioSummary() {
            const dict = t(currentLang());
            const shell = videoExportAudioShell();
            const summary = videoExportAudioSummary();
            if (!shell || !summary) return;

            const labels = [];
            for (let ch = 0; ch < 4; ch++) {
                const box = byId(`video_export_audio_ch${ch}`);
                const label = byId(`video_export_audio_ch${ch}_label`);
                if (box && box.checked) {
                    labels.push(String(label && label.textContent ? label.textContent : "").trim());
                }
            }

            if (!labels.length) {
                summary.textContent = dict.video_export_audio_none || dict.video_export_audio_silent || "Silent video";
            } else if (labels.length === 4) {
                summary.textContent = dict.video_export_audio_all || "All audio tracks";
            } else {
                summary.textContent = labels.join(" / ");
            }
            shell.setAttribute("data-summary", summary.textContent);
        }

        function setVideoExportAudioAll(checked) {
            for (let ch = 0; ch < 4; ch++) {
                const el = byId(`video_export_audio_ch${ch}`);
                if (el) el.checked = checked;
            }
            refreshVideoExportAudioSummary();
            refreshVideoExportRowsLanguage();
        }

        function toggleVideoExportAudioShell(forceOpen = null) {
            const shell = videoExportAudioShell();
            const trigger = byId("video_export_audio_trigger");
            if (!shell || !trigger) return;
            const willOpen = forceOpen === null ? !shell.classList.contains("open") : !!forceOpen;
            shell.classList.toggle("open", willOpen);
            trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
            if (willOpen) refreshVideoExportAudioSummary();
        }

        function closeVideoExportAudioShell() {
            const shell = videoExportAudioShell();
            const trigger = byId("video_export_audio_trigger");
            if (!shell || !trigger) return;
            shell.classList.remove("open");
            trigger.setAttribute("aria-expanded", "false");
        }

        function videoExportSelectedSubtitleLanguages() {
            const codes = ["CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "IT", "JP", "KR", "PT", "RU", "TH", "TR", "VI"];
            const selected = [];
            for (const code of codes) {
                const el = byId(`video_export_subtitle_lang_${code}`);
                if (el && el.checked) selected.push(code);
            }
            return selected;
        }

        function refreshVideoExportSubtitleLangSummary() {
            const dict = t(currentLang());
            const shell = videoExportSubtitleLangShell();
            const summary = byId("video_export_subtitle_lang_summary");
            if (!shell || !summary) return;
            const selectedCodes = videoExportSelectedSubtitleLanguages();
            if (!selectedCodes.length) {
                summary.textContent = dict.video_export_subtitle_lang_none || "No language";
            } else if (selectedCodes.length === 15) {
                summary.textContent = dict.video_export_subtitle_lang_all || "All languages";
            } else {
                const names = selectedCodes
                    .map((code) => {
                        const label = byId(`video_export_subtitle_lang_${code}_label`);
                        return String((label && label.textContent) || code).trim();
                    })
                    .filter(Boolean);
                summary.textContent = names.join(" / ");
            }
        }

        function setVideoExportSubtitleLangAll(checked) {
            const codes = ["CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "IT", "JP", "KR", "PT", "RU", "TH", "TR", "VI"];
            for (const code of codes) {
                const el = byId(`video_export_subtitle_lang_${code}`);
                if (el) el.checked = checked;
            }
            refreshVideoExportSubtitleLangSummary();
        }

        function toggleVideoExportSubtitleLangShell(forceOpen = null) {
            const shell = videoExportSubtitleLangShell();
            const trigger = byId("video_export_subtitle_lang_trigger");
            if (!shell || !trigger) return;
            if (trigger.disabled) {
                closeVideoExportSubtitleLangShell();
                return;
            }
            const willOpen = forceOpen === null ? !shell.classList.contains("open") : !!forceOpen;
            shell.classList.toggle("open", willOpen);
            trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
            if (willOpen) refreshVideoExportSubtitleLangSummary();
        }

        function closeVideoExportSubtitleLangShell() {
            const shell = videoExportSubtitleLangShell();
            const trigger = byId("video_export_subtitle_lang_trigger");
            if (!shell || !trigger) return;
            shell.classList.remove("open");
            trigger.setAttribute("aria-expanded", "false");
        }

        function setCustomSelectDisabled(selectId, disabled) {
            const instance = customSelectInstances.get(selectId);
            if (!instance) return;
            const next = !!disabled;
            if (instance.select) instance.select.disabled = next;
            if (instance.trigger) {
                instance.trigger.disabled = next;
                instance.trigger.setAttribute("aria-disabled", next ? "true" : "false");
                if (next) instance.trigger.setAttribute("aria-expanded", "false");
            }
            if (next && instance.shell) {
                instance.shell.classList.remove("open");
            }
        }

        function setVideoExportUiRunning(running) {
            const locked = !!running;
            if (locked) {
                closeAllVideoExportMultiSelects();
                closeCustomSelects(null);
            }

            ["video_export_output", "video_export_hybrid_limit"].forEach((id) => {
                const el = byId(id);
                if (el) el.disabled = locked;
            });

            [
                "video_export_output_pick_btn",
                "video_export_subtitle_pick_btn",
                "video_export_close_btn",
                "video_export_hw_toggle",
                "video_export_audio_trigger",
                "video_export_audio_all_btn",
                "video_export_audio_none_btn",
                "video_export_subtitle_lang_trigger",
                "video_export_subtitle_lang_all_btn",
                "video_export_subtitle_lang_none_btn",
            ].forEach((id) => {
                const el = byId(id);
                if (el) el.disabled = locked;
            });

            ["video_export_format", "video_export_subtitle_source", "video_export_mode"].forEach((id) => {
                setCustomSelectDisabled(id, locked);
            });

            for (let ch = 0; ch < 4; ch++) {
                const box = byId(`video_export_audio_ch${ch}`);
                if (box) box.disabled = locked;
            }
            const codes = ["CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "IT", "JP", "KR", "PT", "RU", "TH", "TR", "VI"];
            for (const code of codes) {
                const box = byId(`video_export_subtitle_lang_${code}`);
                if (box) box.disabled = locked;
            }

            updateVideoExportHardwareUi();
            updateVideoExportStartButtonState();
        }

        function updateVideoExportStartButtonState() {
            const startBtn = byId("video_export_start_btn");
            const logBtn = byId("video_export_ffmpeg_log_btn");
            if (!startBtn) return;
            const hasCandidates = Array.isArray(videoExportCandidates) && videoExportCandidates.length > 0;
            const outputEl = byId("video_export_output");
            const hasOutput = String((outputEl && outputEl.value) || "").trim().length > 0;
            startBtn.disabled = !!videoExportRunning || !hasCandidates || !hasOutput;
            // FFMPEG Log button is always enabled, user can view logs anytime
            if (logBtn) logBtn.disabled = false;
        }

        function updateVideoExportSubtitleLocalInfo() {
            const dict = t(currentLang());
            const info = byId("video_export_subtitle_local_info");
            if (!info) return;
            const count = videoExportLocalSubtitleFiles.length;
            if (!count) {
                info.textContent = dict.video_export_subtitle_local_none || "No subtitle file selected";
                return;
            }
            info.textContent = (dict.video_export_subtitle_local_count || "Selected {count} file(s)").replace("{count}", String(count));
        }

        function updateVideoExportSubtitleSourceUi() {
            const locked = !!videoExportRunning;
            const source = String((byId("video_export_subtitle_source") && byId("video_export_subtitle_source").value) || "off");
            const localGroup = byId("video_export_subtitle_local_group");
            const pickBtn = byId("video_export_subtitle_pick_btn");
            const localInfo = byId("video_export_subtitle_local_info");
            const langShell = byId("video_export_subtitle_lang_shell");
            const langTrigger = byId("video_export_subtitle_lang_trigger");
            const langAllBtn = byId("video_export_subtitle_lang_all_btn");
            const langNoneBtn = byId("video_export_subtitle_lang_none_btn");
            const showLocal = source === "local";
            if (localGroup) localGroup.style.display = showLocal ? "" : "none";
            if (pickBtn) pickBtn.disabled = locked || source !== "local";
            if (localInfo) localInfo.style.opacity = source === "local" ? "1" : "0.65";
            if (langShell) langShell.style.opacity = (locked || source === "off") ? "0.6" : "1";
            if (langTrigger) {
                langTrigger.disabled = locked || source === "off";
                if (locked || source === "off") {
                    closeVideoExportSubtitleLangShell();
                }
            }
            if (langAllBtn) langAllBtn.disabled = locked || source === "off";
            if (langNoneBtn) langNoneBtn.disabled = locked || source === "off";
            const codes = ["CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "IT", "JP", "KR", "PT", "RU", "TH", "TR", "VI"];
            for (const code of codes) {
                const box = byId(`video_export_subtitle_lang_${code}`);
                if (box) box.disabled = locked || source === "off";
            }
        }

        function updateVideoExportModeUi() {
            const mode = String((byId("video_export_mode") && byId("video_export_mode").value) || "container");
            const limitGroup = byId("video_export_hybrid_group");
            const showLimit = mode === "hybrid";
            if (limitGroup) limitGroup.style.display = showLimit ? "" : "none";

            if (mode === "container") {
                const subSource = byId("video_export_subtitle_source");
                if (subSource && subSource.value === "off") {
                    subSource.value = "online";
                    refreshCustomSelect("video_export_subtitle_source");
                }
                updateVideoExportSubtitleSourceUi();
            }
        }

        function closeVideoExportSubtitleConvertModal(resetPending = true) {
            const modal = byId("video_export_subtitle_convert_modal");
            if (modal) modal.classList.add("hidden");
            if (resetPending) {
                pendingVideoExportPayload = null;
                pendingVideoExportSubtitlePromptInfo = null;
            }
        }

        function buildVideoExportPayload() {
            const profile = videoExportHardwareProfile || {};
            const hwEnabled = !!(profile.available && byId("video_export_hw_toggle") && byId("video_export_hw_toggle").checked);
            return {
                format: byId("video_export_format").value,
                output_dir: String(byId("video_export_output").value || "").trim(),
                candidates: videoExportCandidates,
                selected_channels: videoExportSelectedChannels(),
                subtitle_source: byId("video_export_subtitle_source") ? byId("video_export_subtitle_source").value : "off",
                subtitle_languages: videoExportSelectedSubtitleLanguages(),
                subtitle_local_files: videoExportLocalSubtitleFiles,
                export_mode: byId("video_export_mode") ? byId("video_export_mode").value : "container",
                default_subtitle_lang: getPreferredSoftSubtitleLang(),
                hybrid_hardsub_limit: byId("video_export_hybrid_limit") ? Number(byId("video_export_hybrid_limit").value || 2) : 2,
                subtitle_convert_mode: "original",
                use_hwaccel: hwEnabled,
                hw_encoder: hwEnabled ? String(profile.encoder || "") : "",
            };
        }

        function getVideoExportSubtitlePromptInfo(payload) {
            if (!payload || payload.subtitle_source === "off") return null;
            if (payload.subtitle_source === "online") {
                return payload.subtitle_languages && payload.subtitle_languages.length
                    ? { source: "online", formats: ["SRT"] }
                    : null;
            }
            if (payload.subtitle_source !== "local") return null;
            const formats = Array.from(new Set(
                (videoExportLocalSubtitleFiles || [])
                    .map((file) => {
                        const text = String(file || "").trim().toLowerCase();
                        const idx = text.lastIndexOf(".");
                        return idx >= 0 ? text.slice(idx + 1).toUpperCase() : "";
                    })
                    .filter((ext) => ext === "SRT" || ext === "TXT")
            ));
            return formats.length ? { source: "local", formats } : null;
        }

        function refreshVideoExportSubtitleConvertModalText() {
            if (!pendingVideoExportSubtitlePromptInfo) return;
            const dict = t(currentLang());
            const info = pendingVideoExportSubtitlePromptInfo;
            const formatsText = (info.formats || []).join(" / ") || "SRT";
            const message = info.source === "online"
                ? String(dict.video_export_subtitle_convert_message_online || "Online subtitles are fetched as SRT files. Convert them to ASS before export?")
                : String(dict.video_export_subtitle_convert_message_local || "Detected local subtitle files in {formats}. Convert them to ASS before export?").replace("{formats}", formatsText);
            const noteKey = (info.formats || []).includes("TXT")
                ? "video_export_subtitle_convert_note_txt"
                : "video_export_subtitle_convert_note";
            const note = String(dict[noteKey] || "").trim();
            setText("video_export_subtitle_convert_message", note ? `${message}\n\n${note}` : message);
        }

        function openVideoExportSubtitleConvertModal(info, payload) {
            pendingVideoExportPayload = payload;
            pendingVideoExportSubtitlePromptInfo = info;
            refreshVideoExportSubtitleConvertModalText();
            const modal = byId("video_export_subtitle_convert_modal");
            if (modal) modal.classList.remove("hidden");
        }

        function runVideoExportPayload(payload) {
            if (!bridge || !bridge.startVideoExport || videoExportRunning) return;
            videoExportRunning = true;
            setVideoExportUiRunning(true);
            bridge.startVideoExport(JSON.stringify(payload));
        }

        function refreshVideoExportOnlineCheckProgressText() {
            const dict = t(currentLang());
            const template = String(dict.video_export_online_check_progress || "Checking... ({done}/{total})");
            const text = template.replace("{done}", String(videoExportOnlineCheckDone)).replace("{total}", String(videoExportOnlineCheckTotal));
            const elem = byId("video_export_online_check_progress");
            if (elem) elem.textContent = text;
        }

        function onVideoExportSubtitleCoverageProgress(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            videoExportOnlineCheckDone = Number(payload.done || 0);
            videoExportOnlineCheckTotal = Number(payload.total || 0);
            refreshVideoExportOnlineCheckProgressText();
        }

        function proceedVideoExportWithPrompt(payload) {
            const promptInfo = getVideoExportSubtitlePromptInfo(payload);
            if (promptInfo) {
                openVideoExportSubtitleConvertModal(promptInfo, payload);
                return;
            }
            runVideoExportPayload(payload);
        }

        function maybeCheckVideoExportOnlineSubtitleCoverage(payload) {
            if (!payload || !bridge || !bridge.checkVideoExportOnlineSubtitleCoverage) {
                proceedVideoExportWithPrompt(payload);
                return;
            }
            if (payload.online_subtitle_coverage_confirmed) {
                proceedVideoExportWithPrompt(payload);
                return;
            }
            const isOnline = String(payload.subtitle_source || "off") === "online";
            const langs = Array.isArray(payload.subtitle_languages) ? payload.subtitle_languages : [];
            if (!isOnline || langs.length <= 0) {
                proceedVideoExportWithPrompt(payload);
                return;
            }
            pendingVideoExportCoveragePayload = payload;
            videoExportOnlineCheckDone = 0;
            videoExportOnlineCheckTotal = (payload.candidates || []).length;
            refreshVideoExportOnlineCheckProgressText();
            byId("video_export_online_check_modal").classList.remove("hidden");
            bridge.checkVideoExportOnlineSubtitleCoverage(JSON.stringify(payload));
        }

        let videoExportOnlineCheckDone = 0;
        let videoExportOnlineCheckTotal = 0;
        let pendingVideoExportSubtitleMissingPayload = null;
        let cleanupProgressModel = { display: 0, target: 0, lastTick: Date.now() };
        let cleanupProgressPumpTimer = null;

        function _ensureCleanupProgressPump() {
            if (cleanupProgressPumpTimer !== null) return;
            cleanupProgressPumpTimer = window.setTimeout(_pumpCleanupProgress, 33);
        }

        function _pumpCleanupProgress() {
            cleanupProgressPumpTimer = null;
            const now = Date.now();
            const dtSec = Math.max(0.016, Math.min(0.2, (now - (cleanupProgressModel.lastTick || now)) / 1000));
            // Faster progress for cleanup (up to 4x speed when near 100%)
            const urgency = cleanupProgressModel.target >= 99 ? 4.0 : (cleanupProgressModel.target >= 80 ? 2.5 : 1.2);
            cleanupProgressModel.display = _advanceProgress(
                Number(cleanupProgressModel.display || 0),
                Number(cleanupProgressModel.target || 0),
                dtSec,
                urgency
            );
            cleanupProgressModel.lastTick = now;
            const fill = byId("cleanup_progress_fill");
            const pctText = byId("cleanup_progress_percentage");
            if (fill) fill.style.width = `${cleanupProgressModel.display}%`;
            if (pctText) pctText.textContent = formatProgressText(cleanupProgressModel.display);
            if (Math.abs(Number(cleanupProgressModel.target || 0) - cleanupProgressModel.display) >= 0.1) {
                _ensureCleanupProgressPump();
            }
        }

        function onVideoExportSubtitleCoverageReady(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            byId("video_export_online_check_modal").classList.add("hidden");
            videoExportOnlineCheckDone = 0;
            videoExportOnlineCheckTotal = 0;
            const pendingPayload = pendingVideoExportCoveragePayload;
            pendingVideoExportCoveragePayload = null;
            if (!pendingPayload) {
                return;
            }
            const missing = Array.isArray(payload.missing_names)
                ? payload.missing_names.map((x) => String(x || "").trim()).filter(Boolean)
                : [];
            const total = Number(payload.total || 0);
            if (missing.length <= 0) {
                pendingPayload.online_subtitle_all_missing = false;
                pendingPayload.online_subtitle_coverage_confirmed = true;
                proceedVideoExportWithPrompt(pendingPayload);
                return;
            }
            pendingPayload.online_subtitle_all_missing = total > 0 && missing.length >= total;

            const dict = t(currentLang());
            const preview = missing.slice(0, 12).join("\n");
            const hidden = Math.max(0, missing.length - 12);
            const hiddenText = hidden > 0
                ? `\n${String(dict.video_export_subtitle_online_missing_more || "... and {count} more files").replace("{count}", String(hidden))}`
                : "";
            const template = String(
                dict.video_export_subtitle_online_missing_confirm
                || "The following files did not match online subtitles ({count}/{total}). Continue export without subtitles for these files?\n\n{files}{more}"
            );
            const message = template
                .replace("{count}", String(missing.length))
                .replace("{total}", String(total > 0 ? total : missing.length))
                .replace("{files}", preview)
                .replace("{more}", hiddenText);

            pendingVideoExportSubtitleMissingPayload = pendingPayload;
            byId("video_export_subtitle_missing_confirm_title").textContent = dict.video_export_subtitle_online_missing_title || "Online Subtitles Not Found";
            byId("video_export_subtitle_missing_confirm_message").textContent = message;
            byId("video_export_subtitle_missing_confirm_modal").classList.remove("hidden");
        }

        function confirmVideoExportSubtitleMissing() {
            const payload = pendingVideoExportSubtitleMissingPayload;
            pendingVideoExportSubtitleMissingPayload = null;
            byId("video_export_subtitle_missing_confirm_modal").classList.add("hidden");
            if (!payload) return;
            payload.online_subtitle_coverage_confirmed = true;
            if (payload.online_subtitle_all_missing) {
                const dict = t(currentLang());
                appendLog(dict.video_export_subtitle_online_all_missing_skip_ass_log || "[INFO] Online subtitles missed for all selected videos; skipping ASS conversion prompt and continuing export without subtitles.");
                runVideoExportPayload(payload);
                return;
            }
            proceedVideoExportWithPrompt(payload);
        }

        function cancelVideoExportSubtitleMissing() {
            pendingVideoExportSubtitleMissingPayload = null;
            byId("video_export_subtitle_missing_confirm_modal").classList.add("hidden");
        }

        function confirmVideoExportSubtitleConversion(mode) {
            if (!pendingVideoExportPayload) {
                closeVideoExportSubtitleConvertModal();
                return;
            }
            const payload = pendingVideoExportPayload;
            payload.subtitle_convert_mode = mode === "ass" ? "ass" : "original";
            closeVideoExportSubtitleConvertModal(false);
            pendingVideoExportPayload = null;
            pendingVideoExportSubtitlePromptInfo = null;
            runVideoExportPayload(payload);
        }

        function getPreferredSoftSubtitleLang() {
            const selected = videoExportSelectedSubtitleLanguages();
            if (selected.includes("CHS")) return "CHS";
            if (selected.includes("EN")) return "EN";
            return selected.length ? selected[0] : "";
        }

        function updateVideoExportHardwareUi() {
            const dict = t(currentLang());
            const group = byId("video_export_hw_group");
            const toggle = byId("video_export_hw_toggle");
            const info = byId("video_export_hw_info");
            const profile = videoExportHardwareProfile || {};
            const available = !!profile.available;
            
            if (group) {
                group.classList.toggle("hidden", !available);
            }
            if (toggle) {
                if (!available) {
                    toggle.checked = false;
                }
                toggle.disabled = !!videoExportRunning || !available;
            }
            if (info) {
                if (videoExportHardwareProbePending) {
                    info.textContent = dict.video_export_hw_probe_running || "Detecting hardware...";
                } else if (available) {
                    let infoText = "";
                    const gpuModel = String(profile.gpu_model || "").trim();
                    const vendorLabel = String(profile.vendor_label || profile.vendor || "GPU");
                    const encoderLabel = String(profile.encoder_label || profile.encoder || "H264");
                    
                    if (gpuModel && gpuModel.length > 2) {
                        // If we have the actual GPU model name, show it with encoder info
                        const modelTemplate = dict.video_export_hw_detected_model || "Detected: {model}";
                        infoText = modelTemplate.replace("{model}", gpuModel);
                    } else {
                        // Fallback: show vendor + encoder
                        const template = String(dict.video_export_hw_detected || "Detected: {vendor} ({encoder})");
                        infoText = template
                            .replace("{vendor}", vendorLabel)
                            .replace("{encoder}", encoderLabel);
                    }
                    info.textContent = infoText;
                } else {
                    info.textContent = "";
                }
            }
        }

        function probeVideoExportHardware(force = false) {
            if (!bridge || !bridge.probeVideoExportHardware) {
                return;
            }
            if (videoExportHardwareProbePending) {
                return;
            }
            if (!force && videoExportHardwareProfile) {
                updateVideoExportHardwareUi();
                return;
            }
            videoExportHardwareProbePending = true;
            videoExportHardwareProfile = null;
            updateVideoExportHardwareUi();
            bridge.probeVideoExportHardware();
        }

        function onVideoExportHardwareReady(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            videoExportHardwareProbePending = false;
            videoExportHardwareProfile = payload;
            updateVideoExportHardwareUi();
            if (!payload.available) {
                const dict = t(currentLang());
                const reason = String(payload.reason || dict.video_export_hw_cpu_fallback || "Hardware unavailable, using CPU encoder.");
                appendLog(`[INFO] ${reason}`);
            }
        }

        function updateVideoExportCapabilityUi() {
            const locked = !!videoExportRunning;
            const dict = t(currentLang());
            const hasAnyAudio = videoExportCandidates.some((item) => {
                const tracks = Array.isArray(item && item.audio_tracks) ? item.audio_tracks : [];
                const wavs = Array.isArray(item && item.wavs) ? item.wavs : [];
                return tracks.length > 0 || wavs.length > 0;
            });

            const audioShell = byId("video_export_audio_shell");
            const audioTrigger = byId("video_export_audio_trigger");
            const allBtn = byId("video_export_audio_all_btn");
            const noneBtn = byId("video_export_audio_none_btn");
            if (audioShell) audioShell.style.opacity = hasAnyAudio ? "1" : "0.6";
            if (audioTrigger) audioTrigger.disabled = locked || !hasAnyAudio;
            if (allBtn) allBtn.disabled = locked || !hasAnyAudio;
            if (noneBtn) noneBtn.disabled = locked || !hasAnyAudio;
            for (let ch = 0; ch < 4; ch++) {
                const box = byId(`video_export_audio_ch${ch}`);
                if (box) box.disabled = locked || !hasAnyAudio;
            }
            if (!hasAnyAudio) {
                const summary = byId("video_export_audio_summary");
                if (summary) summary.textContent = dict.video_export_audio_only_ivf || "Video only";
            } else {
                refreshVideoExportAudioSummary();
            }
        }

        function formatVideoExportAudioTracks(item, useSelectedOnly = false) {
            const tracks = Array.isArray(item && item.audio_tracks) ? item.audio_tracks : [];
            const dict = t(currentLang());
            if (!tracks.length) return dict.video_export_audio_only_ivf || "IVF only";
            const selected = new Set(videoExportSelectedChannels());
            const effectiveTracks = useSelectedOnly
                ? tracks.filter((track) => {
                    const rawCh = Number(track && track.ch);
                    return Number.isInteger(rawCh) && selected.has(rawCh);
                })
                : tracks;

            if (useSelectedOnly && !effectiveTracks.length) {
                return dict.video_export_audio_none || dict.video_export_audio_silent || "Silent video";
            }

            return effectiveTracks
                .map((track) => {
                    const rawCh = Number(track && track.ch);
                    if (Number.isInteger(rawCh) && rawCh >= 0 && rawCh <= 3) {
                        const key = `video_export_audio_ch${rawCh}`;
                        const translated = String(dict[key] || "").trim();
                        if (translated) return translated;
                    }
                    return String((track && track.label) || "").trim();
                })
                .filter(Boolean)
                .join(" / ");
        }

        function normalizeVideoExportStatusText(statusText) {
            const raw = String(statusText || "").trim();
            if (!raw) return "";
            const langs = ["zh-CN", "zh-TW", "en"];
            const keys = ["pending", "running", "done", "failed"];
            for (const lang of langs) {
                const dict = t(lang);
                for (const key of keys) {
                    if (raw === String(dict[`video_export_status_${key}`] || "")) {
                        return key;
                    }
                }
            }
            const lowered = raw.toLowerCase();
            if (lowered.includes("pending")) return "pending";
            if (lowered.includes("running")) return "running";
            if (lowered.includes("done")) return "done";
            if (lowered.includes("failed")) return "failed";
            return "";
        }

        function refreshVideoExportRowsLanguage() {
            if (!Array.isArray(videoExportCandidates) || videoExportCandidates.length <= 0) return;
            const dict = t(currentLang());
            for (const item of videoExportCandidates) {
                const id = String(item && (item.id || item.name || ""));
                if (!id) continue;
                const row = byId(`video_export_row_${id}`);
                if (!row) continue;

                const audioCell = row.children && row.children[2];
                if (audioCell) {
                    const audioText = formatVideoExportAudioTracks(item, true);
                    audioCell.className = "video-export-audio-cell" + (audioText === (dict.video_export_audio_only_ivf || "IVF only") ? "" : " has-audio");
                    audioCell.removeAttribute("title");
                    const label = audioCell.querySelector(".audio-track-list");
                    if (label) label.textContent = audioText;
                }

                const statusEl = byId(`video_export_status_${id}`);
                if (statusEl) {
                    const key = normalizeVideoExportStatusText(statusEl.textContent || "") || "pending";
                    const next = dict[`video_export_status_${key}`] || statusEl.textContent || "";
                    statusEl.textContent = next;
                }
            }
        }

        function setText(id, text) {
            const el = byId(id);
            if (!el) return;
            // Support real newlines for line breaks
            const hasNewline = text.indexOf(String.fromCharCode(10)) !== -1;
            if (hasNewline) {
                el.innerHTML = text.split(String.fromCharCode(10)).map(line => {
                    return document.createTextNode(line).nodeValue;
                }).join('<br>');
                el.style.whiteSpace = 'pre-wrap';
            } else {
                el.textContent = text;
                el.style.whiteSpace = '';
            }
        }

        function setTextWithLinks(id, text) {
            const el = byId(id);
            if (!el) return;
            const raw = String(text || "");
            const urlRe = /(https?:\/\/[^\s<]+)/g;
            let html = "";
            let last = 0;
            let m;
            while ((m = urlRe.exec(raw)) !== null) {
                const start = m.index;
                const url = m[0];
                html += escapeHtml(raw.slice(last, start));
                html += `<a href="${escapeHtml(url)}" onclick="openExternalLink('${escapeHtml(url)}'); return false;">${escapeHtml(url)}</a>`;
                last = start + url.length;
            }
            html += escapeHtml(raw.slice(last));
            el.innerHTML = html.replace(/\n/g, "<br>");
            el.style.whiteSpace = "normal";
        }

        function openExternalLink(url) {
            const target = String(url || "").trim();
            if (!target) return;
            if (bridge && bridge.openExternalUrl) {
                bridge.openExternalUrl(target);
                return;
            }
            window.open(target, "_blank", "noopener,noreferrer");
        }

        function setPlaceholder(id, text) {
            const el = byId(id);
            if (el) el.placeholder = text;
        }

        function updateInputSelectionInteraction() {
            const input = byId("input");
            if (!input) return;
            const isMulti = Array.isArray(selectedInputFiles) && selectedInputFiles.length > 1;
            input.classList.toggle("clickable", isMulti);
            if (isMulti) {
                const dict = t(currentLang());
                input.setAttribute("aria-label", dict.input_selection_open_hint || "Click to view selected file list");
            } else {
                input.removeAttribute("aria-label");
            }
        }

        function openInputSelectionModal() {
            if (!Array.isArray(selectedInputFiles) || selectedInputFiles.length <= 1) return;
            const list = byId("input_selection_list");
            if (list) list.value = selectedInputFiles.join("\n");
            const modal = byId("input_selection_modal");
            if (modal) modal.classList.remove("hidden");
        }

        function closeInputSelectionModal() {
            const modal = byId("input_selection_modal");
            if (modal) modal.classList.add("hidden");
        }

        function handleInputSelectionKeydown(event) {
            if (!event) return;
            const key = String(event.key || "");
            if (key === "Enter" || key === " ") {
                event.preventDefault();
                openInputSelectionModal();
            }
        }

        function setInputSelectionTooltip(text) {
            const row = byId("input_row");
            const input = byId("input");
            if (row) {
                row.removeAttribute("data-tooltip");
            }
            if (input) {
                input.removeAttribute("title");
            }
            updateInputSelectionInteraction();
        }

        function setTooltip(id, text) {
            const el = byId(id);
            if (!el) return;
            el.setAttribute("data-tooltip", text || "");
            el.setAttribute("aria-label", text || "");
            el.removeAttribute("title");
        }

        function closeAllVideoExportMultiSelects() {
            closeVideoExportAudioShell();
            closeVideoExportSubtitleLangShell();
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
            refreshVideoExportAudioSummary();
            refreshVideoExportSubtitleLangSummary();
            updateVideoExportSubtitleLocalInfo();
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
                if (willOpen) {
                    closeAllVideoExportMultiSelects();
                }
                closeCustomSelects(willOpen ? selectId : null);
            });

            refreshCustomSelect(selectId);
        }

        function setupCustomSelects() {
            ["game_select", "lang_select", "theme_select", "video_export_format", "video_export_subtitle_source", "video_export_mode"].forEach(setupCustomSelect);
        }

        function setupVideoExportAudioSelect() {
            const shell = videoExportAudioShell();
            const trigger = byId("video_export_audio_trigger");
            if (!shell || !trigger || shell.dataset.bound === "1") return;
            shell.dataset.bound = "1";

            trigger.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const willOpen = !shell.classList.contains("open");
                if (willOpen) {
                    closeCustomSelects();
                    closeVideoExportSubtitleLangShell();
                }
                toggleVideoExportAudioShell();
            });

            const allBtn = byId("video_export_audio_all_btn");
            const noneBtn = byId("video_export_audio_none_btn");
            if (allBtn) {
                allBtn.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setVideoExportAudioAll(true);
                });
            }
            if (noneBtn) {
                noneBtn.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setVideoExportAudioAll(false);
                });
            }

            for (let ch = 0; ch < 4; ch++) {
                const checkbox = byId(`video_export_audio_ch${ch}`);
                if (!checkbox) continue;
                checkbox.addEventListener("change", () => {
                    refreshVideoExportAudioSummary();
                    refreshVideoExportRowsLanguage();
                });
            }

            refreshVideoExportAudioSummary();
        }

        function setupVideoExportSubtitleSelect() {
            const shell = videoExportSubtitleLangShell();
            const trigger = byId("video_export_subtitle_lang_trigger");
            if (!shell || !trigger || shell.dataset.bound === "1") return;
            shell.dataset.bound = "1";

            trigger.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const willOpen = !shell.classList.contains("open");
                if (willOpen) {
                    closeCustomSelects();
                    closeVideoExportAudioShell();
                }
                toggleVideoExportSubtitleLangShell();
            });

            const allBtn = byId("video_export_subtitle_lang_all_btn");
            const noneBtn = byId("video_export_subtitle_lang_none_btn");
            if (allBtn) {
                allBtn.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setVideoExportSubtitleLangAll(true);
                });
            }
            if (noneBtn) {
                noneBtn.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setVideoExportSubtitleLangAll(false);
                });
            }

            const codes = ["CHS", "CHT", "DE", "EN", "ES", "FR", "ID", "IT", "JP", "KR", "PT", "RU", "TH", "TR", "VI"];
            for (const code of codes) {
                const checkbox = byId(`video_export_subtitle_lang_${code}`);
                if (!checkbox) continue;
                checkbox.addEventListener("change", () => {
                    refreshVideoExportSubtitleLangSummary();
                });
            }

            refreshVideoExportSubtitleLangSummary();
            updateVideoExportSubtitleLocalInfo();
            updateVideoExportSubtitleSourceUi();
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

        function displayUsmName(name) {
            const text = String(name || "").trim();
            if (!text) return "";
            return text.replace(/\.usm$/i, "");
        }

        function computeRowVideoExt(row) {
            const explicit = String((row && row.video_ext) || "").trim().toLowerCase();
            if (explicit) return explicit;
            const videoPath = String((row && row.video && row.video.path) || "").trim();
            if (!videoPath) return "";
            const idx = videoPath.lastIndexOf(".");
            return idx >= 0 ? videoPath.slice(idx + 1).toLowerCase() : "";
        }

        function rowAudioTrackCount(row) {
            const tracks = Array.isArray(row && row.audio_tracks) ? row.audio_tracks : [];
            if (tracks.length > 0) return tracks.length;
            const audio = row && row.audio;
            if (audio && typeof audio === "object") {
                return Object.keys(audio).length;
            }
            return 0;
        }

        function renderCompatibilitySummary(rows) {
            const dict = t(currentLang());
            const el = byId("file_compat_summary");
            if (!el) return;
            if (!Array.isArray(rows) || rows.length === 0) {
                el.textContent = dict.file_compat_summary_empty || "Compatibility: no files loaded.";
                return;
            }

            const supported = new Set(["ivf", "264", "h264", "m1v"]);
            let finished = 0;
            let exportable = 0;
            let unsupportedVideo = 0;
            let noAudio = 0;

            for (const row of rows) {
                const status = String((row && row.status) || "pending");
                if (status !== "ok" && status !== "skipped" && status !== "error") continue;
                finished += 1;
                if (status === "ok") {
                    const ext = computeRowVideoExt(row);
                    if (!ext || !supported.has(ext)) {
                        unsupportedVideo += 1;
                    } else {
                        exportable += 1;
                    }
                    if (rowAudioTrackCount(row) <= 0) noAudio += 1;
                }
            }

            el.textContent = (dict.file_compat_summary || "Compatibility: finished {finished}/{total}, exportable {exportable}, unsupported video {unsupported}, no-audio {noAudio}.")
                .replace("{finished}", String(finished))
                .replace("{total}", String(rows.length))
                .replace("{exportable}", String(exportable))
                .replace("{unsupported}", String(unsupportedVideo))
                .replace("{noAudio}", String(noAudio));
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
                renderCompatibilitySummary([]);
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
                    { text: displayUsmName(row.name), title: row.path },
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
                        const hint = t(currentLang()).cell_copy_hint || "";
                        td.classList.add("copyable-cell");
                        td.setAttribute("data-copy-tooltip", hint);
                        td.removeAttribute("title");
                        td.ondblclick = () => copyCellText(td);
                        td.onmouseenter = (ev) => showHoverTooltip(hint, ev.clientX, ev.clientY);
                        td.onmousemove = (ev) => showHoverTooltip(hint, ev.clientX, ev.clientY);
                        td.onmouseleave = () => hideHoverTooltip();
                    }
                    tr.appendChild(td);
                });
                updateReportAction(row.id, row.status || "pending");
                body.appendChild(tr);
            });
            renderCompatibilitySummary(rows);
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
            const dict = t(currentLang());
            setText("blk_sync_success_title", dict.blk_sync_success_title || "BLK Key Sync Complete");
            setText("blk_sync_success_message", message || "");
            byId("blk_sync_success_modal").classList.remove("hidden");
        }

        function closeBlkSyncSuccessModal() {
            byId("blk_sync_success_modal").classList.add("hidden");
        }

        function showBlkParseInvalidPopup() {
            const dict = t(currentLang());
            setText("blk_sync_success_title", dict.blk_parse_invalid_title || dict.blk_sync_success_title || "BLK Parse Error");
            setText("blk_sync_success_message", dict.blk_parse_invalid_popup || "blk file is invalid, please choose again.");
            byId("blk_sync_success_modal").classList.remove("hidden");
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

        function onLogExportResult(payloadJson) {
            const dict = t(currentLang());
            try {
                const payload = JSON.parse(payloadJson || "{}");
                openBlkSaveSuccessModal(
                    payload.message || dict.log_exported || "",
                    payload.path || "",
                    !!payload.can_reveal,
                    payload.title || dict.log_export_result_title || dict.log_window || ""
                );
            } catch (_) {
                openBlkSaveSuccessModal(
                    dict.log_exported || "",
                    "",
                    false,
                    dict.log_export_result_title || dict.log_window || ""
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
                console.error("Failed to parse payload JSON:", _); // Added error logging
            }

            if (!payload || typeof payload !== "object") {
                openSyncResultModal(dict.blk_sync_popup_note || "", content || dict.blk_sync_popup_empty || "");
                return;
            refreshVideoExportAudioSummary();
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
            renderCompatibilitySummary(Array.from(fileRows.values()));
        }

        function _advanceProgress(current, target, dtSec, urgency = 1) {
            const delta = target - current;
            if (Math.abs(delta) < 0.15) {
                return target;
            }
            const speed = (7 + Math.min(52, Math.abs(delta) * 0.85)) * urgency;
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
            if (text) text.textContent = formatProgressText(safe);
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
            byId("overall_progress_value").textContent = formatProgressText(overallProgressCurrent);

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
            model.target = value >= 100 ? 100 : Math.max(Number(model.target || 0), value);
            rowProgressModel.set(id, model);
            _ensureProgressPump();
        }

        function setOverallProgress(done, total) {
            const t = Math.max(0, Number(total || 0));
            const d = Math.max(0, Math.min(t, Number(done || 0)));
            overallProgressTarget = t > 0 ? (d * 100) / t : 0;
            if (overallProgressTarget < 100) {
                overallProgressTarget = Math.max(overallProgressCurrent, overallProgressTarget);
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
            videoExportProgressModel.clear();
            videoExportOverallCurrent = 0;
            videoExportOverallTarget = 0;
            videoExportOverallLastTick = 0;
            for (const item of videoExportCandidates) {
                const id = String(item.id || item.name || Math.random());
                videoExportRows.set(id, {
                    id,
                    progress: 0,
                    progressTarget: 0,
                    progressDisplay: 0,
                    status: dict.video_export_status_pending || "Pending",
                });
                videoExportProgressModel.set(id, { display: 0, target: 0, lastTick: Date.now() });
                const tr = document.createElement("tr");
                tr.id = `video_export_row_${id}`;
                const audioText = formatVideoExportAudioTracks(item, true);
                const displayName = displayUsmName(String(item.name || "—"));
                tr.innerHTML = `
                    <td>${escapeHtml(displayName || "—")}</td>
                    <td id="video_export_status_${id}">${dict.video_export_status_pending || "Pending"}</td>
                    <td class="video-export-audio-cell${audioText === (dict.video_export_audio_only_ivf || "IVF only") ? "" : " has-audio"}"><span class="audio-track-list">${audioText}</span></td>
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

        function _ensureVideoExportPump() {
            if (videoExportPumpTimer !== null) return;
            videoExportPumpTimer = window.setTimeout(_pumpVideoExportProgress, 33);
        }

        function _pumpVideoExportProgress() {
            videoExportPumpTimer = null;
            const now = Date.now();
            let pendingRows = false;

            videoExportRows.forEach((row, id) => {
                const model = videoExportProgressModel.get(id) || {
                    display: Number(row.progress || 0),
                    target: Number(row.progressTarget || row.progress || 0),
                    lastTick: now,
                };
                const dtSec = Math.max(0.016, Math.min(0.2, (now - (model.lastTick || now)) / 1000));
                const urgency = model.target >= 99 ? 3.2 : 1.0;
                const next = _advanceProgress(Number(model.display || 0), Number(model.target || 0), dtSec, urgency);
                model.display = next;
                model.lastTick = now;
                videoExportProgressModel.set(id, model);

                row.progressDisplay = next;
                row.progress = Number(model.target || 0);
                videoExportRows.set(id, row);
                const fill = byId(`video_export_fill_${id}`);
                const text = byId(`video_export_text_${id}`);
                if (fill) fill.style.width = `${next}%`;
                if (text) text.textContent = formatProgressText(next);

                if (Math.abs(Number(model.target || 0) - next) >= 0.15) pendingRows = true;
            });

            const dtOverall = Math.max(0.016, Math.min(0.2, (now - (videoExportOverallLastTick || now)) / 1000));
            videoExportOverallLastTick = now;
            const overallUrgency = videoExportOverallTarget >= 99 ? 3.0 : 1.25;
            videoExportOverallCurrent = _advanceProgress(videoExportOverallCurrent, videoExportOverallTarget, dtOverall, overallUrgency);

            const fill = byId("video_export_overall_fill");
            const text = byId("video_export_overall_value");
            if (fill) fill.style.width = `${videoExportOverallCurrent}%`;
            if (text) text.textContent = formatProgressText(videoExportOverallCurrent);

            const pendingOverall = Math.abs(videoExportOverallTarget - videoExportOverallCurrent) >= 0.15;
            if (pendingRows || pendingOverall) {
                _ensureVideoExportPump();
            }
        }

        function setVideoExportOverallProgress(done, total) {
            const t = Math.max(0, Number(total || 0));
            const d = Math.max(0, Math.min(t, Number(done || 0)));
            videoExportOverallTarget = t > 0 ? (d * 100) / t : 0;
            if (videoExportOverallTarget < 100) {
                videoExportOverallTarget = Math.max(videoExportOverallCurrent, videoExportOverallTarget);
            }
            _ensureVideoExportPump();
        }

        function updateVideoExportRowProgress(id, progress, status) {
            const value = Math.max(0, Math.min(100, Number(progress || 0)));
            const statusEl = byId(`video_export_status_${id}`);
            const dict = t(currentLang());
            const row = videoExportRows.get(id) || { id, progress: 0, progressDisplay: 0, status: dict.video_export_status_pending || "Pending" };
            row.progressTarget = value;
            const model = videoExportProgressModel.get(id) || { display: Number(row.progress || 0), target: 0, lastTick: Date.now() };
            model.target = value >= 100 ? 100 : Math.max(Number(model.target || 0), value);
            videoExportProgressModel.set(id, model);
            row.progress = Number(model.target || 0);
            row.progressDisplay = Number(model.display || 0);
            videoExportRows.set(id, row);

            if (statusEl && status) {
                const normalizedKey = normalizeVideoExportStatusText(status);
                statusEl.textContent = normalizedKey ? (dict[`video_export_status_${normalizedKey}`] || String(status)) : String(status);
            }
            _ensureVideoExportPump();
        }

        function openVideoExportModal() {
            resetFfmpegLog();
            renderVideoExportRows();
            refreshVideoExportAudioSummary();
            refreshVideoExportSubtitleLangSummary();
            updateVideoExportSubtitleLocalInfo();
            updateVideoExportSubtitleSourceUi();
            updateVideoExportModeUi();
            updateVideoExportCapabilityUi();
            probeVideoExportHardware(true);
            byId("video_export_modal").classList.remove("hidden");
        }

        function resetVideoExportModalOptions() {
            if (byId("video_export_audio_ch0")) byId("video_export_audio_ch0").checked = true;
            if (byId("video_export_audio_ch1")) byId("video_export_audio_ch1").checked = true;
            if (byId("video_export_audio_ch2")) byId("video_export_audio_ch2").checked = true;
            if (byId("video_export_audio_ch3")) byId("video_export_audio_ch3").checked = true;
            if (byId("video_export_subtitle_source")) byId("video_export_subtitle_source").value = "online";
            if (byId("video_export_mode")) byId("video_export_mode").value = "container";
            if (byId("video_export_hybrid_limit")) byId("video_export_hybrid_limit").value = "2";
            if (byId("video_export_hw_toggle")) byId("video_export_hw_toggle").checked = true;
            setVideoExportSubtitleLangAll(true);
            videoExportLocalSubtitleFiles = [];
            updateVideoExportSubtitleLocalInfo();
            updateVideoExportSubtitleSourceUi();
            updateVideoExportModeUi();
            refreshVideoExportAudioSummary();
            refreshVideoExportSubtitleLangSummary();
            updateVideoExportCapabilityUi();
            updateVideoExportHardwareUi();
            refreshCustomSelect("video_export_subtitle_source");
            refreshCustomSelect("video_export_mode");
        }

        function closeVideoExportModal() {
            if (videoExportRunning) return;
            closeVideoExportSubtitleConvertModal();
            byId("video_export_modal").classList.add("hidden");
            resetVideoExportModalOptions();
        }

        function devReloadStyle() {
            if (bridge && bridge.reloadStyle) bridge.reloadStyle();
        }

        function pickVideoExportOutput() {
            if (!bridge || !bridge.pickVideoExportOutput) return;
            bridge.pickVideoExportOutput();
        }

        function pickVideoExportSubtitles() {
            if (!bridge || !bridge.pickVideoExportSubtitleFiles) return;
            bridge.pickVideoExportSubtitleFiles();
        }

        function startVideoExport() {
            if (!bridge || !bridge.startVideoExport || videoExportRunning) return;
            if (!videoExportHardwareProfile) {
                if (bridge.probeVideoExportHardware) {
                    if (!videoExportHardwareProbePending) {
                        probeVideoExportHardware(true);
                    }
                    showCopyToast(t(currentLang()).video_export_hw_probe_running || "Detecting hardware...");
                    return;
                }
            }
            const payload = buildVideoExportPayload();
            if (!payload.output_dir) {
                showCopyToast(t(currentLang()).video_export_output_required || "");
                return;
            }
            maybeCheckVideoExportOnlineSubtitleCoverage(payload);
        }

        function onVideoExportReady(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            const hadCandidates = Array.isArray(videoExportCandidates) && videoExportCandidates.length > 0;
            videoExportCandidates = Array.isArray(payload.candidates) ? payload.candidates : [];
            if (byId("video_export_output")) {
                byId("video_export_output").value = "";
            }
            if (!hadCandidates) {
                if (byId("video_export_audio_ch0")) byId("video_export_audio_ch0").checked = true;
                if (byId("video_export_audio_ch1")) byId("video_export_audio_ch1").checked = true;
                if (byId("video_export_audio_ch2")) byId("video_export_audio_ch2").checked = true;
                if (byId("video_export_audio_ch3")) byId("video_export_audio_ch3").checked = true;
                setVideoExportSubtitleLangAll(true);
                if (byId("video_export_subtitle_source")) byId("video_export_subtitle_source").value = "online";
                if (byId("video_export_mode")) {
                    const modeEl = byId("video_export_mode");
                    const modeVal = String(modeEl.value || "");
                    if (!["container", "burn", "hybrid"].includes(modeVal)) {
                        modeEl.value = "container";
                    }
                }
                if (byId("video_export_hybrid_limit")) byId("video_export_hybrid_limit").value = "2";
                videoExportLocalSubtitleFiles = [];
            }
            updateVideoExportSubtitleLocalInfo();
            updateVideoExportSubtitleSourceUi();
            updateVideoExportModeUi();
            refreshVideoExportAudioSummary();
            refreshVideoExportSubtitleLangSummary();
            updateVideoExportCapabilityUi();
            updateVideoExportHardwareUi();
            updateVideoExportStartButtonState();
            renderVideoExportButton();
        }

        /**
         * 计算多视频的平均进度
         * @returns 0-100 的百分比
         */
        function calculateAverageVideoProgress() {
            if (videoExportRows.size === 0) return 0;

            let totalProgress = 0;
            videoExportRows.forEach((row) => {
                const progress = Math.max(0, Math.min(100, Number(row.progressTarget || row.progress || 0)));
                totalProgress += progress;
            });
            
            const average = totalProgress / videoExportRows.size;
            return Math.round(average);
        }

        function onVideoExportProgress(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            updateVideoExportRowProgress(payload.id, payload.progress, payload.status);
            // 使用平均进度而非简单 done/total
            const avgProgress = calculateAverageVideoProgress();
            setVideoExportOverallProgress(avgProgress, 100);
        }

        function onVideoExportFinished(payloadJson) {
            const dict = t(currentLang());
            videoExportRunning = false;
            setVideoExportUiRunning(false);
            updateVideoExportCapabilityUi();
            updateVideoExportSubtitleSourceUi();
            setVideoExportOverallProgress(Math.max(videoExportCandidates.length, 1), Math.max(videoExportCandidates.length, 1));
            try {
                const payload = JSON.parse(payloadJson || "{}");
                openBlkSaveSuccessModal(
                    payload.message || "",
                    payload.path || "",
                    !!payload.can_reveal,
                    payload.title || dict.video_export_result_title || ""
                );
            } catch (_) {
                openBlkSaveSuccessModal(
                    dict.video_export_failed || "",
                    "",
                    false,
                    dict.video_export_result_title || ""
                );
            }
        }

        function refreshFileList() {
            renderFileList(Array.from(fileRows.values()));
        }

        function applyLanguage(lang) {
            const dict = t(lang);
            if (hoverTooltipVisible) {
                hideHoverTooltip();
            }
            document.documentElement.lang = lang;
            document.title = dict.app_title;
            setText("window_title_text", dict.app_title);
            setText("title_text", dict.app_title);
            setText("subtitle_text", dict.app_subtitle);
            setText("project_author_text", dict.project_author_text || "Author: @LoneOne-HRB");
            setTextWithLinks("project_repo_text", dict.project_repo_text || "Project repo: https://github.com/HRB-YuPai/UsmDiviner-GUI");
            setText("game_label_text", dict.game_label || "Game");
            setText("game_opt_honkai_star_rail", dict.game_opt_honkai_star_rail || "Honkai: Star Rail");
            setText("game_opt_genshin_impact", dict.game_opt_genshin_impact || "Genshin Impact");
            setText("game_opt_zenless_zone_zero", dict.game_opt_zenless_zone_zero || "Zenless Zone Zero");
            setText("game_opt_honkai_impact_3rd", dict.game_opt_honkai_impact_3rd || "Honkai Impact 3rd");
            setText("game_opt_petit_planet", dict.game_opt_petit_planet || "Petit Planet");
            setText("game_warning_text", dict.game_warning_text || "Please ensure imported USM files belong to the selected game.");
            setText("lang_label_text", dict.lang_label);
            setText("lang_opt_zh_cn", dict.lang_zh_cn);
            setText("lang_opt_zh_tw", dict.lang_zh_tw);
            setText("lang_opt_en", dict.lang_en);
            setText("theme_label_text", dict.theme_label);
            setText("theme_opt_dark", dict.theme_dark);
            setText("theme_opt_light", dict.theme_light);
            setText("analysis_mode_text", dict.analysis_mode);
            setText("blk_parse_mode_text", dict.blk_parse_toggle_label || "Parse blk");
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
            setText("open_credits_btn", dict.open_credits || "Credits");
            setText("open_video_export_btn", dict.export_video || "Export Video");
            setText("export_all_reports_btn", dict.export_all_reports || "Export All Reports");
            setText("log_window_title", dict.log_window);
            setText("export_game_keys_btn", dict.export_game_keys || "Export Game Keys");
            setText("copy_log_btn", dict.copy_log || dict.blk_versions_copy || "Copy");
            setText("export_log_btn", dict.export_log);
            setText("clear_log_btn", dict.clear_log);
            setText("close_log_btn", dict.close);
            setText("open_usage_btn", dict.open_usage || "Usage");
            setText("usage_title", dict.usage_title || "Usage Guide");
            setText("usage_close_btn", dict.close);
            setTextWithLinks("usage_content", dict.usage_content || "");
            setText("credits_title", dict.credits_title || "Open Source Acknowledgements");
            setTextWithLinks("credits_content", dict.credits_content || "");
            setText("credits_close_btn", dict.close || "Close");
            setText("exit_confirm_modal_title", dict.exit_confirm_title || "");
            setText("exit_confirm_modal_message", dict.exit_confirm_message || "");
            setText("exit_confirm_modal_yes_btn", dict.yes || "Yes");
            setText("exit_confirm_modal_no_btn", dict.no || "No");
            setText("cleanup_progress_modal_title", dict.cleanup_dialog_title || "");
            setText("run", dict.run);
            setText("blk_label", dict.blk_file_label);
            setText("blk_pick_btn", dict.btn_blk_load);
            setText("pick_versions_patch_base_btn", dict.btn_pick_versions_patch_base || "Base JSON");
            setText("open_versions_btn", dict.btn_view_versions);
            setText("open_versions_patch_btn", dict.btn_patch_versions || "Patch");
            setText("blk_versions_title", dict.blk_versions_title);
            setText("blk_versions_copy_btn", dict.blk_versions_copy);
            setText("blk_versions_save_btn", dict.blk_versions_save || dict.save_report);
            setText("blk_versions_sync_btn", dict.blk_versions_sync);
            setText("blk_versions_close_btn", dict.close);
            setText("versions_patch_mode_text", dict.versions_patch_mode_label || "versions.json patch");
            setText("versions_patch_title", dict.versions_patch_title || "versions.json patch");
            setText("versions_patch_summary", dict.versions_patch_modal_empty || "No patch preview available.");
            setText("versions_patch_source", dict.versions_patch_source_empty || "Source BLK: —");
            setText("versions_patch_warning", "");

            setText("versions_patch_copy_btn", dict.blk_versions_copy || "Copy");
            setText("versions_patch_save_btn", dict.versions_patch_save || dict.save_report || "Save");
            setText("versions_patch_close_btn", dict.close || "Close");
            setText("sync_result_title", dict.blk_sync_popup_title || dict.blk_versions_sync);
            setText("sync_result_close_btn", dict.close);
            setText("sync_result_note", dict.blk_sync_popup_note || "");
            setText("blk_sync_success_title", dict.blk_sync_success_title || dict.blk_versions_sync);
            setText("blk_sync_success_ok_btn", dict.settings_ok || "OK");
            setText("blk_save_confirm_title", dict.blk_versions_save_confirm_title || dict.blk_versions_title);
            setText("blk_save_confirm_yes_btn", dict.yes);
            setText("blk_save_confirm_no_btn", dict.no);
            setText("video_export_subtitle_convert_title", dict.video_export_subtitle_convert_title || "Convert subtitles to ASS?");
            setText("video_export_subtitle_convert_yes_btn", dict.video_export_subtitle_convert_yes || "Convert to ASS");
            setText("video_export_subtitle_convert_no_btn", dict.video_export_subtitle_convert_no || "Use Original");
            setText("video_export_subtitle_convert_cancel_btn", dict.settings_cancel || "Cancel");
            setText("video_export_subtitle_missing_confirm_title", dict.video_export_subtitle_online_missing_title || "Online Subtitles Not Found");
            setText("video_export_subtitle_missing_confirm_yes_btn", dict.video_export_subtitle_online_missing_continue || "Continue Export");
            setText("video_export_subtitle_missing_confirm_no_btn", dict.video_export_subtitle_online_missing_cancel || dict.settings_cancel || "Cancel");
            setText("input_selection_modal_title", dict.input_selection_modal_title || "Selected USM Files");
            setText("input_selection_close_btn", dict.close || "Close");
            setText("blk_save_success_title", dict.blk_versions_saved_title || dict.blk_versions_title);
            setText("blk_save_reveal_btn", dict.blk_versions_saved_reveal || dict.browse);
            setText("blk_save_success_ok_btn", dict.settings_ok || "OK");
            setText("video_export_title", dict.video_export_title || "Export Video");
            setText("video_export_format_label", dict.video_export_format_label || "Format");
            setText("video_export_mode_label", dict.video_export_mode_label || "Export Strategy");
            setText("video_export_hybrid_limit_label", dict.video_export_hybrid_limit_label || "Hybrid hard-sub count");
            setText("video_export_hw_label", dict.video_export_hw_label || "Hardware");
            setText("video_export_hw_toggle_text", dict.video_export_hw_toggle_text || "Use hardware acceleration");
            setText("video_export_output_label", dict.video_export_output_label || "Output");
            setText("video_export_output_pick_btn", dict.browse || "Browse");
            setText("video_export_audio_label", dict.video_export_audio || "Audio");
            setText("video_export_audio_all_btn", dict.video_export_audio_all || "All");
            setText("video_export_audio_none_btn", dict.video_export_audio_none || "None");
            setText("video_export_audio_ch0_label", dict.video_export_audio_ch0 || "Chinese");
            setText("video_export_audio_ch1_label", dict.video_export_audio_ch1 || "English");
            setText("video_export_audio_ch2_label", dict.video_export_audio_ch2 || "Japanese");
            setText("video_export_audio_ch3_label", dict.video_export_audio_ch3 || "Korean");
            setText("video_export_subtitle_source_label", dict.video_export_subtitle_source || "Subtitles");
            setText("video_export_subtitle_local_label", dict.video_export_subtitle_local || "Local");
            setText("video_export_subtitle_pick_btn", dict.video_export_subtitle_pick || "Pick");
            setText("video_export_subtitle_lang_label", dict.video_export_subtitle_languages || "Languages");
            setText("video_export_subtitle_lang_all_btn", dict.video_export_subtitle_lang_all || "All");
            setText("video_export_subtitle_lang_none_btn", dict.video_export_subtitle_lang_none || "None");
            const subtitleSource = byId("video_export_subtitle_source");
            if (subtitleSource && subtitleSource.options.length >= 3) {
                subtitleSource.options[0].text = dict.video_export_subtitle_source_off || "Off";
                subtitleSource.options[1].text = dict.video_export_subtitle_source_local || "Local Files";
                subtitleSource.options[2].text = dict.video_export_subtitle_source_online || "Online";
            }
            const exportMode = byId("video_export_mode");
            if (exportMode && exportMode.options.length >= 3) {
                exportMode.options[0].text = dict.video_export_mode_container || "Container (multi audio + multi subtitles)";
                exportMode.options[1].text = dict.video_export_mode_burn || "Hard Subtitle (multiple files)";
                exportMode.options[2].text = dict.video_export_mode_hybrid || "Hybrid (container + hard subtitle)";
            }
            setText("video_export_subtitle_lang_CHS_label", dict.video_export_subtitle_lang_name_CHS || "Simplified Chinese");
            setText("video_export_subtitle_lang_CHT_label", dict.video_export_subtitle_lang_name_CHT || "Traditional Chinese");
            setText("video_export_subtitle_lang_DE_label", dict.video_export_subtitle_lang_name_DE || "German");
            setText("video_export_subtitle_lang_EN_label", dict.video_export_subtitle_lang_name_EN || "English");
            setText("video_export_subtitle_lang_ES_label", dict.video_export_subtitle_lang_name_ES || "Spanish");
            setText("video_export_subtitle_lang_FR_label", dict.video_export_subtitle_lang_name_FR || "French");
            setText("video_export_subtitle_lang_ID_label", dict.video_export_subtitle_lang_name_ID || "Indonesian");
            setText("video_export_subtitle_lang_IT_label", dict.video_export_subtitle_lang_name_IT || "Italian");
            setText("video_export_subtitle_lang_JP_label", dict.video_export_subtitle_lang_name_JP || "Japanese");
            setText("video_export_subtitle_lang_KR_label", dict.video_export_subtitle_lang_name_KR || "Korean");
            setText("video_export_subtitle_lang_PT_label", dict.video_export_subtitle_lang_name_PT || "Portuguese");
            setText("video_export_subtitle_lang_RU_label", dict.video_export_subtitle_lang_name_RU || "Russian");
            setText("video_export_subtitle_lang_TH_label", dict.video_export_subtitle_lang_name_TH || "Thai");
            setText("video_export_subtitle_lang_TR_label", dict.video_export_subtitle_lang_name_TR || "Turkish");
            setText("video_export_subtitle_lang_VI_label", dict.video_export_subtitle_lang_name_VI || "Vietnamese");
            setText("video_export_th_name", dict.table_name || "Name");
            setText("video_export_th_status", dict.video_export_status || "Status");
            setText("video_export_th_audio", dict.video_export_audio || "Audio");
            setText("video_export_th_progress", dict.table_progress || "Progress");
            setText("video_export_overall_label", dict.overall_progress || "Overall progress");
            setText("video_export_ffmpeg_log_btn", dict.video_export_ffmpeg_log_btn || "FFMPEG Log");
            setText("ffmpeg_log_window_title", dict.ffmpeg_log_window_title || "FFMPEG Log");
            setText("ffmpeg_copy_log_btn", dict.ffmpeg_log_copy || "Copy");
            setText("ffmpeg_export_log_btn", dict.ffmpeg_log_export || "Export");
            setText("ffmpeg_clear_log_btn", dict.ffmpeg_log_clear || "Clear log");
            setText("ffmpeg_close_log_btn", dict.ffmpeg_log_close || "Close");
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
            setTooltip("pick_versions_patch_base_btn", dict.btn_pick_versions_patch_base_tooltip || dict.select_versions_patch_base_file || dict.versions_patch_base_label || "Select base versions.json");
            setTooltip("open_versions_btn", dict.btn_view_versions_tooltip);
            setTooltip("open_versions_patch_btn", dict.btn_patch_versions_tooltip || dict.btn_view_versions_tooltip);
            setTooltip("blk_parse_toggle_shell", dict.blk_parse_toggle_tooltip || "原神 26236578.blk 解析");
            setTooltip("versions_patch_toggle_shell", dict.versions_patch_mode_tooltip || dict.versions_patch_toggle_tooltip || "Patch versions.json from BLK data");

            setTooltip("versions_patch_copy_btn", dict.btn_versions_patch_copy_tooltip || dict.blk_versions_copy || "Copy");
            setTooltip("versions_patch_save_btn", dict.btn_versions_patch_save_tooltip || dict.versions_patch_save || dict.save_report_tooltip);
            setTooltip("versions_patch_close_btn", dict.btn_versions_patch_close_tooltip || dict.close);
            setTooltip("video_export_output_pick_btn", dict.browse || "Browse");
            setTooltip("video_export_subtitle_pick_btn", dict.video_export_subtitle_pick_tooltip || dict.video_export_subtitle_pick || "Pick");
            setTooltip("video_export_hw_toggle_shell", dict.video_export_hw_toggle_tooltip || dict.video_export_hw_toggle_text || "Use hardware acceleration");
            setTooltip("video_export_ffmpeg_log_btn", dict.video_export_ffmpeg_log_tooltip || dict.video_export_ffmpeg_log_btn || "FFMPEG Log");
            setTooltip("video_export_start_btn", dict.video_export_start_tooltip || dict.video_export_start || "Start Export");
            setTooltip("video_export_close_btn", dict.video_export_close_tooltip || dict.close || "Close");
            setText("settings_title", dict.settings_title);
            setText("settings_ok_btn", dict.settings_ok);
            setText("settings_cancel_btn", dict.settings_cancel);
            setTooltip("open_settings_btn", dict.btn_settings_tooltip);
            setTooltip("open_log_btn", dict.btn_logs_tooltip);
            setTooltip("open_usage_btn", dict.btn_usage_tooltip || dict.open_usage || "Usage");
            setTooltip("open_credits_btn", dict.btn_credits_tooltip || dict.open_credits || "Credits");
            setTooltip("open_video_export_btn", dict.btn_export_video_tooltip || dict.export_video);
            setTooltip("export_all_reports_btn", dict.btn_export_all_reports_tooltip || dict.export_all_reports);
            setTooltip("export_index_btn", dict.btn_export_index_tooltip || dict.export_index);
            setTooltip("export_game_keys_btn", dict.btn_export_game_keys_tooltip || dict.export_game_keys || "Export Game Keys");
            setTooltip("run", dict.btn_run_tooltip);
            setTooltip("export_log_btn", dict.btn_export_log_tooltip);
            setTooltip("copy_log_btn", dict.btn_copy_log_tooltip || dict.blk_versions_copy || "Copy");
            setTooltip("clear_log_btn", dict.btn_clear_log_tooltip);
            setTooltip("close_log_btn", dict.btn_close_log_tooltip);
            setTooltip("settings_ok_btn", dict.btn_settings_ok_tooltip);
            setTooltip("settings_cancel_btn", dict.btn_settings_cancel_tooltip);
            setTooltip("blk_versions_copy_btn", dict.btn_blk_versions_copy_tooltip);
            setTooltip("blk_versions_save_btn", dict.btn_blk_versions_save_tooltip || dict.save_report_tooltip);
            setTooltip("blk_versions_sync_btn", dict.btn_blk_versions_sync_tooltip);
            setTooltip("blk_versions_close_btn", dict.btn_blk_versions_close_tooltip);
            // Keep window control buttons free of browser-native title tooltips.
            const minBtn = byId("window_min_btn");
            const closeBtn = byId("window_close_btn");
            if (minBtn) minBtn.removeAttribute("title");
            if (closeBtn) closeBtn.removeAttribute("title");
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
            } else {
                updateInputSelectionInteraction();
            }
            refreshContextMenuLanguage();
            refreshAllCustomSelects();
            updateVideoExportModeUi();
            refreshVideoExportSubtitleConvertModalText();
            refreshVideoExportRowsLanguage();
            updateVideoExportHardwareUi();
            refreshFileList();
            syncInputMode(true);
            syncRules();
            updateManualKeyVisibility();
            updateGameAwareUi(false);
            renderBlkStatus();
            renderBlkModal();
            renderVersionsPatchModal();
            updateBlkSearchStatus();
            syncBlkParseToggle(false);
            syncVersionsPatchToggle(false);
            renderLogBox();
            refreshVideoExportOnlineCheckProgressText();
            updateStatusStrip();
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
            const copyBtn = byId("copy_log_btn");
            const exportBtn = byId("export_log_btn");
            const clearBtn = byId("clear_log_btn");
            const hasLogs = hasUsableLogs();
            if (copyBtn) copyBtn.disabled = !hasLogs;
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
                box.textContent = logLines.join("\n");
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
            const content = logLines.join("\n");
            const ts = new Date().toISOString().replace(/[.:]/g, "-");
            const name = "usmdiviner-log-" + ts + ".txt";
            bridge.exportLog(content, name);
        }

        function copyLogSelectionOrAll() {
            const dict = t(currentLang());
            const selected = (window.getSelection && window.getSelection().toString()) || "";
            let text = String(selected || "").trim();
            if (!text) {
                text = logLines.join("\n").trim();
            }
            if (!text) {
                showCopyToast(dict.log_empty_placeholder || "");
                return;
            }
            copyTextToClipboard(text);
            showCopyToast(dict.cell_copied || "Copied");
        }

        function exportIndexJson() {
            if (!bridge || !bridge.exportIndexJson) return;
            bridge.exportIndexJson();
        }

        function exportAllReports() {
            if (!bridge || !bridge.exportAllReports) return;
            bridge.exportAllReports();
        }

        function exportGameKeys() {
            if (!bridge || !bridge.exportGameKeys) return;
            bridge.exportGameKeys();
        }

        function openLogModal() {
            byId("log_modal").classList.remove("hidden");
            renderLogBox();
        }

        function closeLogModal() {
            byId("log_modal").classList.add("hidden");
        }

        /* ============ FFMPEG 日志管理函数 ============ */
        function appendFfmpegLog(line) {
            if ((line || "").trim().length === 0) {
                return;
            }
            lastFfmpegLogLine = line;
            lastFfmpegLogTs = Date.now();
            ffmpegLogLines.push(line);
            // Render live only when modal is open
            if (!byId("ffmpeg_log_modal").classList.contains("hidden")) {
                renderFfmpegLogBox();
                updateFfmpegLogUiState();
            }
        }

        function hasFfmpegUsableLogs() {
            return ffmpegLogLines.some((line) => (line || "").trim().length > 0);
        }

        function updateFfmpegLogUiState() {
            const copyBtn = byId("ffmpeg_copy_log_btn");
            const exportBtn = byId("ffmpeg_export_log_btn");
            const clearBtn = byId("ffmpeg_clear_log_btn");
            const hasLogs = hasFfmpegUsableLogs();
            if (copyBtn) copyBtn.disabled = !hasLogs;
            if (exportBtn) exportBtn.disabled = !hasLogs;
            if (clearBtn) clearBtn.disabled = !hasLogs;
        }

        function renderFfmpegLogBox() {
            const box = byId("ffmpeg_log_box");
            if (!box) return;
            if (!hasFfmpegUsableLogs()) {
                box.classList.add("empty");
                const dict = t(currentLang());
                box.textContent = dict.log_empty_placeholder || "No logs";
            } else {
                box.classList.remove("empty");
                box.textContent = ffmpegLogLines.join("\n");
                box.scrollTop = box.scrollHeight;
            }
            updateFfmpegLogUiState();
        }

        function clearFfmpegLog() {
            if (!hasFfmpegUsableLogs()) {
                updateFfmpegLogUiState();
                return;
            }
            ffmpegLogLines = [];
            lastFfmpegLogLine = null;
            lastFfmpegLogTs = 0;
            renderFfmpegLogBox();
        }

        function exportFfmpegLog() {
            const dict = t(currentLang());
            if (!hasFfmpegUsableLogs()) {
                showCopyToast(dict.export_log_empty || "No logs to export.");
                return;
            }
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
            const filename = `FFmpeg_Log_${timestamp}.txt`;
            const content = ffmpegLogLines.join("\n");
            if (bridge && bridge.exportFfmpegLog) {
                bridge.exportFfmpegLog(filename, content);
            } else {
                // Fallback：使用 blob 下载
                const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(url);
                showCopyToast(dict.log_exported || "Log exported");
            }
        }

        function copyFfmpegLogSelectionOrAll() {
            const dict = t(currentLang());
            const box = byId("ffmpeg_log_box");
            if (!box) return;
            const selection = (window.getSelection && window.getSelection().toString()) || "";
            const text = selection ? selection : ffmpegLogLines.join("\n").trim();
            if (!text) {
                showCopyToast(dict.copy_log_empty || "Nothing to copy.");
                return;
            }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(() => {
                    const dict_local = t(currentLang());
                    showCopyToast(dict_local.cell_copied || "Copied");
                }).catch(err => {
                    console.error("Clipboard error:", err);
                });
            } else {
                // Fallback 用于不支持 clipboard API 的浏览器
                const textarea = document.createElement("textarea");
                textarea.value = text;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand("copy");
                document.body.removeChild(textarea);
                showCopyToast(dict.cell_copied || "Copied");
            }
        }

        function openFfmpegLogModal() {
            renderFfmpegLogBox();
            updateFfmpegLogUiState();
            byId("ffmpeg_log_modal").classList.remove("hidden");
        }

        function closeFfmpegLogModal() {
            byId("ffmpeg_log_modal").classList.add("hidden");
        }

        function resetFfmpegLog() {
            ffmpegLogLines = [];
            lastFfmpegLogLine = null;
            lastFfmpegLogTs = 0;
            updateFfmpegLogUiState();
        }

        function openUsageModal() {
            byId("usage_modal").classList.remove("hidden");
        }

        function closeUsageModal() {
            byId("usage_modal").classList.add("hidden");
        }

        function openCreditsModal() {
            byId("credits_modal").classList.remove("hidden");
        }

        function closeCreditsModal() {
            byId("credits_modal").classList.add("hidden");
        }

        function openExitConfirmModal(title, message, yesText, noText) {
            setText("exit_confirm_modal_title", title || "");
            setText("exit_confirm_modal_message", message || "");
            setText("exit_confirm_modal_yes_btn", yesText || "Yes");
            setText("exit_confirm_modal_no_btn", noText || "No");
            byId("exit_confirm_modal").classList.remove("hidden");
        }

        function closeExitConfirmModal() {
            byId("exit_confirm_modal").classList.add("hidden");
        }

        function openCleanupProgressModal() {
            byId("cleanup_progress_modal").classList.remove("hidden");
        }

        function closeCleanupProgressModal() {
            byId("cleanup_progress_modal").classList.add("hidden");
        }

        function onExitPromptReady(payloadJson) {
            const dict = t(currentLang());
            try {
                const payload = JSON.parse(payloadJson || "{}");
                openExitConfirmModal(
                    payload.title || dict.exit_confirm_title || "",
                    payload.message || dict.exit_confirm_message || "",
                    payload.yes || dict.yes || "Yes",
                    payload.no || dict.no || "No"
                );
            } catch (_) {
                openExitConfirmModal(
                    dict.exit_confirm_title || "",
                    dict.exit_confirm_message || "",
                    dict.yes || "Yes",
                    dict.no || "No"
                );
            }
        }

        function confirmExitFromModal() {
            closeExitConfirmModal();
            openCleanupProgressModal();
            if (bridge && bridge.confirmWindowClose) {
                bridge.confirmWindowClose();
            }
        }

        function onCleanupProgress(payloadJson) {
            let payload = {};
            try {
                payload = JSON.parse(payloadJson || "{}");
            } catch (_) {
                payload = {};
            }
            const done = Math.max(0, Number(payload.done || 0));
            const total = Math.max(1, Number(payload.total || 1));
            const removed = Math.max(0, Number(payload.removed || 0));
            const failed = Math.max(0, Number(payload.failed || 0));
            const pct = Math.max(0, Math.min(100, (done * 100) / total));
            const file = String(payload.file || "").trim();
            
            setText("cleanup_progress_modal_title", payload.title || "");
            setText("cleanup_progress_status", payload.status || "");
            setText("cleanup_progress_file", file);
            
            // Show statistics: Removed X / Failed Y / Total Z
            const statsText = done > 0 
                ? `✓ Removed: ${removed} | ✗ Failed: ${failed} | Total: ${total}`
                : `Total files: ${total}`;
            setText("cleanup_progress_stats", statsText);
            
            cleanupProgressModel.target = pct >= 100 ? 100 : Math.max(Number(cleanupProgressModel.target || 0), pct);
            _ensureCleanupProgressPump();
            if (byId("cleanup_progress_modal").classList.contains("hidden")) {
                openCleanupProgressModal();
            }
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
            updateStatusStrip();
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
                    setInputSelectionTooltip(text);
                }
            } else if (el) {
                el.value = value;
            }
            if (field === "versions_patch_base") {
                versionsPatchBasePath = String(value || "");
                versionsPatchPreviewText = "";
                versionsPatchPreviewMeta = null;
                renderVersionsPatchModal();
            }
            if (field === "video_export_subtitles") {
                try {
                    const parsed = JSON.parse(String(value || "[]"));
                    videoExportLocalSubtitleFiles = Array.isArray(parsed)
                        ? parsed.map((x) => String(x || "").trim()).filter(Boolean)
                        : [];
                } catch (_) {
                    videoExportLocalSubtitleFiles = [];
                }
                updateVideoExportSubtitleLocalInfo();
            }
            if (field === "video_export_output") {
                updateVideoExportStartButtonState();
            }
            if (field === "input") {
                previewInput();
            } else if (field === "blk_input") {
                if (!(blkParseEnabled || versionsPatchEnabled)) {
                    return;
                }
                blkParsePending = true;
                blkVersionsData = null;
                blkVersionsEditorText = "";
                renderBlkStatus();
                renderBlkModal();
            }
        }

        function renderBlkStatus() {
            const parseBtn = byId("open_versions_btn");
            const patchBtn = byId("open_versions_patch_btn");
            const patchBaseBtn = byId("pick_versions_patch_base_btn");
            const row = byId("blk_row");
            if (row) {
                row.classList.toggle("hidden", !(blkParseEnabled || versionsPatchEnabled));
            }
            if (!isGenshinSelected() || !blkParseEnabled) {
                if (parseBtn) parseBtn.classList.add("hidden");
            } else if (parseBtn) {
                const hasVersions = !!(blkVersionsData && !blkVersionsData.error &&
                    blkVersionsData.versions_json && blkVersionsData.versions_json !== "null");
                parseBtn.classList.toggle("hidden", !hasVersions);
            }
            if (!isGenshinSelected() || !versionsPatchEnabled) {
                if (patchBaseBtn) patchBaseBtn.classList.add("hidden");
                if (patchBtn) patchBtn.classList.add("hidden");
                return;
            }
            if (patchBaseBtn) patchBaseBtn.classList.remove("hidden");
            const hasVersions = !!(blkVersionsData && !blkVersionsData.error &&
                blkVersionsData.versions_json && blkVersionsData.versions_json !== "null");
            if (patchBtn) patchBtn.classList.remove("hidden");
            if (versionsPatchEnabled) {
                renderVersionsPatchModal();
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
            if (!(blkParseEnabled || versionsPatchEnabled)) {
                return;
            }
            blkParsePending = false;
            try {
                blkVersionsData = JSON.parse(payloadJson);
                blkVersionsEditorText = String((blkVersionsData && blkVersionsData.versions_json) || "");
            } catch (_) {
                blkVersionsData = { error: payloadJson };
                blkVersionsEditorText = "";
            }
            const compatible = isVersionsJsonCompatible(blkVersionsData && blkVersionsData.versions_json);
            if (!compatible) {
                resetBlkInputField();
                showBlkParseInvalidPopup();
                return;
            }
            renderBlkStatus();
            renderBlkModal();
            renderVersionsPatchModal();
        }

        function pickBlkInput() {
            if (!bridge || !(blkParseEnabled || versionsPatchEnabled)) return;
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

        function clearVersionsPatchPreview() {
            versionsPatchPreviewText = "";
            versionsPatchPreviewMeta = null;
            renderVersionsPatchModal();
        }

        function renderVersionsPatchModal() {
            const summary = byId("versions_patch_summary");
            const source = byId("versions_patch_source");
            const baseLine = byId("versions_patch_base_line");
            const warning = byId("versions_patch_warning");
            const box = byId("versions_patch_box");
            const dict = t(currentLang());
            const sourcePath = blkVersionsData && blkVersionsData.versions ? blkVersionsData.versions.source : null;
            if (baseLine) {
                const baseLabel = dict.versions_patch_base_label || "Base versions.json";
                baseLine.textContent = baseLabel + ": " + (versionsPatchBasePath || "—");
            }
            if (summary) {
                summary.textContent = versionsPatchPreviewMeta && versionsPatchPreviewMeta.summary
                    ? versionsPatchPreviewMeta.summary
                    : (dict.versions_patch_modal_empty || "No patch preview available.");
            }
            if (source) {
                source.textContent = (dict.versions_patch_source_label || "Source BLK") + ": " + String(sourcePath || "—");
            }
            if (warning) {
                warning.textContent = versionsPatchPreviewMeta && versionsPatchPreviewMeta.warning
                    ? versionsPatchPreviewMeta.warning
                    : "";
            }
            const raw = versionsPatchPreviewText || "";
            if (box && box.value !== raw) {
                box.value = raw;
            }
        }

        function openVersionsPatchModal() {
            renderVersionsPatchModal();
            byId("versions_patch_modal").classList.remove("hidden");
            if (versionsPatchBasePath && blkVersionsData && blkVersionsData.versions_json && blkVersionsData.versions_json !== "null" && bridge && bridge.requestVersionsPatchPreview) {
                requestVersionsPatchPreview();
            }
        }

        function closeVersionsPatchModal() {
            byId("versions_patch_modal").classList.add("hidden");
        }

        function pickVersionsPatchBase() {
            if (!bridge || !bridge.pickVersionsPatchBaseFile) return;
            bridge.pickVersionsPatchBaseFile();
        }

        function requestVersionsPatchPreview() {
            const dict = t(currentLang());
            if (!versionsPatchBasePath) {
                showCopyToast(dict.versions_patch_base_required || dict.blk_versions_modal_empty || "");
                return;
            }
            if (!blkVersionsData || !blkVersionsData.versions_json || blkVersionsData.versions_json === "null") {
                showCopyToast(dict.blk_versions_sync_no_data || "");
                return;
            }
            if (!bridge || !bridge.requestVersionsPatchPreview) {
                showCopyToast(dict.blk_versions_sync_no_bridge || "");
                return;
            }
            const rows = Array.from(fileRows.values() || []);
            bridge.requestVersionsPatchPreview(versionsPatchBasePath, JSON.stringify(rows));
        }

        function copyVersionsPatch() {
            const dict = t(currentLang());
            const text = String(versionsPatchPreviewText || "");
            if (!text) {
                showCopyToast(dict.versions_patch_modal_empty || dict.blk_versions_modal_empty || "");
                return;
            }
            copyTextToClipboard(text);
            showCopyToast(dict.blk_versions_copied || dict.cell_copied || "Copied");
        }

        function saveVersionsPatch() {
            const dict = t(currentLang());
            const text = String(versionsPatchPreviewText || "");
            if (!text) {
                showCopyToast(dict.versions_patch_modal_empty || dict.blk_versions_modal_empty || "");
                return;
            }
            if (!bridge || !bridge.saveVersionsPatch) {
                showCopyToast(dict.blk_versions_sync_no_bridge || "");
                return;
            }
            bridge.saveVersionsPatch();
        }

        function onVersionsPatchReady(payloadJson) {
            try {
                const payload = JSON.parse(payloadJson || "{}");
                versionsPatchPreviewText = String(payload.patched_json || "");
                versionsPatchPreviewMeta = {
                    summary: String(payload.summary || ""),
                    warning: String(payload.warning || ""),
                    base_path: String(payload.base_path || versionsPatchBasePath || ""),
                    source_path: String(payload.source_path || ""),
                    stats: payload.stats || {},
                };
                if (payload.base_path) {
                    versionsPatchBasePath = String(payload.base_path || "");
                }
                renderVersionsPatchModal();
                if (!byId("versions_patch_modal").classList.contains("hidden")) {
                    const box = byId("versions_patch_box");
                    if (box) box.focus();
                }
            } catch (_) {
                versionsPatchPreviewText = "";
                versionsPatchPreviewMeta = { summary: payloadJson || "", warning: "", stats: {} };
                renderVersionsPatchModal();
            }
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

        function syncBlkParseToggle(clearExisting = true) {
            const toggle = byId("blk_parse_toggle");
            const patchToggle = byId("versions_patch_toggle");
            const row = byId("blk_row");
            if (!isGenshinSelected()) {
                if (toggle) toggle.checked = false;
                if (patchToggle) patchToggle.checked = false;
                blkParseEnabled = false;
                versionsPatchEnabled = false;
                if (row) row.classList.add("hidden");
                closeBlkVersionsModal();
                closeVersionsPatchModal();
                if (clearExisting) {
                    resetBlkInputField();
                    clearVersionsPatchPreview();
                }
                return;
            }
            blkParseEnabled = !!(toggle && toggle.checked);
            if (blkParseEnabled && patchToggle && patchToggle.checked) {
                patchToggle.checked = false;
                versionsPatchEnabled = false;
                closeVersionsPatchModal();
                    resetBlkInputField();
                    clearVersionsPatchPreview();
            }
            if (!blkParseEnabled) {
                closeBlkVersionsModal();
                if (clearExisting && !versionsPatchEnabled) {
                    resetBlkInputField();
                }
            } else if (clearExisting) {
                // Keep original behavior: enabling parse mode starts from a clean BLK parse state.
                clearBlkParseState();
            }
            if (row) row.classList.toggle("hidden", !(blkParseEnabled || versionsPatchEnabled));
            renderBlkStatus();
            if (clearExisting && !blkParseEnabled && !versionsPatchEnabled) {
                clearVersionsPatchPreview();
            }
        }

        function syncVersionsPatchToggle(clearExisting = true) {
            const toggle = byId("versions_patch_toggle");
            const parseToggle = byId("blk_parse_toggle");
            const row = byId("blk_row");
            if (!isGenshinSelected()) {
                if (toggle) toggle.checked = false;
                if (parseToggle) parseToggle.checked = false;
                versionsPatchEnabled = false;
                blkParseEnabled = false;
                if (row) row.classList.add("hidden");
                closeVersionsPatchModal();
                closeBlkVersionsModal();
                if (clearExisting) {
                    clearVersionsPatchPreview();
                    resetBlkInputField();
                }
                return;
            }
            versionsPatchEnabled = !!(toggle && toggle.checked);
            if (versionsPatchEnabled && parseToggle && parseToggle.checked) {
                parseToggle.checked = false;
                blkParseEnabled = false;
                closeBlkVersionsModal();
                    resetBlkInputField();
            }
            if (!versionsPatchEnabled) {
                closeVersionsPatchModal();
                if (clearExisting && !blkParseEnabled) {
                    clearVersionsPatchPreview();
                }
            }
            if (row) row.classList.toggle("hidden", !(blkParseEnabled || versionsPatchEnabled));
            renderBlkStatus();
        }

        function getInputMode() {
            return byId("mode_batch").checked ? "batch" : "single";
        }

        function updateInputModeToggleUi() {
            const shell = byId("mode_switch");
            const mode = getInputMode();
            if (shell) shell.setAttribute("data-mode", mode);
            const btn = byId("mode_toggle_btn");
            if (btn) {
                const dict = t(currentLang());
                const singleText = byId("single_file_text") ? byId("single_file_text").textContent : (dict.single_file || "File selection");
                const batchText = byId("batch_folder_text") ? byId("batch_folder_text").textContent : (dict.batch_folder || "Folder selection");
                const active = mode === "batch" ? batchText : singleText;
                btn.setAttribute("aria-label", `${dict.analysis_mode || "Mode"}: ${active}`);
                btn.removeAttribute("title");
            }
        }

        function clearBlkParseState() {
            blkParsePending = false;
            blkVersionsData = null;
            blkVersionsEditorText = "";
            renderBlkStatus();
            renderBlkModal();
            clearVersionsPatchPreview();
        }

        function resetBlkInputField() {
            const blkInput = byId("blk_input");
            if (blkInput) {
                blkInput.value = "";
                blkInput.title = "";
            }
            clearBlkParseState();
        }

        function isVersionsJsonCompatible(raw) {
            const text = String(raw || "").trim();
            if (!text || text === "null") return false;
            let decoded = null;
            try {
                decoded = JSON.parse(text);
            } catch (_) {
                return false;
            }
            if (Array.isArray(decoded)) {
                return decoded.every((item) => item && typeof item === "object" && !Array.isArray(item));
            }
            if (decoded && typeof decoded === "object") {
                return Array.isArray(decoded.list);
            }
            return false;
        }

        function updateGameAwareUi(clearBlkState = true) {
            const modeRow = byId("blk_parse_mode_row");
            const patchRow = byId("versions_patch_mode_row");
            const allowBlk = isGenshinSelected();
            if (modeRow) modeRow.classList.toggle("hidden", !allowBlk);
            if (patchRow) patchRow.classList.toggle("hidden", !allowBlk);
            if (!allowBlk) {
                syncBlkParseToggle(clearBlkState);
                syncVersionsPatchToggle(clearBlkState);
            }
        }

        function toggleInputMode() {
            const nextMode = getInputMode() === "batch" ? "single" : "batch";
            byId("mode_batch").checked = nextMode === "batch";
            byId("mode_single").checked = nextMode === "single";
            syncInputMode();
        }

        function syncInputMode(preserveState = false) {
            const mode = getInputMode();
            const dict = t(currentLang());
            updateInputModeToggleUi();
            byId("input_label").textContent = mode === "batch" ? dict.input_usm_folder : dict.input_usm_file;
            byId("input_pick_btn").textContent = mode === "batch" ? dict.pick : dict.browse;
            byId("input").placeholder = mode === "batch" ? dict.placeholder_input_folder : dict.placeholder_input_file;
            if (preserveState) {
                return;
            }
            selectedInputFiles = [];
            byId("input").value = "";
            setInputSelectionTooltip("");
            closeInputSelectionModal();
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
            setInputSelectionTooltip(selectedInputFiles.join("\n"));
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

        function setGame(game) {
            const select = byId("game_select");
            const nextGame = String(game || "").trim() || "genshin_impact";
            if (select) {
                select.value = nextGame;
                refreshCustomSelect("game_select");
            }
            updateGameAwareUi(true);
            if (bridge && bridge.setGame) {
                bridge.setGame(nextGame);
            }
        }

        function applyTheme(theme) {
            const mode = theme === "light" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", mode);
            byId("theme_select").value = mode;
            refreshCustomSelect("theme_select");
            if (bridge && bridge.setTheme) {
                bridge.setTheme(mode);
            }
            try {
                localStorage.setItem("usmdiviner_theme", mode);
            } catch (_) {
                // Ignore storage errors in restricted runtime.
            }
            updateStatusStrip();
        }

        function setTheme(theme) {
            applyTheme(theme);
        }

        function beginWindowDrag(event) {
            if (!event || event.button !== 0) return;
            const target = event.target;
            if (target instanceof Element && target.closest(".window-title-actions")) {
                return;
            }
            if (bridge && bridge.beginWindowDrag) {
                bridge.beginWindowDrag();
            }
        }

        function windowMinimize() {
            if (bridge && bridge.windowMinimize) {
                bridge.windowMinimize();
            }
        }

        function windowClose() {
            if (bridge && bridge.requestWindowClose) {
                bridge.requestWindowClose();
            }
        }

        function runTask() {
            if (!bridge) return;
            setOverallProgress(0, 0);
            const inputFiles = selectedInputFiles.length > 0 ? selectedInputFiles : (byId("input").value ? [byId("input").value] : []);
            const mode = getInputMode();
            const payload = {
                language: currentLang(),
                game: currentGame(),
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
            setupVideoExportAudioSelect();
            setupVideoExportSubtitleSelect();
            bridge.logMessage.connect(appendLog);
            bridge.ffmpegLogMessage.connect(appendFfmpegLog);
            bridge.uiToast.connect(showCopyToast);
            bridge.syncResultReady.connect(onSyncResultReady);
            bridge.blkSavePromptReady.connect(onBlkSavePromptReady);
            bridge.blkSaveCompleted.connect(onBlkSaveCompleted);
            bridge.indexExportResultReady.connect(onIndexExportResult);
            bridge.logExportResultReady.connect(onLogExportResult);
            bridge.videoExportReady.connect(onVideoExportReady);
            bridge.videoExportProgress.connect(onVideoExportProgress);
            bridge.videoExportFinished.connect(onVideoExportFinished);
            bridge.videoExportHardwareReady.connect(onVideoExportHardwareReady);
            bridge.videoExportSubtitleCoverageReady.connect(onVideoExportSubtitleCoverageReady);
            bridge.videoExportSubtitleCoverageProgress.connect(onVideoExportSubtitleCoverageProgress);
            bridge.runStateChanged.connect(setRunning);
            bridge.exitPromptReady.connect(onExitPromptReady);
            bridge.cleanupProgressReady.connect(onCleanupProgress);
            bridge.fieldChosen.connect(setField);
            bridge.fileListReady.connect(loadFileList);
            bridge.fileRowUpdate.connect(updateFileRow);
            bridge.fileProgressUpdate.connect(updateFileProgress);
            bridge.overallProgressUpdate.connect(updateOverallProgress);
            bridge.blkVersionsReady.connect(setBlkVersions);
            bridge.versionsPatchReady.connect(onVersionsPatchReady);
            bridge.styleRefreshed.connect(function(css) {
                const el = document.querySelector("style");
                if (el) el.textContent = css;
            });
            try {
                const storedTheme = localStorage.getItem("usmdiviner_theme") || "dark";
                applyTheme(storedTheme);
            } catch (_) {
                applyTheme("dark");
            }
            const game = byId("game_select").value || "genshin_impact";
            if (bridge.setGame) {
                bridge.setGame(game);
            }
            updateGameAwareUi(false);
            const lang = byId("lang_select").value || "zh-CN";
            bridge.setLanguage(lang);
            applyLanguage(lang);
            syncBlkParseToggle(false);
            if (bridge.uiReady) bridge.uiReady();
        });

        document.addEventListener("click", (event) => {
            const target = event.target;
            if (target instanceof Element && (target.closest(".select-shell") || target.closest(".multi-select-shell"))) {
                return;
            }
            closeCustomSelects();
            closeVideoExportAudioShell();
            closeVideoExportSubtitleLangShell();
        });


        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeCustomSelects();
                closeVideoExportAudioShell();
                closeVideoExportSubtitleLangShell();
                closeUsageModal();
                closeCreditsModal();
                closeExitConfirmModal();
                closeCleanupProgressModal();
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


def _dialog_stylesheet(theme: str) -> str:
    family = str(QT_DIALOG_FONT_FAMILY or "Segoe UI").replace("'", "")
    if theme == "light":
        return (
            f"QDialog {{ background: #f8f2e8; color: #3b3126; border: 1px solid #d7c9b5; border-radius: 12px; font-family: '{family}'; }}"
            f"QLabel {{ color: #3b3126; font-size: 12px; font-family: '{family}'; }}"
            "QLabel#DialogTitle { font-size: 14px; font-weight: 700; color: #3b3126; }"
            f"QProgressBar {{ border: 1px solid #d8cab6; border-radius: 7px; background: #efe4d4; color: #3b3126; text-align: center; font-family: '{family}'; }}"
            "QProgressBar::chunk { border-radius: 6px; background: #5aa884; }"
            f"QPushButton {{ border: 1px solid #cdbca7; border-radius: 8px; padding: 6px 14px; background: #fffaf1; color: #3b3126; font-weight: 600; font-family: '{family}'; }}"
            "QPushButton:hover { background: #f4eadc; }"
            "QPushButton#PrimaryButton { background: #5aa884; border-color: #438f70; color: white; }"
            "QPushButton#PrimaryButton:hover { background: #438f70; }"
        )
    return (
        f"QDialog {{ background: #1f1f1f; color: #e0e0e0; border: 1px solid #3e3e3e; border-radius: 12px; font-family: '{family}'; }}"
        f"QLabel {{ color: #e0e0e0; font-size: 12px; font-family: '{family}'; }}"
        "QLabel#DialogTitle { font-size: 14px; font-weight: 700; color: #e0e0e0; }"
        f"QProgressBar {{ border: 1px solid #505050; border-radius: 7px; background: #1a1a1a; color: #e0e0e0; text-align: center; font-family: '{family}'; }}"
        "QProgressBar::chunk { border-radius: 6px; background: #2f7d42; }"
        f"QPushButton {{ border: 1px solid #555555; border-radius: 8px; padding: 6px 14px; background: #3a3a3a; color: #e0e0e0; font-weight: 600; font-family: '{family}'; }}"
        "QPushButton:hover { background: #2a2a2a; }"
        "QPushButton#PrimaryButton { background: #2f7d42; border-color: #1e5a2f; color: white; }"
        "QPushButton#PrimaryButton:hover { background: #1e5a2f; }"
    )


def _load_qt_dialog_font(app: QApplication) -> str:
    if not FONT_PATH.exists():
        app.setFont(QFont("Segoe UI", 9))
        return ""
    font_id = QFontDatabase.addApplicationFont(str(FONT_PATH))
    if font_id == -1:
        app.setFont(QFont("Segoe UI", 9))
        return ""
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        app.setFont(QFont("Segoe UI", 9))
        return ""
    family = str(families[0])
    app.setFont(QFont(family, 9))
    return family


class _ExitConfirmDialog(QDialog):
    def __init__(self, title: str, message: str, yes_text: str, no_text: str, theme: str, parent=None) -> None:
        super().__init__(parent)
        self._accepted = False
        self.setWindowTitle("")
        self.setModal(True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(520)
        self.setStyleSheet(_dialog_stylesheet(theme))

        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        body_label = QLabel(message)
        body_label.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        no_btn = QPushButton(no_text)
        yes_btn = QPushButton(yes_text)
        yes_btn.setObjectName("PrimaryButton")
        buttons.addWidget(no_btn)
        buttons.addWidget(yes_btn)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(title_label)
        layout.addWidget(body_label)
        layout.addLayout(buttons)
        self.setLayout(layout)

        no_btn.clicked.connect(self.reject)
        yes_btn.clicked.connect(self._on_accept)

    def _on_accept(self) -> None:
        self._accepted = True
        self.accept()

    @property
    def accepted_choice(self) -> bool:
        return self._accepted


class _CleanupProgressDialog(QDialog):
    def __init__(self, title: str, theme: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("")
        self.setModal(True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(560)
        self.setStyleSheet(_dialog_stylesheet(theme))
        self._title = QLabel(title)
        self._title.setObjectName("DialogTitle")
        self._status = QLabel("")
        self._file_label = QLabel("")
        self._rel_label = QLabel("")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addWidget(self._file_label)
        layout.addWidget(self._rel_label)
        layout.addWidget(self._bar)
        self.setLayout(layout)

    def update_step(self, status_text: str, file_name: str, relative_path: str, done: int, total: int) -> None:
        self._status.setText(status_text)
        self._file_label.setText(file_name)
        self._rel_label.setText(relative_path)
        safe_total = max(1, int(total))
        safe_done = max(0, min(safe_total, int(done)))
        self._bar.setValue(int((safe_done * 100) / safe_total))
        QApplication.processEvents()


class _MainView(QWebEngineView):
    def __init__(self, bridge: "WebBridge") -> None:
        super().__init__()
        self._bridge = bridge
        self._corner_radius = 16
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.page().setBackgroundColor(QColor(0, 0, 0, 0))

    def _apply_rounded_mask(self) -> None:
        rect = self.rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), self._corner_radius, self._corner_radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_rounded_mask()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._bridge.can_close_window():
            event.accept()
            return
        if not self._bridge.can_present_exit_modal():
            event.accept()
            return
        self._bridge.requestWindowClose()
        event.ignore()


class WebBridge(QObject):
    logMessage = Signal(str)
    ffmpegLogMessage = Signal(str)
    uiToast = Signal(str)
    syncResultReady = Signal(str)
    blkSavePromptReady = Signal(str)
    blkSaveCompleted = Signal(str)
    versionsPatchReady = Signal(str)
    indexExportResultReady = Signal(str)
    logExportResultReady = Signal(str)
    videoExportReady = Signal(str)
    videoExportProgress = Signal(str)
    videoExportFinished = Signal(str)
    videoExportHardwareReady = Signal(str)
    videoExportSubtitleCoverageReady = Signal(str)
    videoExportSubtitleCoverageProgress = Signal(str)
    runStateChanged = Signal(bool)
    windowTitleChanged = Signal(str)
    fieldChosen = Signal(str, str)
    blkVersionsReady = Signal(str)
    fileListReady = Signal(str)
    fileRowUpdate = Signal(str)
    fileProgressUpdate = Signal(str)
    overallProgressUpdate = Signal(str)
    styleRefreshed = Signal(str)
    exitPromptReady = Signal(str)
    cleanupProgressReady = Signal(str)
    hostCloseRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._view: _MainView | None = None
        self._ui_ready = False
        self._allow_window_close = False
        self._close_state_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._blk_worker: threading.Thread | None = None
        self._video_export_worker: threading.Thread | None = None
        self._video_export_subtitle_probe_worker: threading.Thread | None = None
        self._cleanup_worker: threading.Thread | None = None
        self._blk_result_lock = threading.Lock()
        self._last_blk_result: dict | None = None
        self._patch_result_lock = threading.Lock()
        self._last_patch_result: dict | None = None
        self._language = DEFAULT_LANGUAGE
        self._language_lock = threading.Lock()
        self._game = DEFAULT_GAME
        self._game_lock = threading.Lock()
        self._theme = "dark"
        self._theme_lock = threading.Lock()
        self._reports_by_id: dict[str, dict] = {}
        self._reports_lock = threading.Lock()
        self._artifact_lock = threading.Lock()
        self._generated_files: set[str] = set()
        self._generated_dirs: set[str] = set()

    def bind_view(self, view: _MainView) -> None:
        self._view = view

    def _main_view(self) -> _MainView | None:
        return self._view

    def _set_language(self, language: str) -> None:
        lang = language if language in TRANSLATIONS else DEFAULT_LANGUAGE
        with self._language_lock:
            self._language = lang

    def _normalize_game_id(self, game: str) -> str:
        normalized = str(game or "").strip().lower()
        if normalized in SUPPORTED_GAMES:
            return normalized
        return DEFAULT_GAME

    def _set_game(self, game: str) -> None:
        normalized = self._normalize_game_id(game)
        with self._game_lock:
            self._game = normalized

    def _get_game(self) -> str:
        with self._game_lock:
            return self._game

    def _get_language(self) -> str:
        with self._language_lock:
            return self._language

    def _set_theme(self, theme: str) -> None:
        mode = "light" if str(theme or "").strip().lower() == "light" else "dark"
        with self._theme_lock:
            self._theme = mode

    def _get_theme(self) -> str:
        with self._theme_lock:
            return self._theme

    def _t(self, key: str, **kwargs) -> str:
        return _t(self._get_language(), key, **kwargs)

    def _register_generated_file(self, path: Path) -> None:
        try:
            normalized = str(path.resolve())
        except OSError:
            normalized = str(path.absolute())
        with self._artifact_lock:
            self._generated_files.add(normalized)

    def _register_generated_dir(self, path: Path) -> None:
        try:
            normalized = str(path.resolve())
        except OSError:
            normalized = str(path.absolute())
        with self._artifact_lock:
            self._generated_dirs.add(normalized)

    def _register_report_artifacts(self, report: dict[str, Any]) -> None:
        report_path_text = str(report.get("report_path") or "").strip()
        if report_path_text:
            self._register_generated_file(Path(report_path_text))

        video = report.get("video") or {}
        video_text = str(video.get("path") or "").strip()
        if video_text:
            self._register_generated_file(Path(video_text))

        audio = report.get("audio") or {}
        if isinstance(audio, dict):
            for item in audio.values():
                if not isinstance(item, dict):
                    continue
                path_text = str(item.get("path") or "").strip()
                if path_text:
                    audio_path = Path(path_text)
                    self._register_generated_file(audio_path)
                    # Sidecar key files are temporary decode helpers.
                    self._register_generated_file(audio_path.with_suffix(audio_path.suffix + "key"))
                decode = item.get("decode") if isinstance(item.get("decode"), dict) else {}
                wav_text = str(decode.get("wav") or "").strip()
                if wav_text:
                    self._register_generated_file(Path(wav_text))

        mux = report.get("mux") or {}
        if isinstance(mux, dict):
            for key in ("mp4", "mkv"):
                mux_text = str(mux.get(key) or "").strip()
                if mux_text:
                    self._register_generated_file(Path(mux_text))

    def cleanup_generated_artifacts(
        self,
        dialog: _CleanupProgressDialog | None = None,
        progress_callback: Any | None = None,
    ) -> None:
        with self._artifact_lock:
            file_items = [Path(p) for p in sorted(self._generated_files)]
            dir_items = [Path(p) for p in sorted(self._generated_dirs)]

        # Parallel directory deletion using ThreadPoolExecutor
        max_workers = min(12, (os.cpu_count() or 1) * 2)
        
        def _delete_dir_tree(folder: Path) -> bool:
            if not folder.exists() or not folder.is_dir():
                return True
            try:
                shutil.rmtree(folder)
                return True
            except OSError:
                return False
        
        def _delete_file(path: Path) -> bool:
            try:
                path.unlink()
                return True
            except OSError:
                return False
        
        # Fast path: if we have registered dirs, delete them in parallel
        # This covers most intermediate files and folders
        if dir_items:
            with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                dir_futures = [executor.submit(_delete_dir_tree, d) for d in dir_items]
                # Wait for all directory deletions to complete
                futures.wait(dir_futures)
        
        # Delete remaining registered files in parallel
        existing_files = [p for p in file_items if p.exists() and p.is_file()]
        total = len(existing_files)
        
        if total > 0:
            removed = 0
            failed = 0
            update_interval = max(1, total // 10)  # Update ~10 times
            
            with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                file_futures = {executor.submit(_delete_file, p): (idx, p) for idx, p in enumerate(existing_files, 1)}
                
                # Process completed tasks
                completed_count = 0
                for future in futures.as_completed(file_futures):
                    idx, path = file_futures[future]
                    try:
                        success = future.result()
                        if success:
                            removed += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                    
                    completed_count += 1
                    # Throttle progress updates to reduce overhead
                    if completed_count % update_interval == 0 or completed_count == total:
                        try:
                            relative_path = str(path.relative_to(Path.cwd()))
                        except ValueError:
                            relative_path = str(path)
                        
                        if callable(progress_callback):
                            try:
                                progress_callback(
                                    self._t("cleanup_dialog_progress", done=completed_count, total=total),
                                    f"{self._t('cleanup_file_label')} {path.name}",
                                    f"{self._t('cleanup_relative_path_label')} {relative_path}",
                                    completed_count,
                                    total,
                                    removed,
                                    failed,
                                )
                            except TypeError:
                                # Fallback
                                progress_callback(
                                    self._t("cleanup_dialog_progress", done=completed_count, total=total),
                                    f"{self._t('cleanup_file_label')} {path.name}",
                                    f"{self._t('cleanup_relative_path_label')} {relative_path}",
                                    completed_count,
                                    total,
                                )
            
            # Final cleanup: remove empty parent directories
            parent_dirs: set[Path] = set()
            for path in existing_files:
                try:
                    parent_dirs.add(path.parent)
                except Exception:
                    pass
            
            # Delete empty dirs in reverse order (deepest first)
            for folder in sorted(parent_dirs, key=lambda p: len(str(p)), reverse=True):
                if folder.exists() and folder.is_dir():
                    try:
                        folder.rmdir()
                    except OSError:
                        pass
        
        # Final status callback
        if callable(progress_callback):
            try:
                progress_callback(
                    self._t("cleanup_dialog_done", removed=total, failed=0),
                    self._t("cleanup_file_none"),
                    "",
                    total or 1,
                    total or 1,
                    total,
                    0,
                )
            except TypeError:
                progress_callback(
                    self._t("cleanup_dialog_done", removed=total, failed=0),
                    self._t("cleanup_file_none"),
                    "",
                    total or 1,
                    total or 1,
                )

    @Slot()
    def reloadStyle(self) -> None:
        """Extract the CSS block and emit it so the page can hot-swap the style tag."""
        import re as _re
        html = _render_html()
        m = _re.search(r'<style[^>]*>(.*?)</style>', html, _re.DOTALL)
        if m:
            self.styleRefreshed.emit(m.group(1))

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        self._set_language(language)
        self.windowTitleChanged.emit(self._t("app_title"))

    @Slot(str)
    def setGame(self, game: str) -> None:
        self._set_game(game)
        self._ensure_game_key_scaffold()

    @Slot(str)
    def setTheme(self, theme: str) -> None:
        self._set_theme(theme)

    def can_present_exit_modal(self) -> bool:
        with self._close_state_lock:
            return self._ui_ready

    def can_close_window(self) -> bool:
        with self._close_state_lock:
            return self._allow_window_close

    @Slot()
    def uiReady(self) -> None:
        with self._close_state_lock:
            self._ui_ready = True

    @Slot()
    def requestWindowClose(self) -> None:
        if self._cleanup_worker and self._cleanup_worker.is_alive():
            return
        payload = {
            "title": self._t("exit_confirm_title"),
            "message": self._t("exit_confirm_message"),
            "yes": self._t("yes"),
            "no": self._t("no"),
        }
        self.exitPromptReady.emit(json.dumps(payload, ensure_ascii=False))

    def _emit_cleanup_progress(self, status_text: str, file_name: str, relative_path: str, done: int, total: int, removed: int = 0, failed: int = 0) -> None:
        payload = {
            "title": self._t("cleanup_dialog_title"),
            "status": status_text,
            "file": file_name,
            "relative_path": relative_path,
            "done": int(done),
            "total": int(max(1, total)),
            "removed": int(removed),
            "failed": int(failed),
        }
        self.cleanupProgressReady.emit(json.dumps(payload, ensure_ascii=False))
        QApplication.processEvents()

    def _run_cleanup_then_close(self) -> None:
        self.cleanup_generated_artifacts(progress_callback=self._emit_cleanup_progress)
        # Always delete the output folder when program closes
        output_dir = Path.cwd() / "output"
        if output_dir.exists():
            try:
                shutil.rmtree(output_dir)
            except OSError as exc:
                logger.debug("failed to delete output folder: %s", exc)
        with self._close_state_lock:
            self._allow_window_close = True
        self.hostCloseRequested.emit()

    @Slot()
    def confirmWindowClose(self) -> None:
        if self._cleanup_worker and self._cleanup_worker.is_alive():
            return
        self._cleanup_worker = threading.Thread(target=self._run_cleanup_then_close, daemon=True)
        self._cleanup_worker.start()

    @Slot()
    def beginWindowDrag(self) -> None:
        view = self._main_view()
        if view is None:
            return
        handle = view.windowHandle()
        if handle is None:
            return
        try:
            handle.startSystemMove()
        except Exception:
            return

    @Slot()
    def windowMinimize(self) -> None:
        view = self._main_view()
        if view is None:
            return
        view.showMinimized()

    @Slot()
    def windowClose(self) -> None:
        view = self._main_view()
        if view is None:
            return
        view.close()

    @Slot(str)
    def copyText(self, text: str) -> None:
        QApplication.clipboard().setText(str(text or ""))

    @Slot(str)
    def openExternalUrl(self, url: str) -> None:
        target = str(url or "").strip()
        if not target:
            return
        QDesktopServices.openUrl(QUrl(target))

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

    @Slot()
    def pickVersionsPatchBaseFile(self) -> None:
        picked_file, _ = QFileDialog.getOpenFileName(
            None,
            self._t("select_versions_patch_base_file"),
            "",
            "JSON (*.json);;All files (*.*)",
        )
        if not picked_file:
            return
        self.fieldChosen.emit("versions_patch_base", picked_file)

    def _load_json_payload_from_file(self, path: Path) -> tuple[Any | None, str | None]:
        if not path.exists() or not path.is_file():
            return None, self._t("versions_patch_base_missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return None, self._t("versions_patch_base_invalid_json", reason=exc)
        if self._load_versions_list_from_payload(payload) is None:
            return None, self._t("versions_patch_base_invalid_root")
        return payload, None

    @staticmethod
    def _clone_json_payload(payload: Any) -> Any:
        return json.loads(json.dumps(payload, ensure_ascii=False))

    def _collect_patch_row_records(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key_val = self._parse_sync_key(row.get("usm_decrypt_key"))
            if key_val is None:
                key_val = self._parse_sync_key(row.get("genshin_like_key"))
            if key_val is None:
                continue
            row_name = str(row.get("name") or "").strip()
            row_path = str(row.get("path") or "").strip()
            stored_name = ""
            if row_path:
                stored_name = Path(row_path).name.lower()
            if not stored_name and row_name:
                stored_name = row_name.lower()
            candidates: set[str] = set()
            if row_name:
                candidates.add(self._norm_video_name(row_name))
            if row_path:
                candidates.add(self._norm_video_name(Path(row_path).name))
                candidates.add(self._norm_video_name(Path(row_path).stem))
            candidates = {candidate for candidate in candidates if candidate}
            if not candidates:
                continue
            records.append(
                {
                    "key": key_val,
                    "stored_name": stored_name,
                    "candidates": candidates,
                }
            )
        return records

    def _build_versions_patch_preview(self, base_payload: Any, rows: list[dict[str, Any]], base_path: str) -> dict[str, Any] | None:
        with self._blk_result_lock:
            result = json.loads(json.dumps(self._last_blk_result or {}, ensure_ascii=False))
        versions_json = result.get("versions_json")
        if not versions_json or versions_json == "null":
            return None
        try:
            source_payload = json.loads(versions_json)
        except json.JSONDecodeError:
            return None

        source_list = self._load_versions_list_from_payload(source_payload) or []
        base_list = self._load_versions_list_from_payload(base_payload)
        if base_list is None:
            return None

        key_map, key_source, key_mode = self._build_template_key_map()
        row_records = self._collect_patch_row_records(rows)

        patched_root = self._clone_json_payload(base_payload)
        patched_list = patched_root.get("list") if isinstance(patched_root, dict) else patched_root
        if not isinstance(patched_list, list):
            return None

        def norm_version(value: Any) -> str:
            return str(value or "").strip()

        def collect_video_names(item: dict[str, Any], group: dict[str, Any] | None = None) -> set[str]:
            videos = item.get("videos") if group is None else group.get("videos")
            if not isinstance(videos, list):
                return set()
            names: set[str] = set()
            for video in videos:
                name = self._norm_video_name(str(video or ""))
                if name:
                    names.add(name)
            return names

        def append_unique_videos(target: list[Any], source: Any) -> int:
            if not isinstance(source, list):
                return 0
            existing = {self._norm_video_name(str(item or "")) for item in target if self._norm_video_name(str(item or ""))}
            added = 0
            for video in source:
                raw = str(video or "").strip()
                if not raw:
                    continue
                norm = self._norm_video_name(raw)
                if not norm or norm in existing:
                    continue
                target.append(raw)
                existing.add(norm)
                added += 1
            return added

        base_index: dict[str, dict[str, Any]] = {}
        for item in patched_list:
            if not isinstance(item, dict):
                continue
            version = norm_version(item.get("version"))
            if version and version not in base_index:
                base_index[version] = item

        added_versions = 0
        added_groups = 0
        added_videos = 0
        appended_row_keys = 0
        library_keys_filled = 0
        last_row_keys_filled = 0
        skipped_outside_last = 0
        unresolved_outside_last = 0
        used_increment_names: dict[str, int] = {}

        for source_item in source_list:
            if not isinstance(source_item, dict):
                continue
            version = norm_version(source_item.get("version"))
            if not version:
                continue

            target_item = base_index.get(version)
            if target_item is None:
                new_item = self._clone_json_payload(source_item)
                patched_list.append(new_item)
                base_index[version] = new_item
                added_versions += 1
                continue

            source_groups = source_item.get("videoGroups")
            target_groups = target_item.get("videoGroups")
            if isinstance(source_groups, list):
                if not isinstance(target_groups, list):
                    target_groups = []
                    target_item["videoGroups"] = target_groups
                target_group_index: dict[str, dict[str, Any]] = {}
                for group in target_groups:
                    if not isinstance(group, dict):
                        continue
                    group_version = norm_version(group.get("version"))
                    if group_version and group_version not in target_group_index:
                        target_group_index[group_version] = group
                for source_group in source_groups:
                    if not isinstance(source_group, dict):
                        continue
                    group_version = norm_version(source_group.get("version"))
                    target_group = target_group_index.get(group_version)
                    if target_group is None:
                        new_group = self._clone_json_payload(source_group)
                        target_groups.append(new_group)
                        if group_version:
                            target_group_index[group_version] = new_group
                        added_groups += 1
                    else:
                        target_videos = target_group.setdefault("videos", [])
                        added_videos += append_unique_videos(target_videos, source_group.get("videos"))
            else:
                target_videos = target_item.setdefault("videos", [])
                added_videos += append_unique_videos(target_videos, source_item.get("videos"))

        patched_last_item = patched_list[-1] if patched_list else None
        last_item_video_names: set[str] = set()
        if isinstance(patched_last_item, dict):
            groups = patched_last_item.get("videoGroups")
            if isinstance(groups, list):
                for group in groups:
                    if isinstance(group, dict):
                        last_item_video_names.update(collect_video_names(patched_last_item, group))
            else:
                last_item_video_names.update(collect_video_names(patched_last_item))

        def find_library_key(videos: set[str]) -> int | None:
            for video in videos:
                key_val = key_map.get(video)
                if key_val is not None:
                    return key_val
            return None

        def find_row_key(videos: set[str]) -> tuple[int | None, str | None]:
            for record in row_records:
                candidates = record.get("candidates") or set()
                if not isinstance(candidates, set):
                    continue
                if not candidates.intersection(videos):
                    continue
                return record.get("key"), record.get("stored_name")
            return None, None

        for index, item in enumerate(patched_list):
            if not isinstance(item, dict):
                continue
            is_last_item = index == len(patched_list) - 1
            groups = item.get("videoGroups")
            if isinstance(groups, list):
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    if self._parse_sync_key(group.get("key")) is not None:
                        continue
                    videos = collect_video_names(item, group)
                    if not videos:
                        continue
                    key_val = find_library_key(videos)
                    if key_val is not None:
                        group["key"] = key_val
                        library_keys_filled += 1
                        continue
                    if is_last_item:
                        key_val, stored_name = find_row_key(videos)
                        if key_val is not None:
                            group["key"] = key_val
                            last_row_keys_filled += 1
                            appended_row_keys += 1
                            if stored_name:
                                used_increment_names[str(stored_name).lower()] = key_val
                        continue
                    row_key_val, _ = find_row_key(videos)
                    if row_key_val is not None:
                        skipped_outside_last += 1
                        continue
                    unresolved_outside_last += 1
                continue

            if self._parse_sync_key(item.get("key")) is not None:
                continue
            videos = collect_video_names(item)
            if not videos:
                continue
            key_val = find_library_key(videos)
            if key_val is not None:
                item["key"] = key_val
                library_keys_filled += 1
                continue
            if is_last_item:
                key_val, stored_name = find_row_key(videos)
                if key_val is not None:
                    item["key"] = key_val
                    last_row_keys_filled += 1
                    appended_row_keys += 1
                    if stored_name:
                        used_increment_names[str(stored_name).lower()] = key_val
                continue
            row_key_val, _ = find_row_key(videos)
            if row_key_val is not None:
                skipped_outside_last += 1
                continue
            unresolved_outside_last += 1

        normalized_list: list[dict[str, Any]] = []
        for item in patched_list:
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
        patched_root["list"] = normalized_list

        patched_json = json.dumps(patched_root, ensure_ascii=False, indent=2)
        last_version = ""
        if isinstance(patched_last_item, dict):
            last_version = norm_version(patched_last_item.get("version"))

        patch_summary = self._t(
            "versions_patch_summary",
            versions=added_versions,
            groups=added_groups,
            videos=added_videos,
            library_keys=library_keys_filled,
            rows_keys=last_row_keys_filled,
            skipped_rows=skipped_outside_last,
            unresolved=unresolved_outside_last,
            last_version=last_version or "—",
        )
        warning_text = ""
        if unresolved_outside_last > 0:
            warning_text = self._t("versions_patch_unresolved_warning", count=unresolved_outside_last)
        elif appended_row_keys > 0 and len(used_increment_names) != appended_row_keys:
            warning_text = self._t("versions_patch_row_applied_warning", count=appended_row_keys)

        return {
            "summary": patch_summary,
            "warning": warning_text,
            "source_path": str(result.get("input") or ""),
            "base_path": str(base_path or ""),
            "patched_json": patched_json,
            "base_key_source": str(key_source or ""),
            "base_key_mode": str(key_mode or ""),
            "used_increment_names": used_increment_names,
            "stats": {
                "versions": added_versions,
                "groups": added_groups,
                "videos": added_videos,
                "library_keys": library_keys_filled,
                "rows_keys": last_row_keys_filled,
                "unresolved": unresolved_outside_last,
                "skipped_rows": skipped_outside_last,
                "last_version": last_version,
            },
        }

    def _default_versions_patch_save_path(self, source_path: str) -> str:
        source = Path(str(source_path or "").strip())
        stamp = dt.datetime.now().strftime("%Y%m%d")
        filename = f"versions_patched_gi_{stamp}.json"
        if source.is_file():
            return str(source.with_name(filename))
        if source.exists() and source.is_dir():
            return str(source / filename)
        return str(Path.cwd() / filename)

    def _save_versions_patch_to_path(self, content: str, source_path: str) -> str | None:
        default_path = self._default_versions_patch_save_path(source_path)
        target_path, _ = QFileDialog.getSaveFileName(
            None,
            self._t("select_versions_patch_save_file"),
            default_path,
            "JSON (*.json);;All files (*.*)",
        )
        if not target_path:
            return None
        try:
            Path(target_path).write_text(str(content or ""), encoding="utf-8")
        except OSError as exc:
            self.logMessage.emit(self._t("error_line", file="versions_patched_gi.json", reason=exc))
            self.uiToast.emit(self._t("versions_patch_save_failed", reason=exc))
            return None
        return target_path

    @Slot(str, str)
    def requestVersionsPatchPreview(self, base_path: str, rows_json: str) -> None:
        with self._blk_result_lock:
            has_blk = bool(self._last_blk_result)
        if not has_blk:
            self.uiToast.emit(self._t("versions_patch_no_blk_data"))
            self.logMessage.emit(self._t("versions_patch_no_blk_data"))
            return

        raw_base_path = str(base_path or "").strip()
        if not raw_base_path:
            self.uiToast.emit(self._t("versions_patch_base_required"))
            self.logMessage.emit(self._t("versions_patch_base_required"))
            return

        base_payload, error = self._load_json_payload_from_file(Path(raw_base_path))
        if error:
            self.uiToast.emit(error)
            self.logMessage.emit(error)
            return
        if base_payload is None:
            self.uiToast.emit(self._t("versions_patch_no_data"))
            return

        try:
            rows = json.loads(rows_json or "[]")
        except json.JSONDecodeError:
            rows = []

        preview = self._build_versions_patch_preview(base_payload, rows if isinstance(rows, list) else [], raw_base_path)
        if not preview:
            self.uiToast.emit(self._t("versions_patch_build_failed"))
            self.logMessage.emit(self._t("versions_patch_build_failed"))
            return

        preview["base_path"] = raw_base_path
        with self._patch_result_lock:
            self._last_patch_result = json.loads(json.dumps(preview, ensure_ascii=False))

        self.versionsPatchReady.emit(json.dumps(preview, ensure_ascii=False))
        self.logMessage.emit(
            self._t(
                "versions_patch_preview_ready_log",
                path=raw_base_path,
                last_version=str(preview.get("stats", {}).get("last_version") or "—"),
            )
        )

    @Slot()
    def saveVersionsPatch(self) -> None:
        with self._patch_result_lock:
            result = json.loads(json.dumps(self._last_patch_result or {}, ensure_ascii=False))
        if not result:
            self.uiToast.emit(self._t("versions_patch_no_preview"))
            return

        patched_json = str(result.get("patched_json") or "")
        if not patched_json.strip():
            self.uiToast.emit(self._t("versions_patch_no_preview"))
            return

        base_path = str(result.get("base_path") or "")
        saved_path = self._save_versions_patch_to_path(patched_json, base_path)
        if not saved_path:
            return

        used_increment_names = result.get("used_increment_names")
        if isinstance(used_increment_names, dict) and used_increment_names:
            template_only_keys: dict[str, int] = {}
            template_payload, template_source = self._load_versions_template_payload()
            if template_payload is not None:
                template_only_keys = self._extract_key_map_from_versions_payload(template_payload)

            target = self._resolve_increment_target_path()
            if target is not None:
                merged = self._read_usm_key_increment_map(target)
                added = 0
                skipped_by_template = 0
                for name, key_val in used_increment_names.items():
                    normalized = str(name or "").strip().lower()
                    parsed_key = self._parse_sync_key(key_val)
                    if not normalized or parsed_key is None or normalized in merged:
                        continue
                    if normalized in template_only_keys:
                        skipped_by_template += 1
                        continue
                    merged[normalized] = parsed_key
                    added += 1
                if added > 0:
                    try:
                        self._write_usm_key_increment_map(target, merged)
                        self.logMessage.emit(self._t("versions_patch_increment_updated", count=added, path=str(target)))
                    except OSError as exc:
                        self.logMessage.emit(self._t("versions_patch_increment_update_failed", reason=exc))
                if skipped_by_template > 0:
                    self.logMessage.emit(
                        self._t(
                            "versions_patch_template_existing_skipped",
                            count=skipped_by_template,
                            path=str(template_source or "-"),
                        )
                    )

        self.blkSaveCompleted.emit(
            json.dumps(
                {
                    "title": self._t("versions_patch_saved_title"),
                    "message": self._t("versions_patch_saved_message", path=saved_path),
                    "path": saved_path,
                    "can_reveal": self._can_reveal_saved_path(),
                },
                ensure_ascii=False,
            )
        )
        self.logMessage.emit(self._t("versions_patch_saved_log", path=saved_path))

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

    def _game_usm_data_dir(self) -> Path:
        return get_resource_path(f"assets/usm_data/{self._get_game()}")

    def _game_sync_template_path(self) -> Path:
        return self._game_usm_data_dir() / "usm_key_base.json"

    def _game_increment_path(self) -> Path:
        return self._game_usm_data_dir() / "usm_key_increment.json"

    def _sync_template_candidates(self) -> tuple[Path, ...]:
        game = self._get_game()
        candidates: list[Path] = [
            get_resource_path(f"assets/usm_data/{game}/usm_key_base.json"),
            self._game_sync_template_path(),
        ]
        if game == GENSHIN_GAME_ID:
            candidates.extend(LEGACY_SYNC_TEMPLATE_CANDIDATES)
        return tuple(candidates)

    def _increment_candidates(self) -> tuple[Path, ...]:
        game = self._get_game()
        candidates: list[Path] = [
            get_resource_path(f"assets/usm_data/{game}/usm_key_increment.json"),
            self._game_increment_path(),
        ]
        if game == GENSHIN_GAME_ID:
            candidates.extend(LEGACY_USM_KEY_INCREMENT_CANDIDATES)
        return tuple(candidates)

    @staticmethod
    def _copy_file_if_missing(target: Path, sources: tuple[Path, ...]) -> None:
        if target.exists():
            return
        for source in sources:
            if not source.exists() or not source.is_file():
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                return
            except OSError:
                continue

    def _ensure_game_key_scaffold(self) -> None:
        # Validate selected game's asset folder on game switch, without creating
        # user-data folders or copying files.
        game_dir = self._game_usm_data_dir()
        if not game_dir.exists() or not game_dir.is_dir():
            logger.warning("[USM DATA] missing asset dir: %s", game_dir)
            return
        for name in ("usm_key_base.json", "usm_key_increment.json"):
            path = game_dir / name
            if not path.exists():
                logger.warning("[USM DATA] missing asset file: %s", path)

    def _load_versions_template_payload(self) -> tuple[Any | None, str | None]:
        for template_path in self._sync_template_candidates():
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

    def _read_usm_key_increment_map(self, path: Path) -> dict[str, int]:
        if not path.exists() or not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        raw_map: dict[str, Any] = {}
        if isinstance(payload, dict):
            keys_payload = payload.get("keys")
            if isinstance(keys_payload, dict):
                raw_map = keys_payload
            else:
                # Backward-compatible plain mapping support.
                raw_map = payload

        parsed: dict[str, int] = {}
        for raw_name, raw_key in raw_map.items():
            norm = self._norm_video_name(str(raw_name or ""))
            key_val = self._parse_sync_key(raw_key)
            if norm and key_val is not None:
                parsed[norm] = key_val
        return parsed

    def _write_usm_key_increment_map(self, path: Path, mapping: dict[str, int]) -> None:
        payload = {
            "format": "usm_key_increment_v1",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "keys": {name: mapping[name] for name in sorted(mapping)},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_incremental_key_map(self) -> tuple[dict[str, int], str | None]:
        for candidate in self._increment_candidates():
            parsed = self._read_usm_key_increment_map(candidate)
            if parsed:
                return parsed, str(candidate)
        return {}, None

    def _load_base_key_map(self) -> tuple[dict[str, int], str | None]:
        for candidate in self._sync_template_candidates():
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            parsed = self._extract_key_map_from_versions_payload(payload)
            if parsed:
                return parsed, str(candidate)
        return {}, None

    def _resolve_increment_target_path(self) -> Path | None:
        for candidate in self._increment_candidates():
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
            if candidate.exists() and not candidate.is_file():
                continue
            return candidate
        return None

    def _collect_increment_names_from_report(self, report: dict[str, Any]) -> set[str]:
        names: set[str] = set()

        file_text = str(report.get("file") or "").strip()
        if file_text:
            file_path = Path(file_text)
            if file_path.suffix.lower() == ".usm":
                # Persist keys for original USM file names only.
                # Normalize to strip .usm suffix so keys are consistent with _read_usm_key_increment_map.
                names.add(self._norm_video_name(file_path.name))

        return names

    def _auto_append_usm_key_increment(self, report: dict[str, Any]) -> None:
        key_val = self._parse_sync_key(report.get("usm_decrypt_key"))
        if key_val is None:
            key_val = self._parse_sync_key(report.get("genshin_like_key"))
        if key_val is None:
            return

        names = self._collect_increment_names_from_report(report)
        if not names:
            return

        target = self._resolve_increment_target_path()
        if target is None:
            self.logMessage.emit("[WARN] [USM KEY] failed to resolve incremental file path")
            return

        merged = self._read_usm_key_increment_map(target)
        added = 0
        for name in names:
            if name in merged:
                continue
            merged[name] = key_val
            added += 1
        if added <= 0:
            return

        try:
            self._write_usm_key_increment_map(target, merged)
        except OSError as exc:
            self.logMessage.emit(f"[WARN] [USM KEY] failed to write increment file: {exc}")
            return

        self.logMessage.emit(
            f"[INFO] [USM KEY] increment updated: +{added} -> {target}"
        )

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

    def _extract_key_map_from_versions_payload(self, payload: Any) -> dict[str, int]:
        def add_videos(mapping: dict[str, int], videos: Any, key_val: int | None) -> None:
            if key_val is None or not isinstance(videos, list):
                return
            for video_name in videos:
                normalized = self._norm_video_name(str(video_name or ""))
                if normalized:
                    mapping[normalized] = key_val

        versions_list = self._load_versions_list_from_payload(payload)
        if not isinstance(versions_list, list):
            return {}

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
        return mapping

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
        raw_path = str(target_path or "").strip().strip('"').strip("'")
        path = Path(raw_path).expanduser()
        try:
            resolved_path = path.resolve()
        except OSError:
            resolved_path = path.absolute()

        if not resolved_path.exists():
            self.uiToast.emit(self._t("blk_versions_reveal_failed"))
            return
        try:
            if sys.platform.startswith("win"):
                if resolved_path.is_file():
                    try:
                        subprocess.Popen(["explorer.exe", "/select,", str(resolved_path)])
                    except OSError:
                        subprocess.Popen(["explorer.exe", str(resolved_path.parent)])
                else:
                    # Highlight folder in parent explorer view when possible.
                    if resolved_path.parent != resolved_path:
                        try:
                            subprocess.Popen(["explorer.exe", "/select,", str(resolved_path)])
                        except OSError:
                            subprocess.Popen(["explorer.exe", str(resolved_path)])
                    else:
                        # Drive roots (e.g. J:\) cannot be selected from a parent.
                        subprocess.Popen(["explorer.exe", str(resolved_path)])
                return
            if sys.platform == "darwin":
                # Prefer Finder reveal (selection). If it fails, open the target directly.
                try:
                    subprocess.Popen(["open", "-R", str(resolved_path)])
                except OSError:
                    subprocess.Popen(["open", str(resolved_path)])
                return
            if not self._linux_has_desktop_environment():
                return

            uri = resolved_path.as_uri()
            is_file = resolved_path.is_file()
            select_commands: list[list[str]] = []
            open_commands: list[list[str]] = []

            if is_file:
                parent = resolved_path.parent
                select_commands = [
                    ["nautilus", "--select", str(resolved_path)],
                    ["dolphin", "--select", str(resolved_path)],
                    ["thunar", "--select", str(resolved_path)],
                    ["nemo", str(resolved_path)],
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
                ]
                open_commands = [
                    ["xdg-open", str(parent)],
                ]
            else:
                # For directories, try selecting the directory in parent first, then open directly.
                parent = resolved_path.parent
                select_commands = [
                    ["nautilus", "--select", str(resolved_path)],
                    ["dolphin", "--select", str(resolved_path)],
                    ["thunar", "--select", str(resolved_path)],
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
                ]
                open_commands = [
                    ["xdg-open", str(resolved_path)],
                    ["xdg-open", str(parent)],
                ]

            for command in (*select_commands, *open_commands):
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

    def _build_template_key_map(self, fallback_from_blk: dict[str, int] = None) -> tuple[dict[str, int], str | None, str]:
        """
        Returns: (key_map, source_path, sync_mode)
        sync_mode: 'normal', 'increment-only', 'blk-fallback'
        """
        incremental_map, incremental_path = self._load_incremental_key_map()
        merged_map: dict[str, int] = dict(incremental_map)
        source_path: str | None = incremental_path
        sync_mode = "increment-only" if incremental_map else "normal"

        found_template = False
        self._ensure_game_key_scaffold()
        for template_path in self._sync_template_candidates():
            if not template_path.exists() or not template_path.is_file():
                continue
            try:
                decoded = json.loads(template_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            mapping = self._extract_key_map_from_versions_payload(decoded)

            if mapping:
                found_template = True
                for name, key_val in mapping.items():
                    merged_map.setdefault(name, key_val)
                if source_path is None:
                    source_path = str(template_path)
                else:
                    source_path = f"{source_path} + {template_path}"
                sync_mode = "normal" if incremental_map else "template-only"
                break

        # If no template and fallback_from_blk is provided, use it as base
        if not found_template and fallback_from_blk:
            for name, key_val in fallback_from_blk.items():
                merged_map.setdefault(name, key_val)
            source_path = "[BLK parse fallback]"
            sync_mode = "blk-fallback"

        if merged_map:
            return merged_map, source_path, sync_mode
        return {}, None, sync_mode


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

        # Build fallback_from_blk: parse keys from BLK rows if no template exists
        fallback_from_blk: dict[str, int] = {}
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
                    fallback_from_blk[c] = key_val

        name_to_key, template_path, sync_mode = self._build_template_key_map(fallback_from_blk=fallback_from_blk if fallback_from_blk else None)
        # User notification of sync mode
        if sync_mode == "blk-fallback":
            self.logMessage.emit(self._t("blk_sync_template_missing_blk_fallback"))
            self.uiToast.emit(self._t("blk_sync_template_missing_blk_fallback"))
        elif sync_mode == "increment-only":
            self.logMessage.emit(self._t("blk_sync_template_missing_increment_only"))
            self.uiToast.emit(self._t("blk_sync_template_missing_increment_only"))
        elif sync_mode == "template-only":
            self.logMessage.emit(self._t("blk_sync_template_loaded", path=template_path, count=len(name_to_key)))
        else:
            self.logMessage.emit(self._t("blk_sync_template_loaded", path=template_path, count=len(name_to_key)))

        # Apply BLK parse keys as highest priority (overrides template/increment)
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
                    name_to_key[c] = key_val

        if not name_to_key:
            self.logMessage.emit(self._t("blk_sync_no_usm_keys"))
            return

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
        self.logExportResultReady.emit(
            json.dumps(
                {
                    "title": self._t("log_export_result_title"),
                    "message": self._t("log_exported", path=target_path),
                    "path": target_path,
                    "can_reveal": self._can_reveal_saved_path(),
                },
                ensure_ascii=False,
            )
        )

    @Slot(str, str)
    def exportFfmpegLog(self, suggested_name: str, content: str) -> None:
        """Export FFMPEG log to file."""
        base_dir = ASSETS_DIR.parent.resolve()
        fallback_name = Path(str(suggested_name or "").strip() or "ffmpeg-log.txt").name
        default_path = str(base_dir / fallback_name)

        target_path, _ = QFileDialog.getSaveFileName(
            None,
            "Save FFMPEG Log",
            default_path,
            "Text (*.txt);;All files (*.*)",
        )
        if not target_path:
            target_path = default_path

        try:
            Path(target_path).write_text(str(content or ""), encoding="utf-8")
        except OSError as exc:
            logger.error(f"Failed to export FFMPEG log: {exc}")
            return

        logger.info(f"FFMPEG log exported: {target_path}")
        self._register_generated_file(Path(target_path))

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
    def exportGameKeys(self) -> None:
        self._ensure_game_key_scaffold()
        merged_map, source_path, _ = self._build_template_key_map()
        if not merged_map:
            msg = self._t("game_key_export_no_data")
            self.logMessage.emit(msg)
            self.indexExportResultReady.emit(
                json.dumps(
                    {
                        "title": self._t("game_key_export_title"),
                        "message": msg,
                        "path": "",
                        "can_reveal": False,
                    },
                    ensure_ascii=False,
                )
            )
            return

        game = self._get_game()
        payload = {
            "format": "usm_key_merged_v1",
            "game": game,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": source_path or "",
            "keys_count": len(merged_map),
            "keys": {name: merged_map[name] for name in sorted(merged_map)},
        }

        default_path = str(Path.cwd() / f"{game}_usm_key_merged.json")
        target_path, _ = QFileDialog.getSaveFileName(
            None,
            self._t("select_game_key_save_file"),
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
            msg = self._t("game_key_export_failed", reason=exc)
            self.logMessage.emit(msg)
            self.indexExportResultReady.emit(
                json.dumps(
                    {
                        "title": self._t("game_key_export_title"),
                        "message": msg,
                        "path": "",
                        "can_reveal": False,
                    },
                    ensure_ascii=False,
                )
            )
            return

        msg = self._t("game_key_exported", game=game, path=target_path, count=len(merged_map))
        self.logMessage.emit(msg)
        self.indexExportResultReady.emit(
            json.dumps(
                {
                    "title": self._t("game_key_export_title"),
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
        reveal_target: Path | None = None
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
                if reveal_target is None:
                    reveal_target = out
            except OSError:
                fail_count += 1

        message = self._t("export_all_reports_done", ok=ok_count, failed=fail_count)
        self.logMessage.emit(message)
        self.indexExportResultReady.emit(
            json.dumps(
                {
                    "title": self._t("export_all_reports_title"),
                    "message": message,
                    "path": str(reveal_target if reveal_target is not None else target_root),
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

    @Slot()
    def pickVideoExportSubtitleFiles(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            None,
            self._t("select_video_export_subtitle_files"),
            "",
            "Subtitle Files (*.srt *.ass *.txt);;All files (*.*)",
        )
        if files:
            self.fieldChosen.emit("video_export_subtitles", json.dumps(files, ensure_ascii=False))

    @Slot()
    def probeVideoExportHardware(self) -> None:
        ffmpeg = find_ffmpeg(None)
        profile = detect_video_export_hardware(ffmpeg)
        payload = {
            "available": bool(profile.get("available")),
            "vendor": str(profile.get("vendor") or ""),
            "vendor_label": str(profile.get("vendor_label") or ""),
            "encoder": str(profile.get("encoder") or ""),
            "encoder_label": str(profile.get("encoder_label") or ""),
            "gpu_model": str(profile.get("gpu_model") or ""),
            "reason": str(profile.get("reason") or ""),
            "ffmpeg": str(ffmpeg or ""),
        }
        self.videoExportHardwareReady.emit(json.dumps(payload, ensure_ascii=False))

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
        self._register_generated_dir(output_dir)

        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        subtitle_source = str(payload.get("subtitle_source") or "off").strip().lower()
        if subtitle_source not in {"off", "local", "online"}:
            subtitle_source = "off"
        subtitle_languages_raw = payload.get("subtitle_languages") if isinstance(payload.get("subtitle_languages"), list) else []
        subtitle_languages: list[str] = []
        for item in subtitle_languages_raw:
            code = str(item or "").strip().upper()
            if code in SUBTITLE_LANG_CODES and code not in subtitle_languages:
                subtitle_languages.append(code)
        subtitle_local_files = [
            str(item).strip()
            for item in (payload.get("subtitle_local_files") if isinstance(payload.get("subtitle_local_files"), list) else [])
            if str(item).strip()
        ]
        subtitle_convert_mode = str(payload.get("subtitle_convert_mode") or "original").strip().lower()
        if subtitle_convert_mode not in {"original", "ass"}:
            subtitle_convert_mode = "original"
        export_mode = str(payload.get("export_mode") or "container").strip().lower()
        if export_mode not in {"container", "burn", "hybrid"}:
            export_mode = "container"
        default_subtitle_lang = str(payload.get("default_subtitle_lang") or "").strip().upper()
        if default_subtitle_lang and default_subtitle_lang not in SUBTITLE_LANG_CODES:
            default_subtitle_lang = ""
        try:
            hybrid_hardsub_limit = int(payload.get("hybrid_hardsub_limit") or 2)
        except (TypeError, ValueError):
            hybrid_hardsub_limit = 2
        hybrid_hardsub_limit = max(0, min(8, hybrid_hardsub_limit))
        selected_channels_raw = payload.get("selected_channels") if isinstance(payload.get("selected_channels"), list) else None
        selected_channels: list[int] | None = None
        if selected_channels_raw is not None:
            selected_channels = []
            for item in selected_channels_raw:
                try:
                    ch = int(item)
                except (TypeError, ValueError):
                    continue
                if 0 <= ch <= 3 and ch not in selected_channels:
                    selected_channels.append(ch)
        use_hwaccel = bool(payload.get("use_hwaccel"))
        hw_encoder = str(payload.get("hw_encoder") or "").strip().lower()
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
            target=self._run_video_export_safe,
            args=(
                fmt,
                output_dir,
                candidates,
                selected_channels,
                subtitle_source,
                subtitle_languages,
                subtitle_local_files,
                subtitle_convert_mode,
                export_mode,
                default_subtitle_lang,
                hybrid_hardsub_limit,
                ffmpeg,
                use_hwaccel,
                hw_encoder,
            ),
            daemon=True,
        )
        self._video_export_worker.start()

    @Slot(str)
    def checkVideoExportOnlineSubtitleCoverage(self, payload_json: str) -> None:
        if self._video_export_subtitle_probe_worker and self._video_export_subtitle_probe_worker.is_alive():
            return
        self._video_export_subtitle_probe_worker = threading.Thread(
            target=self._run_video_export_subtitle_coverage_probe,
            args=(payload_json,),
            daemon=True,
        )
        self._video_export_subtitle_probe_worker.start()

    def _run_video_export_subtitle_coverage_probe(self, payload_json: str) -> None:
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}

        subtitle_source = str(payload.get("subtitle_source") or "off").strip().lower()
        subtitle_languages_raw = payload.get("subtitle_languages") if isinstance(payload.get("subtitle_languages"), list) else []
        subtitle_languages: list[str] = []
        for item in subtitle_languages_raw:
            code = str(item or "").strip().upper()
            if code in SUBTITLE_LANG_CODES and code not in subtitle_languages:
                subtitle_languages.append(code)
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []

        total = len(candidates)
        self.videoExportSubtitleCoverageProgress.emit(
            json.dumps(
                {
                    "done": 0,
                    "total": total,
                },
                ensure_ascii=False,
            )
        )

        missing_names: list[str] = []
        if subtitle_source == "online" and subtitle_languages and candidates:
            with tempfile.TemporaryDirectory(prefix="usmdiviner_subtitle_probe_") as tmp:
                cache_dir = Path(tmp)
                for idx, item in enumerate(candidates):
                    name = str((item or {}).get("name") or "")
                    ivf_text = str((item or {}).get("ivf") or "")
                    stem = Path(name).stem or Path(ivf_text).stem
                    if not stem:
                        continue
                    hit = False
                    for lang in subtitle_languages:
                        if self._download_online_subtitle(cache_dir, stem, lang):
                            hit = True
                            break
                    if not hit:
                        missing_names.append(Path(name).name or stem)
                    
                    self.videoExportSubtitleCoverageProgress.emit(
                        json.dumps(
                            {
                                "done": idx + 1,
                                "total": total,
                            },
                            ensure_ascii=False,
                        )
                    )

        self.videoExportSubtitleCoverageReady.emit(
            json.dumps(
                {
                    "missing_names": missing_names,
                    "total": len(candidates),
                },
                ensure_ascii=False,
            )
        )

    def _emit_ffmpeg_log(self, log_text: str) -> None:
        """Emit FFMPEG log lines to the frontend."""
        if not log_text or not str(log_text).strip():
            return
        for line in str(log_text).splitlines():
            if line.strip():
                self.ffmpegLogMessage.emit(line)

    def _run_video_export_safe(
        self,
        fmt: str,
        output_dir: Path,
        candidates: list[Any],
        selected_channels: list[int] | None,
        subtitle_source: str,
        subtitle_languages: list[str],
        subtitle_local_files: list[str],
        subtitle_convert_mode: str,
        export_mode: str,
        default_subtitle_lang: str,
        hybrid_hardsub_limit: int,
        ffmpeg: str,
        use_hwaccel: bool,
        hw_encoder: str,
    ) -> None:
        try:
            self._run_video_export(
                fmt,
                output_dir,
                candidates,
                selected_channels,
                subtitle_source,
                subtitle_languages,
                subtitle_local_files,
                subtitle_convert_mode,
                export_mode,
                default_subtitle_lang,
                hybrid_hardsub_limit,
                ffmpeg,
                use_hwaccel,
                hw_encoder,
            )
        except Exception as exc:
            logger.exception("video export worker crashed")
            self.videoExportFinished.emit(
                json.dumps(
                    {
                        "title": self._t("video_export_result_title"),
                        "message": f"{self._t('video_export_failed')}\n{exc}",
                        "path": str(output_dir),
                        "can_reveal": self._can_reveal_saved_path(),
                    },
                    ensure_ascii=False,
                )
            )

    @staticmethod
    def _split_local_subtitle_stem(stem: str) -> tuple[str, str]:
        for sep in (".", "_", "-"):
            if sep not in stem:
                continue
            prefix, suffix = stem.rsplit(sep, 1)
            code = suffix.upper()
            if prefix and code in SUBTITLE_LANG_CODES:
                return prefix, code
        return stem, ""

    def _collect_local_subtitles_for_video(
        self,
        subtitle_local_files: list[str],
        video_stem: str,
        subtitle_languages: list[str],
    ) -> list[tuple[Path, str]]:
        requested = set(subtitle_languages)
        resolved: list[tuple[Path, str]] = []
        neutral: list[Path] = []

        for text in subtitle_local_files:
            path = Path(text)
            if not path.exists() or not path.is_file():
                continue
            if path.suffix.lower() not in {".srt", ".ass", ".txt"}:
                continue
            key, lang = self._split_local_subtitle_stem(path.stem)
            if key != video_stem:
                continue
            if lang:
                if lang in requested:
                    resolved.append((path, lang))
            else:
                neutral.append(path)

        if neutral:
            # Keep neutral subtitles as a fallback when filename has no language suffix.
            resolved.extend((path, "") for path in neutral)

        dedup: list[tuple[Path, str]] = []
        seen: set[str] = set()
        for path, lang in resolved:
            key = f"{path.resolve()}::{lang}"
            if key in seen:
                continue
            seen.add(key)
            dedup.append((path, lang))
        return dedup

    def _download_online_subtitle(self, cache_dir: Path, video_stem: str, lang: str) -> Path | None:
        # Subtitle repository typically uses `<usm_name>_<lang>.srt` naming.
        # Keep legacy fallback (`<usm_name>.srt`) for compatibility.
        preferred_name = f"{video_stem}_{lang}"
        candidates = [preferred_name, video_stem]
        target = cache_dir / f"{video_stem}.{lang}.srt"
        if target.exists() and target.stat().st_size > 0:
            return target

        data: bytes | None = None
        for raw_name in candidates:
            safe_name = urllib.parse.quote(raw_name, safe="")
            url = ONLINE_SUBTITLE_RAW_URL.format(lang=lang, name=safe_name)
            req = urllib.request.Request(url, headers={"User-Agent": "UsmDiviner/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    if getattr(resp, "status", 200) >= 400:
                        continue
                    payload = resp.read()
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
            if payload:
                data = payload
                break

        if not data:
            return None

        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(data)
        except OSError:
            return None
        return target

    def _probe_online_subtitle_availability(
        self,
        cache_dir: Path,
        candidates: list[Any],
        subtitle_languages: list[str],
    ) -> bool:
        if not candidates or not subtitle_languages:
            return False
        probe_langs = subtitle_languages[:2]
        probe_candidates = candidates[:3]
        for item in probe_candidates:
            name = str((item or {}).get("name") or "")
            ivf_text = str((item or {}).get("ivf") or "")
            stem = Path(name).stem or Path(ivf_text).stem
            if not stem:
                continue
            for lang in probe_langs:
                if self._download_online_subtitle(cache_dir, stem, lang):
                    return True
        return False

    def _run_video_export(
        self,
        fmt: str,
        output_dir: Path,
        candidates: list[Any],
        selected_channels: list[int] | None,
        subtitle_source: str,
        subtitle_languages: list[str],
        subtitle_local_files: list[str],
        subtitle_convert_mode: str,
        export_mode: str,
        default_subtitle_lang: str,
        hybrid_hardsub_limit: int,
        ffmpeg: str,
        use_hwaccel: bool,
        hw_encoder: str,
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, len(candidates))
        done = 0
        success = 0
        failed = 0
        subtitle_miss_count = 0
        subtitle_included_count = 0
        reveal_target: Path | None = None
        effective_export_mode = export_mode
        requested_hw = bool(use_hwaccel)
        active_video_encoder = str(hw_encoder or "").strip().lower() if requested_hw else ""

        if requested_hw and not active_video_encoder:
            detected = detect_video_export_hardware(ffmpeg)
            if detected.get("available"):
                active_video_encoder = str(detected.get("encoder") or "").strip().lower()

        if requested_hw and not active_video_encoder:
            self.logMessage.emit(self._t("video_export_hw_cpu_fallback_log"))
        elif active_video_encoder:
            self.logMessage.emit(
                self._t("video_export_hw_enabled_log", encoder=active_video_encoder)
            )
        else:
            self.logMessage.emit(self._t("video_export_hw_disabled_log"))

        with tempfile.TemporaryDirectory(prefix="usmdiviner_subtitles_") as tmp:
            subtitle_cache_dir = Path(tmp)
            effective_subtitle_source = subtitle_source

            def _emit_video_progress(row_id: str, progress: int, status_text: str, done_units: float) -> None:
                safe_progress = int(max(0, min(100, progress)))
                self.videoExportProgress.emit(
                    json.dumps(
                        {
                            "id": row_id,
                            "progress": safe_progress,
                            "status": status_text,
                            "done": max(0.0, min(float(total), float(done_units))),
                            "total": total,
                        },
                        ensure_ascii=False,
                    )
                )

            for item in candidates:
                row_id = str((item or {}).get("id") or "")
                name = str((item or {}).get("name") or row_id or "video")
                ivf = Path(str((item or {}).get("ivf") or ""))
                stem = Path(name).stem if name else ivf.stem
                row_export_mode = effective_export_mode
                audio_tracks = [track for track in ((item or {}).get("audio_tracks") or []) if isinstance(track, dict)]
                wavs = [Path(str(p)) for p in ((item or {}).get("wavs") or []) if str(p or "").strip()]
                audio_inputs: list[Path] = []
                if selected_channels is None:
                    if audio_tracks:
                        for track in audio_tracks:
                            wav_text = str(track.get("wav") or "").strip()
                            if wav_text:
                                audio_inputs.append(Path(wav_text))
                    else:
                        audio_inputs = wavs
                else:
                    selected_set = set(selected_channels)
                    if audio_tracks:
                        for track in audio_tracks:
                            try:
                                ch = int(track.get("ch"))
                            except (TypeError, ValueError):
                                continue
                            if ch not in selected_set:
                                continue
                            wav_text = str(track.get("wav") or "").strip()
                            if wav_text:
                                audio_inputs.append(Path(wav_text))

                subtitle_inputs: list[tuple[Path, str]] = []
                if effective_subtitle_source == "local":
                    subtitle_inputs = self._collect_local_subtitles_for_video(
                        subtitle_local_files,
                        stem,
                        subtitle_languages,
                    )
                elif effective_subtitle_source == "online" and subtitle_languages:
                    for lang in subtitle_languages:
                        sub_path = self._download_online_subtitle(subtitle_cache_dir, stem, lang)
                        if sub_path:
                            subtitle_inputs.append((sub_path, lang))

                subtitle_hit = bool(subtitle_inputs)

                if effective_subtitle_source in {"local", "online"}:
                    if subtitle_inputs:
                        subtitle_included_count += len(subtitle_inputs)
                    else:
                        subtitle_miss_count += 1

                _emit_video_progress(
                    row_id,
                    8,
                    self._t("video_export_status_running"),
                    done + 0.08,
                )
                _emit_video_progress(
                    row_id,
                    24,
                    self._t("video_export_status_running"),
                    done + 0.24,
                )

                ok = False
                row_encoder_names: set[str] = set()
                row_encoder_kinds: set[str] = set()
                if not ivf.exists() or not ivf.is_file():
                    self.logMessage.emit(
                        f"[ERROR] [{name}] export input video missing: {ivf} (cwd={Path.cwd()})"
                    )
                if ivf.exists() and ivf.is_file():
                    ext = ".mkv" if fmt == "mkv" else ".mp4"
                    _emit_video_progress(
                        row_id,
                        42,
                        self._t("video_export_status_running"),
                        done + 0.42,
                    )

                    def _mark_output(path: Path, success_flag: bool) -> None:
                        nonlocal reveal_target
                        if success_flag and path.exists() and path.is_file():
                            self._register_generated_file(path)
                            if reveal_target is None:
                                reveal_target = path

                    def _export_one(path: Path, subs: list[tuple[Path, str]], mode: str) -> tuple[bool, str]:
                        preferred_encoder = active_video_encoder or None
                        self.logMessage.emit(
                            "[INFO] [FFMPEG] "
                            f"[{name}] mode={mode} fmt={fmt} subtitles={len(subs)} audio_tracks={len(audio_inputs)} "
                            f"subtitle_convert={subtitle_convert_mode} encoder={(preferred_encoder or 'libx264')} out={path}"
                        )

                        def _run_with_encoder(encoder: str | None) -> tuple[bool, str]:
                            if fmt == "mkv":
                                if mode == "container":
                                    return mux_to_mkv_soft(
                                        ffmpeg,
                                        ivf,
                                        audio_inputs,
                                        subs,
                                        path,
                                        default_sub_lang=default_subtitle_lang,
                                        convert_subtitles_to_ass=subtitle_convert_mode == "ass",
                                        video_encoder=encoder,
                                    )
                                return mux_to_mkv(
                                    ffmpeg,
                                    ivf,
                                    audio_inputs,
                                    subs,
                                    path,
                                    convert_subtitles_to_ass=subtitle_convert_mode == "ass",
                                    video_encoder=encoder,
                                )
                            if mode == "container":
                                return transcode_ivf_to_mp4_soft(
                                    ffmpeg,
                                    ivf,
                                    audio_inputs,
                                    subs,
                                    path,
                                    default_sub_lang=default_subtitle_lang,
                                    convert_subtitles_to_ass=subtitle_convert_mode == "ass",
                                    video_encoder=encoder,
                                )
                            return transcode_ivf_to_mp4(
                                ffmpeg,
                                ivf,
                                audio_inputs,
                                subs,
                                path,
                                convert_subtitles_to_ass=subtitle_convert_mode == "ass",
                                video_encoder=encoder,
                            )

                        done_ok, detail = _run_with_encoder(preferred_encoder)
                        actual_encoder = preferred_encoder or "libx264"
                        actual_mode = "HW" if preferred_encoder else "CPU"
                        if not done_ok and preferred_encoder:
                            self.logMessage.emit(
                                self._t("video_export_hw_fallback_log", encoder=preferred_encoder)
                            )
                            done_ok, detail = _run_with_encoder(None)
                            if done_ok:
                                actual_encoder = "libx264"
                                actual_mode = "CPU"

                        if done_ok:
                            self.logMessage.emit(
                                f"[INFO] [FFMPEG] [{name}] actual encoder used: {actual_encoder} ({actual_mode})"
                            )
                        else:
                            self.logMessage.emit(
                                f"[WARN] [FFMPEG] [{name}] export failed after encoder attempt: {actual_encoder} ({actual_mode})"
                            )
                        row_encoder_names.add(actual_encoder)
                        row_encoder_kinds.add(actual_mode)
                        return done_ok, detail

                    # Flag-driven export flow:
                    # - subtitle_hit=True  -> run with subtitle inputs
                    # - subtitle_hit=False -> run no-subtitle command path
                    # Burn mode without subtitles is downgraded to container for reliability.
                    if row_export_mode == "burn" and not subtitle_hit:
                        row_export_mode = "container"
                        self.logMessage.emit(f"[INFO] [{name}] burn mode downgraded to container (subtitle miss)")

                    if row_export_mode == "container":
                        out = output_dir / f"{stem}{ext}"
                        self.logMessage.emit(f"[INFO] [{name}] export start -> {out}")
                        _emit_video_progress(
                            row_id,
                            68,
                            self._t("video_export_status_running"),
                            done + 0.68,
                        )
                        ok, detail = _export_one(out, subtitle_inputs, "container")
                        if detail:
                            self._emit_ffmpeg_log(detail)
                        if (not ok) and subtitle_inputs:
                            self.logMessage.emit(f"[WARN] [{name}] container export with subtitles failed, retrying without subtitles: {detail}")
                            ok, detail = _export_one(out, [], "container")
                            if detail:
                                self._emit_ffmpeg_log(detail)
                        _mark_output(out, ok)
                        if not ok and detail:
                            self.logMessage.emit(f"[ERROR] [{name}] export failed: {detail}")
                    elif row_export_mode == "burn":
                        _emit_video_progress(
                            row_id,
                            68,
                            self._t("video_export_status_running"),
                            done + 0.68,
                        )
                        if subtitle_inputs:
                            ok = True
                            for sub_path, lang in subtitle_inputs:
                                suffix = f"_{lang}" if lang else "_SUB"
                                out = output_dir / f"{stem}{suffix}{ext}"
                                self.logMessage.emit(f"[INFO] [{name}] burn export start ({lang or 'SUB'}) -> {out}")
                                one_ok, detail = _export_one(out, [(sub_path, lang)], "burn")
                                if detail:
                                    self._emit_ffmpeg_log(detail)
                                _mark_output(out, one_ok)
                                if not one_ok and detail:
                                    self.logMessage.emit(f"[ERROR] [{name}] burn export failed ({lang or 'SUB'}): {detail}")
                                ok = ok and one_ok
                        else:
                            out = output_dir / f"{stem}{ext}"
                            self.logMessage.emit(f"[INFO] [{name}] export start (no subtitles) -> {out}")
                            ok, detail = _export_one(out, [], "container")
                            if detail:
                                self._emit_ffmpeg_log(detail)
                            _mark_output(out, ok)
                            if not ok and detail:
                                self.logMessage.emit(f"[ERROR] [{name}] export failed: {detail}")
                    else:
                        base_out = output_dir / f"{stem}{ext}"
                        self.logMessage.emit(f"[INFO] [{name}] hybrid container start -> {base_out}")
                        _emit_video_progress(
                            row_id,
                            68,
                            self._t("video_export_status_running"),
                            done + 0.68,
                        )
                        ok_container, detail = _export_one(base_out, subtitle_inputs, "container")
                        if detail:
                            self._emit_ffmpeg_log(detail)
                        if (not ok_container) and subtitle_inputs:
                            self.logMessage.emit(f"[WARN] [{name}] hybrid container leg with subtitles failed, retrying without subtitles: {detail}")
                            ok_container, detail = _export_one(base_out, [], "container")
                            if detail:
                                self._emit_ffmpeg_log(detail)
                        _mark_output(base_out, ok_container)
                        if not ok_container and detail:
                            self.logMessage.emit(f"[ERROR] [{name}] hybrid container leg failed: {detail}")
                        ok = ok_container
                        if subtitle_inputs and hybrid_hardsub_limit > 0:
                            picked = subtitle_inputs[:hybrid_hardsub_limit]
                            for sub_path, lang in picked:
                                suffix = f"_{lang}" if lang else "_SUB"
                                out = output_dir / f"{stem}{suffix}{ext}"
                                self.logMessage.emit(f"[INFO] [{name}] hybrid burn start ({lang or 'SUB'}) -> {out}")
                                one_ok, detail = _export_one(out, [(sub_path, lang)], "burn")
                                if detail:
                                    self._emit_ffmpeg_log(detail)
                                _mark_output(out, one_ok)
                                if not one_ok and detail:
                                    self.logMessage.emit(f"[ERROR] [{name}] hybrid burn leg failed ({lang or 'SUB'}): {detail}")
                                ok = ok and one_ok

                _emit_video_progress(
                    row_id,
                    92,
                    self._t("video_export_status_running"),
                    done + 0.92,
                )

                subtitle_strategy = f"{effective_subtitle_source}/{('hit' if subtitle_hit else 'miss')}"
                subtitle_convert = subtitle_convert_mode if effective_subtitle_source in {"local", "online"} else "n/a"
                encoder_text = ",".join(sorted(row_encoder_names)) if row_encoder_names else "n/a"
                encoder_kind_text = "+".join(sorted(row_encoder_kinds)) if row_encoder_kinds else "n/a"
                self.logMessage.emit(
                    f"[INFO] [EXPORT SUMMARY] [{name}] "
                    f"result={('ok' if ok else 'failed')} "
                    f"mode={row_export_mode} "
                    f"subtitle={subtitle_strategy} "
                    f"subtitle_convert={subtitle_convert} "
                    f"encoder={encoder_text} ({encoder_kind_text})"
                )

                done += 1
                if ok:
                    success += 1
                else:
                    failed += 1
                _emit_video_progress(
                    row_id,
                    100,
                    self._t("video_export_status_done") if ok else self._t("video_export_status_failed"),
                    done,
                )

        subtitle_note = ""
        if effective_subtitle_source in {"local", "online"}:
            subtitle_note = self._t(
                "video_export_subtitle_summary",
                added=subtitle_included_count,
                missing=subtitle_miss_count,
            )
        # Keep summary aligned with user-selected export mode.
        mode_note = self._t("video_export_mode_summary", mode=self._t(f"video_export_mode_{export_mode}"))

        self.videoExportFinished.emit(
            json.dumps(
                {
                    "title": self._t("video_export_result_title"),
                    "message": (
                        f"{self._t('video_export_done', ok=success, failed=failed)}\n{mode_note}\n{subtitle_note}".strip()
                    ),
                    "path": str(reveal_target if reveal_target is not None else output_dir),
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
        supported_video_exts = {".ivf", ".264", ".h264", ".m1v"}
        all_have_supported_video = True

        def _as_existing_abs_path(text: str) -> Path | None:
            raw = Path(str(text or "").strip())
            if not str(raw):
                return None
            try:
                resolved = raw.resolve()
            except OSError:
                resolved = raw.absolute()
            return resolved if resolved.exists() else None

        for report in ok_reports:
            video = report.get("video") or {}
            video_text = str(video.get("path") or "").strip()
            video_path = _as_existing_abs_path(video_text) if video_text else None
            if (
                not video_path
                or not video_path.exists()
                or video_path.suffix.lower() not in supported_video_exts
            ):
                all_have_supported_video = False
                continue
            audio = report.get("audio") or {}
            audio_tracks: list[dict[str, Any]] = []
            wavs: list[str] = []
            if isinstance(audio, dict):
                for ch_text, item in sorted(
                    audio.items(),
                    key=lambda pair: (0, int(pair[0])) if str(pair[0]).isdigit() else (1, str(pair[0])),
                ):
                    info = item if isinstance(item, dict) else {}
                    decode = info.get("decode") if isinstance(info.get("decode"), dict) else {}
                    wav_text = str(decode.get("wav") or "").strip()
                    wav_path = _as_existing_abs_path(wav_text) if wav_text else None
                    if wav_path:
                        wavs.append(str(wav_path))
                        try:
                            ch = int(ch_text)
                        except (TypeError, ValueError):
                            continue
                        audio_tracks.append(
                            {
                                "ch": ch,
                                "wav": str(wav_path),
                                "label": self._t(f"video_export_audio_ch{ch}"),
                            }
                        )

            file_name = Path(str(report.get("file") or video_path.name)).name
            row_id = str(report.get("id") or "")
            candidates.append(
                {
                    "id": row_id,
                    "name": file_name,
                    "file": str(report.get("file") or ""),
                    "ivf": str(video_path),
                    "video_ext": video_path.suffix.lower().lstrip("."),
                    "audio_tracks": audio_tracks,
                    "wavs": wavs,
                }
            )

        if not all_have_supported_video or len(candidates) != len(ok_reports):
            return [], ""
        # Output folder is required input from user; do not auto-fill a default path.
        return candidates, ""

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
        self._set_game(str(payload.get("game") or self._get_game()))

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

        auto_file_keys: dict[str, int] = {}

        # Resolve existing per-file key from base/increment maps before deciding crack path.
        if manual_key is None and input_files:
            base_map, base_path = self._load_base_key_map()
            increment_map, _ = self._load_incremental_key_map()
            miss_count = 0

            for usm_path in input_files:
                stem = self._norm_video_name(usm_path.stem)
                mapped_key = None
                source = ""

                if stem in base_map:
                    mapped_key = base_map[stem]
                    source = "base"
                    self.logMessage.emit(
                        self._t("process_key_from_base", file=usm_path.name, usm_key=f"{mapped_key:016X}", path=base_path)
                    )
                elif stem in increment_map:
                    mapped_key = increment_map[stem]
                    source = "increment"
                    self.logMessage.emit(
                        self._t("process_key_from_increment", file=usm_path.name, usm_key=f"{mapped_key:016X}")
                    )

                if mapped_key is None:
                    miss_count += 1
                    continue

                # Base/increment stores genshin-like key; convert back to full key for decryption masks.
                full_key = full_key_from_genshin_like_key(mapped_key, usm_path.name)
                try:
                    path_key = str(usm_path.resolve())
                except OSError:
                    path_key = str(usm_path)
                auto_file_keys[path_key] = full_key
                self.logMessage.emit(
                    f"[INFO] auto key converted for {usm_path.name}: mapped={mapped_key:016X} -> full={full_key:016X}"
                )
                logger.debug(
                    "[AUTO KEY] %s source=%s mapped=%016X full=%016X",
                    usm_path.name,
                    source,
                    mapped_key,
                    full_key,
                )

            if miss_count > 0:
                self.logMessage.emit(
                    self._t("process_key_from_maps_miss", count=miss_count)
                )

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
            "auto_file_keys": auto_file_keys,
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
        key_stage = "process_stage_key_apply" if opt.manual_key is not None else "process_stage_key_recovery"
        plan: list[tuple[int, str]] = [
            (4, "process_stage_prepare"),
            (18, key_stage),
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
            auto_file_keys: dict[str, int] = config.get("auto_file_keys") or {}
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
            self._register_generated_dir(Path(opt.output_dir))
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
                        try:
                            path_key = str(path.resolve())
                        except OSError:
                            path_key = str(path)
                        effective_manual_key = opt.manual_key
                        if effective_manual_key is None:
                            effective_manual_key = auto_file_keys.get(path_key)
                        run_opt = dataclasses.replace(opt, manual_key=effective_manual_key)

                        row_id = path_to_id.get(str(path), "")
                        stage_plan = self._stage_plan(run_opt)
                        announced_stage_logs: set[str] = set()
                        if row_id:
                            emit_row_progress(row_id, path.name, 6)
                        self.logMessage.emit(self._t("process_start_line", file=path.name))
                        fut = executor.submit(
                            process_one,
                            str(path),
                            run_opt,
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
                        if report.get("status") == "ok" and not report.get("extract_only"):
                            self._auto_append_usm_key_increment(report)
                        self._register_report_artifacts(report)
                        reports.append(report)
                        if report["id"]:
                            emit_row_progress(report["id"], path.name, 100)
                        self.fileRowUpdate.emit(json.dumps(report, ensure_ascii=False))
                        self.logMessage.emit(_summary_line(self._get_language(), report))
                        for detail in _report_detail_lines(report):
                            self.logMessage.emit(detail)
            else:
                for path in files:
                    try:
                        path_key = str(path.resolve())
                    except OSError:
                        path_key = str(path)
                    effective_manual_key = opt.manual_key
                    if effective_manual_key is None:
                        effective_manual_key = auto_file_keys.get(path_key)
                    run_opt = dataclasses.replace(opt, manual_key=effective_manual_key)

                    row_id = path_to_id.get(str(path), "")
                    self.logMessage.emit(self._t("process_start_line", file=path.name))
                    stage_plan = self._stage_plan(run_opt)
                    announced_stage_logs: set[str] = set()
                    if row_id:
                        emit_row_progress(row_id, path.name, 8)
                    try:
                        report = process_one(
                            str(path),
                            run_opt,
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
                    if report.get("status") == "ok" and not report.get("extract_only"):
                        self._auto_append_usm_key_increment(report)
                    self._register_report_artifacts(report)
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
    global QT_DIALOG_FONT_FAMILY
    QT_DIALOG_FONT_FAMILY = _load_qt_dialog_font(app)
    bridge = WebBridge()
    view = _MainView(bridge)
    bridge.bind_view(view)

    if APP_ICON_PATH.exists():
        app_icon = QIcon(str(APP_ICON_PATH))
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
            view.setWindowIcon(app_icon)

    view.setWindowTitle(_t(DEFAULT_LANGUAGE, "app_title"))
    view.setFixedSize(1180, 850)
    view._apply_rounded_mask()

    channel = QWebChannel(view.page())
    channel.registerObject("bridge", bridge)
    view.page().setWebChannel(channel)

    bridge.windowTitleChanged.connect(view.setWindowTitle)
    bridge.hostCloseRequested.connect(view.close)

    html = _render_html()
    # Use local workspace root as base URL so relative asset paths can be loaded.
    base_dir = ASSETS_DIR.parent.resolve()
    base_url = QUrl.fromLocalFile(str(base_dir) + os.sep)
    view.setHtml(html, base_url)
    view.show()
    return app.exec()

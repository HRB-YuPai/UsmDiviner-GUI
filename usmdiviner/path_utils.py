"""
Path utilities for development and packaged modes.
Supports both direct Python execution and PyInstaller one-file builds.
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path


def get_base_path() -> Path:
    """
    Get the program base path (project root or packaged runtime directory).
    
    - PyInstaller one-file: returns sys._MEIPASS
    - Development: returns parent directory of usmdiviner package
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller one-file packaged
        return Path(sys._MEIPASS)
    else:
        # Development: usmdiviner/__file__ -> usmdiviner/ -> project root
        return Path(__file__).resolve().parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    Get path to bundled resources (fonts, icons, i18n files, etc.).
    Relative to project root or packaged runtime root.
    
    Example:
        get_resource_path("assets/icon/wolf_favicon.png")
        → Path("J:/External_Environment/UsmDiviner/assets/icon/wolf_favicon.png")
    """
    relative_path = relative_path.lstrip('./' + os.sep)
    return get_base_path() / relative_path


def get_user_data_path() -> Path:
    """
    Get user data directory for writable files (incremental keys, reports, cache, etc.).
    
    Priority:
    1. Current working directory (if writable)
    2. Platform-specific app data directory
    3. User home directory
    
    - Windows: %LOCALAPPDATA%/UsmDiviner
    - macOS: ~/Library/Application Support/UsmDiviner
    - Linux: ~/.config/UsmDiviner
    """
    # Priority 1: Current working directory (if writable)
    cwd = Path.cwd()
    try:
        if cwd.exists() and os.access(cwd, os.W_OK):
            return cwd
    except OSError:
        pass
    
    # Priority 2: Platform-specific app data directory
    if sys.platform == "win32":
        appdata = Path.home() / "AppData" / "Local" / "UsmDiviner"
    elif sys.platform == "darwin":
        appdata = Path.home() / "Library" / "Application Support" / "UsmDiviner"
    else:  # Linux and others
        appdata = Path.home() / ".config" / "UsmDiviner"
    
    try:
        appdata.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    
    return appdata


def get_external_tool_path(tool_name: str) -> str | None:
    """
    Find external tool (ffmpeg, vgmstream-cli, etc.).
    
    Priority:
    1. Environment variable: <TOOL_NAME>_PATH (e.g., FFMPEG_PATH, VGMSTREAM_PATH)
    2. Project-internal tool directory: project_root/vgmstream/ or project_root/<tool>/
    3. System PATH
    4. None (not found)
    
    Example:
        get_external_tool_path("ffmpeg")
        → might return "C:/Program Files/ffmpeg/bin/ffmpeg.exe"
    """
    # 1. Check environment variable
    env_var_name = f"{tool_name.upper().replace('-', '_')}_PATH"
    if env_path := os.environ.get(env_var_name):
        path = Path(env_path)
        if path.exists():
            return str(path)
    
    # 2. Check project-internal tool directory
    # For vgmstream-cli, check both "vgmstream" and "vgmstream-cli"
    tool_variants = [tool_name, tool_name.replace('-', '_')]
    base = get_base_path()
    
    for variant in tool_variants:
        tool_dir = base / variant
        if tool_dir.exists() and tool_dir.is_dir():
            # Look for executable inside or the directory itself (when bundled)
            if sys.platform.startswith("win"):
                exe = tool_dir / f"{tool_name}.exe"
                if exe.exists():
                    return str(exe)
            else:
                exe = tool_dir / tool_name
                if exe.exists():
                    return str(exe)
            # Return directory if tool binary not found (might be called via PATH)
            return str(tool_dir)
    
    # 3. Check system PATH
    if found := shutil.which(tool_name):
        return found
    
    return None


def get_font_path(font_name: str = "zh-cn.ttf") -> Path | None:
    """
    Get path to bundled font file.
    """
    font_path = get_resource_path(f"fonts/{font_name}")
    return font_path if font_path.exists() else None


def get_translations_dir() -> Path:
    """
    Get path to i18n translation files directory.
    """
    return get_resource_path("i18n")

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for cross-platform UsmDiviner packaging
# Usage:
#   cd /path/to/UsmDiviner
#   pyinstaller -y build_scripts/UsmDiviner.spec

import sys
import os
from pathlib import Path

block_cipher = None

# Get project root: pyinstaller is run from project root
# so os.getcwd() should be the project directory
PROJECT_ROOT = Path(os.getcwd())

# Verify we're in the right directory
if not (PROJECT_ROOT / "usmdiviner").exists():
    raise RuntimeError(
        f"Error: usmdiviner/ not found in {PROJECT_ROOT}. "
        "Please run pyinstaller from project root."
    )

# Define entry point (GUI)
ENTRY_POINT = str(PROJECT_ROOT / "usmdiviner" / "__main__.py")

# Build data files list - only include directories that exist
datas = []
if (PROJECT_ROOT / "assets").exists():
    datas.append((str(PROJECT_ROOT / "assets"), "assets"))
if (PROJECT_ROOT / "vgmstream").exists():
    datas.append((str(PROJECT_ROOT / "vgmstream"), "vgmstream"))

a = Analysis(
    [ENTRY_POINT],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "PyQt5.QtWidgets",
        "PyQt5.QtWebKit",
        "PyQt5.QtWebKitWidgets",
        "PyQt5.QtWebChannel",
        "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtNetwork",
        "requests",
        "urllib3",
        "chardet",
        "idna",
        "certifi",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="UsmDiviner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window for GUI app
    icon=(str(PROJECT_ROOT / "assets" / "icon" / "wolf_favicon.png") if (PROJECT_ROOT / "assets" / "icon" / "wolf_favicon.png").exists() else None),
)

# Optional: For macOS, create .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="UsmDiviner.app",
        icon=(str(PROJECT_ROOT / "assets" / "icon" / "wolf_favicon.png") if (PROJECT_ROOT / "assets" / "icon" / "wolf_favicon.png").exists() else None),
        bundle_identifier="com.usmdiviner.app",
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": "True",
        },
    )

# UsmDiviner GUI

[简体中文](README.zh-CN.md) | [**English**](README.en.md)

### 1. Overview
UsmDiviner GUI is a desktop toolchain for **CRI USM** workflows, focused on:
- USM key recovery
- Stream extraction
- MP4/MKV export and transcoding
- BLK `versions.json` parsing/editing/key-sync/save

The GUI-first workflow includes multi-language UI and dual themes.

### 2. Supported MHY Titles
The GUI is designed to cover **MHY secondary titles that use USM-based assets**, including:
- Genshin Impact
- Honkai: Star Rail
- Zenless Zone Zero

Note: actual success depends on the target assets, naming consistency, and local toolchain availability.

### 3. Feature Highlights
- Single-file and batch-folder USM processing
- File list preview with per-file progress
- Auto/manual USM key flow
- BLK parse toggle and versions viewer
- Video export modes: container / burn / hybrid
- Online/local subtitle strategies
- Log export, index export, and full-report export
- Exit confirmation with generated-file cleanup

### 4. Requirements
- Python 3.10+
- PySide6
- ffmpeg and vgmstream-cli (recommended in project-local tool folders)

### 5. Detailed GUI Workflow
1. Launch GUI and set language/theme.
2. Choose analysis mode (file or folder).
3. Pick input assets and optional output path.
4. Configure options in "More Features".
5. Run processing and monitor per-file status/key fields.
6. Optionally export video (format/audio/subtitle/mode).
7. Optionally run BLK workflow (parse -> sync -> save).
8. Export logs/reports/index as needed.
9. On app close, confirm cleanup behavior.

### 6. How Key Sync Grows Over Time
`versions.json` sync is incremental and explainable:
- Template map (if available)
- Current USM result map
- Current results override template values
- Missing keys are filled by normalized name matching
- Test-only entries are ignored
- Save-time confirmation warns when unresolved gaps remain

Practical guarantee model:
- The app maximizes completeness, but cannot mathematically guarantee 100% key coverage for every upstream dataset.
- It provides traceable, user-confirmed, low-risk synchronization with explicit unresolved visibility.

### 7. Acknowledgements
- FFmpeg: https://github.com/FFmpeg/FFmpeg
- FFmpeg Builds used here: https://github.com/BtbN/FFmpeg-Builds
- USM key parsing algorithm: https://github.com/Senkin219/UsmDiviner
- Genshin subtitle repository: https://gitlab.com/Dimbreath/AnimeGameData/-/tree/master/Subtitle
- vgmstream: https://github.com/vgmstream/vgmstream
- AnimeStudio inspiration: https://github.com/Escartem/AnimeStudio

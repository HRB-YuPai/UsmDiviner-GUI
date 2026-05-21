# UsmDiviner

**English** | [简体中文](README.zh-CN.md)

UsmDiviner is a CRI USM processing tool with both CLI and GUI support. It can automatically recover USM keys, extract video/audio streams, and optionally use vgmstream/ffmpeg for decoding and muxing.

## Features

- Automatic USM key recovery with no pre-supplied key required
- Single-file and recursive batch processing for `.usm`
- Report export, audio decoding, and MKV muxing support
- GUI included, with BLK `versions.json` viewer

## Requirements

- Python 3.10+
- `PySide6` is required for GUI

```bash
pip install -r requirements.txt
# or
pip install PySide6
```

## Quick Start

```bash
# clone
git clone https://github.com/Senkin219/UsmDiviner.git
cd UsmDiviner

# CLI: single file
python UsmDiviner.py input.usm

# CLI: folder recursive
python UsmDiviner.py ./USM

# CLI: specify output
python UsmDiviner.py input.usm -o output

# CLI: mux MKV with custom ffmpeg
python UsmDiviner.py input.usm --mux-mkv --ffmpeg "D:/tools/ffmpeg/bin/ffmpeg.exe"

# GUI
python UsmDivinerGUI.py
```

## External Tool Paths

### vgmstream

vgmstream is used to decode HCA/ADX to WAV. Place binaries in the structure below and UsmDiviner will auto-detect by platform.

```text
UsmDiviner/
└─ assets/
   └─ tools/
      └─ vgmstream/
         ├─ windows_x64/
         │  └─ vgmstream-cli.exe
         ├─ linux_x64/
         │  └─ vgmstream-cli
         ├─ linux_arm64/
         │  └─ vgmstream-cli
         └─ macos/
            └─ vgmstream-cli
```

### ffmpeg

ffmpeg is used for `--mux-mkv`. The project-local binary is preferred before falling back to system PATH.

Shared builds are recommended:
- Windows: keep `ffmpeg.exe` with its `.dll` files in the same folder
- Linux/macOS: use `bin/ffmpeg` plus a sibling `lib/` directory; UsmDiviner will configure runtime library lookup automatically

```text
UsmDiviner/
└─ assets/
   └─ tools/
      └─ ffmpeg/
         ├─ windows_x64/
         │  ├─ ffmpeg.exe
         │  └─ *.dll
         ├─ linux_x64/
         │  ├─ bin/
         │  │  └─ ffmpeg
         │  └─ lib/
         │     └─ *.so*
         ├─ linux_arm64/
         │  ├─ bin/
         │  │  └─ ffmpeg
         │  └─ lib/
         │     └─ *.so*
         └─ macos/
            ├─ ffmpeg
            └─ *.dylib
```

Also supported:

```text
windows_x64/bin/ffmpeg.exe + *.dll
linux_x64/bin/ffmpeg + *.so*
linux_arm64/bin/ffmpeg + *.so*
macos/bin/ffmpeg + *.dylib
```

## CLI Options

| Option | Description |
|---|---|
| `input` | USM file or folder |
| `-o, --output` | Output directory, default `output` |
| `--no-parallel` | Disable multiprocessing |
| `--report` | Generate `<USM file name>_Report.json` |
| `--report-dir PATH` | Custom report directory |
| `--report-lang {en,zh-CN,zh-TW}` | Report directory language |
| `--fast` | Use only the first 50 MB of video for key recovery |
| `--key KEY` | Manually provide a 16-hex key |
| `--extract-only` | Extract only, no stream decryption |
| `--vgmstream PATH` | Custom vgmstream-cli path |
| `--keep-intermediate-audio` | Keep `.hca/.adx/.hcakey` files |
| `--no-adx-audiomask` | Disable ADX AudioMask |
| `--mux-mkv` | Mux MKV via ffmpeg |
| `--ffmpeg PATH` | Custom ffmpeg path |

## Output

Default output directory:

```text
output/<usm_name>/
```

When `--mux-mkv` succeeds, `.mkv` is written to `output/` root.

## Test Status

The project has been tested against a large set of Genshin Impact USM assets. Most files are processed correctly; a small number may fail key recovery when the video stream is too small.

## Credits

- USM chunk parsing and mask/key handling were implemented with reference to [GI-cutscenes](https://github.com/ToaHartor/GI-cutscenes).
- The blind key recovery algorithm was provided by Gemini.
- Audio decoding is delegated to [vgmstream](https://vgmstream.org/). This repository does not include vgmstream binaries.

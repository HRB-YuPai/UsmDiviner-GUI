# UsmDiviner

## 简介 | Overview

**中文**
UsmDiviner 是一个用于处理 CRI USM 文件的工具，支持命令行与 GUI。它可以自动尝试恢复 USM 密钥、提取视频与音频，并在可用时自动调用 vgmstream/ffmpeg 完成解码和封装。

**English**
UsmDiviner is a CRI USM processing tool with both CLI and GUI support. It can automatically recover USM keys, extract video/audio streams, and optionally use vgmstream/ffmpeg for decoding and muxing.

## 功能 | Features

**中文**
- 自动尝试恢复 USM 密钥（无需预置密钥）
- 支持单文件或目录递归批量处理 `.usm`
- 支持报告导出、音频解码、MKV 封装
- 提供 GUI，包括 BLK `versions.json` 查看

**English**
- Automatic USM key recovery (no pre-supplied key required)
- Single-file and recursive batch processing for `.usm`
- Report export, audio decoding, and MKV muxing support
- GUI included, with BLK `versions.json` viewer

## 环境要求 | Requirements

**中文**
- Python 3.10+
- GUI 需要 `PySide6`

**English**
- Python 3.10+
- `PySide6` is required for GUI

```bash
pip install -r requirements.txt
# or
pip install PySide6
```

## 快速开始 | Quick Start

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

## 工具依赖路径 | External Tool Paths

### vgmstream

**中文**
vgmstream 用于将 HCA/ADX 解码为 WAV。推荐将可执行文件放到以下结构，程序会按平台自动匹配。

**English**
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

**中文**
ffmpeg 用于 `--mux-mkv`。程序优先使用项目内置 ffmpeg，其次才回退到系统 PATH。

**English**
ffmpeg is used for `--mux-mkv`. The project-local binary is preferred before falling back to system PATH.

```text
UsmDiviner/
└─ assets/
   └─ tools/
      └─ ffmpeg/
         ├─ windows_x64/
         │  └─ ffmpeg.exe
         ├─ linux_x64/
         │  └─ ffmpeg
         ├─ linux_arm64/
         │  └─ ffmpeg
         └─ macos/
            └─ ffmpeg
```

## 命令行参数 | CLI Options

| 选项 / Option | 说明 / Description |
|---|---|
| `input` | USM 文件或目录 / USM file or folder |
| `-o, --output` | 输出目录（默认 `output`）/ Output directory (default `output`) |
| `--no-parallel` | 关闭多进程 / Disable multiprocessing |
| `--report` | 生成 `<USM文件名>_Report.json` / Generate per-file report |
| `--report-dir PATH` | 自定义报告目录 / Custom report directory |
| `--report-lang {en,zh-CN,zh-TW}` | 报告目录语言 / Report directory language |
| `--fast` | 仅用前 50 MB 视频尝试恢复密钥 / Use first 50 MB for fast key recovery |
| `--key KEY` | 手动指定 16 位十六进制密钥 / Manually provide 16-hex key |
| `--extract-only` | 仅提取，不解密流 / Extract only, no stream decryption |
| `--vgmstream PATH` | 手动指定 vgmstream-cli / Custom vgmstream-cli path |
| `--keep-intermediate-audio` | 保留 `.hca/.adx/.hcakey` / Keep intermediate audio files |
| `--no-adx-audiomask` | 不应用 ADX AudioMask / Disable ADX AudioMask |
| `--mux-mkv` | 使用 ffmpeg 封装 MKV / Mux MKV via ffmpeg |
| `--ffmpeg PATH` | 手动指定 ffmpeg / Custom ffmpeg path |

## 输出说明 | Output

**中文**
默认输出目录：

```text
output/<usm_name>/
```

若启用 `--mux-mkv` 且封装成功，`.mkv` 会输出到 `output/` 根目录。

**English**
Default output directory:

```text
output/<usm_name>/
```

When `--mux-mkv` succeeds, `.mkv` is written to `output/` root.

## 测试情况 | Test Status

**中文**
项目已针对大量《原神》USM 资源进行验证，绝大多数可正常处理；极少数样本因视频流过小导致密钥恢复不稳定。

**English**
The project has been tested against a large set of Genshin Impact USM assets. Most files are processed correctly; a small number may fail key recovery when the video stream is too small.

## 致谢 | Credits

- USM chunk parsing and mask/key handling were implemented with reference to [GI-cutscenes](https://github.com/ToaHartor/GI-cutscenes).
- The blind key recovery algorithm was provided by Gemini.
- Audio decoding is delegated to [vgmstream](https://vgmstream.org/). This repository does not include vgmstream binaries.

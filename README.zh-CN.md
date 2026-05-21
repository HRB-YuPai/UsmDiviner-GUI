# UsmDiviner

[English](README.md) | **简体中文**

UsmDiviner 是一个用于处理 CRI USM 文件的工具，支持命令行与 GUI。它可以自动尝试恢复 USM 密钥、提取视频与音频，并在可用时自动调用 vgmstream/ffmpeg 完成解码和封装。

## 功能

- 自动尝试恢复 USM 密钥，无需预置密钥
- 支持单文件或目录递归批量处理 `.usm`
- 支持报告导出、音频解码、MKV 封装
- 提供 GUI，包括 BLK `versions.json` 查看

## 环境要求

- Python 3.10+
- GUI 需要 `PySide6`

```bash
pip install -r requirements.txt
# or
pip install PySide6
```

## 快速开始

```bash
# clone
git clone https://github.com/Senkin219/UsmDiviner.git
cd UsmDiviner

# CLI: 单文件
python UsmDiviner.py input.usm

# CLI: 目录递归
python UsmDiviner.py ./USM

# CLI: 指定输出
python UsmDiviner.py input.usm -o output

# CLI: 使用自定义 ffmpeg 封装 MKV
python UsmDiviner.py input.usm --mux-mkv --ffmpeg "D:/tools/ffmpeg/bin/ffmpeg.exe"

# GUI
python UsmDivinerGUI.py
```

## 外部工具路径

### vgmstream

vgmstream 用于将 HCA/ADX 解码为 WAV。推荐将可执行文件放到以下结构，程序会按平台自动匹配。

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

ffmpeg 用于 `--mux-mkv`。程序优先使用项目内置 ffmpeg，其次才回退到系统 PATH。

建议使用 shared build（动态库版本）：
- Windows: `ffmpeg.exe` 与其 `.dll` 放在同一目录
- Linux/macOS: 使用 `bin/ffmpeg` + 相邻 `lib/` 目录，程序会自动补运行库搜索路径

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

同样支持以下布局：

```text
windows_x64/bin/ffmpeg.exe + *.dll
linux_x64/bin/ffmpeg + *.so*
linux_arm64/bin/ffmpeg + *.so*
macos/bin/ffmpeg + *.dylib
```

## 命令行参数

| 选项 | 说明 |
|---|---|
| `input` | USM 文件或目录 |
| `-o, --output` | 输出目录，默认 `output` |
| `--no-parallel` | 关闭多进程 |
| `--report` | 生成 `<USM文件名>_Report.json` |
| `--report-dir PATH` | 自定义报告目录 |
| `--report-lang {en,zh-CN,zh-TW}` | 报告目录语言 |
| `--fast` | 仅用前 50 MB 视频尝试恢复密钥 |
| `--key KEY` | 手动指定 16 位十六进制密钥 |
| `--extract-only` | 仅提取，不解密流 |
| `--vgmstream PATH` | 手动指定 vgmstream-cli 路径 |
| `--keep-intermediate-audio` | 保留 `.hca/.adx/.hcakey` |
| `--no-adx-audiomask` | 不应用 ADX AudioMask |
| `--mux-mkv` | 使用 ffmpeg 封装 MKV |
| `--ffmpeg PATH` | 手动指定 ffmpeg 路径 |

## 输出说明

默认输出目录：

```text
output/<usm_name>/
```

若启用 `--mux-mkv` 且封装成功，`.mkv` 会输出到 `output/` 根目录。

## 测试情况

项目已针对大量《原神》USM 资源进行验证，绝大多数可正常处理；极少数样本因视频流过小导致密钥恢复不稳定。

## 致谢

- USM chunk parsing and mask/key handling were implemented with reference to [GI-cutscenes](https://github.com/ToaHartor/GI-cutscenes).
- The blind key recovery algorithm was provided by Gemini.
- Audio decoding is delegated to [vgmstream](https://vgmstream.org/). This repository does not include vgmstream binaries.

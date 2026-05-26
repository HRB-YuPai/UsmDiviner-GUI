# UsmDiviner GUI

[简体中文](#简体中文) | [English](#english)

---

## 简体中文

### 1. 项目简介
UsmDiviner GUI 是一个面向 **CRI USM** 资源的桌面化处理工具，聚焦于：
- USM 密钥恢复（含自动恢复与手动输入）
- 音视频流提取
- MP4/MKV 导出与转码
- BLK `versions.json` 解析、编辑、同步与保存

该工具以图形界面为核心工作流，支持双主题（暗色/亮色）与多语言界面（简中/繁中/英文）。

项目作者：中文 `@独行者` / English `@LoneOne-HRB`

项目仓库：https://github.com/HRB-YuPai/UsmDiviner-GUI

### 2. 支持游戏（MHY 二游）
当前 GUI 设计目标是覆盖 **MHY 全部二游中采用 USM 资产链路的场景**，包括但不限于：
- 原神（Genshin Impact）
- 崩坏：星穹铁道（Honkai: Star Rail）
- 绝区零（Zenless Zone Zero）

说明：
- 实际可处理性取决于目标资源是否确实为 USM、是否包含可恢复的关键结构，以及本地工具链（ffmpeg/vgmstream）可用性。
- 若游戏资源结构后续发生变更，建议优先通过日志与报告确认具体失败阶段。

### 3. 核心功能
- 单文件/批量文件夹 USM 处理
- 自动预览文件清单与逐文件进度
- 自动/手动 USM key 处理
- BLK 解析开关（专用于相关版本文件）
- `versions.json` 搜索、编辑、保存、同步 Key
- `versions.json` 补丁工作流：基准 JSON 对比、自动预览、复制/保存补丁结果
- 视频导出：
  - 容器模式（多音轨 + 多字幕）
  - 硬字幕模式（多文件）
  - 混合模式（容器 + 硬字幕）
- 在线字幕与本地字幕混合流程
- 日志导出、索引导出、全报告导出
- 退出前自动清理本次生成文件（可确认）

### 4. 环境与依赖
- Python 3.10+
- GUI 依赖：`PySide6`
- 媒体处理依赖（推荐放在项目内置目录）：
  - `ffmpeg`
  - `vgmstream-cli`

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

### 5. GUI 详细操作步骤（推荐按此顺序）
#### 步骤 1：启动程序
1. 进入项目根目录。
2. 运行 GUI 入口（例如项目既有 GUI 启动方式）。
3. 首次进入后，先在右上角选择：
	- 语言
	- 主题

#### 步骤 2：选择分析模式
1. 在“分析模式”区域选择：
	- 文件选择（单文件/多文件）
	- 文件夹选择（批量递归）
2. 点击“选择/浏览”载入输入资源。

#### 步骤 3：配置输出与功能项
1. 输出目录可留空（使用默认输出目录）。
2. 打开“更多功能”按需启用：
	- 关闭多进程
	- 快速密钥恢复
	- 仅提取
	- 保留中间音频
	- 关闭 ADX AudioMask
	- 自定义 USM 密钥

#### 步骤 4：执行处理
1. 点击“开始”。
2. 观察文件列表中每个文件的状态、进度、Key 信息。
3. 处理完成后可导出：
	- 全部报告
	- 索引 JSON

#### 步骤 5：视频导出（可选）
1. 点击“导出视频”。
2. 选择格式（MP4/MKV）与输出目录。
3. 选择音轨。
4. 配置字幕来源：
	- 关闭
	- 本地文件
	- 在线字幕
5. 选择导出策略（容器/硬字幕/混合），点击开始导出。
6. 在导出列表中查看每个文件进度与总体进度。

#### 步骤 6：BLK / versions 工作流（可选）
1. 打开“解析 blk”开关。
2. 选择 BLK 文件（如 `26236578.blk` 相关场景）。
3. 打开 versions 查看器，执行搜索/编辑。
4. 点击“同步 Key”从当前 USM 处理结果回填缺失键值。
5. 点击“保存”，在确认后输出 `versions.json`。
6. 保存成功弹窗中可直接点击“前往保存路径”。

#### 步骤 6.1：`versions.json` 补丁流程（可选）
1. 打开“versions.json 补丁”开关。
2. 加载 BLK 后，在主界面点击“基准 JSON”选择 base `versions.json`。
3. 点击“补丁”会直接自动生成并显示新的 `versions.json` 预览。
4. 在补丁弹窗中可直接复制或保存；灰字会显示完整基准文件路径。

#### 步骤 7：日志与收尾
1. 在“日志”窗口可复制/导出日志。
2. 导出日志成功后会显示保存结果弹窗，并可“前往保存路径”。
3. 关闭程序时会出现确认弹窗，可选择是否清理本次生成文件。

### 6. Key 同步机制说明（为什么是“逐步补齐”）
本工具的 `versions.json` 同步不是“盲写覆盖”，而是 **模板映射 + 当前结果增量回填**：

1. 先尝试加载参考模板（若存在）。
2. 基于已处理 USM 行（文件名、路径名、提取结果）建立 `name -> key` 映射。
3. 用“当前 USM 映射”覆盖模板同名项（保证最新结果优先）。
4. 对 `versions.json` 中缺失 key 的条目按视频名匹配回填。
5. 对明显 test-only 项执行忽略策略，避免污染正式结果。
6. 保存前做缺失分析：
	- 若缺失较多，会给出强提示确认。
	- 若只剩最新版本少量缺失，也会提示你确认风险。

重要说明：
- **无法在理论上保证任何输入都“100%完美全 key”**，因为上游数据可能不完整、命名可能变化、目标版本可能尚无可匹配 USM。
- 本工具做的是“可追踪、可解释、可回填、可确认”的最稳妥流程，尽可能把缺失降到最低并显式暴露未解决项。

### 7. 功能特点（工程向）
- 多语言 + 双主题统一 UI 风格
- 自绘窗口与统一弹窗体系
- 大文件/多文件进度可视化
- 导出成功结果有路径回溯能力（含一键打开）
- BLK 解析与 USM 流程联动，便于持续补齐 key

### 8. 常见建议
- 在线字幕命中不稳定时优先使用本地字幕。
- 导出失败先看日志，再看 ffmpeg 编码器可用性。
- 对关键版本更新，建议先处理一批代表性 USM，再执行 BLK 同步与保存。

### 9. 致谢
本项目使用或参考了以下开源项目：

1. FFmpeg
	- 官方源码：https://github.com/FFmpeg/FFmpeg
	- 项目使用构建：https://github.com/BtbN/FFmpeg-Builds

2. USM 秘钥解析算法
	- https://github.com/Senkin219/UsmDiviner

3. 原神 USM 字幕资源库
	- https://gitlab.com/Dimbreath/AnimeGameData/-/tree/master/Subtitle

4. Wav 流解析工具 vgmstream
	- https://github.com/vgmstream/vgmstream

5. blk 解析核心算法灵感来源 AnimeStudio
	- https://github.com/Escartem/AnimeStudio

---

## English

# UsmDiviner GUI

[绠€浣撲腑鏂嘳(README.md) | [**English**](README.en.md)

### 1. Overview
UsmDiviner GUI is a desktop toolchain for **CRI USM** workflows, focused on:
- USM key recovery
- Stream extraction
- MP4/MKV export and transcoding
- BLK `versions.json` parsing/editing/key-sync/save

The GUI-first workflow includes multi-language UI and dual themes.

Author: Chinese `@独行者` / English `@LoneOne-HRB`

Repository: https://github.com/HRB-YuPai/UsmDiviner-GUI

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
- `versions.json` patch flow: base JSON comparison, auto-preview, and patched result copy/save
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
8. Optionally run `versions.json` patch workflow (pick base JSON -> open Patch -> auto-preview -> copy/save).
9. Export logs/reports/index as needed.
10. On app close, confirm cleanup behavior.

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

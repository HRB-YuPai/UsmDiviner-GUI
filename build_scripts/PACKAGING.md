# UsmDiviner 打包指南

## 快速开始

### Windows 打包

```bash
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 打包（生成单文件 .exe）
python build_scripts/build.py

# 或带清理
python build_scripts/build.py --clean

# 输出：dist/windows_x64/UsmDiviner.exe
```

### macOS 打包

```bash
# 1. 安装依赖
pip install pyinstaller

# 2. 打包（生成 .app 或单文件二进制）
python build_scripts/build.py

# 输出：dist/macos/UsmDiviner（或 dist/macos/UsmDiviner.app）
```

### Linux 打包

```bash
# 1. 安装依赖
pip install pyinstaller

# 2. 打包（生成单文件可执行文件）
python build_scripts/build.py

# 输出：dist/linux_x64/UsmDiviner
```

---

## 详细说明

### 目录结构

```
build_scripts/
├── UsmDiviner.spec   # PyInstaller 配置（所有平台通用）
├── build.py          # 自动化构建脚本
└── PACKAGING.md      # 本文件
```

### 打包原理

1. **入口点**：`usmdiviner/__main__.py`（GUI 启动）
2. **资源打包**：
   - ✅ `assets/`（字体、i18n、图标）→ 打包到 `.exe/.app/二进制`  
   - ✅ `vgmstream/`（平台特定二进制，可选）→ 打包到输出目录

3. **路径解析**（无需改动代码）：
   - **开发模式**：`__file__` 相对路径
   - **打包模式**：`sys._MEIPASS`（PyInstaller 临时目录）
   - → `path_utils.py` 自动处理两种情况

4. **外部工具**（FFMPEG、vgmstream）：
   - 通过环境变量优先查找
   - 次优先在项目 `vgmstream/` 目录查找
   - 最后回退到系统 PATH

---

## 高级选项

### 生成特定平台

```bash
# Windows 64-bit
python build_scripts/build.py -p windows_x64

# macOS (Intel + Apple Silicon universal)
python build_scripts/build.py -p macos

# Linux 64-bit
python build_scripts/build.py -p linux_x64

# Linux ARM64 (树莓派等)
python build_scripts/build.py -p linux_arm64
```

### 清理旧的构建

```bash
python build_scripts/build.py --clean
```

### 手动调用 PyInstaller

```bash
# 完整控制
pyinstaller -y \
  --distpath ./dist/windows_x64 \
  --buildpath ./build/windows_x64 \
  ./build_scripts/UsmDiviner.spec
```

---

## 打包增强（可选）

### 1. 指定图标（Windows）

编辑 `UsmDiviner.spec`：
```python
exe = EXE(
    ...
    icon="assets/icon/wolf_favicon.ico",  # 使用 .ico 格式
)
```

生成 .ico 文件：
```bash
pip install Pillow
python -c "from PIL import Image; Image.open('assets/icon/wolf_favicon.png').save('assets/icon/wolf_favicon.ico')"
```

### 2. 创建 macOS DMG 安装程序

```bash
# 需要 create-dmg 工具
brew install create-dmg

# 创建 DMG
create-dmg \
  --volname "UsmDiviner" \
  --window-pos 200 120 \
  --window-size 800 400 \
  --icon-size 100 \
  --icon UsmDiviner.app 200 190 \
  --hide-extension UsmDiviner.app \
  --app-drop-link 600 190 \
  dist/UsmDiviner.dmg \
  dist/macos/UsmDiviner.app
```

### 3. 创建 Linux AppImage（可选）

```bash
# 安装 appimagetool
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage

# 使用官方模板创建 AppDir
mkdir -p UsmDiviner.AppDir/usr/bin
cp dist/linux_x64/UsmDiviner UsmDiviner.AppDir/usr/bin/

# 生成 AppImage
./appimagetool-x86_64.AppImage UsmDiviner.AppDir UsmDiviner-x86_64.AppImage
```

---

## 输出验证

### Windows

```cmd
# 验证 .exe 执行
dist\windows_x64\UsmDiviner.exe

# 检查嵌入的资源
python -c "import PyInstaller; ..." # 列出 onefile 内容
```

### macOS

```bash
# 验证 .app 运行
open dist/macos/UsmDiviner.app

# 检查二进制
file dist/macos/UsmDiviner
```

### Linux

```bash
# 验证可执行文件
./dist/linux_x64/UsmDiviner

# 检查依赖
ldd dist/linux_x64/UsmDiviner
```

---

## 故障排除

### 问题 1：缺少 Qt 模块

**症状**：`ImportError: No module named 'PyQt5.QtWebEngine'`

**解决**：
```bash
pip install PyQt5 PyQtWebEngine
```

### 问题 2：字体未加载

**原因**：资源路径不对

**验证**：在代码中加入调试：
```python
from usmdiviner.path_utils import get_resource_path
print(get_resource_path("assets/fonts/zh-cn.ttf"))
```

### 问题 3：外部工具找不到

**原因**：FFMPEG、vgmstream 不在 PATH

**解决**：
```bash
# 方案 1：设置环境变量
export FFMPEG_PATH=/usr/local/bin/ffmpeg
export VGMSTREAM_PATH=/usr/local/bin/vgmstream-cli

# 方案 2：复制到 vgmstream/ 目录
cp /usr/local/bin/vgmstream-cli ./vgmstream/linux_x64/
cp /usr/local/bin/ffmpeg ./vgmstream/linux_x64/
```

### 问题 4：打包文件过大

**原因**：PyInstaller 默认包含了整个库

**优化**：编辑 `UsmDiviner.spec`，排除不需要的模块：
```python
excludedimports=[
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    # 添加不需要的库
]
```

---

## CI/CD 集成（GitHub Actions 示例）

创建 `.github/workflows/build.yml`：

```yaml
name: Build UsmDiviner

on:
  push:
    tags:
      - "v*"

jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.10"
      - run: pip install -r requirements.txt pyinstaller
      - run: python build_scripts/build.py --clean
      - uses: actions/upload-artifact@v3
        with:
          name: UsmDiviner-${{ runner.os }}
          path: dist/
```

---

## 分发清单

打包完成后，检查以下项：

- [ ] `UsmDiviner.exe`（Windows）/ `UsmDiviner`（Linux）/ `UsmDiviner.app`（macOS）运行无误
- [ ] 双击/命令行执行，GUI 正常显示
- [ ] 所有资源（字体、图标、翻译）正常加载
- [ ] FFMPEG 和 vgmstream 可正常发现和使用
- [ ] 导出文件和日志无路径错误
- [ ] 版本号在 GUI 中正确显示

---

## 大小参考

| 平台 | one-file 大小 | 单独 ZIP | 备注 |
|------|-------------|---------|------|
| Windows | ~200-250 MB | 可选 | PyQt5 + 所有依赖 |
| macOS | ~180-220 MB | .dmg | 通常 100-150 MB |
| Linux | ~150-200 MB | .AppImage | 更小，移植性好 |

---

## 总结

✅ **一键打包**：`python build_scripts/build.py`
✅ **跨平台支持**：Windows / macOS / Linux（x64 & ARM64）
✅ **无代码改动**：path_utils.py 自动兼容 PyInstaller
✅ **资源嵌入**：assets 自动打包到可执行文件
✅ **外部工具**：FFMPEG / vgmstream 自动发现机制

祝打包顺利！🎉

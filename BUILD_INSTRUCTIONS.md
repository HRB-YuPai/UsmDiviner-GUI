# UsmDiviner 打包说明 (PySide6 版本)

## 快速开始

### Windows

```bash
# 1. 创建干净虚拟环境（仅PySide6，不要PyQt5）
python -m venv build_env_pyside

# 2. 激活虚拟环境并安装依赖
build_env_pyside\Scripts\activate
pip install PySide6 lz4 requests PyInstaller Pillow

# 3. 打包
python -m PyInstaller -y ^
    --distpath dist/windows_x64 ^
    --workpath build/windows_x64 ^
    build_scripts/UsmDiviner_PySide6.spec

# 输出: dist/windows_x64/UsmDiviner.exe (约 950 MB)
```

### macOS / Linux

```bash
# 1. 创建干净虚拟环境
python3 -m venv build_env_pyside

# 2. 激活虚拟环境并安装依赖
source build_env_pyside/bin/activate
pip install PySide6 lz4 requests PyInstaller Pillow

# 3. 打包
python3 -m PyInstaller -y \
    --distpath dist/macos \
    --workpath build/macos \
    build_scripts/UsmDiviner_PySide6.spec

# 输出: dist/macos/UsmDiviner.app 或 dist/macos/UsmDiviner
```

## 重要事项

⚠️  **不要同时安装 PyQt5 和 PySide6**
- PyInstaller 会检测到多个 Qt 框架并报错
- 必须创建干净的虚拟环境，仅安装 PySide6

## 文件说明

| 文件 | 用途 |
|------|------|
| `build_scripts/UsmDiviner_PySide6.spec` | ✅ **正确的 spec 文件** (用于打包) |
| `build_scripts/UsmDiviner.spec` | ⚠️   旧的关于 PyQt5 的文件 (不要用) |
| `build_scripts/build.py` | 可选的自动化脚本 |

## 打包成功标志

✅ `dist/windows_x64/UsmDiviner.exe` 生成
✅ 大小约 950-1000 MB（包含 PySide6 全部依赖）
✅ 双击可启动 GUI

## 故障排除

### 错误：`ModuleNotFoundError: No module named 'PySide6'`
- **原因**：打包时环境中没有装 PySide6
- **解决**：确保在虚拟环境中安装了 PySide6

### 错误：`Multiple Qt bindings packages`
- **原因**：虚拟环境混装了 PyQt5 和 PySide6
- **解决**：创建新的干净虚拟环境

### 错误：`Pillow not found`
- **原因**：无法处理图标文件
- **解决**：`pip install Pillow`

---

现在你可以使用以下命令快速打包：

```bash
# 假设你已经有了 build_env_pyside
build_env_pyside\Scripts\python -m PyInstaller -y ^
    --distpath dist/windows_x64 ^
    --workpath build/windows_x64 ^
    build_scripts/UsmDiviner_PySide6.spec
```

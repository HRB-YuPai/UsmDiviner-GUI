#!/bin/bash
# UsmDiviner Build Script for macOS & Linux
# Usage: ./build.sh [--clean] [-p PLATFORM]

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC_FILE="$PROJECT_ROOT/build_scripts/UsmDiviner.spec"
CLEAN_BUILD=0
TARGET_PLATFORM=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN_BUILD=1
            shift
            ;;
        -p|--platform)
            TARGET_PLATFORM="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--clean] [-p PLATFORM]"
            exit 1
            ;;
    esac
done

# Detect platform if not specified
if [ -z "$TARGET_PLATFORM" ]; then
    case "$(uname -s)" in
        Darwin)
            TARGET_PLATFORM="macos"
            ;;
        Linux)
            ARCH=$(uname -m)
            if [ "$ARCH" = "aarch64" ]; then
                TARGET_PLATFORM="linux_arm64"
            else
                TARGET_PLATFORM="linux_x64"
            fi
            ;;
        *)
            echo "[ERROR] Unsupported platform: $(uname -s)"
            exit 1
            ;;
    esac
fi

DIST_DIR="$PROJECT_ROOT/dist/$TARGET_PLATFORM"
BUILD_DIR="$PROJECT_ROOT/build/$TARGET_PLATFORM"

echo "[INFO] Building UsmDiviner for $TARGET_PLATFORM..."
echo "[INFO] Spec file: $SPEC_FILE"
echo "[INFO] Output dir: $DIST_DIR"

# Check if PyInstaller is installed
if ! python3 -m pip show pyinstaller >/dev/null 2>&1; then
    echo "[INFO] PyInstaller not found. Installing..."
    python3 -m pip install pyinstaller
fi

# Clean previous builds if requested
if [ "$CLEAN_BUILD" = "1" ]; then
    echo "[INFO] Cleaning previous builds..."
    rm -rf "$DIST_DIR"
    rm -rf "$BUILD_DIR"
fi

# Run PyInstaller
python3 -m PyInstaller -y \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    "$SPEC_FILE"

if [ $? -ne 0 ]; then
    echo "[ERROR] Build failed!"
    exit 1
fi

echo "[OK] Build successful!"
echo "[OK] Output: $DIST_DIR"
echo ""
echo "[INFO] Generated files:"
find "$DIST_DIR" -type f | sed 's/^/  - /'

echo ""
if [ "$TARGET_PLATFORM" = "macos" ]; then
    echo "[INFO] To run:"
    echo "  open $DIST_DIR/UsmDiviner.app"
else
    echo "[INFO] To run:"
    echo "  $DIST_DIR/UsmDiviner"
fi

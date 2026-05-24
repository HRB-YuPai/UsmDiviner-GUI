#!/usr/bin/env python3
"""
Cross-platform PyInstaller build script for UsmDiviner.

Usage:
    python build_scripts/build.py          # Build for current platform
    python build_scripts/build.py --help   # Show help
"""

import argparse
import sys
import subprocess
import shutil
from pathlib import Path


def get_project_root() -> Path:
    return Path(__file__).parent.parent


def get_dist_dir(platform_name: str) -> Path:
    root = get_project_root()
    return root / "dist" / platform_name


def get_build_dir(platform_name: str) -> Path:
    root = get_project_root()
    return root / "build" / platform_name


def build_for_platform(platform_name: str = None, clean: bool = False) -> int:
    """Build executable for given platform."""
    
    if platform_name is None:
        # Detect current platform
        if sys.platform.startswith("win"):
            platform_name = "windows_x64"
        elif sys.platform == "darwin":
            platform_name = "macos"
        elif sys.platform.startswith("linux"):
            platform_name = "linux_x64"
        else:
            print(f"[ERROR] Unsupported platform: {sys.platform}")
            return 1
    
    root = get_project_root()
    dist_dir = get_dist_dir(platform_name)
    build_dir = get_build_dir(platform_name)
    spec_file = root / "build_scripts" / "UsmDiviner.spec"
    
    print(f"[INFO] Building for {platform_name}...")
    print(f"[INFO] Spec file: {spec_file}")
    print(f"[INFO] Output dir: {dist_dir}")
    
    if clean:
        print(f"[INFO] Cleaning previous builds...")
        shutil.rmtree(dist_dir, ignore_errors=True)
        shutil.rmtree(build_dir, ignore_errors=True)
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--distpath", str(dist_dir),
        "--workpath", str(build_dir),
        "-y",
        str(spec_file),
    ]
    
    print(f"[INFO] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"[OK] Build successful!")
        print(f"[OK] Output: {dist_dir}")
        
        # Show output structure
        if dist_dir.exists():
            print(f"\n[INFO] Generated files:")
            for item in dist_dir.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(dist_dir)
                    print(f"  - {rel}")
        
        return 0
    else:
        print(f"[ERROR] Build failed!")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Build UsmDiviner executable for current platform.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_scripts/build.py                # Build for current platform
  python build_scripts/build.py --clean         # Clean and rebuild
  python build_scripts/build.py -p windows_x64 # Build for specific platform
        """,
    )
    
    parser.add_argument(
        "-p", "--platform",
        choices=["windows_x64", "macos", "linux_x64", "linux_arm64"],
        help="Target platform (auto-detect if not specified)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean previous builds before building",
    )
    
    args = parser.parse_args()
    
    return build_for_platform(args.platform, args.clean)


if __name__ == "__main__":
    sys.exit(main())

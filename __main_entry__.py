#!/usr/bin/env python3
"""
Entry point for PyInstaller packaged UsmDiviner.
This script is used as the main entry for the packaged executable.
It ensures proper module discovery in both development and packaged modes.
"""

import sys
from pathlib import Path

# Ensure usmdiviner package is importable
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Now import and run the GUI
if __name__ == "__main__":
    from usmdiviner.gui import main
    sys.exit(main())

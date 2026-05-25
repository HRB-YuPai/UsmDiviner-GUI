#!/usr/bin/env python3
"""PyInstaller entrypoint for launching the UsmDiviner GUI."""

import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    # This file lives in `usmdiviner/`, so project root is one level up.
    project_root = Path(__file__).resolve().parent.parent
    root_text = str(project_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)


if __name__ == "__main__":
    _ensure_project_root_on_path()
    from usmdiviner.gui import main

    raise SystemExit(main())

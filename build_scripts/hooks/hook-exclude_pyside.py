"""
PyInstaller hook to completely prevent PySide6/PySide2 from being collected.
This hook is applied when processing all modules to ensure PySide doesn't interfere.
"""

# This hook prevents PyInstaller from auto-collecting PySide6/PySide2
# when analyzing module dependencies
excludedimports = [
    'PySide6',
    'PySide2',
]

excludes = [
    'PySide6',
    'PySide2',
]


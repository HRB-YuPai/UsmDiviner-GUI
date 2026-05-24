#!/usr/bin/env python3
"""Fix spec file to use PySide6 instead of PyQt5"""

spec_file = r"j:\External_Environment\UsmDiviner\build_scripts\UsmDiviner.spec"

with open(spec_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace PyQt5 imports with PySide6 imports
old_imports = '''    hiddenimports=[
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "PyQt5.QtWidgets",
        "PyQt5.QtWebChannel",
        "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtNetwork",
    ],'''

new_imports = '''    hiddenimports=[
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtWebChannel",
    ],'''

content = content.replace(old_imports, new_imports)

# Replace excludedimports to exclude PyQt5 instead
old_excludes = '''    excludedimports=[
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtWebChannel",
        "PySide2",
        "PySide2.QtCore",
        "PySide2.QtGui",
        "PySide2.QtWidgets",
        "tkinter",
    ],'''

new_excludes = '''    excludedimports=[
        "PyQt5",
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "PyQt5.QtWidgets",
        "PyQt5.QtWebChannel",
        "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtNetwork",
        "PyQt5.QtWebKit",
        "PyQt5.QtWebKitWidgets",
        "PySide2",
        "tkinter",
    ],'''

content = content.replace(old_excludes, new_excludes)

with open(spec_file, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Spec file updated to use PySide6 instead of PyQt5")

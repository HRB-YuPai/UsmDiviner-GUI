@echo off
REM UsmDiviner Build Script for Windows
REM Usage: build.bat [--clean]

setlocal enabledelayedexpansion

set PROJECT_ROOT=%~dp0..
set SPEC_FILE=%PROJECT_ROOT%\build_scripts\UsmDiviner.spec
set DIST_DIR=%PROJECT_ROOT%\dist\windows_x64
set BUILD_DIR=%PROJECT_ROOT%\build\windows_x64
set CLEAN_BUILD=0

if "%1"=="--clean" (
    set CLEAN_BUILD=1
    echo [INFO] Clean build enabled
)

REM Check if PyInstaller is installed
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller not found. Installing...
    python -m pip install pyinstaller
)

REM Clean previous builds if requested
if !CLEAN_BUILD! equ 1 (
    echo [INFO] Cleaning previous builds...
    if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
    if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
)

echo [INFO] Building UsmDiviner for Windows...
echo [INFO] Spec file: %SPEC_FILE%
echo [INFO] Output dir: %DIST_DIR%

REM Run PyInstaller from project root so spec file can locate resources
cd /d "%PROJECT_ROOT%"
python -m PyInstaller -y ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%" ^
    "build_scripts\UsmDiviner.spec"

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo [OK] Build successful!
echo [OK] Output: %DIST_DIR%
echo.
echo [INFO] Generated files:
for /r "%DIST_DIR%" %%F in (*) do (
    echo   - %%~F
)

echo.
echo [INFO] To run:
echo   %DIST_DIR%\UsmDiviner.exe
pause

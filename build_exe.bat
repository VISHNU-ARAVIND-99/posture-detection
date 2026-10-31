@echo off
title Build Posture Guardian Standalone Executable
echo =======================================================================
echo   Building Posture Guardian Standalone Windows Executable (.exe)
echo =======================================================================
echo.

call .venv\Scripts\activate.bat

echo Compiling with PyInstaller using PostureGuardian.spec...
pyinstaller PostureGuardian.spec --noconfirm

echo.
if exist "dist\PostureGuardian.exe" (
    echo =======================================================================
    echo   BUILD SUCCESSFUL!
    echo   Executable is ready at: dist\PostureGuardian.exe
    echo =======================================================================
) else (
    echo [ERROR] Build failed. Please check the logs above.
)
pause

@echo off
echo Building PDF/DOCX File Manager (Simple Version)...

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install PySide6==6.6.0
pip install watchdog==3.0.0
pip install pyinstaller==6.3.0

REM Clean previous builds
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del *.spec

REM Build executable with minimal configuration
echo Building executable...
pyinstaller ^
    --onefile ^
    --noconsole ^
    --name "PDFDocxManager" ^
    --distpath "build_output" ^
    --specpath "." ^
    --workpath "temp_build" ^
    --clean ^
    --noconfirm ^
    file_manager.py

REM Clean up temporary files
if exist "temp_build" rmdir /s /q temp_build
if exist "*.spec" del *.spec

echo.
if exist "build_output\PDFDocxManager.exe" (
    echo ✓ Build successful!
    echo Executable: build_output\PDFDocxManager.exe
    echo File size: 
    dir "build_output\PDFDocxManager.exe" | findstr PDFDocxManager
) else (
    echo ✗ Build failed!
    echo Check the error messages above.
)
echo.

pause
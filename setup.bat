@echo off
setlocal
cd /d "%~dp0"

echo === Quran Video Studio - Setup ===
echo.

REM ---- Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo [MISSING] Python was not found. Install Python 3.11+ from https://python.org
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do set PYV=%%i
echo [OK] %PYV%

REM ---- Node ----
where node >nul 2>&1
if errorlevel 1 (
    echo [MISSING] Node.js was not found. Install Node 20+ from https://nodejs.org
    exit /b 1
)
echo [OK] node %node_version% & node --version

REM ---- FFmpeg ----
set "QVS_FFMPEG="
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [MISSING] FFmpeg not on PATH.
    echo         Install it with:  winget install Gyan.FFmpeg
    echo         (or download from https://www.gyan.dev/ffmpeg/builds/ and add to PATH)
    echo         Then run setup again. FFmpeg is required to export video.
) else (
    echo [OK] ffmpeg found on PATH
)

echo.
echo --- Backend environment ---
if not exist "backend\.venv" (
    python -m venv backend\.venv
)
backend\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
backend\.venv\Scripts\python.exe -m pip install --quiet -r backend\requirements.txt
if errorlevel 1 ( echo [ERROR] Failed to install backend requirements & exit /b 1 )
echo [OK] backend packages installed

echo.
echo --- Quran text cache ---
if exist "data\surahs.json" (
    echo [OK] Quran text cache already present
) else (
    echo Downloading Quran text + translation from api.alquran.cloud ...
    backend\.venv\Scripts\python.exe backend\scripts\fetch_quran_data.py
    if errorlevel 1 ( echo [ERROR] Quran data download failed - check internet connection & exit /b 1 )
)

echo.
echo --- Fonts ---
set FONTS_OK=1
for %%f in (Amiri-Regular.ttf Amiri-Bold.ttf NotoNaskhArabic.ttf NotoSansArabic.ttf Inter.ttf) do (
    if not exist "fonts\%%f" set FONTS_OK=0
)
if "%FONTS_OK%"=="1" (
    echo [OK] fonts present
) else (
    echo [MISSING] Some fonts are absent. Run:
    echo   curl -L -o fonts\Amiri-Regular.ttf https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf
    echo   curl -L -o fonts\Amiri-Bold.ttf    https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Bold.ttf
    echo   curl -L -o fonts\NotoNaskhArabic.ttf "https://github.com/google/fonts/raw/main/ofl/notonaskharabic/NotoNaskhArabic%%5Bwght%%5D.ttf"
    echo   curl -L -o fonts\NotoSansArabic.ttf  "https://github.com/google/fonts/raw/main/ofl/notosansarabic/NotoSansArabic%%5Bwdth%%2Cwght%%5D.ttf"
    echo   curl -L -o fonts\Inter.ttf           "https://github.com/google/fonts/raw/main/ofl/inter/Inter%%5Bopsz%%2Cwght%%5D.ttf"
)

echo.
echo --- Frontend dependencies ---
cd frontend
if not exist "node_modules" (
    call npm install
    if errorlevel 1 ( echo [ERROR] npm install failed & exit /b 1 )
) else (
    echo [OK] node_modules present
)
cd ..

echo.
echo Setup complete. Run start.bat to launch the app.
endlocal

@echo off
rem Stufe-1-Befehl fuer den PC-Agenten (P22). Nicht interaktiv: es wird auf keine Eingabe gewartet.
rem Pfade relativ zum Jarvis-Ordner (diese Datei liegt in Jarvis\pc_befehle).
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set EMBEDDING_THREADS=2
set OMP_NUM_THREADS=2
set HF_HUB_DISABLE_PROGRESS_BARS=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set "JARVIS=%~dp0.."
cd /d "%JARVIS%\backend" || exit /b 2
if not exist venv\Scripts\activate.bat (
  echo FEHLER: venv fehlt in %JARVIS%\backend
  exit /b 2
)
call venv\Scripts\activate.bat
echo ==== Updates pruefen (nur auflisten, nichts installieren) %DATE% %TIME% ====
echo.
echo --- pip (backend\venv): veraltete Pakete ---
python -m pip list --outdated
echo.
echo --- npm: veraltete Pakete (falls npm vorhanden) ---
where npm >nul 2>&1
if "%ERRORLEVEL%"=="0" (npm outdated -g) else (echo npm nicht gefunden)
echo.
echo --- winget: verfuegbare Updates (nur Liste) ---
where winget >nul 2>&1
if "%ERRORLEVEL%"=="0" (winget upgrade --include-unknown) else (echo winget nicht gefunden)
exit /b 0

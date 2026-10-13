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
echo ==== Pruefen (Vault-Pflege und Suchtest, ohne Claude) %DATE% %TIME% ====
echo.
echo --- 1. Vault-Pflege ---
python -m tools.vault_pflege
set "FEHLER=%ERRORLEVEL%"
echo.
echo --- 2. Suchtest ---
python -m tests.eval_search
if not "%ERRORLEVEL%"=="0" set "FEHLER=%ERRORLEVEL%"
echo.
echo ==== Pruefen fertig, Ergebnis %FEHLER% ====
exit /b %FEHLER%

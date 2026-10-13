@echo off
rem Jarvis-Chattest: echte Claude-Anfragen (ca. 5-10 Cent), prueft Antwort mit
rem Quellen, den Werkzeug-Modus und den Schutz vor versteckten Anweisungen.
rem WICHTIG: Backend (uvicorn) vorher stoppen.
chcp 65001 >nul
cd /d "%~dp0"
set "LOG=%~dp0chattest_log.txt"
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_PROGRESS_BARS=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
echo Auron-Chattest laeuft ...
echo ==== Auron Chattest %DATE% %TIME% ==== > "%LOG%"
call venv\Scripts\activate.bat
python -m tests.chat_smoketest >> "%LOG%" 2>&1
echo ==== FERTIG %DATE% %TIME% ==== >> "%LOG%"
if not "%1"=="--no-notepad" notepad "%LOG%"

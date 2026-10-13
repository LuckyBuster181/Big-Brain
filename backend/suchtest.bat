@echo off
rem Jarvis-Suchtest: schnelle Tests (ohne Modell, ohne Claude) + Messung der Suchqualitaet.
rem Belastung gering: nur Suchanfragen gegen den vorhandenen Index, kein Neuaufbau.
rem WICHTIG: Backend (uvicorn) vorher stoppen - sonst bricht der Test ab.
chcp 65001 >nul
cd /d "%~dp0"
set "LOG=%~dp0suchtest_log.txt"
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_PROGRESS_BARS=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
echo Auron-Suchtest laeuft (ca. 1 Minute) ...
echo ==== Auron Suchtest %DATE% %TIME% ==== > "%LOG%"
call venv\Scripts\activate.bat
echo. >> "%LOG%"
echo ==== 1. Schnelle Tests ==== >> "%LOG%"
python -m unittest discover -s tests -t . -p "test_*.py" -v >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ==== 2. Suchqualitaet und Schwelle ==== >> "%LOG%"
python -m tests.eval_search >> "%LOG%" 2>&1
echo ==== FERTIG %DATE% %TIME% ==== >> "%LOG%"
if not "%1"=="--no-notepad" notepad "%LOG%"

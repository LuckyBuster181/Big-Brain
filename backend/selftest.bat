@echo off
rem Jarvis-Selbsttest: prueft Embedding-Modell, Index, Reindex-API, Chat mit Verlauf
rem und baut das Dashboard einmal (TypeScript-Pruefung). Ergebnis: selftest_log.txt
rem WICHTIG: Backend (uvicorn) vorher stoppen - sonst bricht der Test ab.
chcp 65001 >nul
cd /d "%~dp0"
set "LOG=%~dp0selftest_log.txt"
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_PROGRESS_BARS=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
echo Auron-Selbsttest laeuft - Index-Aufbau dauert ca. 3-10 Minuten (gedrosselt auf 2 CPU-Threads).
echo Fenster bitte offen lassen. Am Ende oeffnet sich das Protokoll im Editor.
echo.
echo ==== Auron Selbsttest %DATE% %TIME% ==== > "%LOG%"
call venv\Scripts\activate.bat
python -m tests.selftest --log "%LOG%" %*
echo. >> "%LOG%"
echo ==== Dashboard: npm run build ==== >> "%LOG%"
echo Baue Dashboard ...
pushd "%~dp0..\dashboard"
call npm run build >> "%LOG%" 2>&1
popd
echo ==== FERTIG %DATE% %TIME% ==== >> "%LOG%"
notepad "%LOG%"

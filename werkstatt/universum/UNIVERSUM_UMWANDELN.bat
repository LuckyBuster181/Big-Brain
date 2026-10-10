@echo off
rem UNIVERSUM_UMWANDELN.bat (04.10.2026, Claude): wandelt alle Universe-Sandbox-Dateien (.ubox)
rem aus Dokumente\Universe Sandbox\Simulations in kleine Szenen fuer universum_3d.html um.
rem Liest die Spieldateien nur, aendert sie nicht. Bericht: data\universum_bericht.txt
setlocal
chcp 65001 >nul
set "HIER=%~dp0"
for %%I in ("%~dp0..\..") do set "J=%%~fI"
set "QUELLE=%USERPROFILE%\Documents\Universe Sandbox\Simulations"
set "BERICHT=%J%\data\universum_bericht.txt"
set "PY=%J%\backend\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set PYTHONIOENCODING=utf-8
echo ===== Universum umwandeln %date% %time% ===== > "%BERICHT%"
"%PY%" "%HIER%standard_szene.py" >> "%BERICHT%" 2>&1
"%PY%" "%HIER%ubox_lesen.py" "%QUELLE%" "%HIER%szenen" >> "%BERICHT%" 2>&1
type "%BERICHT%"
echo.
echo Fertig. Ansehen: http://127.0.0.1:8001/werkstatt/universum/universum_3d.html (Strg+F5)
echo Im Chat "fertig" schreiben.
pause

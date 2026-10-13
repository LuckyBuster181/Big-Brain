@echo off
rem Ordner seit 24.09.2026: 1 Starten\ - J = der Jarvis-Ordner darueber.
for %%I in ("%~dp0..") do set "J=%%~fI"
rem HANDY_STARTEN.bat - startet Jarvis so, dass auch das Handy im Heimnetz ihn erreicht (24.09.2026, Claude).
rem Wie NEUSTART.bat, nur hoert das Backend zusaetzlich im WLAN (Port 8000).
rem Schutz: Zugangscode (JARVIS_HANDY_TOKEN in der .env, wird beim ersten Mal erzeugt) und
rem vom Handy aus nur Chat, Briefing, Denkblock und Vorschlaege (backend\app\handy_zugang.py).
rem Beim ersten Mal fragt Windows nach Administrator-Rechten fuer die Firewall-Freigabe (nur Heimnetz).
chcp 65001 >nul
cd /d "%J%"

echo.
echo   Auron mit Handy-Zugang starten ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0handy_zugang.ps1" -Jarvis "%J%"
if errorlevel 1 ( echo. & echo   Abgebrochen - Meldung oben an Claude. & pause & exit /b 1 )

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":8000 .*[AL]"') do (
  taskkill /f /pid %%P >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":5173 .*[AL]"') do (
  taskkill /f /pid %%P >nul 2>&1
)
taskkill /f /fi "WINDOWTITLE eq Jarvis Backend*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Jarvis Dashboard*" >nul 2>&1
timeout /t 2 /nobreak >nul

start "Jarvis Backend (mit Handy)" cmd /k "cd /d "%J%\backend" && call venv\Scripts\activate.bat && python -m uvicorn main:app --host 0.0.0.0 --port 8000"
start "Jarvis Dashboard" cmd /k "cd /d "%J%\dashboard" && npm run dev"
timeout /t 8 /nobreak >nul
call "%~dp0CHROME_OEFFNEN.bat" http://localhost:5173
set /p HANDYLINK=<"%J%\data\handy_link.txt"
call "%~dp0CHROME_OEFFNEN.bat" "%HANDYLINK%"
echo.
echo   ================================================================
echo    Handy-Adresse (Handy im selben WLAN):
echo      %HANDYLINK%
echo    Am einfachsten: Im Chrome-Tab mit dieser Adresse oben auf "Teilen"
echo    - "An Ihre Geraete senden" - Ihr Handy. Auf dem Handy oeffnen,
echo    dann im Chrome-Menue "Zum Startbildschirm hinzufuegen".
echo   ================================================================
echo.
pause

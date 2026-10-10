@echo off
rem Ordner seit 24.09.2026: 1 Starten\ - J = der Jarvis-Ordner darueber.
rem CHROME_OEFFNEN.bat - oeffnet eine Adresse in Google Chrome (24.09.2026, Wunsch von Sir).
rem Wird von NEUSTART.bat, start_jarvis.bat und JARVIS_MINIPC_OEFFNEN.bat aufgerufen:
rem   call "%~dp0CHROME_OEFFNEN.bat" http://localhost:5173
rem Gibt es Chrome auf diesem PC nicht, oeffnet sich der Standard-Browser.
setlocal
set "ZIEL=%~1"
if "%ZIEL%"=="" set "ZIEL=http://localhost:5173"
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if defined CHROME (
  start "" "%CHROME%" "%ZIEL%"
) else (
  echo   Chrome nicht gefunden - oeffne den Standard-Browser.
  start "" "%ZIEL%"
)
endlocal

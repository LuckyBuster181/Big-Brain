@echo off
rem GPU MIETE.bat (P24, 16.10.2026, Claude Code): GPU-Miete (RunPod) von Hand bedienen. Ungetestet am PC.
rem 1 = Stand zeigen (ruft RunPod nicht auf), 2 = Waechter jetzt (loescht Pods, die nicht da sein duerfen),
rem 3 = offenen Code-Auftrag SOFORT auf einer gemieteten GPU erledigen (kostet Geld, Pod wird danach geloescht).
rem 4 = Alexa-Alarm testen (schickt eine Test-Benachrichtigung an das Echo, P24b).
rem Ergebnis: data\gpu_miete_bericht.txt
setlocal
chcp 65001 >nul
title GPU-Miete
cd /d "%~dp0"
for %%I in ("%~dp0..") do set "J=%%~fI"
set "BERICHT=%J%\data\gpu_miete_bericht.txt"
echo.
echo  GPU-Miete (RunPod)
echo    1 = Stand zeigen
echo    2 = Waechter jetzt: nicht erlaubte Pods loeschen
echo    3 = Code-Auftrag jetzt auf eine gemietete GPU (kostet Geld)
echo    4 = Alexa-Alarm testen (Test-Benachrichtigung an das Echo)
choice /c 1234 /m " Was soll passieren"
set "WAHL=%errorlevel%"
set "NR=0"
set "AKTION=status"
if "%WAHL%"=="2" set "AKTION=aufraeumen"
if "%WAHL%"=="4" set "AKTION=alarmtest"
if "%WAHL%"=="3" (
  set "AKTION=auftrag"
  set /p NR=" Nummer des offenen Code-Auftrags: "
)
> "%BERICHT%" echo ===== GPU-Miete %AKTION% %date% %time% =====
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gpu_miete.ps1" -Aktion %AKTION% -Nr %NR% >> "%BERICHT%" 2>&1
type "%BERICHT%"
echo.
echo  Fertig.
pause

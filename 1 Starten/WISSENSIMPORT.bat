@echo off
rem ======================================================================
rem  WISSENSIMPORT.bat (29.09.2026, Claude)
rem  Wissen aus Wikipedia in den Vault holen (app/wissensimport.py):
rem  Sonnet fasst ausgezeichnete Artikel zusammen, Haiku prueft jede Notiz
rem  gegen den Artikel, Opus jede 10. Notiz. Deckel 10 $ fuer alles.
rem  Laeuft auf dem Mini-PC im Hintergrund weiter (auch wenn dieses Fenster zu ist).
rem  Vorher einmal 1 Starten\JARVIS STARTEN.bat (bringt den neuen Code hin).
rem ======================================================================
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "J=%%~fI"
chcp 65001 >nul
title Jarvis Wissensimport
set "IP=192.168.68.139"
set "ZIEL=max1@%IP%"
set "SSHO=-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes"

ssh %SSHO% %ZIEL% "mkdir -p ~/jarvis-umzug" >nul 2>&1
if errorlevel 1 (
  echo  FEHLER: SSH zum Mini-PC geht nicht. Ist er an?
  goto ende
)
scp %SSHO% "%J%\linux\jarvis_mini.sh" %ZIEL%:jarvis-umzug/jarvis_mini.sh >nul 2>&1

:menue
echo.
echo  ===== Jarvis Wissensimport =====
ssh %SSHO% %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh wissen_status"
echo.
echo   1 = Probelauf mit 20 Notizen
echo   2 = Anzahl selbst eingeben
echo   3 = Stand neu anzeigen
echo   4 = Laufenden Import abbrechen
echo   5 = Beenden
set "WAHL="
set /p "WAHL=  Auswahl: "
if "%WAHL%"=="1" (
  ssh %SSHO% %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh wissen_start 20"
  goto menue
)
if "%WAHL%"=="2" (
  set "ANZ="
  set /p "ANZ=  Wie viele Notizen (1-1000)? "
  call :starten
  goto menue
)
if "%WAHL%"=="3" goto menue
if "%WAHL%"=="4" (
  ssh %SSHO% %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh wissen_abbrechen"
  goto menue
)
if "%WAHL%"=="5" exit /b 0
goto menue

:starten
ssh %SSHO% %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh wissen_start %ANZ%"
exit /b 0

:ende
echo.
pause

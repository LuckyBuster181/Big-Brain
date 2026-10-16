@echo off
rem ======================================================================
rem  AURON STARTEN.bat - die EINE Startdatei (ab 26.09.2026, Claude; Name ab 16.10.2026, P20).
rem  Die alte Datei JARVIS STARTEN.bat leitet nur hierher weiter (Verknuepfungen bleiben gueltig).
rem  Auron laeuft auf dem Mini-PC. Diese Datei:
rem    1. beendet einen alten Auron auf DIESEM PC (nie zwei gleichzeitig)
rem    2. traegt die aktuelle Haupt-PC-IP in die .env ein (PC-Steuerung, keine feste IP noetig)
rem    3. wartet, bis Syncthing neuen Code zum Mini-PC gebracht hat
rem    4. startet Auron auf dem Mini-PC neu (neuester Code, wie frueher NEUSTART.bat)
rem    5. prueft, ob der Mini-PC den Haupt-PC (PC-Steuerung) wirklich erreicht
rem    6. oeffnet Auron: http://127.0.0.1:8001/auron (gesicherter SSH-Tunnel; altes HUD weiter unter /)
rem  Auch nach Code-Aenderungen von Claude einfach diese Datei starten.
rem  Aenderungen an dieser Datei macht Claude hier - keine neuen Startdateien.
rem  Stand-Protokoll: data\jarvis_starten_bericht.txt (Dateiname bleibt, Technik: Dienst "jarvis", jarvis_mini.sh)
rem ======================================================================
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "J=%%~fI"
chcp 65001 >nul
title Auron starten
cd /d "%~dp0"

set "IP=192.168.68.139"
set "ZIEL=max1@%IP%"
set "SSHO=-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
set "BERICHT=%J%\data\jarvis_starten_bericht.txt"
> "%BERICHT%" echo ===== Auron starten %date% %time% =====

echo.
echo  [1/6] Alten Auron auf diesem PC beenden ...
rem nur Prozesse, die auf diesem PC an Port 8000/5173 LAUSCHEN (Gegenstelle :0) - nie Chrome o.ae.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:"TCP *[^ ]*:8000 " ^| findstr /c:":0 "') do taskkill /f /pid %%P >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:"TCP *[^ ]*:5173 " ^| findstr /c:":0 "') do taskkill /f /pid %%P >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Jarvis Backend*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq Jarvis Dashboard*" >nul 2>&1

echo  [2/6] Haupt-PC-Adresse pruefen (PC-Steuerung) ...
rem 27.09.2026 abends: ohne Deco-Reservierung kann sich die IP des Haupt-PCs aendern - dann fand
rem der Mini-PC ihn nicht mehr ("Der Haupt-PC antwortet nicht"). Jetzt bei jedem Start neu eintragen.
echo  [2/6] Haupt-PC-Adresse pruefen (PC-Steuerung) ... >> "%BERICHT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0hauptpc_ip_aktualisieren.ps1" -J "%J%" >> "%BERICHT%" 2>&1
rem 30.09.2026: PC-Agent neu starten, wenn Claude seinen Code geaendert hat (sonst laeuft die alte Version weiter).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc_agent_aktualisieren.ps1" -J "%J%" >> "%BERICHT%" 2>&1

echo  [3/6] Mini-PC erreichbar? (%IP%)
ping -n 2 -w 2000 %IP% >nul
if errorlevel 1 (
  call :fehler "Mini-PC %IP% antwortet nicht. Ist er an? Neue Adresse? Am Mini-PC: hostname -I"
  goto ende
)
ssh %SSHO% -o BatchMode=yes %ZIEL% "mkdir -p ~/jarvis-umzug" >nul 2>&1
if errorlevel 1 (
  call :fehler "SSH-Anmeldung am Mini-PC geht nicht - Schluessel? JARVIS_UMZUG_MINIPC.bat einmal starten."
  goto ende
)
scp %SSHO% -o BatchMode=yes "%J%\linux\jarvis_mini.sh" %ZIEL%:jarvis-umzug/jarvis_mini.sh >nul 2>&1

echo  [4/6] Warte auf den Abgleich (neuester Code zum Mini-PC, bis 2 Min.) ...
ssh %SSHO% -o BatchMode=yes %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh sync" >> "%BERICHT%" 2>&1
rem 27.09.2026: fehlende Pakete (PyMuPDF fuer "Dateien umwandeln") einmalig nachinstallieren
ssh %SSHO% -o BatchMode=yes %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh pakete" >> "%BERICHT%" 2>&1

echo  [5/6] Auron auf dem Mini-PC neu starten ...
ssh %SSHO% -o BatchMode=yes %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh neustart" >> "%BERICHT%" 2>&1
if errorlevel 3 (
  echo.
  echo  Einmalig: Bitte das Passwort des Mini-PCs eingeben, danach nie wieder.
  ssh -t %SSHO% %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh einrichten"
)
ssh %SSHO% -o BatchMode=yes %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh status" > "%TEMP%\jarvis_status.txt" 2>&1
rem 26.09.2026: Laptop und Handy brauchen Auron im Heimnetz - einmalig umstellen
findstr /c:"HOST=127.0.0.1" "%TEMP%\jarvis_status.txt" >nul
if not errorlevel 1 (
  echo.
  echo  Einmalig: Auron fuer Laptop und Handy freigeben. Bitte das Passwort des Mini-PCs eingeben.
  ssh -t %SSHO% %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh netz"
  scp %SSHO% -o BatchMode=yes %ZIEL%:jarvis-umzug/netz.log "%J%\data\jarvis_netz_bericht.txt" >nul 2>&1
  ssh %SSHO% -o BatchMode=yes %ZIEL% "bash ~/jarvis-umzug/jarvis_mini.sh status" > "%TEMP%\jarvis_status.txt" 2>&1
)
type "%TEMP%\jarvis_status.txt" >> "%BERICHT%"
findstr /c:"JARVIS=200" "%TEMP%\jarvis_status.txt" >nul
if errorlevel 1 (
  type "%TEMP%\jarvis_status.txt"
  call :fehler "Auron antwortet auf dem Mini-PC nicht. Claude liest data\jarvis_starten_bericht.txt."
  goto ende
)

echo  [6/6] PC-Steuerung pruefen und HUD oeffnen ...
rem 27.09.2026 abends: nicht nur lokal testen (das sagt nichts ueber die IP, die der Mini-PC nutzt),
rem sondern denselben Weg pruefen, den der Mini-PC auch nimmt - direkter Beweis statt Vermutung.
set "HPURL="
if exist "%J%\pc_agent_windows\agent.env" for /f "tokens=2 delims==" %%U in ('findstr /b /c:"HAUPTPC_URL=" "%J%\.env" 2^>nul') do set "HPURL=%%U"
if defined HPURL (
  ssh %SSHO% -o BatchMode=yes %ZIEL% "curl -s -m 5 %HPURL%/ping" > "%TEMP%\hauptpc_ping.txt" 2>&1
  echo  PC-Steuerung: Mini-PC ruft %HPURL%/ping auf ... >> "%BERICHT%"
  type "%TEMP%\hauptpc_ping.txt" >> "%BERICHT%"
  echo. >> "%BERICHT%"
  findstr /c:"agent_version" "%TEMP%\hauptpc_ping.txt" >nul
  if errorlevel 1 (
    echo       WARNUNG: PC-Steuerung nicht erreichbar >> "%BERICHT%"
    echo.
    echo  WARNUNG: Der Mini-PC erreicht die PC-Steuerung ^(%HPURL%^) nicht.
    echo  Pruefen: laeuft der Agent noch? "3 Einrichten\PC_STEUERUNG_EINRICHTEN.bat" erneut starten.
  ) else (
    echo       OK >> "%BERICHT%"
  )
  rem Lokaler Agent nicht erreichbar (Prozess weg)? Ueber Autostart-Verknuepfung neu starten.
  curl -s -o nul -m 2 http://127.0.0.1:8766/ping
  if errorlevel 1 start "" wscript.exe "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Jarvis PC-Agent.vbs"
)
curl -s -o nul -m 3 http://127.0.0.1:8001/api/health
if not errorlevel 1 goto tunnel_da
start "Auron Tunnel (offen lassen)" /min ssh %SSHO% -o BatchMode=yes -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -L 8001:127.0.0.1:8000 %ZIEL%
set /a N=0
:tunnel_warten
timeout /t 1 /nobreak >nul
curl -s -o nul -m 3 http://127.0.0.1:8001/api/health
if not errorlevel 1 goto tunnel_da
set /a N+=1
if %N% LSS 20 goto tunnel_warten
call :fehler "Tunnel zum Mini-PC steht nicht (Port 8001)."
goto ende
:tunnel_da
rem 05.10.2026: Auron als App-Fenster (eigenes Profil, Stimme ohne Klick) statt normalem Chrome-Tab
if exist "%~dp0AURON.vbs" (start "" wscript.exe "%~dp0AURON.vbs") else (call "%~dp0CHROME_OEFFNEN.bat" http://127.0.0.1:8001/auron)
>> "%BERICHT%" echo ===== Auron laeuft, HUD offen %date% %time% =====
echo.
type "%TEMP%\jarvis_status.txt"
echo.
echo  Auron laeuft auf dem Mini-PC. Auron: http://127.0.0.1:8001/auron
echo  Laptop und Handy: Adresse %IP%:8000 (statt frueher 192.168.68.119).
echo  Das minimierte Fenster "Auron Tunnel" offen lassen, solange Sie das HUD nutzen.
timeout /t 8 /nobreak >nul
exit /b 0

:ende
echo.
pause
exit /b 1

:fehler
echo.
echo  FEHLER: %~1
>> "%BERICHT%" echo [%date% %time%] FEHLER: %~1
exit /b 0

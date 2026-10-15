@echo off
rem GESTEN_HOLEN.bat (15.10.2026, Claude Code): laedt einmalig die Dateien fuer die Gesten-Steuerung in Auron
rem nach werkstatt\lib\mediapipe. Danach laeuft das Handtracking komplett lokal im Browser, ohne Internet.
rem - MediaPipe Tasks Vision 0.10.35 (Google, Lizenz Apache-2.0) von cdn.jsdelivr.net (Spiegel von npm)
rem - Handmodell hand_landmarker.task (float16, Version 1, Apache-2.0) von storage.googleapis.com
rem Jede Datei wird per SHA256 geprueft. Falsche oder kaputte Dateien werden nicht uebernommen.
rem Nichts wird installiert. Die Dateien (ca. 30 MB) kommen nicht ins Repo (.gitignore).
setlocal
cd /d "%~dp0"
set "QUELLE=https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35"
set "MODELL=https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
set "ZIEL=%~dp0lib\mediapipe"
set "BERICHT=%~dp0..\data\gesten_holen_bericht.txt"
if not exist "%~dp0..\data" set "BERICHT=%~dp0gesten_holen_bericht.txt"
echo ===== Gesten-Dateien holen %date% %time% ===== > "%BERICHT%"
set FEHLER=0
if not exist "%ZIEL%\wasm" mkdir "%ZIEL%\wasm"
call :HOLEN "%QUELLE%/vision_bundle.mjs" "%ZIEL%\vision_bundle.mjs" 55d7ab624fbb70dcc5adc4ae6d7ea9cfcb569139d3dbfbf2b1deafcb966bc0fe
call :HOLEN "%QUELLE%/wasm/vision_wasm_internal.js" "%ZIEL%\wasm\vision_wasm_internal.js" e7fd9858e8e8f221d9b96eddc11f8e077f263e0b7bbd79d3cbe882b134274f8c
call :HOLEN "%QUELLE%/wasm/vision_wasm_internal.wasm" "%ZIEL%\wasm\vision_wasm_internal.wasm" 6a5c64584c2ab61c763b6e204afbdbc7ce1caf7f5216187322bca8df94f646bc
call :HOLEN "%QUELLE%/wasm/vision_wasm_nosimd_internal.js" "%ZIEL%\wasm\vision_wasm_nosimd_internal.js" 438d1fe8ff7f4d946025bc211c291543c037d8a3785ed4eee60f1f521b236296
call :HOLEN "%QUELLE%/wasm/vision_wasm_nosimd_internal.wasm" "%ZIEL%\wasm\vision_wasm_nosimd_internal.wasm" 8a3092d34c79d3f57e6ba8592105e8a90f6b07c27891ffecd14cca428bfd3e31
call :HOLEN "%MODELL%" "%ZIEL%\hand_landmarker.task" fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1
if "%FEHLER%"=="0" (echo ERGEBNIS=OK >> "%BERICHT%") else (echo ERGEBNIS=FEHLER - Internet pruefen, dann noch einmal starten >> "%BERICHT%")
type "%BERICHT%"
echo.
if "%FEHLER%"=="0" (echo Fertig. In Auron Strg+F5 druecken, dann Knopf "Gesten" oder "Auron, Gesten an".) else (echo Es gab Fehler. Bitte Claude Bescheid geben.)
pause
exit /b 0

:HOLEN
rem %1 = Adresse, %2 = Ziel, %3 = erwartete SHA256-Pruefsumme
set "PRUEF="
curl.exe -s -f -L -o "%~2.neu" "%~1"
if errorlevel 1 (echo FEHLT %~nx2 - Download fehlgeschlagen >> "%BERICHT%" & set FEHLER=1 & del /q "%~2.neu" 2>nul & exit /b 0)
for /f "delims=" %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%~2.neu').Hash"') do set "PRUEF=%%H"
if /i not "%PRUEF%"=="%~3" (echo FEHLER %~nx2 - Pruefsumme falsch >> "%BERICHT%" & set FEHLER=1 & del /q "%~2.neu" 2>nul & exit /b 0)
move /y "%~2.neu" "%~2" >nul
for %%A in ("%~2") do echo OK %%~nxA %%~zA Bytes >> "%BERICHT%"
exit /b 0

@echo off
rem THREE_HOLEN.bat (04.10.2026, Claude): laedt die 3D-Bibliothek Three.js r147 einmalig nach werkstatt\lib\three,
rem damit stadt_3d.html auch ohne Internet laeuft. Nur Download von cdn.jsdelivr.net, nichts wird installiert.
setlocal
cd /d "%~dp0"
set QUELLE=https://cdn.jsdelivr.net/npm/three@0.147.0
set ZIEL=%~dp0lib\three
set BERICHT=%~dp0..\data\three_holen_bericht.txt
echo ===== Three.js holen %date% %time% ===== > "%BERICHT%"
set FEHLER=0
if not exist "%ZIEL%\build" mkdir "%ZIEL%\build"
curl.exe -s -f -L -o "%ZIEL%\build\three.min.js" "%QUELLE%/build/three.min.js"
if errorlevel 1 (echo FEHLT build/three.min.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\build\three.min.js") do echo OK build/three.min.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\controls" mkdir "%ZIEL%\examples\js\controls"
curl.exe -s -f -L -o "%ZIEL%\examples\js\controls\OrbitControls.js" "%QUELLE%/examples/js/controls/OrbitControls.js"
if errorlevel 1 (echo FEHLT examples/js/controls/OrbitControls.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\controls\OrbitControls.js") do echo OK examples/js/controls/OrbitControls.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\objects" mkdir "%ZIEL%\examples\js\objects"
curl.exe -s -f -L -o "%ZIEL%\examples\js\objects\Water.js" "%QUELLE%/examples/js/objects/Water.js"
if errorlevel 1 (echo FEHLT examples/js/objects/Water.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\objects\Water.js") do echo OK examples/js/objects/Water.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\objects" mkdir "%ZIEL%\examples\js\objects"
curl.exe -s -f -L -o "%ZIEL%\examples\js\objects\Sky.js" "%QUELLE%/examples/js/objects/Sky.js"
if errorlevel 1 (echo FEHLT examples/js/objects/Sky.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\objects\Sky.js") do echo OK examples/js/objects/Sky.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\shaders" mkdir "%ZIEL%\examples\js\shaders"
curl.exe -s -f -L -o "%ZIEL%\examples\js\shaders\CopyShader.js" "%QUELLE%/examples/js/shaders/CopyShader.js"
if errorlevel 1 (echo FEHLT examples/js/shaders/CopyShader.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\shaders\CopyShader.js") do echo OK examples/js/shaders/CopyShader.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\shaders" mkdir "%ZIEL%\examples\js\shaders"
curl.exe -s -f -L -o "%ZIEL%\examples\js\shaders\LuminosityHighPassShader.js" "%QUELLE%/examples/js/shaders/LuminosityHighPassShader.js"
if errorlevel 1 (echo FEHLT examples/js/shaders/LuminosityHighPassShader.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\shaders\LuminosityHighPassShader.js") do echo OK examples/js/shaders/LuminosityHighPassShader.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\postprocessing" mkdir "%ZIEL%\examples\js\postprocessing"
curl.exe -s -f -L -o "%ZIEL%\examples\js\postprocessing\EffectComposer.js" "%QUELLE%/examples/js/postprocessing/EffectComposer.js"
if errorlevel 1 (echo FEHLT examples/js/postprocessing/EffectComposer.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\postprocessing\EffectComposer.js") do echo OK examples/js/postprocessing/EffectComposer.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\postprocessing" mkdir "%ZIEL%\examples\js\postprocessing"
curl.exe -s -f -L -o "%ZIEL%\examples\js\postprocessing\RenderPass.js" "%QUELLE%/examples/js/postprocessing/RenderPass.js"
if errorlevel 1 (echo FEHLT examples/js/postprocessing/RenderPass.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\postprocessing\RenderPass.js") do echo OK examples/js/postprocessing/RenderPass.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\postprocessing" mkdir "%ZIEL%\examples\js\postprocessing"
curl.exe -s -f -L -o "%ZIEL%\examples\js\postprocessing\ShaderPass.js" "%QUELLE%/examples/js/postprocessing/ShaderPass.js"
if errorlevel 1 (echo FEHLT examples/js/postprocessing/ShaderPass.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\postprocessing\ShaderPass.js") do echo OK examples/js/postprocessing/ShaderPass.js %%~zA Bytes >> "%BERICHT%")
if not exist "%ZIEL%\examples\js\postprocessing" mkdir "%ZIEL%\examples\js\postprocessing"
curl.exe -s -f -L -o "%ZIEL%\examples\js\postprocessing\UnrealBloomPass.js" "%QUELLE%/examples/js/postprocessing/UnrealBloomPass.js"
if errorlevel 1 (echo FEHLT examples/js/postprocessing/UnrealBloomPass.js >> "%BERICHT%" & set FEHLER=1) else (for %%A in ("%ZIEL%\examples\js\postprocessing\UnrealBloomPass.js") do echo OK examples/js/postprocessing/UnrealBloomPass.js %%~zA Bytes >> "%BERICHT%")
if "%FEHLER%"=="0" (echo ERGEBNIS=OK >> "%BERICHT%") else (echo ERGEBNIS=FEHLER - Internet pruefen >> "%BERICHT%")
type "%BERICHT%"
echo.
echo Fertig. Bitte Claude Bescheid geben.
pause

# auron_app.ps1 (04.10.2026, Claude) - startet Auron als eigenes Fenster (Desktop-Symbol "Auron").
# Ablauf: 1. laeuft der Tunnel zum Mini-PC (127.0.0.1:8001)? Wenn nicht: Tunnel verdeckt starten.
#         2. Antwortet Auron? Wenn nicht: Meldung, auf Wunsch JARVIS STARTEN.bat starten.
#         3. Auron im App-Fenster (ohne Adressleiste) oeffnen: Chrome, sonst Edge.
# Nur ASCII, damit Windows PowerShell die Datei sicher liest.
# 05.10.2026: Chrome/Edge mit eigenem Profil und Autoplay erlaubt (Stimme beim Start ohne Klick).
$ErrorActionPreference = "SilentlyContinue"
Add-Type -AssemblyName System.Windows.Forms
$ip = "192.168.68.139"
$ziel = "max1@$ip"
$url = "http://127.0.0.1:8001/auron"
$health = "http://127.0.0.1:8001/api/health"
$ordner = Split-Path -Parent $MyInvocation.MyCommand.Path
$bericht = Join-Path (Split-Path -Parent $ordner) "data\auron_app_bericht.txt"

function Schreibe($t) { try { Add-Content -Path $bericht -Value ("[" + (Get-Date -Format "dd.MM.yyyy HH:mm:ss") + "] " + $t) } catch {} }
function Antwortet {
  try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $health; return ($r.StatusCode -eq 200) } catch { return $false }
}
function Meldung($text, $knoepfe) {
  return [System.Windows.Forms.MessageBox]::Show($text, "Auron", $knoepfe, [System.Windows.Forms.MessageBoxIcon]::Information)
}

if (-not (Antwortet)) {
  Schreibe "Tunnel fehlt - starte ihn"
  $arg = @("-o","StrictHostKeyChecking=accept-new","-o","ConnectTimeout=10","-o","BatchMode=yes",
           "-o","ServerAliveInterval=30","-o","ExitOnForwardFailure=yes","-N","-L","8001:127.0.0.1:8000",$ziel)
  Start-Process -FilePath "ssh" -ArgumentList $arg -WindowStyle Hidden
  for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Seconds 1
    if (Antwortet) { break }
  }
}

if (-not (Antwortet)) {
  Schreibe "Auron antwortet nicht"
  if (-not (Test-Connection -ComputerName $ip -Count 1 -Quiet)) {
    Meldung "Der Mini-PC ($ip) antwortet nicht. Ist er an? Danach Auron noch einmal starten." ([System.Windows.Forms.MessageBoxButtons]::OK) | Out-Null
    exit 1
  }
  $antwort = Meldung "Auron antwortet nicht. Soll JARVIS STARTEN.bat jetzt gestartet werden?" ([System.Windows.Forms.MessageBoxButtons]::YesNo)
  if ($antwort -eq [System.Windows.Forms.DialogResult]::Yes) {
    Start-Process -FilePath (Join-Path $ordner "JARVIS STARTEN.bat")
  }
  exit 1
}

$browser = $null
$kandidaten = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LocalAppData\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
foreach ($k in $kandidaten) { if ($k -and (Test-Path $k)) { $browser = $k; break } }
# 05.10.2026: Auron nur EINMAL offen. Ist schon ein Auron-Fenster da, wird es nach vorne geholt statt ein zweites zu oeffnen
# (am 05.10. liefen drei Fenster gleichzeitig - jedes mit eigenem 3D-Universum, Tour und Stimme).
$offen = Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" |
  Where-Object { $_.CommandLine -like "*Auron\Browser*" -and $_.CommandLine -like "*--app=*" }
if ($offen) {
  $shell = New-Object -ComObject WScript.Shell
  if ($shell.AppActivate("Auron")) { Schreibe "Auron ist schon offen - Fenster nach vorne geholt"; exit 0 }
}
if ($browser) {
  Schreibe "Oeffne App-Fenster mit $browser"
  # 05.10.2026: eigenes Profil nur fuer Auron, damit die Stimme ohne Klick sprechen darf (Ladebildschirm ohne Startknopf).
  # Das Mikrofon muss in diesem Profil einmal neu erlaubt werden.
  $profil = Join-Path $env:LOCALAPPDATA "Auron\Browser"
  Start-Process -FilePath $browser -ArgumentList @("--app=$url", "--start-maximized", "--user-data-dir=`"$profil`"",
    "--autoplay-policy=no-user-gesture-required", "--no-first-run", "--no-default-browser-check")
} else {
  Schreibe "Kein Chrome/Edge gefunden - Standardbrowser"
  Start-Process $url
}

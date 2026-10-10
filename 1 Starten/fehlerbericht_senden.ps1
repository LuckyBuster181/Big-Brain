# fehlerbericht_senden.ps1 (10.10.2026, Claude Code) - gestartet von FEHLERBERICHT SENDEN.bat. Nur ASCII.
# 1. Holt den Fehlerbericht von Jarvis (Tunnel 127.0.0.1:8001 zum Mini-PC, sonst 127.0.0.1:8000).
# 2. Haengt die Start-Protokolle dieses PCs an (data\jarvis_starten_bericht.txt, data\auron_app_bericht.txt).
# 3. Legt alles als berichte\fehlerbericht.md in KI\Big-Brain-Repo und schiebt es zu GitHub (main).
# Claude liest den Bericht dort. Schluessel, Tokens und Mailadressen werden vorher unkenntlich gemacht.
param([string]$J = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
      [string]$repo = "C:\Users\maxi1\Documents\KI\Big-Brain-Repo",
      [string[]]$adressen = @("http://127.0.0.1:8001/api/fehlerbericht", "http://127.0.0.1:8000/api/fehlerbericht"))
$ErrorActionPreference = "Stop"
$datei = "berichte/fehlerbericht.md"

function Saeubern([string]$t) {
  $t = $t -replace 'sk-ant-[A-Za-z0-9_\-]+', 'sk-ant-***'
  $t = $t -replace '(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]+', '$1***'
  $t = $t -replace '(?i)((?:api[_-]?key|token|secret|passwor[dt]|passwd|client_secret)\s*[=:]\s*)[^\s,;&"'']+', '$1***'
  $t = $t -replace '(?i)([?&](?:token|key|access_token|refresh_token|code|sig|signature)=)[^&\s"'']+', '$1***'
  $t = $t -replace '/calendar/ical/[^\s"'']+', '/calendar/ical/***'
  $t = $t -replace '[\w.+-]+@[\w-]+(?:\.[\w-]+)+', '<mail>'
  $t = $t -replace '\b[A-Za-z0-9_\-]{32,}\b', '***'
  return $t
}

function Ende([string]$text, [int]$code) {
  Write-Host ""
  Write-Host " $text"
  exit $code
}

if (-not (Test-Path (Join-Path $repo ".git"))) {
  Ende "FEHLER: $repo ist kein Git-Ordner. Einmal REPO HOLEN.bat oder REPO HOCHLADEN.bat starten." 1
}
$zweig = (git -C $repo rev-parse --abbrev-ref HEAD).Trim()
if ($zweig -ne "main") { Ende "STOPP: In $repo ist der Zweig '$zweig' aktiv, nicht main. Claude Bescheid geben." 1 }

Write-Host " [1/3] Fehlerbericht von Jarvis holen ..."
$bericht = $null
foreach ($u in $adressen) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 90 -Uri $u
    if ($r.StatusCode -eq 200) {
      $bericht = [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
      Write-Host "       geholt von $u"
      break
    }
  } catch { Write-Host "       $u antwortet nicht" }
}
if (-not $bericht) {
  $bericht = "# Fehlerbericht Auron - $(Get-Date -Format 'dd.MM.yyyy HH:mm')`n`nJARVIS NICHT ERREICHBAR: weder 127.0.0.1:8001 (Tunnel) noch 127.0.0.1:8000 haben geantwortet. Unten die Protokolle dieses PCs.`n"
}

$teile = @($bericht, "", "## Dieser PC ($env:COMPUTERNAME)", "")
foreach ($name in @("jarvis_starten_bericht.txt", "auron_app_bericht.txt")) {
  $p = Join-Path $J "data\$name"
  if (Test-Path $p) {
    $zeilen = Get-Content -Path $p -Tail 80 -Encoding UTF8
    $teile += @("### data\$name (letzte 80 Zeilen)", "", '```', ($zeilen -join "`n"), '```', "")
  } else {
    $teile += @("### data\$name", "", "(fehlt)", "")
  }
}
$text = Saeubern ($teile -join "`n")

Write-Host " [2/3] Neuesten Stand holen ..."
git -C $repo pull --rebase --autostash origin main
if ($LASTEXITCODE -ne 0) { Ende "FEHLER: git pull ging nicht. Bitte die Meldung oben Claude zeigen." 1 }

$ziel = Join-Path $repo "berichte\fehlerbericht.md"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ziel) | Out-Null
[System.IO.File]::WriteAllText($ziel, $text, (New-Object System.Text.UTF8Encoding $false))

Write-Host " [3/3] Zu GitHub schicken ..."
git -C $repo add -- $datei
git -C $repo commit -q -m "Fehlerbericht vom PC $(Get-Date -Format 'dd.MM.yyyy HH:mm')" -- $datei
if ($LASTEXITCODE -ne 0) { Ende "Nichts Neues im Bericht seit dem letzten Senden." 0 }
git -C $repo push origin main
if ($LASTEXITCODE -ne 0) { Ende "FEHLER: git push ging nicht. Bitte die Meldung oben Claude zeigen." 1 }
Ende "Fertig. Claude kann den Bericht jetzt lesen (berichte/fehlerbericht.md)." 0

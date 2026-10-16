# nachtarbeit_heute.ps1 (04.10.2026, Claude): legt den Nachtauftrag aus data\nachtauftrag_5_quellen.txt an
# (einmal, nicht doppelt), zeigt Warteschlange und naechsten Lauf, startet auf Wunsch sofort. Nur ASCII.
param([switch]$Sofort)
$ErrorActionPreference = "Stop"
$ip = "192.168.68.139"
$ziel = "max1@$ip"
$basis = "http://127.0.0.1:8001"
$ordner = Split-Path -Parent $MyInvocation.MyCommand.Path
$datei = Join-Path (Split-Path -Parent $ordner) "data\nachtauftrag_5_quellen.txt"
$marke = Join-Path (Split-Path -Parent $ordner) "data\nachtauftrag_5_angelegt.txt"

function Antwortet {
  try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "$basis/api/health"; return ($r.StatusCode -eq 200) } catch { return $false }
}
if (-not (Antwortet)) {
  Write-Output "Tunnel zum Mini-PC fehlt - starte ihn ..."
  $arg = @("-o","StrictHostKeyChecking=accept-new","-o","ConnectTimeout=10","-o","BatchMode=yes",
           "-o","ServerAliveInterval=30","-o","ExitOnForwardFailure=yes","-N","-L","8001:127.0.0.1:8000",$ziel)
  Start-Process -FilePath "ssh" -ArgumentList $arg -WindowStyle Hidden
  for ($i = 0; $i -lt 25; $i++) { Start-Sleep -Seconds 1; if (Antwortet) { break } }
}
if (-not (Antwortet)) { throw "Auron antwortet nicht (Port 8001). Bitte zuerst AURON STARTEN.bat." }

if (-not (Test-Path $marke)) {
  $text = [System.IO.File]::ReadAllText($datei, [System.Text.Encoding]::UTF8).Trim()
  $json = @{ text = $text; art = "recherche"; quelle = "claude" } | ConvertTo-Json -Compress
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
  $neu = Invoke-RestMethod -Method Post -Uri "$basis/api/nachtauftraege" -ContentType "application/json; charset=utf-8" -Body $bytes
  Write-Output ("ANGELEGT Nr. " + $neu.id + " (" + $neu.status + "): " + $neu.titel)
  if ($neu.rueckfragen -and $neu.rueckfragen.Count -gt 0) { Write-Output ("RUECKFRAGEN: " + ($neu.rueckfragen -join " | ")) }
  Set-Content -Path $marke -Value ("Auftrag " + $neu.id + " angelegt " + (Get-Date -Format "dd.MM.yyyy HH:mm"))
} else {
  Write-Output ("Auftrag schon angelegt (" + (Get-Content $marke) + ").")
}

$l = Invoke-RestMethod -Uri "$basis/api/nachtauftraege"
Write-Output ("NAECHSTER_LAUF=" + $l.naechster_lauf)
Write-Output ("LAEUFT_GERADE=" + $l.laeuft)
foreach ($a in $l.auftraege) {
  if ($a.status -in @("offen","in_arbeit","rueckfrage","vorschlag")) { Write-Output ("  Nr. " + $a.id + " [" + $a.status + "] " + $a.titel) }
}
if ($Sofort) {
  $s = Invoke-RestMethod -Method Post -Uri "$basis/api/nachtarbeit/start"
  Write-Output ("SOFORT_GESTARTET running=" + $s.running)
}

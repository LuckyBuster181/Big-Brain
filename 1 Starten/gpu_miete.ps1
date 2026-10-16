# gpu_miete.ps1 (P24, 16.10.2026, Claude Code): GPU-Miete von Hand bedienen. Nur ASCII. Ungetestet am PC.
#   -Aktion status      Stand zeigen (Deckel, laufender Pod, Alarm). Ruft RunPod NICHT auf.
#   -Aktion aufraeumen  Waechter jetzt: alle Pods im RunPod-Konto pruefen und loeschen, was nicht da sein darf.
#   -Aktion auftrag -Nr 7   offenen Code-Auftrag Nr. 7 SOFORT auf einer gemieteten GPU erledigen (kostet Geld).
#   -Aktion alarmtest   Test-Benachrichtigung an das Echo schicken (P24b, Alexa-Alarm). Zeigt auch, was noch zur Einrichtung fehlt.
param([string]$Aktion = "status", [int]$Nr = 0)
$ErrorActionPreference = "Stop"
$ip = "192.168.68.139"
$ziel = "max1@$ip"
$basis = "http://127.0.0.1:8001"

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

if ($Aktion -eq "status") {
  $s = Invoke-RestMethod -Uri "$basis/api/gpu-miete/status"
  Write-Output ("AKTIV=" + $s.aktiv + "  (ohne RUNPOD_API_KEY in der .env ist die GPU-Miete aus)")
  Write-Output ("MONAT=" + $s.monat + "  AUSGEGEBEN_EUR=" + $s.ausgegeben_eur + "  DECKEL_EUR=" + $s.rahmen_eur + "  REST_EUR=" + $s.rest_eur + "  AMPEL=" + $s.ampel)
  Write-Output ("GPU=" + $s.gpu + "  MODELL=" + $s.modell + "  MAX_STUNDEN=" + $s.max_stunden)
  Write-Output ("FENSTER=" + $s.fenster.von + "-" + $s.fenster.bis + "  JETZT_ERLAUBT=" + $s.fenster.jetzt_erlaubt)
  Write-Output ("LAEUFT_GERADE=" + $s.laeuft)
  foreach ($p in $s.laufend) { Write-Output ("  Pod laut Protokoll: " + $p.name + " seit " + $p.seit) }
  if ($s.alarm) { Write-Output ("ALARM: " + $s.alarm.text) }
  Write-Output $s.volume_hinweis
}
elseif ($Aktion -eq "aufraeumen") {
  $r = Invoke-RestMethod -Method Post -Uri "$basis/api/gpu-miete/aufraeumen" -TimeoutSec 400
  Write-Output ("GEPRUEFT=" + $r.geprueft + "  GELOESCHT=" + $r.geloescht.Count + "  OK=" + $r.ok)
  foreach ($g in $r.geloescht) { Write-Output ("  geloescht: " + $g.name + " (" + $g.grund + ")") }
  foreach ($f in $r.fehler) { Write-Output ("  FEHLER: " + $f) }
}
elseif ($Aktion -eq "auftrag") {
  if ($Nr -le 0) { throw "Bitte die Auftragsnummer angeben." }
  $json = @{ auftrag = $Nr } | ConvertTo-Json -Compress
  $r = Invoke-RestMethod -Method Post -Uri "$basis/api/gpu-miete/auftrag" -ContentType "application/json" -Body $json
  Write-Output ("GESTARTET: Auftrag " + $r.auftrag + ". " + $r.hinweis)
  Write-Output "Bitte jetzt die RunPod-Konsole offen halten: der Pod erscheint, arbeitet und verschwindet wieder."
}
elseif ($Aktion -eq "alarmtest") {
  $s = Invoke-RestMethod -Uri "$basis/api/alarm/status"
  Write-Output ("ALEXA_ALARM_EINGERICHTET=" + $s.alexa_eingerichtet)
  if ($s.alexa_fehlt) { Write-Output ("FEHLT NOCH: " + $s.alexa_fehlt) }
  $r = Invoke-RestMethod -Method Post -Uri "$basis/api/alarm/test" -TimeoutSec 60
  Write-Output ("GESENDET=" + $r.gesendet)
  Write-Output $r.text
  if ($r.gesendet) { Write-Output "Am Echo sollte jetzt der gelbe Ring leuchten. Fragen Sie: Alexa, Benachrichtigungen." }
}
else { throw "Unbekannte Aktion: $Aktion" }

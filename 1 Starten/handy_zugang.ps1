# handy_zugang.ps1 - Zugangscode in der .env sicherstellen, Firewall (nur Heimnetz), Handy-Adresse ermitteln.
# Zeigt den API-Schluessel nie an. Schreibt die .env nur, wenn der Zugangscode fehlt (mit Sicherung).
param([string]$Jarvis)
$ErrorActionPreference = "Stop"
try {
  $env_ = Join-Path $Jarvis ".env"
  if (-not (Test-Path $env_)) { Write-Host "  .env nicht gefunden: $env_"; exit 1 }
  $zeilen = @(Get-Content -Path $env_ -Encoding UTF8)
  $vorhanden = $zeilen | Where-Object { $_ -match '^\s*JARVIS_HANDY_TOKEN\s*=\s*\S{8,}' } | Select-Object -First 1
  if ($vorhanden) {
    $code = ($vorhanden -split '=', 2)[1].Trim().Trim('"').Trim("'")
    Write-Host "  Zugangscode ist schon da."
  } else {
    $zeichen = "abcdefghjkmnpqrstuvwxyz23456789".ToCharArray()
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 10
    $rng.GetBytes($bytes)
    $code = -join ($bytes | ForEach-Object { $zeichen[$_ % $zeichen.Length] })
    $daten = Join-Path $Jarvis "data"
    if (-not (Test-Path $daten)) { New-Item -ItemType Directory -Force $daten | Out-Null }
    Copy-Item -LiteralPath $env_ -Destination (Join-Path $daten "env_sicherung_handy.txt") -Force
    $neu = @($zeilen | Where-Object { $_ -notmatch '^\s*JARVIS_HANDY_TOKEN\s*=' })
    $neu += ("JARVIS_HANDY_TOKEN=" + $code)
    Set-Content -Path $env_ -Value $neu -Encoding UTF8
    Write-Host "  Neuer Zugangscode erzeugt und in der .env gespeichert (Sicherung: data\env_sicherung_handy.txt)."
  }

  # Firewall: Port 8000 nur im privaten Netz (Heimnetz)
  $regel = "Jarvis Handy (Port 8000)"
  $da = (netsh advfirewall firewall show rule name="$regel" | Out-String) -match [regex]::Escape($regel)
  if (-not $da) {
    Write-Host "  Firewall-Freigabe fuer das Heimnetz einrichten - Windows fragt nach Administrator-Rechten ..."
    $argumente = "advfirewall firewall add rule name=""$regel"" dir=in action=allow protocol=TCP localport=8000 profile=private"
    Start-Process -FilePath "netsh.exe" -ArgumentList $argumente -Verb RunAs -Wait -WindowStyle Hidden
  } else {
    Write-Host "  Firewall-Freigabe ist schon da."
  }
  $profil = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($profil -and $profil.NetworkCategory -ne "Private") {
    Write-Host ""
    Write-Host "  ACHTUNG: Ihr Netzwerk steht in Windows auf 'Oeffentlich'. Dann blockt die Firewall das Handy."
    Write-Host "  Aendern: Einstellungen - Netzwerk und Internet - Ihr WLAN/LAN - Netzwerkprofil 'Privat'."
  }

  $ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | Select-Object -First 1).IPv4Address.IPAddress
  if (-not $ip) { Write-Host "  Keine Heimnetz-Adresse gefunden (kein Netzwerk?)."; exit 1 }
  $link = "http://" + $ip + ":8000/handy?zugang=" + $code
  Set-Content -Path (Join-Path $Jarvis "data\handy_link.txt") -Value $link -Encoding ASCII
  exit 0
} catch {
  Write-Host ("  FEHLER: " + $_.Exception.Message)
  exit 1
}

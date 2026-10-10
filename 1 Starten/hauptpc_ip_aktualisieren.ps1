# hauptpc_ip_aktualisieren.ps1 (27.09.2026 abends, Claude)
# Grund: Sir konnte die IP des Haupt-PCs noch nicht in der Deco-App reservieren. Ohne Reservierung kann
# der Router (DHCP) dem Haupt-PC jederzeit eine ANDERE IP geben - dann steht in der .env noch die alte
# HAUPTPC_URL und der Mini-PC erreicht die PC-Steuerung nicht mehr ("Der Haupt-PC antwortet nicht").
# Dieses Skript traegt bei JEDEM Start die aktuelle IP ein, egal ob reserviert oder nicht.
# Wird von JARVIS STARTEN.bat aufgerufen, macht nichts, wenn die PC-Steuerung nicht eingerichtet ist.
param([Parameter(Mandatory = $true)][string]$J)
$ErrorActionPreference = 'Stop'
$envDatei = Join-Path $J '.env'
$utf8 = New-Object System.Text.UTF8Encoding $false

try {
    if (-not (Test-Path $envDatei)) { Write-Host 'HAUPTPC_IP: keine .env gefunden'; exit 0 }
    $text = [IO.File]::ReadAllText($envDatei).TrimStart([char]0xFEFF)
    $m = [regex]::Match($text, '(?m)^HAUPTPC_URL=http://([\d.]+):(\d+)\s*$')
    if (-not $m.Success) { Write-Host 'HAUPTPC_IP: PC-Steuerung noch nicht eingerichtet - ueberspringe'; exit 0 }
    $alteIp = $m.Groups[1].Value
    $port = $m.Groups[2].Value
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like '192.168.68.*' } |
        Select-Object -First 1).IPAddress
    if (-not $ip) { Write-Host 'HAUPTPC_IP: keine 192.168.68.x-Adresse gefunden (Heimnetz? Deco?) - .env bleibt wie sie ist'; exit 0 }
    if ($ip -eq $alteIp) { Write-Host "HAUPTPC_IP=$ip (unveraendert)"; exit 0 }
    Copy-Item $envDatei (Join-Path $J 'data\env_sicherung_ip_auto.txt') -Force
    $neu = [regex]::Replace($text, '(?m)^HAUPTPC_URL=http://[\d.]+:\d+\s*$', "HAUPTPC_URL=http://${ip}:$port")
    [IO.File]::WriteAllText($envDatei, $neu, $utf8)
    Write-Host "HAUPTPC_IP=$ip (geaendert von $alteIp - .env aktualisiert, Sicherung: data\env_sicherung_ip_auto.txt)"
} catch {
    Write-Host "HAUPTPC_IP_FEHLER=$($_.Exception.Message)"
}

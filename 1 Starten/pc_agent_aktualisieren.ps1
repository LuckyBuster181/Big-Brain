# pc_agent_aktualisieren.ps1 (30.09.2026, Claude)
# Grund: Der PC-Agent (pc_agent_windows\jarvis_pc_agent.py) laeuft dauerhaft im Hintergrund.
# Aendert Claude seinen Code, laeuft bis zum naechsten Anmelden noch die alte Version weiter.
# Dieses Skript vergleicht die Version in der Datei mit der laufenden Version und startet den
# Agent nur dann neu, wenn sie sich unterscheiden (oder wenn er gar nicht laeuft).
# Wird von JARVIS STARTEN.bat aufgerufen. Macht nichts, wenn die PC-Steuerung nicht eingerichtet ist.
param([Parameter(Mandatory = $true)][string]$J)
$ErrorActionPreference = 'Stop'
try {
    $agent = Join-Path $J 'pc_agent_windows\jarvis_pc_agent.py'
    $vbs = Join-Path ([Environment]::GetFolderPath('Startup')) 'Jarvis PC-Agent.vbs'
    if (-not (Test-Path $agent) -or -not (Test-Path $vbs)) { Write-Host 'PC_AGENT: nicht eingerichtet - ueberspringe'; exit 0 }
    $m = Select-String -Path $agent -Pattern '^VERSION = "([\d.]+)"' | Select-Object -First 1
    $soll = if ($m) { $m.Matches[0].Groups[1].Value } else { '' }
    $ist = ''
    try { $ist = (Invoke-RestMethod -Uri 'http://127.0.0.1:8766/ping' -TimeoutSec 3).agent_version } catch { $ist = '' }
    if ($ist -and $ist -eq $soll) { Write-Host "PC_AGENT=$ist (aktuell)"; exit 0 }
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*jarvis_pc_agent.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + $vbs + '"') -WorkingDirectory (Split-Path $agent)
    $neu = ''
    for ($i = 0; $i -lt 10 -and -not $neu; $i++) {
        Start-Sleep -Seconds 1
        try { $neu = (Invoke-RestMethod -Uri 'http://127.0.0.1:8766/ping' -TimeoutSec 2).agent_version } catch { $neu = '' }
    }
    if ($neu) { Write-Host "PC_AGENT=$neu (neu gestartet, vorher: $(if ($ist) { $ist } else { 'lief nicht' }))" }
    else { Write-Host 'PC_AGENT_FEHLER=Agent startet nicht - Protokoll: pc_agent_windows\agent_protokoll.txt' }
} catch {
    Write-Host "PC_AGENT_FEHLER=$($_.Exception.Message)"
}

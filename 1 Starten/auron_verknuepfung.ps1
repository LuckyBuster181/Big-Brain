# auron_verknuepfung.ps1 (04.10.2026, Claude): legt "Auron" auf dem Desktop und im Startmenue an. Nur ASCII.
$ErrorActionPreference = "Stop"
$ordner = Split-Path -Parent $MyInvocation.MyCommand.Path
$ico = Join-Path $ordner "auron.ico"
if (-not (Test-Path $ico)) { throw "auron.ico fehlt in $ordner" }
# Icon an einen festen Ort kopieren, damit die Verknuepfung auch bei verschobenem Projektordner das Bild behaelt
$fest = Join-Path $env:LOCALAPPDATA "Auron"
New-Item -ItemType Directory -Force -Path $fest | Out-Null
Copy-Item -Force $ico (Join-Path $fest "auron.ico")
$vbs = Join-Path $ordner "AURON.vbs"
$wsh = New-Object -ComObject WScript.Shell
$orte = @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))
foreach ($o in $orte) {
  $lnk = Join-Path $o "Auron.lnk"
  $s = $wsh.CreateShortcut($lnk)
  $s.TargetPath = "$env:WINDIR\System32\wscript.exe"
  $s.Arguments = '"' + $vbs + '"'
  $s.WorkingDirectory = $ordner
  $s.IconLocation = (Join-Path $fest "auron.ico") + ",0"
  $s.Description = "Auron - Universum und Assistent"
  $s.Save()
  Write-Output ("OK " + $lnk)
}

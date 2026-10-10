' AURON.vbs (04.10.2026, Claude): startet auron_app.ps1 ohne sichtbares Fenster. Nur ASCII.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ordner = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ordner & "\auron_app.ps1""", 0, False

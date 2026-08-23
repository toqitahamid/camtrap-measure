' CamTrap Measure - what Settings > Apps > Uninstall runs.
'
' Same reason as launch.vbs: wscript opens no console, so removing the app is dialog boxes and nothing
' else. The questions, and the removal itself, are in uninstall.ps1.
Option Explicit
Dim shell, here
Set shell = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & here & "\uninstall.ps1""", 0, False

' CamTrap Measure - what install.bat runs.
'
' The installer has a window of its own; a console behind it is noise. wscript is not a console program,
' so starting the installer through it (window style 0) means the setup window is the only thing on
' screen. install.ps1 -Console is still there for a machine where the window cannot be drawn.
Option Explicit
Dim shell, here
Set shell = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & here & "\install.ps1""", 0, False

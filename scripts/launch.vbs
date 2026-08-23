' CamTrap Measure - what the desktop shortcut runs.
'
' A shortcut to a .bat is run by cmd.exe, a console program, so Windows must open a black window and
' leave it there for the whole session. wscript is not a console program: it opens nothing. It starts
' the launcher with window style 0 (hidden), so no console appears at any point - and unlike
' `powershell -WindowStyle Hidden`, not even a black flash. The splash and the app window are the only
' things the researcher sees.
Option Explicit
Dim shell, here, ps, args, i
Set shell = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
ps = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & here & "\launcher.ps1"""
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next
shell.Run ps & args, 0, False

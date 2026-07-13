' Double-click launcher that behaves like a normal app:
'  - First time ever (setup not done yet): opens Run.bat in a visible window,
'    so you can see progress and any error messages.
'  - Every time after that: launches Run.bat with no visible window at all -
'    just double-click, wait a few seconds, and your browser opens.
' To stop the program when it is running hidden, use Stop.bat.

Dim fso, shell, scriptDir, venvPython

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir
venvPython = scriptDir & "\.venv\Scripts\python.exe"

If fso.FileExists(venvPython) Then
    ' Already set up before - run quietly in the background, like a normal app.
    shell.Run """" & scriptDir & "\Run.bat""", 0, False
Else
    ' First run on this computer - show the window so setup / errors are visible.
    shell.Run """" & scriptDir & "\Run.bat""", 1, False
End If

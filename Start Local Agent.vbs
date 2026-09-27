Option Explicit
Dim shell, files, root, python, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = root & "\.venv-client\Scripts\pythonw.exe"
If Not files.FileExists(python) Then
  MsgBox "Missing .venv-client. Install the desktop dependencies first (see README).", 16, "Local Agent"
  WScript.Quit 1
End If
shell.CurrentDirectory = root
command = Chr(34) & python & Chr(34) & " " & Chr(34) & root & "\scripts\desktop-launch.pyw" & Chr(34)
shell.Run command, 0, False

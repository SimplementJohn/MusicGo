Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

' Chemin absolu du script VBS (= dossier d'installation de MusicGo)
sDir = oFSO.GetParentFolderName(WScript.ScriptFullName)

sPythonW  = sDir & "\python\pythonw.exe"
sLauncher = sDir & "\musicgo_launcher.py"

' Verification que les fichiers existent
If Not oFSO.FileExists(sPythonW) Then
    MsgBox "pythonw.exe introuvable :" & vbCrLf & sPythonW, vbCritical, "MusicGo"
    WScript.Quit 1
End If

If Not oFSO.FileExists(sLauncher) Then
    MsgBox "musicgo_launcher.py introuvable :" & vbCrLf & sLauncher, vbCritical, "MusicGo"
    WScript.Quit 1
End If

' Lance pythonw (sans console) avec le launcher, WorkDir = dossier d'installation
' WindowStyle 0 = cache (aucune fenetre)
oShell.Run """" & sPythonW & """ """ & sLauncher & """", 0, False

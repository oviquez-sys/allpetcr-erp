' Crea un acceso directo en el Escritorio para iniciar el ERP AllPetCR,
' usando el logo real como icono.
' Uso: doble clic en este archivo UNA vez. Luego podes borrarlo.

Set oShell = CreateObject("WScript.Shell")
strDesktop = oShell.SpecialFolders("Desktop")
strScriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

Set oShortcut = oShell.CreateShortcut(strDesktop & "\AllPetCR ERP.lnk")
oShortcut.TargetPath = strScriptDir & "\Iniciar_AllPetCR_ERP.bat"
oShortcut.WorkingDirectory = strScriptDir
oShortcut.IconLocation = strScriptDir & "\AllPetCR.ico"
oShortcut.Description = "Iniciar servidor local del ERP AllPetCR"
oShortcut.Save

MsgBox "Listo. Se creo el acceso directo 'AllPetCR ERP' en el Escritorio.", 64, "AllPetCR ERP"

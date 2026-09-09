' ===========================================================================
'  AllPetCR - Crear los accesos directos del Escritorio
' ===========================================================================
'  Doble clic en este archivo UNA vez. Crea (o vuelve a crear) los accesos
'  directos y avisa cuales quedaron listos.
'
'  Se puede correr las veces que haga falta: si un acceso directo ya existe,
'  lo reemplaza. Sirve para reparar uno roto sin borrar nada a mano.
'
'  Por que se rompio el anterior (01/09/2026): el .bat que arranca el ERP
'  tenia la ruta de la carpeta escrita a mano, apuntando al perfil viejo de
'  Windows. Al cambiar el disco quedo apuntando a una carpeta que ya no
'  existia, y el acceso directo dejo de abrir sin decir por que. Ahora el .bat
'  calcula su propia ubicacion, asi que la carpeta se puede mover o renombrar
'  sin romper nada.
'
'  Nota para quien edite este archivo: va sin tildes a proposito. El Windows
'  Script Host lo lee en la pagina de codigos del sistema, no en UTF-8, y los
'  acentos salen como simbolos raros en los mensajes.
' ===========================================================================

Option Explicit

Dim oShell, oFS, strDesktop, strAccesoDir, strRaizERP, strRaizWeb, strMsg, nHechos

Set oShell = CreateObject("WScript.Shell")
Set oFS = CreateObject("Scripting.FileSystemObject")

strDesktop = oShell.SpecialFolders("Desktop")
strAccesoDir = oFS.GetParentFolderName(WScript.ScriptFullName)
strRaizERP = oFS.GetParentFolderName(strAccesoDir)
strRaizWeb = oFS.BuildPath(oFS.GetParentFolderName(strRaizERP), "allpetcr-web")

strMsg = ""
nHechos = 0

' --- 1. El ERP -------------------------------------------------------------
If oFS.FileExists(oFS.BuildPath(strAccesoDir, "Iniciar_AllPetCR_ERP.bat")) Then
    CrearAcceso strDesktop & "\AllPetCR ERP.lnk", _
                oFS.BuildPath(strAccesoDir, "Iniciar_AllPetCR_ERP.bat"), _
                strRaizERP, _
                oFS.BuildPath(strAccesoDir, "AllPetCR.ico"), _
                "Iniciar AllPetCR: punto de venta, inventario y caja"
    strMsg = strMsg & "  - AllPetCR ERP" & vbCrLf
    nHechos = nHechos + 1
Else
    strMsg = strMsg & "  ! No se encontro Iniciar_AllPetCR_ERP.bat" & vbCrLf
End If

' --- 2. El sitio web, si el repo esta al lado ------------------------------
If oFS.FileExists(oFS.BuildPath(strRaizWeb, "Iniciar_AllPetCR_WEB.bat")) Then
    CrearAcceso strDesktop & "\AllPetCR Sitio Web.lnk", _
                oFS.BuildPath(strRaizWeb, "Iniciar_AllPetCR_WEB.bat"), _
                strRaizWeb, _
                oFS.BuildPath(strAccesoDir, "AllPetCR.ico"), _
                "Iniciar el sitio web de AllPetCR en modo desarrollo"
    strMsg = strMsg & "  - AllPetCR Sitio Web" & vbCrLf
    nHechos = nHechos + 1
End If

If nHechos > 0 Then
    MsgBox "Accesos directos creados en el Escritorio:" & vbCrLf & vbCrLf & _
           strMsg & vbCrLf & _
           "Ya podes borrar los accesos directos viejos." & vbCrLf & vbCrLf & _
           "Si el ERP no arranca, revisa que POSTGRES_HOST este configurada" & vbCrLf & _
           "en Windows: el propio .bat te lo explica al abrirlo.", _
           64, "AllPetCR"
Else
    MsgBox "No se pudo crear ningun acceso directo." & vbCrLf & vbCrLf & _
           strMsg & vbCrLf & _
           "Este archivo tiene que quedarse dentro de la carpeta" & vbCrLf & _
           "'acceso-directo' del ERP: calcula las rutas a partir de" & vbCrLf & _
           "donde esta guardado.", _
           48, "AllPetCR"
End If

' --- Crea un acceso directo, reemplazando el que hubiera -------------------
Sub CrearAcceso(strDestino, strObjetivo, strDirTrabajo, strIcono, strDescripcion)
    Dim oAcceso
    If oFS.FileExists(strDestino) Then oFS.DeleteFile strDestino, True
    Set oAcceso = oShell.CreateShortcut(strDestino)
    oAcceso.TargetPath = strObjetivo
    oAcceso.WorkingDirectory = strDirTrabajo
    ' Sin icono propio, Windows pone el de una ventana de comandos y en el
    ' escritorio no se distingue de cualquier otro .bat.
    If oFS.FileExists(strIcono) Then oAcceso.IconLocation = strIcono
    oAcceso.Description = strDescripcion
    oAcceso.Save
End Sub

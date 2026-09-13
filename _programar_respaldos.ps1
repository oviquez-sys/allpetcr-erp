# ===========================================================================
#  AllPetCR - Deja los respaldos corriendo solos
# ===========================================================================
#  Registra dos tareas en el Programador de Windows:
#
#    Diario  21:00  -> solo la base de datos (menos de 1 MB), 30 copias
#    Domingo 21:30  -> base + todas las fotos (~130 MB), 4 copias
#
#  Las dos guardan en OneDrive, fuera de esta computadora, y avisan por correo
#  si algo falla.
#
#  Por que "StartWhenAvailable": si a las 21:00 la computadora estaba apagada,
#  la tarea NO se saltea el dia. Corre apenas se prende. Sin esa opcion, un
#  dia apagado es un dia sin respaldo y nadie se entera; que es exactamente lo
#  que paso entre el 3 de agosto y el 1 de setiembre de 2026.
#
#  Por que las tareas quedan a nombre del usuario y no del sistema: el respaldo
#  necesita el OneDrive de Oscar y el entorno de Python de su perfil. Una tarea
#  corriendo como SYSTEM no ve ninguna de las dos cosas, guardaria en el disco
#  local y creeriamos que hay copia en la nube. Ese error ya se cometio una vez.
#
#  Este archivo va sin tildes a proposito: PowerShell lo lee en la pagina de
#  codigos del sistema y los acentos salen como simbolos raros.
# ===========================================================================

$ErrorActionPreference = "Stop"

# La carpeta de este script es la del ERP. Nunca escribir la ruta a mano: es
# lo que rompio el acceso directo cuando cambio el disco.
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path

function Registrar($nombre, $bat, $disparador, $descripcion) {
    $ruta = Join-Path $carpeta $bat
    if (-not (Test-Path $ruta)) {
        Write-Host "  SALTEADA: no se encontro $bat" -ForegroundColor Yellow
        return $false
    }

    $accion = New-ScheduledTaskAction -Execute $ruta -WorkingDirectory $carpeta

    $ajustes = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -DontStopIfGoingOnBatteries `
        -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -MultipleInstances IgnoreNew

    Register-ScheduledTask -TaskName $nombre `
        -Action $accion -Trigger $disparador -Settings $ajustes `
        -Description $descripcion -Force | Out-Null

    Write-Host "  OK: $nombre" -ForegroundColor Green
    return $true
}

Write-Host ""
Write-Host "Carpeta del ERP: $carpeta"
Write-Host ""
Write-Host "Registrando las tareas de respaldo..." -ForegroundColor Cyan
Write-Host ""

$hechas = 0

if (Registrar "AllPetCR - Respaldo diario" "RESPALDO_DIARIO.bat" `
      (New-ScheduledTaskTrigger -Daily -At "21:00") `
      "Respalda la base de datos del ERP a OneDrive. Avisa por correo si falla.") {
    $hechas++
}

if (Registrar "AllPetCR - Respaldo semanal" "RESPALDO_SEMANAL.bat" `
      (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "21:30") `
      "Respalda base + fotos del ERP a OneDrive. Avisa por correo si falla.") {
    $hechas++
}

# 12/09/2026. Las dos tareas de arriba respaldan la base de ESTA computadora.
# Desde que el ERP corre en DigitalOcean, las ventas del dia ya no pasan por
# aca: el servidor se respalda solo y deja la copia en el bucket. Esta tercera
# tarea es la que la baja a OneDrive, para que quede en otra empresa y otra
# cuenta. Sin ella, el respaldo de la nube vive solo dentro de DigitalOcean.
if (Registrar "AllPetCR - Traer respaldos del servidor" "TRAER_RESPALDOS_NUBE.bat" `
      (New-ScheduledTaskTrigger -Daily -At "22:15") `
      "Baja a OneDrive los respaldos que el servidor hace solo. Falla a proposito si dejan de llegar.") {
    $hechas++
}

Write-Host ""
if ($hechas -ne 3) {
    Write-Host "No se pudieron registrar las tres tareas." -ForegroundColor Red
    Write-Host "Este archivo tiene que estar dentro de la carpeta del ERP,"
    Write-Host "junto a RESPALDO_DIARIO.bat, RESPALDO_SEMANAL.bat y TRAER_RESPALDOS_NUBE.bat."
    return
}

Write-Host "Las dos tareas quedaron programadas." -ForegroundColor Green
Write-Host ""
Write-Host "  Diario  : todos los dias a las 21:00 (solo la base)"
Write-Host "  Semanal : domingos a las 21:30 (base + fotos)"
Write-Host ""
Write-Host "Si la computadora esta apagada a esa hora, la tarea corre apenas"
Write-Host "se prende. No se saltea el dia."
Write-Host ""
Write-Host "Para verlas: menu inicio -> 'Programador de tareas'"
Write-Host ""
Write-Host "Corriendo el respaldo diario UNA VEZ ahora, para comprobar que la" -ForegroundColor Cyan
Write-Host "tarea funciona de verdad y no solo que quedo escrita..." -ForegroundColor Cyan
Write-Host ""

Start-ScheduledTask -TaskName "AllPetCR - Respaldo diario"

# Esperar a que termine de verdad en vez de dormir una cantidad fija de
# segundos: si el respaldo tarda mas que la espera, leeriamos el resultado de
# una corrida que todavia no termino y diriamos que fallo sin que fallara.
$limite = 300
$transcurrido = 0
do {
    Start-Sleep -Seconds 5
    $transcurrido += 5
    $estado = (Get-ScheduledTask -TaskName "AllPetCR - Respaldo diario").State
    Write-Host "  ... $transcurrido s (estado: $estado)"
} while ($estado -eq "Running" -and $transcurrido -lt $limite)

$info = Get-ScheduledTaskInfo -TaskName "AllPetCR - Respaldo diario"
Write-Host ""
Write-Host "  Ultima corrida : $($info.LastRunTime)"
Write-Host "  Resultado      : $($info.LastTaskResult)  (0 = bien)"
Write-Host ""

$log = Join-Path $carpeta "respaldos\log_respaldo_diario.txt"
if (Test-Path $log) {
    Write-Host "  --- ultimas lineas del registro del respaldo ---" -ForegroundColor Cyan
    Get-Content $log -Tail 25 | ForEach-Object { Write-Host "  $_" }
    Write-Host "  --- fin del registro ---" -ForegroundColor Cyan
    Write-Host ""
}

if ($info.LastTaskResult -eq 0) {
    Write-Host "FUNCIONA. El respaldo corrio solo y quedo verificado." -ForegroundColor Green
} else {
    Write-Host "La tarea corrio pero devolvio un error." -ForegroundColor Yellow
    Write-Host "El registro de arriba dice por que. Mostraselo a Claude."
}
Write-Host ""

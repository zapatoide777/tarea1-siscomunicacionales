@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0preparar_entorno.ps1" -Abrir
if errorlevel 1 (
    echo.
    echo No se pudo abrir la interfaz. Revisa el mensaje anterior.
    pause
    exit /b 1
)
endlocal

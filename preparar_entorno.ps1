param([switch]$Abrir)

# Bypass se aplica solo al proceso del lanzador; no cambia politicas del equipo.
$ErrorActionPreference = 'Stop'
$taskProjectRoot = $PSScriptRoot
$taskPython = Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
$taskRequirements = Join-Path $taskProjectRoot 'codigo\receptor\requirements.txt'
$taskApp = Join-Path $taskProjectRoot 'codigo\receptor\interfaz.py'

function Test-TaskPython([string]$Executable, [switch]$Dependencies) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    $taskCheck = 'import sys, tkinter, venv; assert sys.version_info >= (3, 11)'
    if ($Dependencies) {
        $taskCheck += '; import numpy, scipy, cv2, matplotlib, av'
    }
    try {
        & $Executable -c $taskCheck *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

try {
    # Temporales de este proceso y sus hijos; no modifica variables persistentes.
    $taskTemp = Join-Path $taskProjectRoot '.cache\tmp'
    New-Item -ItemType Directory -Path $taskTemp -Force | Out-Null
    $taskCacheItem = Get-Item -LiteralPath (Join-Path $taskProjectRoot '.cache') -Force
    $taskCacheItem.Attributes = $taskCacheItem.Attributes -bor [IO.FileAttributes]::Hidden
    if (Test-Path -LiteralPath (Join-Path $taskProjectRoot '.venv')) {
        $taskVenvItem = Get-Item -LiteralPath (Join-Path $taskProjectRoot '.venv') -Force
        $taskVenvItem.Attributes = $taskVenvItem.Attributes -bor [IO.FileAttributes]::Hidden
    }
    $env:TEMP = $taskTemp
    $env:TMP = $taskTemp
    if (-not (Test-TaskPython $taskPython -Dependencies)) {
        Write-Host 'Preparando Python y bibliotecas de la interfaz...'
        if (-not (Test-TaskPython $taskPython)) {
            $taskCandidates = [System.Collections.Generic.List[string]]::new()
            # Runtime local incluido con Codex, cuando esta disponible.
            $taskCandidates.Add((Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
            foreach ($taskCommandName in @('python.exe', 'python3.exe')) {
                $taskCommand = Get-Command $taskCommandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($taskCommand) { $taskCandidates.Add($taskCommand.Source) }
            }
            $taskLauncher = Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($taskLauncher) {
                try {
                    $taskLauncherPython = & $taskLauncher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
                    if ($LASTEXITCODE -eq 0 -and $taskLauncherPython) { $taskCandidates.Add([string]$taskLauncherPython) }
                } catch { }
            }
            foreach ($taskInstallRoot in @(
                (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
                (Join-Path $env:APPDATA 'uv\python'),
                (Join-Path $env:LOCALAPPDATA 'Python')
            )) {
                if (Test-Path -LiteralPath $taskInstallRoot) {
                    Get-ChildItem -LiteralPath $taskInstallRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                        $taskCandidate = Join-Path $_.FullName 'python.exe'
                        if (Test-Path -LiteralPath $taskCandidate) { $taskCandidates.Add($taskCandidate) }
                    }
                }
            }
            $taskBasePython = $null
            foreach ($taskCandidate in ($taskCandidates | Select-Object -Unique)) {
                if (Test-TaskPython $taskCandidate) {
                    $taskBasePython = $taskCandidate
                    break
                }
            }
            if (-not $taskBasePython) {
                throw 'No se encontro Python 3.11 o posterior con Tkinter. Instala Python para Windows desde https://www.python.org/downloads/windows/ (incluye Tcl/Tk), y vuelve a abrir abrir_interfaz.cmd.'
            }
            Write-Host "Creando entorno local con $taskBasePython"
            & $taskBasePython -m venv (Join-Path $taskProjectRoot '.venv')
            if ($LASTEXITCODE -ne 0) { throw 'Python no pudo crear el entorno .venv.' }
            $taskVenvItem = Get-Item -LiteralPath (Join-Path $taskProjectRoot '.venv') -Force
            $taskVenvItem.Attributes = $taskVenvItem.Attributes -bor [IO.FileAttributes]::Hidden
        }
        # Repara entornos parciales cuya creacion se interrumpio en ensurepip.
        $taskHasPip = $false
        try {
            & $taskPython -c 'import pip' *> $null
            $taskHasPip = ($LASTEXITCODE -eq 0)
        } catch { }
        if (-not $taskHasPip) {
            Write-Host 'Preparando pip en el entorno local...'
            & $taskPython -m ensurepip --upgrade
            if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar pip en .venv. Revisa los mensajes anteriores.' }
        }
        Write-Host 'Instalando bibliotecas. La primera vez requiere internet...'
        & $taskPython -m pip install --disable-pip-version-check -r $taskRequirements
        if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las bibliotecas. Revisa la conexion a internet y vuelve a intentar.' }
        if (-not (Test-TaskPython $taskPython -Dependencies)) {
            throw 'El entorno no puede importar todas las bibliotecas o Tkinter. Revisa los mensajes de instalacion.'
        }
    }

    if ($Abrir) {
        if (-not (Test-Path -LiteralPath $taskApp)) { throw "No se encuentra la aplicacion: $taskApp" }
        $taskPythonWindow = Join-Path $taskProjectRoot '.venv\Scripts\pythonw.exe'
        if (-not (Test-Path -LiteralPath $taskPythonWindow)) { $taskPythonWindow = $taskPython }
        # Bootstrap pequeno: mantiene un error de arranque visible aun con pythonw.
        $taskBootstrap = @'
import ctypes
import os
from pathlib import Path
import runpy
import sys
import traceback

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "codigo" / "receptor"))
os.chdir(root)
try:
    runpy.run_path(str(root / "codigo" / "receptor" / "interfaz.py"), run_name="__main__")
except Exception:
    detail = traceback.format_exc()
    log = root / "resultados" / "interfaz_error.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(detail, encoding="utf-8")
        detail = f"No se pudo iniciar la interfaz.\n\nDetalle guardado en:\n{log}\n\n{detail[-1600:]}"
    except OSError:
        pass
    ctypes.windll.user32.MessageBoxW(None, detail, "Interfaz Morse - error de inicio", 0x10)
'@
        $taskEncoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($taskBootstrap))
        $taskRunCode = "import base64;exec(base64.b64decode('$taskEncoded'))"
        $taskArguments = @('-c', ('"{0}"' -f $taskRunCode), ('"{0}"' -f $taskProjectRoot))
        Start-Process -FilePath $taskPythonWindow -ArgumentList $taskArguments -WorkingDirectory $taskProjectRoot -WindowStyle Hidden | Out-Null
    } else {
        Write-Host 'Entorno listo. Abre abrir_interfaz.cmd con doble clic.'
    }
    exit 0
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

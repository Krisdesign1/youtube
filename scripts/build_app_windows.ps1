param(
    [ValidateSet("gui", "cli", "both")]
    [string]$Mode = "gui",
    [string]$VenvDir = "",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
if (-not $VenvDir) {
    $VenvDir = Join-Path $RootDir ".venv"
}

$PythonBin = Join-Path $VenvDir "Scripts\python.exe"
$SpecDir = Join-Path $RootDir "build\spec\windows"
$WorkDir = Join-Path $RootDir "build\windows"
$DistDir = Join-Path $RootDir "dist\windows"
$SrcDir = Join-Path $RootDir "src"
$CliEntrypoint = Join-Path $RootDir "scripts\entrypoints\cli.py"
$GuiEntrypoint = Join-Path $RootDir "scripts\entrypoints\gui.py"
$IconPath = Join-Path $RootDir "assets\app.ico"

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & $PythonBin @Args
}

function New-AppVenv {
    if (Test-Path $PythonBin) {
        return
    }

    Write-Host "-> Creation de l'environnement virtuel: $VenvDir"
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3 -m venv $VenvDir
    } else {
        & python -m venv $VenvDir
    }
}

function Install-App {
    if ($SkipInstall) {
        return
    }

    Write-Host "-> Installation des dependances de build"
    Invoke-Python -m pip install --upgrade pip
    Invoke-Python -m pip install -e "$($RootDir)[build]"
}

function Invoke-PyInstaller {
    param([string[]]$Args)
    Invoke-Python -m PyInstaller @Args
}

function Build-Gui {
    $args = @(
        "--paths", $SrcDir,
        "--onefile",
        "--windowed",
        "--name", "youtube-script-gui",
        "--distpath", $DistDir,
        "--workpath", $WorkDir,
        "--specpath", $SpecDir
    )
    if (Test-Path $IconPath) {
        $args += @("--icon", $IconPath)
    }
    $args += $GuiEntrypoint
    Invoke-PyInstaller $args
}

function Build-Cli {
    Invoke-PyInstaller @(
        "--paths", $SrcDir,
        "--onefile",
        "--name", "youtube-script",
        "--distpath", $DistDir,
        "--workpath", $WorkDir,
        "--specpath", $SpecDir,
        $CliEntrypoint
    )
}

$IsWindowsHost = [System.Environment]::OSVersion.Platform -eq "Win32NT"
if (-not $IsWindowsHost) {
    throw "Ce script doit etre lance sur Windows pour produire des fichiers .exe Windows."
}

New-AppVenv
Install-App

Write-Host "-> Nettoyage des anciens builds Windows"
Remove-Item -Recurse -Force $WorkDir, $DistDir, $SpecDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $SpecDir | Out-Null

Write-Host "-> Build PyInstaller Windows ($Mode)"
switch ($Mode) {
    "gui" { Build-Gui }
    "cli" { Build-Cli }
    "both" {
        Build-Cli
        Build-Gui
    }
}

Write-Host "Build termine. Fichiers disponibles dans: $DistDir"

# Build a standalone Windows exe for the CAN -> NMEA/UDP GPS bridge.
# Output:  <repo>\dist\gps_bridge.exe
#          <repo>\dist\run_gps_bridge.bat  (double-click helper with editable defaults)
#
# Requires: pip install pyinstaller python-can pyserial
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\build_gps_bridge_exe.ps1
#
param(
    [switch]$SkipInstallDeps
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$scripts = Join-Path $root 'scripts'
$dist = Join-Path $root 'dist'
$work = Join-Path $root 'build\gps_bridge_pyi'
$entry = Join-Path $scripts 'gps_bridge.py'

if (-not (Test-Path $entry)) { throw "gps_bridge.py not found: $entry" }

if (-not $SkipInstallDeps) {
    python -m pip install --quiet --upgrade pyinstaller python-can pyserial
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

New-Item -ItemType Directory -Force -Path $dist | Out-Null
New-Item -ItemType Directory -Force -Path $work | Out-Null

Write-Host "Building gps_bridge.exe (one-file) ..." -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name gps_bridge `
    --paths $scripts `
    --distpath $dist `
    --workpath $work `
    --specpath $work `
    --hidden-import can.interfaces.slcan `
    --hidden-import can.interfaces.pcan `
    --hidden-import can.interfaces.virtual `
    --hidden-import serial `
    --hidden-import serial.tools.list_ports `
    --collect-submodules can.interfaces `
    $entry

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $dist 'gps_bridge.exe'
if (-not (Test-Path $exe)) { throw "Expected output missing: $exe" }

# Double-click helper — edit COM / tablet IP here, or pass args:
#   run_gps_bridge.bat COM4 192.168.1.59
$bat = @"
@echo off
setlocal
REM ============================================================
REM  Standalone CAN -> Wi-Fi GPS bridge (John Deere 616R -> tablet)
REM  Needs: CANable on this PC + same Wi-Fi/LAN as the tablet.
REM
REM  Tablet: Setup -> GPS -> UDP port 9999 -> Listen UDP
REM
REM  Defaults below, or override on the command line:
REM      run_gps_bridge.bat COM4
REM      run_gps_bridge.bat COM4 192.168.1.59
REM      run_gps_bridge.bat COM4 192.168.1.59 250000
REM ============================================================

set "COM=COM2"
set "TABLET_IP=192.168.1.59"
set "CAN_BITRATE=250000"
set "TTY_BAUD=2000000"
set "UDP_PORT=9999"

if not "%~1"=="" set "COM=%~1"
if not "%~2"=="" set "TABLET_IP=%~2"
if not "%~3"=="" set "CAN_BITRATE=%~3"

echo Bridging %COM% (CAN %CAN_BITRATE% bps, tty %TTY_BAUD%) -^> %TABLET_IP%:%UDP_PORT%
echo Ctrl+C to stop.
echo.

"%~dp0gps_bridge.exe" --interface %COM% --bitrate %CAN_BITRATE% --tty-baud %TTY_BAUD% --nmea-udp %TABLET_IP%:%UDP_PORT%
set "RC=%ERRORLEVEL%"

echo.
echo Bridge stopped (exit %RC%). Press any key to close.
pause >nul
exit /b %RC%
"@
Set-Content -Path (Join-Path $dist 'run_gps_bridge.bat') -Value $bat -Encoding ASCII

# Convenience copy next to the PUF-mobile tablet launchers
$mobileDist = Join-Path $root '..\PUF-mobile\dist'
if (Test-Path (Join-Path $root '..\PUF-mobile')) {
    New-Item -ItemType Directory -Force -Path $mobileDist | Out-Null
    Copy-Item $exe (Join-Path $mobileDist 'gps_bridge.exe') -Force
    Copy-Item (Join-Path $dist 'run_gps_bridge.bat') (Join-Path $mobileDist 'run_gps_bridge.bat') -Force
    Write-Host "Also copied to $mobileDist" -ForegroundColor DarkGray
}

$info = Get-Item $exe
Write-Host ""
Write-Host "OK: $($info.FullName)" -ForegroundColor Green
Write-Host "    $($info.Length) bytes  $($info.LastWriteTime)"
Write-Host "Run:  dist\run_gps_bridge.bat"
Write-Host "  or: dist\gps_bridge.exe --interface COM2 --bitrate 250000 --tty-baud 2000000 --nmea-udp 192.168.1.59:9999"

# GPS bridge: 616R CAN -> NMEA (AgOpenGPS AgIO) + optional JSON UDP
param(
    [string]$Interface = "COM2",
    [string]$NmeaUdp = "127.0.0.1:9999",
    [string]$JsonUdp = "",
    [switch]$StdoutJson,
    [switch]$Replay,
    [string]$Session = ""
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$exe = Join-Path $Root 'dist\gps_bridge.exe'
$useExe = Test-Path $exe

if ($Replay -and $Session) {
    $bridgeArgs = @("--replay", "recordings\$Session", "--nmea-udp", $NmeaUdp)
} else {
    $bridgeArgs = @("--interface", $Interface, "--nmea-udp", $NmeaUdp)
}
if ($JsonUdp) { $bridgeArgs += @("--json-udp", $JsonUdp) }
if ($StdoutJson) { $bridgeArgs += "--stdout-json" }

Write-Host "616R GPS bridge (OBSERVE CAN only on $Interface)" -ForegroundColor Cyan
if ($useExe) {
    Write-Host "Using standalone: $exe" -ForegroundColor DarkGray
    & $exe @bridgeArgs
} else {
    python @("scripts/gps_bridge.py") @bridgeArgs
}

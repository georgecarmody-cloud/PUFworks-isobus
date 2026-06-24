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

$pyArgs = @("scripts/gps_bridge.py", "--interface", $Interface, "--nmea-udp", $NmeaUdp)
if ($JsonUdp) { $pyArgs += @("--json-udp", $JsonUdp) }
if ($StdoutJson) { $pyArgs += "--stdout-json" }
if ($Replay -and $Session) {
    $pyArgs = @("scripts/gps_bridge.py", "--replay", "recordings\$Session", "--nmea-udp", $NmeaUdp)
    if ($JsonUdp) { $pyArgs += @("--json-udp", $JsonUdp) }
}

Write-Host "616R GPS bridge (OBSERVE CAN only on $Interface)" -ForegroundColor Cyan
python @pyArgs

# 616R field CAN sniff - OBSERVE-only, no actuation.
# Run from PUFworks-isobus repo root with CANable (COM2) or implement-bus adapter.
#
#   .\scripts\field_sniff_616r.ps1 -Interface COM2 -Label "616r_observe_1" -Record
#   .\scripts\field_sniff_616r.ps1 -Interface COM2 -SniffMode 616r_full -Record -Duration 900

param(
    [string]$Interface = "COM2",
    [ValidateSet("filtered", "spray", "616r", "616r_full")]
    [string]$SniffMode = "spray",
    [string]$Label = "",
    [switch]$Record,
    [int]$Duration = 0
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$pyArgs = @("bench/field_sniff_616r.py", "--interface", $Interface, "--sniff-mode", $SniffMode)
if ($Label) { $pyArgs += @("--label", $Label) }
if ($Record) { $pyArgs += "--record" }
if ($Duration -gt 0) { $pyArgs += @("--duration", $Duration) }

Write-Host "PUFworks 616R field sniff - OBSERVE only (RX-only seal)" -ForegroundColor Cyan
python @pyArgs

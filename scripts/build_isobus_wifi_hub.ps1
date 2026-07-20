# Build PUFworks ISOBUS WiFi Hub - native Windows GUI + headless CLI
# Output: dist\IsobusWifiHub\IsobusWifiHub.exe (+ isobus_wifi_config.json copied beside)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$ContractsRoot = Join-Path (Split-Path -Parent $Root) "PUFworks-contracts\python"
$ContractsPy = Join-Path $ContractsRoot "pufworks_contracts"
if (-not (Test-Path $ContractsPy)) {
    Write-Host "WARNING: PUFworks-contracts not found - build may fail at runtime." -ForegroundColor Yellow
}

Write-Host "Building IsobusWifiHub (native Windows GUI)..." -ForegroundColor Cyan

python -m pip install pyinstaller --quiet 2>$null

$Datas = @(
    "--add-data", "record_filter_lib.py;.",
    "--add-data", "bus_engine.py;.",
    "--add-data", "greenseeker_emitter.py;.",
    "--add-data", "sniff_616r.py;.",
    "--add-data", "spray_pgn_library.py;.",
    "--add-data", "contract_import.py;.",
    "--add-data", "library;library"
)
if (Test-Path $ContractsPy) {
    $Datas += @("--add-data", "$ContractsRoot\pufworks_contracts;pufworks_contracts")
}

$Hidden = @(
    "--hidden-import=can",
    "--hidden-import=can.interface",
    "--hidden-import=can.interfaces.slcan",
    "--hidden-import=can.interfaces.pcan",
    "--hidden-import=can.interfaces.socketcan",
    "--hidden-import=can.interfaces.virtual",
    "--hidden-import=serial",
    "--hidden-import=serial.tools.list_ports",
    "--hidden-import=bus_engine",
    "--hidden-import=greenseeker_emitter",
    "--hidden-import=sniff_616r",
    "--hidden-import=spray_pgn_library",
    "--hidden-import=contract_import",
    "--hidden-import=pufworks_contracts",
    "--hidden-import=isobus_wifi_hub",
    "--hidden-import=isobus_hub_service",
    "--hidden-import=isobus_wifi_web",
    "--hidden-import=isobus_wifi_state",
    "--hidden-import=isobus_wifi_stream",
    "--hidden-import=can_wifi_lib",
    "--hidden-import=gps_bridge_lib",
    "--hidden-import=record_filter_lib",
    "--hidden-import=isobus_record_filter_ui"
)

python -m PyInstaller @Hidden @Datas `
    --noconfirm `
    --onedir `
    --windowed `
    --name IsobusWifiHub `
    --distpath dist `
    --workpath build/pyinstaller `
    scripts/isobus_wifi_gui.py

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Dest = Join-Path $Root "dist\IsobusWifiHub"
$CfgDest = Join-Path $Dest "isobus_wifi_config.json"
$CfgSrc = Join-Path $Root "deploy\windows\isobus_wifi_config.json"
# Never clobber a workshop config that already has Phone IP / COM settings.
if (-not (Test-Path $CfgDest)) {
    Copy-Item $CfgSrc $CfgDest -Force
    Write-Host "Installed default config: $CfgDest" -ForegroundColor DarkGray
} else {
    Write-Host "Kept existing config: $CfgDest" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Built: $Dest\IsobusWifiHub.exe" -ForegroundColor Green
Write-Host "Double-click for native GUI. Headless: IsobusWifiHub.exe --console"

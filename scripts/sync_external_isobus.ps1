# Refresh AgValoniaGPS vendored PUFworks-isobus from the live workshop repo.
# Excludes recordings, node_modules, and runtime logs.
$ErrorActionPreference = "Stop"
$Src = "C:\Projects\PUFworks-isobus"
$Dst = "C:\Projects\AgValoniaGPS-develop\AgValoniaGPS-develop\External\PUFworks-isobus"

if (-not (Test-Path $Src)) { throw "Source not found: $Src" }
New-Item -ItemType Directory -Force -Path $Dst | Out-Null

$excludeDirs = @("recordings", "node_modules", "__pycache__", ".git")
$excludeFiles = @("isobus_diagnostics.log")

robocopy $Src $Dst /MIR /XD $excludeDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /nc /ns /np
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
Write-Host "Synced PUFworks-isobus -> External/PUFworks-isobus"

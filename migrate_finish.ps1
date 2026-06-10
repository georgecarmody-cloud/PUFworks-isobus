# PUFworks split — Phase 0/1 finishing steps that need a shell.
# Idempotent; safe to re-run. See BOUNDARY.md in the PUFVision monolith.
$ErrorActionPreference = "Stop"
$git = "C:\Program Files\Git\cmd\git.exe"
$mono = "C:\Projects\PUFVision"
$contracts = "C:\Projects\PUFworks-contracts"
$isobus = "C:\Projects\PUFworks-isobus"

Write-Host "=== 1. Commit pending monolith work + tag v1-monolith-baseline ==="
Push-Location $mono
& $git add BOUNDARY.md DEV_NOTES.md JD_ISOBUS_MAP.md collector/README.md collector/aim_calibration.py collector/camera_config.json collector/image_collector.py
$pending = & $git status --porcelain BOUNDARY.md DEV_NOTES.md JD_ISOBUS_MAP.md collector
if ($pending) {
    & $git commit -m "Boundary doc + calibration tool fixes (pre-split baseline)"
} else {
    Write-Host "Nothing to commit."
}
$tagExists = & $git tag -l v1-monolith-baseline
if (-not $tagExists) {
    & $git tag v1-monolith-baseline
    Write-Host "Tagged v1-monolith-baseline."
} else {
    Write-Host "Tag v1-monolith-baseline already exists."
}
Pop-Location

Write-Host "=== 2. Copy ISOBUS docs + decode scripts into PUFworks-isobus ==="
Copy-Item "$mono\JD_ISOBUS_MAP.md" "$isobus\JD_ISOBUS_MAP.md" -Force
New-Item -ItemType Directory -Force -Path "$isobus\scripts" | Out-Null
Copy-Item "$mono\scripts\*" "$isobus\scripts\" -Force

Write-Host "=== 3. Init git repos + initial commits ==="
foreach ($repo in @($contracts, $isobus)) {
    Push-Location $repo
    if (-not (Test-Path ".git")) { & $git init -b main }
    & $git add -A
    $dirty = & $git status --porcelain
    if ($dirty) {
        & $git commit -m "Initial extraction from PUFVision v1-monolith-baseline (BOUNDARY.md Phase $(if ($repo -eq $contracts) {'0'} else {'1'}))"
    }
    Pop-Location
}

Write-Host "=== 4. Contract shape tests ==="
python "$contracts\python\tests\test_contracts.py"

Write-Host "=== 5. Bus engine smoke test on virtual bus ==="
python "$isobus\bench\bench_harness.py" --duration 6

Write-Host "=== DONE ==="

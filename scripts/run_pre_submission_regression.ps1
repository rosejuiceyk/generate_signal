<#
Run the complete pre-submission software regression suite with live progress.

Usage from PowerShell:
  Set-ExecutionPolicy -Scope Process Bypass
  .\run_pre_submission_regression.ps1

The script performs tests only.  It does not regenerate simulation data,
overwrite frozen V6 outputs, or modify the manuscript.
#>

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

Write-Host ""
Write-Host "=== He-3 pre-submission regression ===" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Write-Host "Environment: signal_create"
Write-Host "Scope: 229 collected tests (unit + integration)"
Write-Host ""
Write-Host "Live test names will appear below. Do not close this window while tests are running." -ForegroundColor Yellow
Write-Host ""

conda run --no-capture-output -n signal_create python -m pytest -vv --tb=short --durations=15
$testExitCode = $LASTEXITCODE

Write-Host ""
if ($testExitCode -eq 0) {
    Write-Host "PASS: complete regression finished successfully." -ForegroundColor Green
} else {
    Write-Host "FAIL: pytest exited with code $testExitCode. Keep the displayed failure traceback." -ForegroundColor Red
}

Write-Host ""
Read-Host "Press Enter to close"
exit $testExitCode

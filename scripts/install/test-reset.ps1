# Reset test environment for install.ps1 testing
#
# This script removes frago and optionally uv to simulate a fresh user environment.
#
# Usage:
#   .\scripts\test-reset.ps1          # Remove frago only
#   .\scripts\test-reset.ps1 -All     # Remove frago + uv (full reset)

param(
    [switch]$All
)

$ErrorActionPreference = "Continue"

function Write-Info { param($msg) Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[-] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "━━━ Test Environment Reset ━━━" -ForegroundColor Cyan
Write-Host ""

# 1. Stop frago server if running
if (Get-Command frago -ErrorAction SilentlyContinue) {
    try {
        $status = & frago server status 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Stopping frago server..."
            & frago server stop 2>$null
        }
    } catch {}
}

# 2. Uninstall frago via uv tool
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $tools = & uv tool list 2>$null
    if ($tools -match "frago-cli") {
        Write-Info "Uninstalling frago-cli..."
        & uv tool uninstall frago-cli
    } else {
        Write-Warn "frago-cli not installed via uv tool"
    }
}

# 3. Remove frago from common PATH locations
$localBin = "$env:USERPROFILE\.local\bin"
if (Test-Path "$localBin\frago.exe") {
    Write-Info "Removing $localBin\frago.exe"
    Remove-Item "$localBin\frago.exe" -Force
}

# 4. Full reset: also remove uv
if ($All) {
    Write-Warn "Full reset: removing uv..."

    # Remove uv binary
    if (Test-Path "$localBin\uv.exe") {
        Write-Info "Removing $localBin\uv.exe"
        Remove-Item "$localBin\uv.exe" -Force
        Remove-Item "$localBin\uvx.exe" -Force -ErrorAction SilentlyContinue
    }

    # Remove uv cache and data
    $uvCache = "$env:LOCALAPPDATA\uv"
    if (Test-Path $uvCache) {
        Write-Info "Removing $uvCache"
        Remove-Item $uvCache -Recurse -Force
    }

    $uvData = "$env:APPDATA\uv"
    if (Test-Path $uvData) {
        Write-Info "Removing $uvData"
        Remove-Item $uvData -Recurse -Force
    }
}

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host ""
Write-Host "━━━ Verification ━━━" -ForegroundColor Cyan
Write-Host ""

# Verify removal
if (Get-Command frago -ErrorAction SilentlyContinue) {
    Write-Err "frago still found: $((Get-Command frago).Source)"
} else {
    Write-Info "frago removed successfully"
}

if ($All) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Err "uv still found: $((Get-Command uv).Source)"
    } else {
        Write-Info "uv removed successfully"
    }
}

Write-Host ""
Write-Info "Reset complete. Run install.ps1 to test:"
Write-Host "    .\install.ps1"
Write-Host ""

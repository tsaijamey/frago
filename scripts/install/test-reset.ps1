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

function Stop-PythonProcesses {
    # Stop Python processes that may be locking files
    $pythonProcesses = Get-Process -Name python*, frago* -ErrorAction SilentlyContinue
    if ($pythonProcesses) {
        Write-Warn "Stopping Python/frago processes..."
        $pythonProcesses | ForEach-Object {
            Write-Info "  Stopping $($_.ProcessName) (PID: $($_.Id))"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }
}

function Remove-LockedDirectory {
    param([string]$Path)

    if (-not (Test-Path $Path)) { return }

    Write-Info "Removing $Path"

    # First attempt: normal removal
    try {
        Remove-Item $Path -Recurse -Force -ErrorAction Stop
        return
    } catch {}

    # Second attempt: stop processes and retry
    Stop-PythonProcesses
    try {
        Remove-Item $Path -Recurse -Force -ErrorAction Stop
        return
    } catch {}

    # Third attempt: remove files one by one, skip locked ones
    Write-Warn "  Some files locked, removing what we can..."
    Get-ChildItem $Path -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force -Recurse -Confirm:$false -ErrorAction SilentlyContinue
    }
    Remove-Item $Path -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue

    if (Test-Path $Path) {
        Write-Err "  Could not fully remove $Path (files locked)"
        Write-Warn "  Try closing all terminals and run again, or reboot"
    }
}

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
    Remove-Item "$localBin\frago.exe" -Force -ErrorAction SilentlyContinue
}

# 4. Full reset: also remove uv
if ($All) {
    Write-Warn "Full reset: removing uv..."

    # Stop any Python processes first
    Stop-PythonProcesses

    # Try to uninstall via WinGet first (if installed that way)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $wingetList = & winget list --id astral-sh.uv 2>$null
        if ($wingetList -match "astral-sh.uv") {
            Write-Info "Uninstalling uv via WinGet..."
            & winget uninstall --id astral-sh.uv --silent 2>$null
        }
    }

    # Remove uv binary from common locations
    $uvLocations = @(
        "$localBin\uv.exe",
        "$localBin\uvx.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uvx.exe"
    )
    foreach ($loc in $uvLocations) {
        if (Test-Path $loc) {
            Write-Info "Removing $loc"
            Remove-Item $loc -Force -ErrorAction SilentlyContinue
        }
    }

    # Remove uv cache and data directories
    Remove-LockedDirectory "$env:LOCALAPPDATA\uv"
    Remove-LockedDirectory "$env:APPDATA\uv"
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

# frago LOCAL installation script for Windows
#
# Usage (run from repository root):
#   .\local_install.ps1
#
# This script builds frago from source instead of installing from PyPI.
# Use install.ps1 for production installations.

$ErrorActionPreference = "Stop"

# ═══════════════════════════════════════════════════════════════════════════════
# Color and Style Functions
# ═══════════════════════════════════════════════════════════════════════════════

# Check if Windows Terminal (supports true color)
$UseAnsiColors = $env:WT_SESSION -or $env:TERM_PROGRAM

function Write-GradientLine {
    param([string]$Text, [int]$Index)

    if ($UseAnsiColors) {
        # Green gradient for local build
        $colors = @(
            "`e[38;2;0;255;127m",    # spring green
            "`e[38;2;0;220;100m",    # light green
            "`e[38;2;0;180;80m",     # medium green
            "`e[38;2;0;140;60m",     # green
            "`e[38;2;0;100;50m",     # dark green
            "`e[38;2;0;70;35m"       # deep green
        )
        $reset = "`e[0m"
        Write-Host "$($colors[$Index])$Text$reset"
    } else {
        # Fallback: use PowerShell colors
        $psColors = @("Green", "Green", "DarkGreen", "DarkGreen", "DarkGreen", "DarkGreen")
        Write-Host $Text -ForegroundColor $psColors[$Index]
    }
}

function Write-Banner {
    Write-Host ""
    Write-GradientLine '███████╗██████╗  █████╗  ██████╗  ██████╗ ' 0
    Write-GradientLine '██╔════╝██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗' 1
    Write-GradientLine '█████╗  ██████╔╝███████║██║  ███╗██║   ██║' 2
    Write-GradientLine '██╔══╝  ██╔══██╗██╔══██║██║   ██║██║   ██║' 3
    Write-GradientLine '██║     ██║  ██║██║  ██║╚██████╔╝╚██████╔╝' 4
    Write-GradientLine '╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ' 5
    Write-Host "           [LOCAL BUILD]" -ForegroundColor Yellow
    Write-Host ""
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "━━━ $Title ━━━" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success {
    param([string]$Message)
    Write-Host " + $Message" -ForegroundColor Green
}

function Write-Step {
    param([string]$Message)
    Write-Host "   $Message" -ForegroundColor Cyan -NoNewline
}

function Write-Done {
    param([string]$Message)
    Write-Host "`r + $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "   $Message" -ForegroundColor DarkGray
}

function Write-Err {
    param([string]$Message)
    Write-Host " ✗ $Message" -ForegroundColor Red
}

# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

function Test-Command {
    param([string]$Command)
    return [bool](Get-Command $Command -ErrorAction SilentlyContinue)
}

function Get-CommandVersion {
    param([string]$Command)
    try {
        $output = & $Command --version 2>$null | Select-Object -First 1
        return $output
    } catch {
        return "unknown"
    }
}

function Update-SessionPath {
    # Get paths from registry
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")

    # Split all paths into arrays
    $currentPaths = $env:Path -split ';' | Where-Object { $_ }
    $registryPaths = ($machinePath + ";" + $userPath) -split ';' | Where-Object { $_ }

    # Add new registry paths that don't exist in current session
    $newPaths = $registryPaths | Where-Object { $_ -notin $currentPaths }

    if ($newPaths) {
        $env:Path = ($newPaths -join ';') + ";" + $env:Path
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Installation Functions
# ═══════════════════════════════════════════════════════════════════════════════

function Install-Uv {
    if (Test-Command "uv") {
        $version = Get-CommandVersion "uv"
        Write-Success "uv $version"
        return
    }

    Write-Step "Installing uv..."

    try {
        $response = Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing
        # Handle both string and byte array responses (varies by PowerShell version)
        $installScript = if ($response.Content -is [byte[]]) {
            [System.Text.Encoding]::UTF8.GetString($response.Content)
        } else {
            $response.Content
        }
        Invoke-Expression $installScript *>$null
        Update-SessionPath

        if (Test-Command "uv") {
            $version = Get-CommandVersion "uv"
            Write-Done "uv $version"
        } else {
            Write-Err "uv installation failed"
            exit 1
        }
    }
    catch {
        Write-Err "Failed to install uv: $_"
        exit 1
    }
}

function Test-Node {
    if (Test-Command "node") {
        $version = Get-CommandVersion "node"
        Write-Success "Node.js $version"
        return $true
    } else {
        Write-Err "Node.js not found (required for building frontend)"
        Write-Info "Install from: https://nodejs.org/"
        exit 1
    }
}

function Test-Pnpm {
    if (Test-Command "pnpm") {
        $version = Get-CommandVersion "pnpm"
        Write-Success "pnpm $version"
        return
    }

    Write-Step "Installing pnpm..."
    & npm install -g pnpm *>$null
    Update-SessionPath

    if (Test-Command "pnpm") {
        $version = Get-CommandVersion "pnpm"
        Write-Done "pnpm $version"
    } else {
        Write-Err "pnpm installation failed"
        exit 1
    }
}

function Build-Frontend {
    Write-Step "Building frontend..."

    Push-Location "src/frago/client"
    try {
        & pnpm install --frozen-lockfile *>$null 2>&1
        if ($LASTEXITCODE -ne 0) {
            & pnpm install *>$null
        }
        & pnpm build *>$null
        Write-Done "Frontend built"
    } catch {
        Write-Err "Frontend build failed: $_"
        exit 1
    } finally {
        Pop-Location
    }
}

function Install-FragoLocal {
    Update-SessionPath

    Write-Step "Building frago from source..."

    # Clean previous builds
    Remove-Item -Path "dist" -Recurse -Force -ErrorAction SilentlyContinue

    # Build wheel
    & uv build *>$null

    # Find and install the wheel
    $wheel = Get-ChildItem -Path "dist" -Filter "*.whl" | Select-Object -First 1
    if (-not $wheel) {
        Write-Err "Build failed - no wheel found"
        exit 1
    }

    # Install with force to replace any existing version
    & uv tool install $wheel.FullName --force *>$null
    Update-SessionPath

    if (Test-Command "frago") {
        $version = Get-CommandVersion "frago"
        Write-Done "frago $version (from source)"
    } else {
        Write-Err "frago installation failed"
        exit 1
    }
}

function Show-NextSteps {
    Write-Section "Getting Started"

    Write-Host "  " -NoNewline
    Write-Host "Commands:" -ForegroundColor DarkGray
    Write-Host "    " -NoNewline
    Write-Host "frago start" -ForegroundColor White -NoNewline
    Write-Host "         Start frago and open Web UI"
    Write-Host "    " -NoNewline
    Write-Host "frago --help" -ForegroundColor White -NoNewline
    Write-Host "        Show all available commands"
    Write-Host ""
}

function Wait-ForServer {
    # Wait for server to accept connections (max 30 seconds)
    $maxAttempts = 30

    for ($attempt = 0; $attempt -lt $maxAttempts; $attempt++) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("127.0.0.1", 8093)
            $tcp.Close()
            # Port is open, wait a bit more for HTTP to be fully ready
            Start-Sleep -Seconds 2
            return $true
        } catch {
            # Server not ready yet
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-Frago {
    Write-Section "Launching"

    Update-SessionPath
    Write-Host "  " -NoNewline
    Write-Host "Starting frago server..." -ForegroundColor DarkGray

    # Stop any existing server first, then start fresh
    & frago server stop *>$null
    Start-Sleep -Seconds 2  # Give port time to be released
    & frago server start *>$null

    # Wait for server to be ready before opening browser
    if (Wait-ForServer) {
        Write-Host "  " -NoNewline
        Write-Host "Opening browser..." -ForegroundColor DarkGray
        Write-Host ""
        Start-Process "http://127.0.0.1:8093"
    } else {
        Write-Host " ~ Server did not start in time. Run 'frago start' manually." -ForegroundColor Yellow
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

function Main {
    # Ensure we're in the repository root
    if (-not (Test-Path "pyproject.toml") -or -not (Test-Path "src/frago")) {
        Write-Err "This script must be run from the frago repository root"
        exit 1
    }

    Write-Banner

    Write-Section "Environment"
    $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
    Write-Success "Windows ($arch)"

    Write-Section "Dependencies"
    Install-Uv
    Test-Node
    Test-Pnpm

    Write-Section "Build"
    Build-Frontend
    Install-FragoLocal

    Show-NextSteps
    Start-Frago
}

Main

# frago installation script for Windows
#
# Usage:
#   irm https://frago.ai/install.ps1 | iex

$ErrorActionPreference = "Stop"

# ═══════════════════════════════════════════════════════════════════════════════
# Color and Style Functions
# ═══════════════════════════════════════════════════════════════════════════════

# Check if Windows Terminal (supports true color)
$UseAnsiColors = $env:WT_SESSION -or $env:TERM_PROGRAM

function Write-GradientLine {
    param([string]$Text, [int]$Index)

    if ($UseAnsiColors) {
        $colors = @(
            "`e[38;2;0;255;255m",    # cyan
            "`e[38;2;0;191;255m",    # deep sky blue
            "`e[38;2;65;105;225m",   # royal blue
            "`e[38;2;138;43;226m",   # blue violet
            "`e[38;2;148;0;211m",    # dark violet
            "`e[38;2;186;85;211m"    # medium orchid
        )
        $reset = "`e[0m"
        Write-Host "$($colors[$Index])$Text$reset"
    } else {
        # Fallback: use PowerShell colors
        $psColors = @("Cyan", "Cyan", "Blue", "Magenta", "DarkMagenta", "Magenta")
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

function Install-Frago {
    Update-SessionPath

    if (Test-Command "frago") {
        $version = Get-CommandVersion "frago"
        Write-Step "Upgrading frago..."

        try {
            & uv tool upgrade frago-cli *>$null
        } catch {
            & uv tool install frago-cli --force *>$null
        }

        Update-SessionPath
        $newVersion = Get-CommandVersion "frago"
        Write-Done "frago $newVersion"
    } else {
        Write-Step "Installing frago..."
        & uv tool install frago-cli *>$null
        Update-SessionPath

        if (Test-Command "frago") {
            $version = Get-CommandVersion "frago"
            Write-Done "frago $version"
        } else {
            Write-Err "frago installation failed"
            exit 1
        }
    }
}

function Show-NextSteps {
    Write-Section "Getting Started"

    Write-Host "  " -NoNewline
    Write-Host "Commands:" -ForegroundColor DarkGray
    Write-Host "    " -NoNewline
    Write-Host "frago start" -ForegroundColor White -NoNewline
    Write-Host "       Start frago and open Web UI"
    Write-Host "    " -NoNewline
    Write-Host "frago --help" -ForegroundColor White -NoNewline
    Write-Host "      Show all available commands"
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
    # (restart can fail on Windows due to process termination issues)
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
    Write-Banner

    Write-Section "Environment"
    $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
    Write-Success "Windows ($arch)"

    Write-Section "Dependencies"
    Install-Uv
    Install-Frago

    Show-NextSteps
    Start-Frago
}

Main

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
        if ($Command -eq "tmux") {
            $output = & tmux -V 2>$null | Select-Object -First 1
            return "$output".Trim()
        }
        if ($Command -eq "ffmpeg") {
            $output = & ffmpeg -version 2>$null | Select-Object -First 1
            return ("$output" -replace '\s+Copyright.*$', '').Trim()
        }
        $output = & $Command --version 2>$null | Select-Object -First 1
        return "$output".Trim()
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

function Select-NetworkMirror {
    if ($env:FRAGO_INSTALL_SOURCE -eq "official") { return }
    $useMirror = $env:FRAGO_INSTALL_SOURCE -in @("cn", "mirror")
    if (-not $useMirror) {
        try {
            $req = [System.Net.HttpWebRequest]::Create("https://github.com/astral-sh/uv")
            $req.Method = "HEAD"
            $req.Timeout = 3000
            $resp = $req.GetResponse()
            $resp.Close()
        } catch {
            $useMirror = $true
        }
    }
    if ($useMirror) {
        if (-not $env:UV_DEFAULT_INDEX) {
            $env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
        }
        if (-not $env:UV_PYTHON_INSTALL_MIRROR) {
            $env:UV_PYTHON_INSTALL_MIRROR = "https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone"
        }
        try {
            [System.Environment]::SetEnvironmentVariable("UV_DEFAULT_INDEX", $env:UV_DEFAULT_INDEX, "User")
            [System.Environment]::SetEnvironmentVariable("UV_PYTHON_INSTALL_MIRROR", $env:UV_PYTHON_INSTALL_MIRROR, "User")
        } catch {}
        Write-Success "Network source: China Mainland Mirror (Tsinghua PyPI + NJU Python)"
    }
}

function Install-Dependencies {
    Update-SessionPath
    if ((-not (Test-Command "git")) -or (-not (Test-Command "tmux")) -or (-not (Test-Command "ffmpeg")) -or (-not (Test-Command "uv"))) {
        if (Test-Path ".\install.ps1") {
            & .\install.ps1 -NoStart
            Update-SessionPath
        }
    }

    foreach ($cmd in @("git", "tmux", "ffmpeg", "uv")) {
        if (Test-Command $cmd) {
            $version = Get-CommandVersion $cmd
            Write-Success "$cmd ($version)"
        } else {
            Write-Err "$cmd installation failed"
            exit 1
        }
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
    try { & uv tool update-shell *>$null } catch {}
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
    Select-NetworkMirror

    Write-Section "Dependencies"
    Install-Dependencies

    Write-Section "Build"
    Install-FragoLocal

    Show-NextSteps
    Start-Frago
}

Main

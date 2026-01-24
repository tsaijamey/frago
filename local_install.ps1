# frago LOCAL installation script for Windows
#
# Usage:
#   .\local_install.ps1
#
# NOTE: This script installs from local dist/ directory instead of PyPI

$ErrorActionPreference = "Stop"

# Capture script directory at top level (required for functions)
$script:ScriptDirectory = $PSScriptRoot
if (-not $script:ScriptDirectory) {
    $script:ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# ═══════════════════════════════════════════════════════════════════════════════
# Color and Style Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Check if Windows Terminal (supports true color)
$UseAnsiColors = $env:WT_SESSION -or $env:TERM_PROGRAM

# ANSI codes for styling
if ($UseAnsiColors) {
    $script:RESET = "`e[0m"
    $script:BOLD = "`e[1m"
    $script:DIM = "`e[2m"
    $script:CYAN = "`e[36m"
    $script:GREEN = "`e[32m"
    $script:YELLOW = "`e[33m"
    $script:RED = "`e[31m"
} else {
    $script:RESET = ""
    $script:BOLD = ""
    $script:DIM = ""
    $script:CYAN = ""
    $script:GREEN = ""
    $script:YELLOW = ""
    $script:RED = ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# Progress Display
# ═══════════════════════════════════════════════════════════════════════════════

$script:TOTAL_STEPS = 7
$script:CURRENT_STEP = 0

function Write-GradientLine {
    param([string]$Text, [int]$Index)

    if ($UseAnsiColors) {
        $colors = @(
            "`e[38;2;0;255;127m",    # spring green (bright)
            "`e[38;2;0;220;100m",    # light green
            "`e[38;2;0;180;80m",     # medium green
            "`e[38;2;0;140;60m",     # green
            "`e[38;2;0;100;50m",     # dark green
            "`e[38;2;0;70;35m"       # deep green
        )
        $reset = "`e[0m"
        Write-Host "$($colors[$Index])$Text$reset"
    } else {
        # Fallback: use PowerShell colors (green gradient approximation)
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
    Write-Host ""
    Write-Host "   [LOCAL INSTALL]" -ForegroundColor Yellow
    Write-Host ""
}

# Print step with dots padding, no newline
function Write-Step {
    param([string]$Task)
    $script:CURRENT_STEP++
    # Calculate padding (38 chars total for task + dots)
    $taskLen = $Task.Length
    $dotsCount = 38 - $taskLen
    if ($dotsCount -lt 1) { $dotsCount = 1 }
    $dots = "." * $dotsCount
    if ($UseAnsiColors) {
        Write-Host "$($script:DIM)[$($script:CURRENT_STEP)/$($script:TOTAL_STEPS)]$($script:RESET) $Task $dots " -NoNewline
    } else {
        Write-Host "[$($script:CURRENT_STEP)/$($script:TOTAL_STEPS)] $Task $dots " -ForegroundColor DarkGray -NoNewline
    }
}

# Print success result
function Write-Ok {
    param([string]$Message)
    if ($UseAnsiColors) {
        Write-Host "$($script:GREEN)$Message$($script:RESET)"
    } else {
        Write-Host $Message -ForegroundColor Green
    }
}

# Print error result and exit
function Write-Fail {
    param([string]$Message)
    if ($UseAnsiColors) {
        Write-Host "$($script:RED)$Message$($script:RESET)"
    } else {
        Write-Host $Message -ForegroundColor Red
    }
    exit 1
}

# Print warning result
function Write-Warn {
    param([string]$Message)
    if ($UseAnsiColors) {
        Write-Host "$($script:YELLOW)$Message$($script:RESET)"
    } else {
        Write-Host $Message -ForegroundColor Yellow
    }
}

function Write-Err {
    param([string]$Message)
    Write-Host " x $Message" -ForegroundColor Red
}

# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

function Exit-VirtualEnv {
    # Exit any active virtual environment to ensure we use uv tool installed frago
    if ($env:VIRTUAL_ENV) {
        # Remove virtual environment paths from PATH (filter by actual VIRTUAL_ENV value)
        $venvPattern = [regex]::Escape($env:VIRTUAL_ENV)
        $env:Path = ($env:Path -split ';' | Where-Object { $_ -and $_ -notmatch "^$venvPattern" }) -join ';'
        # Remove VIRTUAL_ENV variable
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    }
}

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
# Installation Steps
# ═══════════════════════════════════════════════════════════════════════════════

function Step-DetectPlatform {
    Write-Step "Detecting platform"
    $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
    Write-Ok "Windows ($arch)"
}

function Step-CheckUv {
    Write-Step "Checking uv"

    if (Test-Command "uv") {
        $version = Get-CommandVersion "uv"
        Write-Ok $version
        return
    }

    # Need to install uv
    if ($UseAnsiColors) {
        Write-Host "$($script:DIM)installing...$($script:RESET) " -NoNewline
    } else {
        Write-Host "installing... " -ForegroundColor DarkGray -NoNewline
    }

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
            Write-Ok $version
        } else {
            Write-Fail "install failed"
        }
    }
    catch {
        Write-Fail "install failed"
    }
}

function Step-BuildFrontend {
    Write-Step "Building UI"

    $WebDir = Join-Path $script:ScriptDirectory "src\frago\server\web"

    if (-not (Test-Command "pnpm")) {
        Write-Fail "pnpm not found"
    }

    try {
        Push-Location $WebDir
        & pnpm install --frozen-lockfile *>$null
        & pnpm build *>$null
        Pop-Location
        Write-Ok "done"
    }
    catch {
        Pop-Location
        Write-Fail "build failed"
    }
}

function Step-BuildPackage {
    Write-Step "Packaging"

    try {
        Push-Location $script:ScriptDirectory
        & uv build *>$null
        Pop-Location
        Write-Ok "done"
    }
    catch {
        Pop-Location
        Write-Fail "build failed"
    }
}

function Step-InstallFrago {
    Write-Step "Installing frago"

    Update-SessionPath
    $DistDir = Join-Path $script:ScriptDirectory "dist"

    # Find the newest wheel file
    $WheelFile = Get-ChildItem -Path $DistDir -Filter "frago_cli-*.whl" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1

    if (-not $WheelFile) {
        Write-Fail "wheel not found"
    }

    try {
        if (Test-Command "frago") {
            & uv tool install $WheelFile.FullName --force *>$null
        } else {
            & uv tool install $WheelFile.FullName *>$null
        }

        Update-SessionPath

        if (Test-Command "frago") {
            $version = Get-CommandVersion "frago"
            Write-Ok $version
        } else {
            Write-Fail "install failed"
        }
    }
    catch {
        Write-Fail "install failed"
    }
}

function Step-CreateShortcut {
    Write-Step "Creating shortcut"

    Update-SessionPath

    try {
        # Get frago executable path
        $FragoBin = (Get-Command frago -ErrorAction SilentlyContinue).Source
        if (-not $FragoBin) {
            Write-Warn "skipped"
            return
        }

        # Icon source
        $IconSrc = Join-Path $script:ScriptDirectory "src\frago\server\assets\icons\frago.ico"
        $IconPng = Join-Path $script:ScriptDirectory "src\frago\server\assets\icons\frago.png"

        # Windows Start Menu shortcut
        $StartMenuDir = [System.IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs")
        $ShortcutPath = Join-Path $StartMenuDir "frago.lnk"

        # Create shortcut using WScript.Shell COM object
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $FragoBin
        $Shortcut.Arguments = "start"
        $Shortcut.WorkingDirectory = $env:USERPROFILE
        $Shortcut.Description = "AI-powered automation framework"

        # Set icon (prefer .ico, fallback to .png, then exe itself)
        if (Test-Path $IconSrc) {
            $Shortcut.IconLocation = $IconSrc
        } elseif (Test-Path $IconPng) {
            $Shortcut.IconLocation = $IconPng
        } else {
            $Shortcut.IconLocation = "$FragoBin,0"
        }

        $Shortcut.Save()
        [System.Runtime.Interopservices.Marshal]::ReleaseComObject($WshShell) | Out-Null

        Write-Ok "Start Menu"
    }
    catch {
        Write-Warn "skipped"
    }
}

function Wait-ForServer {
    # Wait for server to accept connections (max 10 seconds)
    $maxAttempts = 10

    for ($attempt = 0; $attempt -lt $maxAttempts; $attempt++) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("127.0.0.1", 8093)
            $tcp.Close()
            return $true
        } catch {
            # Server not ready yet
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Step-Launch {
    Write-Step "Launching"

    Update-SessionPath

    # Stop any existing server first, then start fresh
    & frago server stop *>$null
    Start-Sleep -Seconds 1
    & frago server start *>$null

    # Wait for server to be ready before opening browser
    if (Wait-ForServer) {
        Write-Ok "done"
        # Open browser in background
        Start-Sleep -Seconds 1
        & frago start *>$null
    } else {
        Write-Warn "manual start needed"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Completion Message
# ═══════════════════════════════════════════════════════════════════════════════

function Write-Complete {
    Write-Host ""
    if ($UseAnsiColors) {
        Write-Host "$($script:GREEN)v$($script:RESET) $($script:BOLD)Installation complete!$($script:RESET)"
    } else {
        Write-Host "v " -ForegroundColor Green -NoNewline
        Write-Host "Installation complete!"
    }
    Write-Host ""

    # How to open
    if ($UseAnsiColors) {
        Write-Host "  $($script:DIM)Open frago:$($script:RESET)"
        Write-Host "    * Search $($script:CYAN)frago$($script:RESET) in Start Menu"
        Write-Host "    * Or run $($script:CYAN)frago start$($script:RESET)"
    } else {
        Write-Host "  Open frago:" -ForegroundColor DarkGray
        Write-Host "    * Search " -NoNewline
        Write-Host "frago" -ForegroundColor Cyan -NoNewline
        Write-Host " in Start Menu"
        Write-Host "    * Or run " -NoNewline
        Write-Host "frago start" -ForegroundColor Cyan
    }
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

function Main {
    Write-Banner

    # Exit virtual environment first to avoid PATH conflicts
    Exit-VirtualEnv

    Step-DetectPlatform
    Step-CheckUv
    Step-BuildFrontend
    Step-BuildPackage
    Step-InstallFrago
    Step-CreateShortcut
    Step-Launch

    Write-Complete
}

Main

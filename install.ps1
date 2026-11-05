# frago installation script for Windows (PowerShell 5.1+ / PowerShell Core 7+)
#
# Usage:
#   irm https://frago.ai/install.ps1 | iex
#   .\install.ps1 [-Source auto|cn|official] [-NoStart]
#
# Environment overrides:
#   $env:FRAGO_INSTALL_SOURCE = "auto"|"cn"|"official"
#   $env:FRAGO_NO_START = "1"
#   $env:UV_DEFAULT_INDEX
#   $env:UV_PYTHON_INSTALL_MIRROR

param(
    [ValidateSet("auto", "cn", "mirror", "official", "global")]
    [string]$Source = $(if ($env:FRAGO_INSTALL_SOURCE) { $env:FRAGO_INSTALL_SOURCE } else { "auto" }),
    [switch]$NoStart = ($env:FRAGO_NO_START -eq "1")
)

$ErrorActionPreference = "Stop"

# Ensure TLS 1.2+ is enabled in Windows PowerShell 5.1
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

# ═══════════════════════════════════════════════════════════════════════════════
# Constants & Mirror Definitions
# ═══════════════════════════════════════════════════════════════════════════════

$TunaPypiBase = "https://pypi.tuna.tsinghua.edu.cn"
$TunaSimpleIndex = "$TunaPypiBase/simple"
$NjuPythonMirror = "https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone"
$OfficialUvInstallPs1 = "https://astral.sh/uv/install.ps1"

$Script:UseCnMirror = $false
$Script:OsFamily = "windows"
$Script:PlatformLabel = "Windows"
$Script:ArchLabel = "x64"
$Script:UvWheelTag = "win_amd64.whl"
$Script:UvWheelPinnedPath = "packages/8e/4f/041b59d2a38807a3e31ef41064cf3e45d2752fe0409d89040d52778049ae/uv-0.13.7-py3-none-win_amd64.whl"

# ═══════════════════════════════════════════════════════════════════════════════
# Color and Style Functions
# ═══════════════════════════════════════════════════════════════════════════════

$UseAnsiColors = ($env:WT_SESSION -or $env:TERM_PROGRAM) -and ($PSVersionTable.PSVersion.Major -ge 7)

function Write-GradientLine {
    param([string]$Text, [int]$Index)

    if ($UseAnsiColors) {
        $colors = @(
            "`e[38;2;0;255;255m",
            "`e[38;2;0;191;255m",
            "`e[38;2;65;105;225m",
            "`e[38;2;138;43;226m",
            "`e[38;2;148;0;211m",
            "`e[38;2;186;85;211m"
        )
        $reset = "`e[0m"
        Write-Host "$($colors[$Index])$Text$reset"
    } else {
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

function Write-Warn {
    param([string]$Message)
    Write-Host " ~ $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host " ✗ $Message" -ForegroundColor Red
}

# ═══════════════════════════════════════════════════════════════════════════════
# Utility & Platform Detection Functions
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

function Get-LocalBinDir {
    $homeDir = if ($HOME) { $HOME } elseif ($env:USERPROFILE) { $env:USERPROFILE } else { [Environment]::GetFolderPath("UserProfile") }
    return (Join-Path $homeDir ".local\bin")
}

function Update-SessionPath {
    $binDir = Get-LocalBinDir
    $sep = [IO.Path]::PathSeparator

    if ($Script:OsFamily -eq "windows") {
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")

        $extraDirs = @()
        if ($env:LOCALAPPDATA) {
            $wingetLinks = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
            if (Test-Path $wingetLinks) {
                $extraDirs += $wingetLinks
            }
            $wingetPkgs = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
            if (Test-Path $wingetPkgs) {
                $tmuxExes = Get-ChildItem -Path $wingetPkgs -Filter "tmux.exe" -Recurse -ErrorAction SilentlyContinue
                foreach ($exe in $tmuxExes) {
                    $extraDirs += $exe.DirectoryName
                }
                $ffmpegExes = Get-ChildItem -Path $wingetPkgs -Filter "ffmpeg.exe" -Recurse -ErrorAction SilentlyContinue
                foreach ($exe in $ffmpegExes) {
                    $extraDirs += $exe.DirectoryName
                }
            }
        }

        $currentPaths = $env:Path -split ';' | Where-Object { $_ }
        $registryPaths = (($machinePath + ";" + $userPath) -split ';' | Where-Object { $_ }) + $extraDirs

        $newPaths = $registryPaths | Where-Object { $_ -notin $currentPaths } | Select-Object -Unique
        if ($newPaths) {
            $env:Path = ($newPaths -join ';') + ";" + $env:Path
        }
    }

    $activePaths = $env:Path -split [regex]::Escape("$sep") | Where-Object { $_ }
    if ($binDir -notin $activePaths) {
        $env:Path = "$binDir$sep$env:Path"
    }
}

function Select-PlatformTarget {
    if ($PSVersionTable.PSVersion.Major -ge 6) {
        if ($IsMacOS) {
            $Script:OsFamily = "macos"
            $Script:PlatformLabel = "macOS"
        } elseif ($IsLinux) {
            $Script:OsFamily = "linux"
            $Script:PlatformLabel = "Linux"
        } else {
            $Script:OsFamily = "windows"
            $Script:PlatformLabel = "Windows"
        }
    } else {
        $Script:OsFamily = "windows"
        $Script:PlatformLabel = "Windows"
    }

    $rawArch = ""
    try {
        $rawArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLower()
    } catch {}
    if (-not $rawArch) {
        $rawArch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
        $rawArch = "$rawArch".ToLower()
    }

    switch -Regex ($rawArch) {
        "arm64|aarch64" { $Script:ArchLabel = "arm64" }
        "x86$|i386|i686" {
            if ([Environment]::Is64BitOperatingSystem) {
                $Script:ArchLabel = "x64"
            } else {
                $Script:ArchLabel = "x86"
            }
        }
        default { $Script:ArchLabel = "x64" }
    }

    if ($Script:OsFamily -eq "windows") {
        switch ($Script:ArchLabel) {
            "arm64" {
                $Script:UvWheelTag = "win_arm64.whl"
                $Script:UvWheelPinnedPath = "packages/44/8d/1594dce4465d9699467a639b25aafd335ce1e5917f8bb60c9c0bed9e0859/uv-0.13.7-py3-none-win_arm64.whl"
            }
            "x86" {
                $Script:UvWheelTag = "win32.whl"
                $Script:UvWheelPinnedPath = "packages/c4/f2/3cfb8543acb8dc07b228d2517a0962b124ab97bd859690617d957248129c/uv-0.13.7-py3-none-win32.whl"
            }
            default {
                $Script:UvWheelTag = "win_amd64.whl"
                $Script:UvWheelPinnedPath = "packages/8e/4f/041b59d2a38807a3e31ef41064cf3e45d2752fe0409d89040d52778049ae/uv-0.13.7-py3-none-win_amd64.whl"
            }
        }
    } elseif ($Script:OsFamily -eq "macos") {
        if ($Script:ArchLabel -eq "arm64") {
            $Script:UvWheelTag = "macosx_11_0_arm64.whl"
            $Script:UvWheelPinnedPath = "packages/40/a5/8756c38ace102fa13fd4e653e8bc40e1f65924f1c0a0d23350339dac97e5/uv-0.13.7-py3-none-macosx_11_0_arm64.whl"
        } else {
            $Script:UvWheelTag = "macosx_10_12_x86_64.whl"
            $Script:UvWheelPinnedPath = "packages/3d/5b/e0379e7b172659420b1ec99a8e8229830aa85ea59684847c80b1c959a056/uv-0.13.7-py3-none-macosx_10_12_x86_64.whl"
        }
    } else {
        if ($Script:ArchLabel -eq "arm64") {
            $Script:UvWheelTag = "manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl"
            $Script:UvWheelPinnedPath = "packages/96/72/da1119f94034d7173e6c8e2cd77a6299744458f0af3cb8e3a04d5cd419d1/uv-0.13.7-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl"
        } else {
            $Script:UvWheelTag = "manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
            $Script:UvWheelPinnedPath = "packages/b9/93/0e053a2ca4523ee9825ccbedeb7121470d0a188933f11688b6d90d7f5c08/uv-0.13.7-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Network Detection & Domestic Mirror Configuration
# ═══════════════════════════════════════════════════════════════════════════════

function Test-HttpReachable {
    param([string]$Uri, [int]$TimeoutSec = 3)
    try {
        $req = [System.Net.HttpWebRequest]::Create($Uri)
        $req.Method = "HEAD"
        $req.Timeout = $TimeoutSec * 1000
        $req.ReadWriteTimeout = $TimeoutSec * 1000
        $req.UserAgent = "frago-installer/1.0"
        $resp = $req.GetResponse()
        $resp.Close()
        return $true
    } catch {
        return $false
    }
}

function Enable-CnMirror {
    $Script:UseCnMirror = $true
    if (-not $env:UV_DEFAULT_INDEX) {
        $env:UV_DEFAULT_INDEX = $TunaSimpleIndex
    }
    if (-not $env:UV_PYTHON_INSTALL_MIRROR) {
        $env:UV_PYTHON_INSTALL_MIRROR = $NjuPythonMirror
    }

    if ($Script:OsFamily -eq "windows") {
        try {
            [System.Environment]::SetEnvironmentVariable("UV_DEFAULT_INDEX", $env:UV_DEFAULT_INDEX, "User")
            [System.Environment]::SetEnvironmentVariable("UV_PYTHON_INSTALL_MIRROR", $env:UV_PYTHON_INSTALL_MIRROR, "User")
        } catch {}
    }
}

function Select-NetworkProfile {
    $normalized = "$Source".ToLower()
    if ($normalized -in @("cn", "mirror", "tuna")) {
        Enable-CnMirror
        Write-Success "Network source: China Mainland Mirror (Tsinghua PyPI + NJU Python)"
        return
    }
    if ($normalized -in @("official", "global")) {
        $Script:UseCnMirror = $false
        Write-Success "Network source: Official Global (astral.sh + PyPI + GitHub)"
        return
    }

    $existingMirror = "$($env:UV_DEFAULT_INDEX)$($env:UV_PYTHON_INSTALL_MIRROR)"
    if ($existingMirror -match "tuna\.tsinghua\.edu\.cn|mirror\.nju\.edu\.cn|aliyun\.com|ustc\.edu\.cn") {
        Enable-CnMirror
        Write-Success "Network source: China Mainland Mirror (from existing env)"
        return
    }

    Write-Step "Probing network connectivity..."
    if ((Test-HttpReachable "https://github.com/astral-sh/uv" 3) -and (Test-HttpReachable "https://pypi.org/simple/" 3)) {
        $Script:UseCnMirror = $false
        Write-Done "Network source: Official Global (GitHub + PyPI reachable)"
    } else {
        Enable-CnMirror
        Write-Done "Network source: China Mainland Mirror (Tsinghua PyPI + NJU Python)"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Zero-Python uv Bootstrap (Official Script + PyPI Wheel Zip Extraction)
# ═══════════════════════════════════════════════════════════════════════════════

function Resolve-LatestUvWheelFromTuna {
    try {
        $resp = Invoke-WebRequest -Uri "$TunaSimpleIndex/uv/" -UseBasicParsing -TimeoutSec 15
        $html = if ($resp.Content -is [byte[]]) {
            [System.Text.Encoding]::UTF8.GetString($resp.Content)
        } else {
            [string]$resp.Content
        }
        $escapedTag = [regex]::Escape($Script:UvWheelTag)
        $pattern = 'href="\.\./\.\./(packages/[^"#]+/uv-(\d+\.\d+\.\d+)-py3-none-' + $escapedTag + ')"'
        $matchesList = [regex]::Matches($html, $pattern)
        if ($matchesList.Count -eq 0) {
            return $null
        }
        $latest = $matchesList |
            Sort-Object { [version]$_.Groups[2].Value } |
            Select-Object -Last 1
        return "$TunaPypiBase/$($latest.Groups[1].Value)"
    } catch {
        return $null
    }
}

function Install-UvFromPypiWheel {
    $binDir = Get-LocalBinDir
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null

    $tempRoot = if ($env:TEMP) { $env:TEMP } else { [IO.Path]::GetTempPath() }
    $workDir = Join-Path $tempRoot "frago-uv-$PID"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null
    $uvZip = Join-Path $workDir "uv.zip"
    $uvExtractDir = Join-Path $workDir "uv"

    try {
        $downloaded = $false
        if ($Script:UvWheelPinnedPath) {
            $pinnedUrl = "$TunaPypiBase/$($Script:UvWheelPinnedPath)"
            try {
                Invoke-WebRequest -Uri $pinnedUrl -OutFile $uvZip -UseBasicParsing -TimeoutSec 60
                if ((Test-Path $uvZip) -and ((Get-Item $uvZip).Length -gt 0)) {
                    $downloaded = $true
                }
            } catch {
                $downloaded = $false
            }
        }

        if (-not $downloaded) {
            $latestUrl = Resolve-LatestUvWheelFromTuna
            if ($latestUrl) {
                Invoke-WebRequest -Uri $latestUrl -OutFile $uvZip -UseBasicParsing -TimeoutSec 60
                if ((Test-Path $uvZip) -and ((Get-Item $uvZip).Length -gt 0)) {
                    $downloaded = $true
                }
            }
        }

        if (-not $downloaded) {
            return $false
        }

        Expand-Archive -Path $uvZip -DestinationPath $uvExtractDir -Force
        $scriptsPattern = if ($Script:OsFamily -eq "windows") {
            Join-Path $uvExtractDir "uv-*.data\scripts\*.exe"
        } else {
            Join-Path $uvExtractDir "uv-*.data/scripts/*"
        }

        $binaries = Get-Item $scriptsPattern -ErrorAction SilentlyContinue
        if (-not $binaries) {
            return $false
        }

        Move-Item -Path $scriptsPattern -Destination $binDir -Force
        if ($Script:OsFamily -ne "windows") {
            foreach ($b in (Get-ChildItem -Path $binDir -Filter "uv*")) {
                & chmod +x $b.FullName 2>$null
            }
        }

        Update-SessionPath
        return (Test-Command "uv")
    } catch {
        return $false
    } finally {
        Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Install-UvFromOfficial {
    try {
        $response = Invoke-WebRequest -Uri $OfficialUvInstallPs1 -UseBasicParsing -TimeoutSec 30
        $installScript = if ($response.Content -is [byte[]]) {
            [System.Text.Encoding]::UTF8.GetString($response.Content)
        } else {
            $response.Content
        }
        Invoke-Expression $installScript *>$null
        Update-SessionPath
        return (Test-Command "uv")
    } catch {
        return $false
    }
}

function Install-Uv {
    Update-SessionPath

    if (Test-Command "uv") {
        $version = Get-CommandVersion "uv"
        Write-Success "uv ($version)"
        return
    }

    if ($Script:UseCnMirror) {
        Write-Step "Installing uv (via Tsinghua PyPI precompiled wheel)..."
        if (Install-UvFromPypiWheel) {
            $version = Get-CommandVersion "uv"
            Write-Done "uv ($version, via Tsinghua mirror)"
            return
        }
        Write-Step "Mirror wheel install failed, trying official installer..."
        if (Install-UvFromOfficial) {
            $version = Get-CommandVersion "uv"
            Write-Done "uv ($version)"
            return
        }
    } else {
        Write-Step "Installing uv..."
        if (Install-UvFromOfficial) {
            $version = Get-CommandVersion "uv"
            Write-Done "uv ($version)"
            return
        }
        Write-Step "Official uv installer unreachable, switching to Tsinghua PyPI wheel..."
        Enable-CnMirror
        if (Install-UvFromPypiWheel) {
            $version = Get-CommandVersion "uv"
            Write-Done "uv ($version, via Tsinghua mirror)"
            return
        }
    }

    Write-Err "uv installation failed"
    exit 1
}

function Find-WindowsGitRoot {
    if ($Script:OsFamily -ne "windows") {
        return $null
    }
    $gitCmd = Get-Command "git.exe" -ErrorAction SilentlyContinue
    if ($gitCmd -and $gitCmd.Source) {
        $dir = Split-Path -Parent $gitCmd.Source
        $root = Split-Path -Parent $dir
        if (Test-Path (Join-Path $root "bin\bash.exe")) {
            return $root
        }
        $scoopRoot = Join-Path $root "apps\git\current"
        if (Test-Path (Join-Path $scoopRoot "bin\bash.exe")) {
            return $scoopRoot
        }
    }
    $roots = @(
        "C:\Program Files\Git",
        "C:\Program Files (x86)\Git",
        "D:\Program Files\Git",
        "D:\Program Files (x86)\Git",
        "E:\Program Files\Git",
        "C:\Git",
        "D:\Git"
    )
    if ($env:LOCALAPPDATA) {
        $roots += (Join-Path $env:LOCALAPPDATA "Programs\Git")
    }
    if ($env:USERPROFILE) {
        $roots += (Join-Path $env:USERPROFILE "scoop\apps\git\current")
    }
    foreach ($r in $roots) {
        if ($r -and (Test-Path (Join-Path $r "bin\bash.exe"))) {
            return $r
        }
    }
    return $null
}

function Sync-WindowsGitPath {
    param([string]$GitRoot)
    if ((-not $GitRoot) -or ($Script:OsFamily -ne "windows")) {
        return
    }
    $dirsToEnsure = @(
        (Join-Path $GitRoot "cmd"),
        (Join-Path $GitRoot "bin"),
        (Join-Path $GitRoot "usr\bin")
    ) | Where-Object { Test-Path $_ }

    foreach ($d in $dirsToEnsure) {
        $active = $env:Path -split ';' | Where-Object { $_ }
        if ($d -notin $active) {
            $env:Path = "$d;$env:Path"
        }
    }
    try {
        $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $userParts = ($userPath -split ";") | Where-Object { $_ }
        $changed = $false
        foreach ($d in @((Join-Path $GitRoot "cmd"), (Join-Path $GitRoot "bin"))) {
            if ((Test-Path $d) -and ($d -notin $userParts)) {
                $userParts = @($d) + $userParts
                $changed = $true
            }
        }
        if ($changed) {
            [System.Environment]::SetEnvironmentVariable("Path", ($userParts -join ";"), "User")
        }
    } catch {}
}

function Install-Git {
    Update-SessionPath

    if ($Script:OsFamily -eq "windows") {
        $gitRoot = Find-WindowsGitRoot
        if ($gitRoot) {
            Sync-WindowsGitPath -GitRoot $gitRoot
            $version = Get-CommandVersion "git"
            Write-Success "git ($version, Git Bash ready)"
            return
        }
        if (Test-Command "winget") {
            Write-Step "Installing Git for Windows (provides git & Git Bash)..."
            try {
                & winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements --silent *>$null
            } catch {}
            Update-SessionPath
            $gitRoot = Find-WindowsGitRoot
            if ($gitRoot) {
                Sync-WindowsGitPath -GitRoot $gitRoot
                $version = Get-CommandVersion "git"
                Write-Done "git ($version, Git Bash ready)"
                return
            }
        }
        if (Test-Command "scoop") {
            Write-Step "Installing git via scoop..."
            try { & scoop install git *>$null } catch {}
            Update-SessionPath
        } elseif (Test-Command "choco") {
            Write-Step "Installing git via choco..."
            try { & choco install git -y *>$null } catch {}
            Update-SessionPath
        }
        $gitRoot = Find-WindowsGitRoot
        if ($gitRoot) {
            Sync-WindowsGitPath -GitRoot $gitRoot
        }
        if (Test-Command "git") {
            $version = Get-CommandVersion "git"
            Write-Done "git ($version)"
            return
        }
        Write-Err "git installation failed"
        exit 1
    }

    if (Test-Command "git") {
        $version = Get-CommandVersion "git"
        Write-Success "git ($version)"
        return
    }
    Write-Step "Installing git..."
    if (Test-Command "brew") {
        try { & brew install git *>$null } catch {}
    } elseif (Test-Command "apt-get") {
        try { & sudo apt-get update -qq *>$null; & sudo apt-get install -y git *>$null } catch {}
    } elseif (Test-Command "dnf") {
        try { & sudo dnf install -y git *>$null } catch {}
    } elseif (Test-Command "pacman") {
        try { & sudo pacman -Sy --noconfirm --needed git *>$null } catch {}
    } elseif (Test-Command "apk") {
        try { & sudo apk add --no-cache git *>$null } catch {}
    }
    if (Test-Command "git") {
        $version = Get-CommandVersion "git"
        Write-Done "git ($version)"
        return
    }
    Write-Err "git installation failed"
    exit 1
}

function Install-WindowsTmuxZipFallback {
    $binDir = Get-LocalBinDir
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null

    $releaseUrl = "https://github.com/arndawg/tmux-windows/releases/download/v3.6a-win32.7/tmux-windows-v3.6a-win32.7.zip"
    $candidates = if ($Script:UseCnMirror) {
        @(
            "https://ghfast.top/$releaseUrl",
            "https://mirror.ghproxy.com/$releaseUrl",
            $releaseUrl
        )
    } else {
        @(
            $releaseUrl,
            "https://ghfast.top/$releaseUrl",
            "https://mirror.ghproxy.com/$releaseUrl"
        )
    }

    $tempRoot = if ($env:TEMP) { $env:TEMP } else { [IO.Path]::GetTempPath() }
    $workDir = Join-Path $tempRoot "frago-tmux-win-$PID"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null
    $zipPath = Join-Path $workDir "tmux-windows.zip"
    $extractDir = Join-Path $workDir "extracted"

    try {
        $downloaded = $false
        foreach ($url in $candidates) {
            try {
                Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -TimeoutSec 60
                if ((Test-Path $zipPath) -and ((Get-Item $zipPath).Length -gt 0)) {
                    $downloaded = $true
                    break
                }
            } catch {}
        }
        if (-not $downloaded) {
            return $false
        }
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
        $tmuxExe = Join-Path $extractDir "tmux.exe"
        if (Test-Path $tmuxExe) {
            Move-Item -Path $tmuxExe -Destination (Join-Path $binDir "tmux.exe") -Force
            Update-SessionPath
            return (Test-Command "tmux")
        }
        return $false
    } catch {
        return $false
    } finally {
        Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Install-Tmux {
    Update-SessionPath

    if (Test-Command "tmux") {
        $version = Get-CommandVersion "tmux"
        Write-Success "tmux ($version)"
        return
    }

    if ($Script:OsFamily -eq "windows") {
        Write-Step "Installing tmux (Windows port: arndawg.tmux-windows)..."
        if (Test-Command "winget") {
            try {
                & winget install --id arndawg.tmux-windows -e --source winget --accept-package-agreements --accept-source-agreements --silent *>$null
            } catch {}
            Update-SessionPath
        }
        if (-not (Test-Command "tmux")) {
            Install-WindowsTmuxZipFallback | Out-Null
            Update-SessionPath
        }
        if (Test-Command "tmux") {
            $version = Get-CommandVersion "tmux"
            Write-Done "tmux ($version)"
            return
        }
        Write-Err "tmux (arndawg.tmux-windows) installation failed"
        exit 1
    }

    Write-Step "Installing tmux..."
    if (Test-Command "brew") {
        try { & brew install tmux *>$null } catch {}
    } elseif (Test-Command "apt-get") {
        try { & sudo apt-get update -qq *>$null; & sudo apt-get install -y tmux *>$null } catch {}
    } elseif (Test-Command "dnf") {
        try { & sudo dnf install -y tmux *>$null } catch {}
    } elseif (Test-Command "pacman") {
        try { & sudo pacman -Sy --noconfirm --needed tmux *>$null } catch {}
    } elseif (Test-Command "apk") {
        try { & sudo apk add --no-cache tmux *>$null } catch {}
    }
    if (Test-Command "tmux") {
        $version = Get-CommandVersion "tmux"
        Write-Done "tmux ($version)"
        return
    }
    Write-Err "tmux installation failed"
    exit 1
}

function Install-Ffmpeg {
    Update-SessionPath

    if (Test-Command "ffmpeg") {
        $version = Get-CommandVersion "ffmpeg"
        Write-Success "ffmpeg ($version)"
        return
    }

    Write-Step "Installing ffmpeg..."
    if ($Script:OsFamily -eq "windows") {
        if (Test-Command "winget") {
            try {
                & winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements --silent *>$null
                if ($LASTEXITCODE -ne 0) {
                    & winget install ffmpeg --source winget --accept-package-agreements --accept-source-agreements --silent *>$null
                }
            } catch {}
            Update-SessionPath
        }
        if ((-not (Test-Command "ffmpeg")) -and (Test-Command "scoop")) {
            try { & scoop install ffmpeg *>$null } catch {}
            Update-SessionPath
        } elseif ((-not (Test-Command "ffmpeg")) -and (Test-Command "choco")) {
            try { & choco install ffmpeg -y *>$null } catch {}
            Update-SessionPath
        }
        if (Test-Command "ffmpeg") {
            try {
                $ffCmd = Get-Command "ffmpeg" -ErrorAction SilentlyContinue
                if ($ffCmd -and $ffCmd.Source) {
                    $ffDir = Split-Path -Parent $ffCmd.Source
                    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
                    $parts = ($userPath -split ";") | Where-Object { $_ }
                    if ($ffDir -notin $parts) {
                        $newUserPath = if ($userPath) { "$ffDir;$userPath" } else { $ffDir }
                        [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
                    }
                }
            } catch {}
            $version = Get-CommandVersion "ffmpeg"
            Write-Done "ffmpeg ($version)"
            return
        }
        Write-Err "ffmpeg installation failed"
        exit 1
    }

    if (Test-Command "brew") {
        try { & brew install ffmpeg *>$null } catch {}
    } elseif (Test-Command "apt-get") {
        try { & sudo apt-get update -qq *>$null; & sudo apt-get install -y ffmpeg *>$null } catch {}
    } elseif (Test-Command "dnf") {
        try { & sudo dnf install -y ffmpeg *>$null } catch {}
    } elseif (Test-Command "pacman") {
        try { & sudo pacman -Sy --noconfirm --needed ffmpeg *>$null } catch {}
    } elseif (Test-Command "apk") {
        try { & sudo apk add --no-cache ffmpeg *>$null } catch {}
    }
    if (Test-Command "ffmpeg") {
        $version = Get-CommandVersion "ffmpeg"
        Write-Done "ffmpeg ($version)"
        return
    }
    Write-Err "ffmpeg installation failed"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# frago-cli & Default CoreAgent Runtime Installation
# ═══════════════════════════════════════════════════════════════════════════════

function Invoke-UvToolInstall {
    param([string]$Action)
    try {
        if ($Action -eq "upgrade") {
            & uv tool upgrade frago-cli *>$null
            if ($LASTEXITCODE -ne 0) {
                & uv tool install frago-cli --force *>$null
            }
        } else {
            & uv tool install frago-cli *>$null
        }
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Install-Frago {
    Update-SessionPath

    $action = if (Test-Command "frago") { "upgrade" } else { "install" }
    if ($action -eq "upgrade") {
        Write-Step "Upgrading frago-cli (Python >=3.13 + built-in CoreAgent)..."
    } else {
        Write-Step "Installing frago-cli (Python >=3.13 + built-in CoreAgent)..."
    }

    $ok = Invoke-UvToolInstall -Action $action
    if (-not $ok) {
        if ((-not $Script:UseCnMirror) -and ($Source -notin @("official", "global"))) {
            Write-Step "Retrying with China Mainland Mirror (Tsinghua PyPI + NJU Python)..."
            Enable-CnMirror
            $ok = Invoke-UvToolInstall -Action $action
        }
    }

    if (-not $ok) {
        Write-Err "frago-cli installation failed"
        exit 1
    }

    try {
        & uv tool update-shell *>$null
    } catch {}

    # Also ensure ~/.local/bin is persisted in User PATH on Windows even if current process already had it
    if ($Script:OsFamily -eq "windows") {
        try {
            $binDir = Get-LocalBinDir
            $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
            $parts = ($userPath -split ";") | Where-Object { $_ }
            if ($binDir -notin $parts) {
                $newUserPath = if ($userPath) { "$binDir;$userPath" } else { $binDir }
                [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
            }
        } catch {}
    }
    Update-SessionPath

    if (Test-Command "frago") {
        $version = Get-CommandVersion "frago"
        Write-Done "frago ($version)"
    } else {
        Write-Err "frago installation failed (frago not found in ~/.local/bin)"
        exit 1
    }
}

function Show-NextSteps {
    Write-Section "Getting Started"

    Write-Host "  " -NoNewline
    Write-Host "Commands:" -ForegroundColor DarkGray
    Write-Host "    " -NoNewline
    Write-Host "frago start" -ForegroundColor White -NoNewline
    Write-Host "         Start frago server and open Web UI"
    Write-Host "    " -NoNewline
    Write-Host "frago --version" -ForegroundColor White -NoNewline
    Write-Host "     Verify installed frago version"
    Write-Host "    " -NoNewline
    Write-Host "frago --help" -ForegroundColor White -NoNewline
    Write-Host "        Show all available commands"
    Write-Host ""
}

function Wait-ForServer {
    $maxAttempts = 30

    for ($attempt = 0; $attempt -lt $maxAttempts; $attempt++) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("127.0.0.1", 8093)
            $tcp.Close()
            Start-Sleep -Seconds 2
            return $true
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-Frago {
    if ($NoStart) {
        return
    }

    Write-Section "Launching"

    Update-SessionPath
    Write-Host "  " -NoNewline
    Write-Host "Starting frago server..." -ForegroundColor DarkGray

    try { & frago server stop *>$null } catch {}
    Start-Sleep -Seconds 2
    try { & frago server start *>$null } catch {}

    if (Wait-ForServer) {
        Write-Host "  " -NoNewline
        Write-Host "Opening browser..." -ForegroundColor DarkGray
        Write-Host ""
        Start-Process "http://127.0.0.1:8093"
    } else {
        Write-Warn "Server did not start in time. Run 'frago start' manually."
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

function Main {
    Write-Banner

    Write-Section "Environment"
    Select-PlatformTarget
    Write-Success "$($Script:PlatformLabel) ($($Script:ArchLabel))"
    Select-NetworkProfile

    Write-Section "Dependencies"
    Install-Git
    Install-Tmux
    Install-Ffmpeg
    Install-Uv
    Install-Frago

    Show-NextSteps
    Start-Frago
}

Main

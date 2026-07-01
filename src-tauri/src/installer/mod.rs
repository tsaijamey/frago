//! Bootstrap installer: dependency checks, downloads, and server launch.
//!
//! `commands.rs` holds only the `#[tauri::command]` entry points; the actual
//! install/check/launch logic lives in these submodules.

pub mod claude_code;
pub mod downloader;
pub mod frago;
pub mod launcher;
pub mod process;
pub mod uv;

use std::path::PathBuf;

use serde::Serialize;

// ---------------------------------------------------------------------------
// Public result types (serialized to the webui)
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone)]
pub struct CheckResult {
    pub installed: bool,
    pub version: Option<String>,
}

#[derive(Serialize, Clone)]
pub struct InstallResult {
    pub success: bool,
    pub message: String,
}

#[derive(Serialize, Clone)]
pub struct StartResult {
    pub success: bool,
    pub message: String,
}

// ---------------------------------------------------------------------------
// Shared event payloads
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone)]
pub(crate) struct BootstrapLogEvent {
    pub step: String,
    pub stream: String,
    pub line: String,
}

#[derive(Serialize, Clone)]
pub(crate) struct DownloadProgress {
    pub step: String,
    pub downloaded: u64,
    pub total: u64,
    pub bytes_per_sec: u64,
}

// ---------------------------------------------------------------------------
// PATH resolution — don't rely on shell PATH after fresh installs
// ---------------------------------------------------------------------------

pub(crate) fn home_dir() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("~"))
}

pub(crate) fn resolve_uv_path() -> PathBuf {
    // Try PATH first, then known install locations
    let candidates = [
        home_dir().join(".local/bin/uv"),
        home_dir().join(".cargo/bin/uv"), // older uv installer
    ];
    which::which("uv")
        .ok()
        .or_else(|| candidates.iter().find(|p| p.exists()).cloned())
        .unwrap_or_else(|| PathBuf::from("uv"))
}

pub(crate) fn resolve_frago_path() -> PathBuf {
    let candidate = home_dir().join(".local/bin/frago");
    which::which("frago")
        .ok()
        .or_else(|| candidate.exists().then_some(candidate))
        .unwrap_or_else(|| PathBuf::from("frago"))
}

pub(crate) fn resolve_claude_path() -> PathBuf {
    // Claude Code's official `<binary> install` places the launcher at
    // ~/.local/bin/claude on Unix and %USERPROFILE%\.local\bin\claude.exe on Windows
    let candidates = [
        home_dir().join(".local/bin/claude"),
        home_dir().join(".local/bin/claude.exe"),
        home_dir().join(".claude/local/claude"),
    ];
    which::which("claude")
        .ok()
        .or_else(|| candidates.iter().find(|p| p.exists()).cloned())
        .unwrap_or_else(|| PathBuf::from("claude"))
}

// ---------------------------------------------------------------------------
// Platform detection
// ---------------------------------------------------------------------------

/// Pure platform-key resolver. Mirrors the logic in the official Claude Code
/// install.sh, parameterized so it can be unit-tested without touching the host.
pub(crate) fn detect(os: &str, arch: &str, musl: bool) -> Result<&'static str, String> {
    let arch_str = match arch {
        "x86_64" => "x64",
        "aarch64" => "arm64",
        other => return Err(format!("unsupported arch: {other}")),
    };

    match os {
        "macos" => Ok(if arch_str == "arm64" {
            "darwin-arm64"
        } else {
            "darwin-x64"
        }),
        "windows" => Ok(if arch_str == "arm64" {
            "win32-arm64"
        } else {
            "win32-x64"
        }),
        "linux" => Ok(match (arch_str, musl) {
            ("x64", false) => "linux-x64",
            ("arm64", false) => "linux-arm64",
            ("x64", true) => "linux-x64-musl",
            ("arm64", true) => "linux-arm64-musl",
            _ => unreachable!(),
        }),
        other => Err(format!("unsupported os: {other}")),
    }
}

/// Detect the manifest.json platform key for the current host.
pub(crate) fn detect_platform() -> Result<&'static str, String> {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    let musl = std::path::Path::new("/lib/libc.musl-x86_64.so.1").exists()
        || std::path::Path::new("/lib/libc.musl-aarch64.so.1").exists();
    detect(os, arch, musl)
}

#[cfg(test)]
mod tests {
    use super::detect;

    #[test]
    fn detect_known_platforms() {
        assert_eq!(detect("macos", "aarch64", false).unwrap(), "darwin-arm64");
        assert_eq!(detect("macos", "x86_64", false).unwrap(), "darwin-x64");
        assert_eq!(detect("windows", "aarch64", false).unwrap(), "win32-arm64");
        assert_eq!(detect("windows", "x86_64", false).unwrap(), "win32-x64");
        assert_eq!(detect("linux", "x86_64", false).unwrap(), "linux-x64");
        assert_eq!(detect("linux", "aarch64", false).unwrap(), "linux-arm64");
        assert_eq!(detect("linux", "x86_64", true).unwrap(), "linux-x64-musl");
        assert_eq!(detect("linux", "aarch64", true).unwrap(), "linux-arm64-musl");
    }

    #[test]
    fn detect_rejects_unknown() {
        assert!(detect("linux", "riscv64", false).is_err());
        assert!(detect("plan9", "x86_64", false).is_err());
    }
}

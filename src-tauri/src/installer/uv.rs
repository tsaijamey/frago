//! uv install + check. Uses the vendor `curl | sh` (Unix) / PowerShell (Windows)
//! installer script — no download/verify logic of its own.

use std::process::Command;

use tauri::AppHandle;

use super::process::run_with_streaming;
use super::{resolve_uv_path, CheckResult, InstallResult};

pub async fn check() -> Result<CheckResult, String> {
    let uv = resolve_uv_path();
    let output = Command::new(&uv).arg("--version").output();
    match output {
        Ok(o) if o.status.success() => {
            let raw = String::from_utf8_lossy(&o.stdout);
            // `uv 0.6.x` → extract version part
            let version = raw.trim().strip_prefix("uv ").unwrap_or(raw.trim());
            Ok(CheckResult {
                installed: true,
                version: Some(version.to_string()),
            })
        }
        _ => Ok(CheckResult {
            installed: false,
            version: None,
        }),
    }
}

pub async fn install(app: AppHandle) -> Result<InstallResult, String> {
    // Already installed?
    let check = check().await?;
    if check.installed {
        return Ok(InstallResult {
            success: true,
            message: format!("uv already installed ({})", check.version.unwrap_or_default()),
        });
    }

    #[cfg(unix)]
    {
        let script_path = std::env::temp_dir().join("uv-install.sh");
        let script_str = script_path.to_string_lossy().to_string();

        // Step 1: download install script
        run_with_streaming(
            &app,
            "install_uv",
            "curl",
            &["-LsSf", "https://astral.sh/uv/install.sh", "-o", &script_str],
        )?;

        // Step 2: execute
        run_with_streaming(&app, "install_uv", "sh", &[&script_str])?;
    }

    #[cfg(windows)]
    {
        let script_path = std::env::temp_dir().join("uv-install.ps1");
        let script_str = script_path.to_string_lossy().to_string();

        run_with_streaming(
            &app,
            "install_uv",
            "powershell",
            &[
                "-Command",
                &format!(
                    "Invoke-WebRequest -Uri https://astral.sh/uv/install.ps1 -OutFile '{}'",
                    script_str
                ),
            ],
        )?;

        run_with_streaming(
            &app,
            "install_uv",
            "powershell",
            &["-ExecutionPolicy", "Bypass", "-File", &script_str],
        )?;
    }

    Ok(InstallResult {
        success: true,
        message: "uv installed successfully".into(),
    })
}

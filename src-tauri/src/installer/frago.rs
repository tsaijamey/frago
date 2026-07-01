//! frago-cli install + check via `uv tool install`. No download/verify of its own.

use std::process::Command;

use tauri::{AppHandle, Emitter};

use crate::constants::{BOOTSTRAP_LOG, FALLBACK_VERSION};

use super::process::run_with_streaming;
use super::{resolve_uv_path, BootstrapLogEvent, CheckResult, InstallResult};

pub async fn check() -> Result<CheckResult, String> {
    let uv = resolve_uv_path();
    let output = Command::new(&uv)
        .args(["tool", "list"])
        .output()
        .map_err(|e| e.to_string())?;

    let text = String::from_utf8_lossy(&output.stdout);
    for line in text.lines() {
        if line.starts_with("frago-cli") || line.starts_with("frago ") {
            // line looks like: "frago-cli v0.39.0"
            let version = line
                .split_whitespace()
                .nth(1)
                .map(|v| v.trim_start_matches('v').to_string());
            return Ok(CheckResult {
                installed: true,
                version,
            });
        }
    }
    Ok(CheckResult {
        installed: false,
        version: None,
    })
}

/// Query PyPI JSON API for the latest version of a package.
/// Returns `None` on any failure (network, parse, etc.).
async fn fetch_latest_pypi_version(package: &str) -> Option<String> {
    let url = format!("https://pypi.org/pypi/{package}/json");
    let resp = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .ok()?
        .get(&url)
        .send()
        .await
        .ok()?;
    let json: serde_json::Value = resp.json().await.ok()?;
    json["info"]["version"].as_str().map(|s| s.to_string())
}

pub async fn install(app: AppHandle, version: Option<String>) -> Result<InstallResult, String> {
    let uv = resolve_uv_path();
    let uv_str = uv.to_string_lossy().to_string();

    let target_version_owned: String = match version {
        Some(v) => v,
        None => fetch_latest_pypi_version("frago-cli")
            .await
            .unwrap_or_else(|| FALLBACK_VERSION.to_string()),
    };
    let target_version = target_version_owned.as_str();

    // Check if already installed with matching version
    let check = check().await?;
    if check.installed {
        let current = check.version.as_deref().unwrap_or("");
        if current == target_version {
            return Ok(InstallResult {
                success: true,
                message: format!("frago-cli already installed ({current})"),
            });
        }
        // Version mismatch — upgrade via reinstall
        let _ = app.emit(
            BOOTSTRAP_LOG,
            BootstrapLogEvent {
                step: "install_frago".into(),
                stream: "stdout".into(),
                line: format!("Upgrading frago-cli {current} → {target_version}..."),
            },
        );
        run_with_streaming(
            &app,
            "install_frago",
            &uv_str,
            &["tool", "install", "--force", &format!("frago-cli=={target_version}")],
        )?;
        return Ok(InstallResult {
            success: true,
            message: format!("frago-cli upgraded to {target_version}"),
        });
    }

    let pkg = format!("frago-cli=={target_version}");
    run_with_streaming(&app, "install_frago", &uv_str, &["tool", "install", &pkg])?;

    Ok(InstallResult {
        success: true,
        message: "frago-cli installed successfully".into(),
    })
}

//! Claude Code installer: orchestration layer.
//!
//! Owns version/manifest fetch, mirror selection, retry/backoff, post-download
//! chmod + launcher setup. The single verified download lives in `downloader`.

use std::process::Command;

use tauri::{AppHandle, Emitter};

use crate::constants::{BOOTSTRAP_LOG, CLAUDE_MIRROR_BASE, CLAUDE_OFFICIAL_BASE};

use super::downloader::download_verified;
use super::process::run_with_streaming;
use super::{detect_platform, resolve_claude_path, BootstrapLogEvent, CheckResult, InstallResult};

pub async fn check() -> Result<CheckResult, String> {
    let claude = resolve_claude_path();
    let output = Command::new(&claude).arg("--version").output();
    match output {
        Ok(o) if o.status.success() => {
            let raw = String::from_utf8_lossy(&o.stdout);
            // Output format: "1.0.123 (Claude Code)" — take the first whitespace token.
            let version = raw.split_whitespace().next().map(|s| s.to_string());
            Ok(CheckResult {
                installed: true,
                version,
            })
        }
        _ => Ok(CheckResult {
            installed: false,
            version: None,
        }),
    }
}

/// HEAD probe with a tight timeout. Returns true on 2xx/3xx response.
async fn probe_url(url: &str, timeout_ms: u64) -> bool {
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_millis(timeout_ms))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    match client.head(url).send().await {
        Ok(resp) => resp.status().is_success() || resp.status().is_redirection(),
        Err(_) => false,
    }
}

/// Pick the Claude Code download base URL. Probe official first; fall back to
/// the Tencent Cloud mirror when official is unreachable (e.g. mainland China).
async fn pick_claude_base_url() -> &'static str {
    let probe = format!("{CLAUDE_OFFICIAL_BASE}/latest");
    if probe_url(&probe, 5000).await {
        CLAUDE_OFFICIAL_BASE
    } else {
        CLAUDE_MIRROR_BASE
    }
}

/// Single-attempt installer. Caller is responsible for retries.
async fn install_inner(app: &AppHandle) -> Result<String, String> {
    let platform = detect_platform()?;
    let base = pick_claude_base_url().await;
    let using_mirror = base == CLAUDE_MIRROR_BASE;

    let _ = app.emit(
        BOOTSTRAP_LOG,
        BootstrapLogEvent {
            step: "install_claude_code".into(),
            stream: "stdout".into(),
            line: format!(
                "Source: {} ({})",
                base,
                if using_mirror { "mirror" } else { "official" }
            ),
        },
    );
    let _ = app.emit(
        BOOTSTRAP_LOG,
        BootstrapLogEvent {
            step: "install_claude_code".into(),
            stream: "stdout".into(),
            line: format!("Platform: {platform}"),
        },
    );

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(180))
        .build()
        .map_err(|e| format!("HTTP client init failed: {e}"))?;

    // 1. Latest version
    let version = client
        .get(format!("{base}/latest"))
        .send()
        .await
        .map_err(|e| format!("Fetch latest failed: {e}"))?
        .error_for_status()
        .map_err(|e| format!("Fetch latest HTTP error: {e}"))?
        .text()
        .await
        .map_err(|e| format!("Read latest body failed: {e}"))?
        .trim()
        .to_string();

    let _ = app.emit(
        BOOTSTRAP_LOG,
        BootstrapLogEvent {
            step: "install_claude_code".into(),
            stream: "stdout".into(),
            line: format!("Target version: {version}"),
        },
    );

    // 2. Manifest
    let manifest: serde_json::Value = client
        .get(format!("{base}/{version}/manifest.json"))
        .send()
        .await
        .map_err(|e| format!("Fetch manifest failed: {e}"))?
        .error_for_status()
        .map_err(|e| format!("Fetch manifest HTTP error: {e}"))?
        .json()
        .await
        .map_err(|e| format!("Parse manifest failed: {e}"))?;

    let platform_info = manifest["platforms"]
        .get(platform)
        .ok_or_else(|| format!("Platform {platform} not in manifest"))?;
    let expected_sha = platform_info["checksum"]
        .as_str()
        .ok_or("Manifest missing checksum")?
        .to_string();
    let total_size = platform_info["size"].as_u64().unwrap_or(0);
    let binary_name = platform_info["binary"]
        .as_str()
        .unwrap_or("claude")
        .to_string();

    // 3 + 4. Verified download (stream + progress + SHA256)
    let tmp_path = std::env::temp_dir().join(format!("claude-{version}-{platform}-{binary_name}"));
    let url = format!("{base}/{version}/{platform}/{binary_name}");
    download_verified(app, &client, &url, &expected_sha, total_size, &tmp_path).await?;

    // 5. chmod +x on Unix
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = std::fs::metadata(&tmp_path)
            .map_err(|e| format!("Read perms failed: {e}"))?
            .permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&tmp_path, perms).map_err(|e| format!("chmod failed: {e}"))?;
    }

    // 6. Run `<binary> install` to set up the launcher (~/.local/bin/claude etc).
    //    This is what the official install.sh does at its tail.
    let tmp_str = tmp_path.to_string_lossy().to_string();
    run_with_streaming(app, "install_claude_code", &tmp_str, &["install"])?;

    // 7. Cleanup temp binary
    let _ = std::fs::remove_file(&tmp_path);

    Ok(format!("Claude Code {version} installed"))
}

pub async fn install(app: AppHandle) -> Result<InstallResult, String> {
    // Skip if already present
    let check = check().await?;
    if check.installed {
        return Ok(InstallResult {
            success: true,
            message: format!(
                "Claude Code already installed ({})",
                check.version.unwrap_or_default()
            ),
        });
    }

    // Inline retry — up to 3 attempts, 3s linear backoff
    const MAX_ATTEMPTS: u32 = 3;
    const BACKOFF_MS: u64 = 3000;
    let mut last_err = String::new();
    for attempt in 1..=MAX_ATTEMPTS {
        if attempt > 1 {
            let _ = app.emit(
                BOOTSTRAP_LOG,
                BootstrapLogEvent {
                    step: "install_claude_code".into(),
                    stream: "stdout".into(),
                    line: format!("Retrying ({attempt}/{MAX_ATTEMPTS})..."),
                },
            );
            tokio::time::sleep(std::time::Duration::from_millis(BACKOFF_MS)).await;
        }
        match install_inner(&app).await {
            Ok(msg) => {
                return Ok(InstallResult {
                    success: true,
                    message: msg,
                });
            }
            Err(e) => {
                let _ = app.emit(
                    BOOTSTRAP_LOG,
                    BootstrapLogEvent {
                        step: "install_claude_code".into(),
                        stream: "stderr".into(),
                        line: format!("Attempt {attempt} failed: {e}"),
                    },
                );
                last_err = e;
            }
        }
    }
    Err(last_err)
}

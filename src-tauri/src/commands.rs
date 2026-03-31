use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde::Serialize;
use tauri::{AppHandle, Emitter};

// ---------------------------------------------------------------------------
// Types
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
// Event streaming
// ---------------------------------------------------------------------------

const BOOTSTRAP_LOG: &str = "bootstrap-log";

#[derive(Serialize, Clone)]
struct BootstrapLogEvent {
    step: String,
    stream: String,
    line: String,
}

/// Run a command and stream stdout/stderr lines as Tauri events.
fn run_with_streaming(
    app: &AppHandle,
    step: &str,
    cmd: &str,
    args: &[&str],
) -> Result<(), String> {
    let mut child = Command::new(cmd)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("{step} spawn failed: {e}"))?;

    // Stream stdout
    if let Some(stdout) = child.stdout.take() {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            let _ = app.emit(
                BOOTSTRAP_LOG,
                BootstrapLogEvent {
                    step: step.into(),
                    stream: "stdout".into(),
                    line,
                },
            );
        }
    }

    // Collect any remaining stderr
    if let Some(stderr) = child.stderr.take() {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            let _ = app.emit(
                BOOTSTRAP_LOG,
                BootstrapLogEvent {
                    step: step.into(),
                    stream: "stderr".into(),
                    line,
                },
            );
        }
    }

    let status = child.wait().map_err(|e| e.to_string())?;
    if !status.success() {
        return Err(format!(
            "{step} exited with code {}",
            status.code().unwrap_or(-1)
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// PATH resolution — don't rely on shell PATH after fresh installs
// ---------------------------------------------------------------------------

fn home_dir() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("~"))
}

fn resolve_uv_path() -> PathBuf {
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

fn resolve_frago_path() -> PathBuf {
    let candidate = home_dir().join(".local/bin/frago");
    which::which("frago")
        .ok()
        .or_else(|| candidate.exists().then_some(candidate))
        .unwrap_or_else(|| PathBuf::from("frago"))
}

// ---------------------------------------------------------------------------
// Commands — environment checks
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn check_uv() -> Result<CheckResult, String> {
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

#[tauri::command]
pub async fn check_frago() -> Result<CheckResult, String> {
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

#[tauri::command]
pub async fn check_server() -> Result<bool, String> {
    // Use raw TCP connect instead of reqwest HTTP — reqwest can fail
    // inside macOS .app bundles due to network sandbox restrictions
    use std::net::TcpStream;
    let ok = TcpStream::connect_timeout(
        &"127.0.0.1:8093".parse().unwrap(),
        std::time::Duration::from_secs(2),
    )
    .is_ok();
    Ok(ok)
}

// ---------------------------------------------------------------------------
// Commands — installation
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn install_uv(app: AppHandle) -> Result<InstallResult, String> {
    // Already installed?
    let check = check_uv().await?;
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

#[tauri::command]
pub async fn install_frago(
    app: AppHandle,
    version: Option<String>,
) -> Result<InstallResult, String> {
    let uv = resolve_uv_path();
    let uv_str = uv.to_string_lossy().to_string();

    let target_version_owned: String = match version {
        Some(v) => v,
        None => fetch_latest_pypi_version("frago-cli")
            .await
            .unwrap_or_else(|| env!("CARGO_PKG_VERSION").to_string()),
    };
    let target_version = target_version_owned.as_str();

    // Check if already installed with matching version
    let check = check_frago().await?;
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

// ---------------------------------------------------------------------------
// Commands — server management
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn start_server(app: AppHandle) -> Result<StartResult, String> {
    // Already running?
    if check_server().await.unwrap_or(false) {
        return Ok(StartResult {
            success: true,
            message: "Server already running".into(),
        });
    }

    let frago = resolve_frago_path();

    // Kill anything holding port 8093 — more reliable than `frago server stop`
    // which depends on PID files and matching frago versions
    #[cfg(unix)]
    {
        let output = Command::new("lsof")
            .args(["-ti", ":8093"])
            .output();
        if let Ok(o) = output {
            let pids = String::from_utf8_lossy(&o.stdout);
            for pid_str in pids.split_whitespace() {
                if let Ok(pid) = pid_str.parse::<i32>() {
                    unsafe { libc::kill(pid, libc::SIGTERM); }
                }
            }
            // Give processes a moment to release the port
            if !pids.trim().is_empty() {
                std::thread::sleep(std::time::Duration::from_secs(2));
            }
        }
    }

    // Log server output to a file for debugging
    let log_dir = home_dir().join(".frago");
    let _ = std::fs::create_dir_all(&log_dir);
    let log_file = std::fs::File::create(log_dir.join("server.log"))
        .map_err(|e| format!("Failed to create log file: {e}"))?;
    let log_stderr = log_file.try_clone()
        .map_err(|e| format!("Failed to clone log file: {e}"))?;

    // Run server in foreground mode as a child process.
    // Avoids the daemon double-fork which silently fails in .app bundles.
    // Server lifecycle is tied to the Tauri app — exits when app closes.
    Command::new(&frago)
        .args(["server", "--debug"])
        .stdout(log_file)
        .stderr(log_stderr)
        .spawn()
        .map_err(|e| format!("Failed to start server: {e}"))?;

    let _ = app.emit(
        BOOTSTRAP_LOG,
        BootstrapLogEvent {
            step: "start_server".into(),
            stream: "stdout".into(),
            line: "Server process spawned, waiting for ready...".into(),
        },
    );

    Ok(StartResult {
        success: true,
        message: "Server process spawned".into(),
    })
}

#[tauri::command]
pub async fn wait_for_server(timeout_ms: u64) -> Result<bool, String> {
    let deadline =
        std::time::Instant::now() + std::time::Duration::from_millis(timeout_ms);

    loop {
        if check_server().await.unwrap_or(false) {
            return Ok(true);
        }
        if std::time::Instant::now() >= deadline {
            return Ok(false);
        }
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }
}

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde::Serialize;
use sha2::{Digest, Sha256};
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
const BOOTSTRAP_PROGRESS: &str = "bootstrap-progress";

const CLAUDE_OFFICIAL_BASE: &str = "https://downloads.claude.ai/claude-code-releases";
const CLAUDE_MIRROR_BASE: &str =
    "https://claudebinary-1302792235.cos.ap-singapore.myqcloud.com/claude-binary";

#[derive(Serialize, Clone)]
struct BootstrapLogEvent {
    step: String,
    stream: String,
    line: String,
}

#[derive(Serialize, Clone)]
struct DownloadProgress {
    step: String,
    downloaded: u64,
    total: u64,
    bytes_per_sec: u64,
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

fn resolve_claude_path() -> PathBuf {
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

/// Detect the manifest.json platform key for the current host.
/// Mirrors the logic in the official Claude Code install.sh.
fn detect_platform() -> Result<&'static str, String> {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;

    let arch_str = match arch {
        "x86_64" => "x64",
        "aarch64" => "arm64",
        other => return Err(format!("unsupported arch: {other}")),
    };

    match os {
        "macos" => Ok(if arch_str == "arm64" { "darwin-arm64" } else { "darwin-x64" }),
        "windows" => Ok(if arch_str == "arm64" { "win32-arm64" } else { "win32-x64" }),
        "linux" => {
            let musl = std::path::Path::new("/lib/libc.musl-x86_64.so.1").exists()
                || std::path::Path::new("/lib/libc.musl-aarch64.so.1").exists();
            Ok(match (arch_str, musl) {
                ("x64", false) => "linux-x64",
                ("arm64", false) => "linux-arm64",
                ("x64", true) => "linux-x64-musl",
                ("arm64", true) => "linux-arm64-musl",
                _ => unreachable!(),
            })
        }
        other => Err(format!("unsupported os: {other}")),
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
pub async fn check_claude_code() -> Result<CheckResult, String> {
    let claude = resolve_claude_path();
    let output = Command::new(&claude).arg("--version").output();
    match output {
        Ok(o) if o.status.success() => {
            let raw = String::from_utf8_lossy(&o.stdout);
            // Output format: "1.0.123 (Claude Code)" — take the first whitespace token.
            let version = raw.trim().split_whitespace().next().map(|s| s.to_string());
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
// Claude Code: download + SHA256 + launcher setup, with mirror fallback
// ---------------------------------------------------------------------------

/// Single-attempt installer. Caller is responsible for retries.
async fn install_claude_code_inner(app: &AppHandle) -> Result<String, String> {
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

    // 3. Stream download with progress + SHA256
    let mut resp = client
        .get(format!("{base}/{version}/{platform}/{binary_name}"))
        .send()
        .await
        .map_err(|e| format!("Download start failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("Download HTTP {}", resp.status()));
    }

    let tmp_path = std::env::temp_dir().join(format!("claude-{version}-{platform}-{binary_name}"));
    let mut file = std::fs::File::create(&tmp_path)
        .map_err(|e| format!("Create temp file failed: {e}"))?;
    let mut hasher = Sha256::new();
    let mut downloaded: u64 = 0;
    let start = std::time::Instant::now();
    let mut last_emit = std::time::Instant::now();

    while let Some(chunk) = resp
        .chunk()
        .await
        .map_err(|e| format!("Download interrupted: {e}"))?
    {
        hasher.update(&chunk);
        file.write_all(&chunk)
            .map_err(|e| format!("Write failed: {e}"))?;
        downloaded += chunk.len() as u64;

        if last_emit.elapsed().as_millis() >= 100 {
            let elapsed_ms = start.elapsed().as_millis() as u64;
            let bps = if elapsed_ms > 0 {
                downloaded.saturating_mul(1000) / elapsed_ms.max(1)
            } else {
                0
            };
            let _ = app.emit(
                BOOTSTRAP_PROGRESS,
                DownloadProgress {
                    step: "claude_code".into(),
                    downloaded,
                    total: total_size,
                    bytes_per_sec: bps,
                },
            );
            last_emit = std::time::Instant::now();
        }
    }
    file.flush()
        .map_err(|e| format!("Flush failed: {e}"))?;
    drop(file);

    // Final 100% progress event
    let _ = app.emit(
        BOOTSTRAP_PROGRESS,
        DownloadProgress {
            step: "claude_code".into(),
            downloaded,
            total: total_size,
            bytes_per_sec: 0,
        },
    );

    // 4. SHA256 verify
    let actual_sha = format!("{:x}", hasher.finalize());
    if !actual_sha.eq_ignore_ascii_case(&expected_sha) {
        let _ = std::fs::remove_file(&tmp_path);
        return Err(format!(
            "checksum mismatch: expected {expected_sha}, got {actual_sha}"
        ));
    }

    // 5. chmod +x on Unix
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = std::fs::metadata(&tmp_path)
            .map_err(|e| format!("Read perms failed: {e}"))?
            .permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&tmp_path, perms)
            .map_err(|e| format!("chmod failed: {e}"))?;
    }

    // 6. Run `<binary> install` to set up the launcher (~/.local/bin/claude etc).
    //    This is what the official install.sh does at its tail.
    let tmp_str = tmp_path.to_string_lossy().to_string();
    run_with_streaming(app, "install_claude_code", &tmp_str, &["install"])?;

    // 7. Cleanup temp binary
    let _ = std::fs::remove_file(&tmp_path);

    Ok(format!("Claude Code {version} installed"))
}

#[tauri::command]
pub async fn install_claude_code(app: AppHandle) -> Result<InstallResult, String> {
    // Skip if already present
    let check = check_claude_code().await?;
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
        match install_claude_code_inner(&app).await {
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

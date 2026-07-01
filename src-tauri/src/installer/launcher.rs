//! Server lifecycle: readiness probe, start, and wait.

use std::process::Command;

use tauri::{AppHandle, Emitter};

use crate::constants::{BOOTSTRAP_LOG, SERVER_ADDR};

use super::{home_dir, resolve_frago_path, BootstrapLogEvent, StartResult};

pub async fn check_server() -> Result<bool, String> {
    // Use raw TCP connect instead of reqwest HTTP — reqwest can fail
    // inside macOS .app bundles due to network sandbox restrictions
    use std::net::TcpStream;
    let ok = TcpStream::connect_timeout(
        &SERVER_ADDR.parse().unwrap(),
        std::time::Duration::from_secs(2),
    )
    .is_ok();
    Ok(ok)
}

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
        let port_arg = format!(":{}", crate::constants::SERVER_PORT);
        let output = Command::new("lsof").args(["-ti", &port_arg]).output();
        if let Ok(o) = output {
            let pids = String::from_utf8_lossy(&o.stdout);
            for pid_str in pids.split_whitespace() {
                if let Ok(pid) = pid_str.parse::<i32>() {
                    unsafe {
                        libc::kill(pid, libc::SIGTERM);
                    }
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
    let log_stderr = log_file
        .try_clone()
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

pub async fn wait_for_server(timeout_ms: u64) -> Result<bool, String> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(timeout_ms);

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

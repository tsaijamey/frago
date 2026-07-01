//! Shared child-process helper, reused by uv/frago/claude_code/start_server.

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};

use tauri::{AppHandle, Emitter};

use crate::constants::BOOTSTRAP_LOG;

use super::BootstrapLogEvent;

/// Run a command and stream stdout/stderr lines as Tauri events.
pub(crate) fn run_with_streaming(
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

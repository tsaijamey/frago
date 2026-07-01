//! Tauri command entry points.
//!
//! These are thin wrappers — all install/check/launch logic lives in the
//! `installer` submodules. Keep the command names and signatures frozen: the
//! webui invokes them by name (see `main.rs` `generate_handler!`).

use tauri::AppHandle;

use crate::installer::{self, CheckResult, InstallResult, StartResult};

// ---------------------------------------------------------------------------
// Environment checks
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn check_uv() -> Result<CheckResult, String> {
    installer::uv::check().await
}

#[tauri::command]
pub async fn check_frago() -> Result<CheckResult, String> {
    installer::frago::check().await
}

#[tauri::command]
pub async fn check_claude_code() -> Result<CheckResult, String> {
    installer::claude_code::check().await
}

#[tauri::command]
pub async fn check_server() -> Result<bool, String> {
    installer::launcher::check_server().await
}

// ---------------------------------------------------------------------------
// Installation
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn install_uv(app: AppHandle) -> Result<InstallResult, String> {
    installer::uv::install(app).await
}

#[tauri::command]
pub async fn install_frago(
    app: AppHandle,
    version: Option<String>,
) -> Result<InstallResult, String> {
    installer::frago::install(app, version).await
}

#[tauri::command]
pub async fn install_claude_code(app: AppHandle) -> Result<InstallResult, String> {
    installer::claude_code::install(app).await
}

// ---------------------------------------------------------------------------
// Server management
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn start_server(app: AppHandle) -> Result<StartResult, String> {
    installer::launcher::start_server(app).await
}

#[tauri::command]
pub async fn wait_for_server(timeout_ms: u64) -> Result<bool, String> {
    installer::launcher::wait_for_server(timeout_ms).await
}

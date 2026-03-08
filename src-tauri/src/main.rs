// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            commands::check_uv,
            commands::check_frago,
            commands::check_server,
            commands::install_uv,
            commands::install_frago,
            commands::start_server,
            commands::wait_for_server,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

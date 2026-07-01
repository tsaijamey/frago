//! Shared constants for the bootstrap installer / launcher.

/// Tauri event name for streamed bootstrap log lines.
pub const BOOTSTRAP_LOG: &str = "bootstrap-log";
/// Tauri event name for download progress updates.
pub const BOOTSTRAP_PROGRESS: &str = "bootstrap-progress";

/// Official Claude Code release CDN base.
pub const CLAUDE_OFFICIAL_BASE: &str = "https://downloads.claude.ai/claude-code-releases";
/// Tencent Cloud mirror base (mainland China fallback).
pub const CLAUDE_MIRROR_BASE: &str =
    "https://claudebinary-1302792235.cos.ap-singapore.myqcloud.com/claude-binary";

/// Local frago server port.
pub const SERVER_PORT: u16 = 8093;
/// Local frago server address (used for TCP readiness probes).
pub const SERVER_ADDR: &str = "127.0.0.1:8093";

/// Version fallback when the PyPI lookup fails — pinned to this crate's version.
pub const FALLBACK_VERSION: &str = env!("CARGO_PKG_VERSION");

//! Single-attempt, verified download for the claude_code binary.
//!
//! Streams the binary to `dest`, emits `BOOTSTRAP_PROGRESS` every 100ms, and
//! verifies the SHA256 against `expected_sha`. Retry / mirror fallback is NOT
//! here — that lives in the `claude_code` orchestration layer.

use std::io::Write;
use std::path::Path;

use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter};

use crate::constants::BOOTSTRAP_PROGRESS;

use super::DownloadProgress;

/// Case-insensitive checksum comparison (hex digests).
pub(crate) fn checksum_matches(actual: &str, expected: &str) -> bool {
    actual.eq_ignore_ascii_case(expected)
}

/// Download `url` to `dest`, streaming progress events, then verify SHA256.
///
/// On checksum mismatch the partial file is removed and an `Err` is returned.
/// The caller (claude_code orchestration) owns retries and mirror selection.
pub(crate) async fn download_verified(
    app: &AppHandle,
    client: &reqwest::Client,
    url: &str,
    expected_sha: &str,
    total_size: u64,
    dest: &Path,
) -> Result<(), String> {
    let mut resp = client
        .get(url)
        .send()
        .await
        .map_err(|e| format!("Download start failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("Download HTTP {}", resp.status()));
    }

    let mut file =
        std::fs::File::create(dest).map_err(|e| format!("Create temp file failed: {e}"))?;
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
    file.flush().map_err(|e| format!("Flush failed: {e}"))?;
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

    // SHA256 verify
    let actual_sha = format!("{:x}", hasher.finalize());
    if !checksum_matches(&actual_sha, expected_sha) {
        let _ = std::fs::remove_file(dest);
        return Err(format!(
            "checksum mismatch: expected {expected_sha}, got {actual_sha}"
        ));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::checksum_matches;
    use sha2::{Digest, Sha256};

    /// Deterministic SHA256 of a known fixture, verifying the exact digest the
    /// download path computes and the case-insensitive comparison it uses.
    #[test]
    fn sha256_of_fixture_matches_known_digest() {
        let fixture = b"frago claude_code fixture";
        let actual = format!("{:x}", Sha256::digest(fixture));

        // Precomputed: `printf 'frago claude_code fixture' | shasum -a 256`
        let expected = "902464f2b57c7b7d190ac7b56653abb535824ecf2f7bfd44b75952bd56d1fada";

        assert_eq!(actual, expected);
        assert!(checksum_matches(&actual, expected));
        assert!(checksum_matches(&actual, &expected.to_uppercase()));
        assert!(!checksum_matches(&actual, "deadbeef"));
    }
}

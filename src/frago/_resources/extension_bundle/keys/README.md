# frago bridge extension keys

This directory holds the RSA 2048 keypair that pins the Chrome extension ID.

## Files

- `private.pem` — **NOT committed**. Developer-only, used to sign builds for
  Chrome Web Store submission. Generated once by
  `scripts/generate_extension_id.py`. Mode 0600.
- `public.der` — SubjectPublicKeyInfo DER. Hash of this bytestring (via
  Chrome's algorithm: `sha256(der)[:16]` mapped hex `0-f` → `a-p`) yields
  the stable extension ID. Committed so anyone can reproduce the ID.

## Stable extension ID

    eajjhcepifleiifebabkjmhampcephfp

This ID is hardcoded in two places:

1. `bundle/manifest.json` as the base64-encoded `key` field (embeds the
   public key; Chrome uses it to derive the ID at load time).
2. `src/frago/extension/native_host.py` as `STABLE_EXTENSION_ID` (the
   native messaging manifest's `allowed_origins` field trusts only this ID).

## Regenerating

    uv run python scripts/generate_extension_id.py

If `private.pem` already exists the script is a no-op. To rotate the key,
delete `private.pem` first, then rerun — and update both hardcoded sites.

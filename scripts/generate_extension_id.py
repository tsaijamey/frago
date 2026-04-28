"""Generate a stable Chrome extension ID + RSA keypair (via openssl).

Chrome derives the extension ID deterministically from the public key
embedded in manifest.json's ``key`` field:

    id = map(sha256(DER(pubkey))[:16].hex(), "0-f" -> "a-p")

Running this script once writes:

    src/frago/_resources/extension_bundle/keys/private.pem
    src/frago/_resources/extension_bundle/keys/public.der
    <out>/extension_id.txt
    <out>/manifest_key_snippet.json

Note: private.pem is excluded from the wheel (see pyproject.toml
[tool.hatch.build.targets.wheel] exclude). Only run this when rotating
the extension ID — the current ID is pinned in manifest.json's "key"
field and STABLE_EXTENSION_ID in src/frago/chrome/extension/native_host.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEYS_DIR = REPO / "src" / "frago" / "_resources" / "extension_bundle" / "keys"


def derive_extension_id(der_pubkey: bytes) -> str:
    digest = hashlib.sha256(der_pubkey).digest()[:16]
    hexstr = digest.hex()
    return "".join(chr(ord("a") + int(c, 16)) for c in hexstr)


def main(output_dir: Path) -> None:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv_path = KEYS_DIR / "private.pem"
    pub_der_path = KEYS_DIR / "public.der"

    if not priv_path.exists():
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "RSA",
             "-pkeyopt", "rsa_keygen_bits:2048",
             "-out", str(priv_path)],
            check=True, capture_output=True,
        )
        priv_path.chmod(0o600)
        print(f"[write] {priv_path}", file=sys.stderr)
    else:
        print(f"[reuse] {priv_path}", file=sys.stderr)

    # Export SubjectPublicKeyInfo DER (what Chrome hashes).
    der = subprocess.run(
        ["openssl", "pkey", "-in", str(priv_path), "-pubout", "-outform", "DER"],
        check=True, capture_output=True,
    ).stdout
    pub_der_path.write_bytes(der)

    ext_id = derive_extension_id(der)
    manifest_key_b64 = base64.b64encode(der).decode("ascii")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "extension_id.txt").write_text(ext_id + "\n")
    (output_dir / "manifest_key_snippet.json").write_text(
        json.dumps({"key": manifest_key_b64}, indent=2) + "\n"
    )

    print(json.dumps({
        "extension_id": ext_id,
        "manifest_key_b64_len": len(manifest_key_b64),
        "private_key": str(priv_path),
        "public_der": str(pub_der_path),
    }, indent=2))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "outputs"
    main(out)

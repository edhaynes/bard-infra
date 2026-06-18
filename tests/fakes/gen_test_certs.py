"""Generate throwaway self-signed TLS certs for local tests.

    python tests/fakes/gen_test_certs.py [out_dir]

Output is gitignored (``.tls-test/`` by default) and MUST NEVER be committed
(CLAUDE.md §6). Uses ``trustme`` so no openssl/shell dependency is required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import trustme


def generate(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ca = trustme.CA()
    cert = ca.issue_cert("localhost", "127.0.0.1")
    cert_path = out_dir / "test-cert.pem"
    key_path = out_dir / "test-key.pem"
    cert.cert_chain_pems[0].write_to_path(str(cert_path))
    cert.private_key_pem.write_to_path(str(key_path))
    return cert_path, key_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./.tls-test")
    cert, key = generate(out)
    print(f"wrote {cert} and {key} (gitignored — do not commit)")

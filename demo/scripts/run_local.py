"""Run the whole refinery demo locally: Registry + orchestrator + fleet + console.

Starts the four processes that make up the demo, wires them with an ephemeral
in-memory JWT secret (never written to disk), waits until each is healthy, and prints
the URLs. Ctrl-C tears everything down. Cross-platform (subprocess + pathlib, no shell).

    python scripts/run_local.py            # all four services
    python scripts/run_local.py --no-console   # backend only (no node)

Tiers (see ../PLAN_refinery_demo.md §4):
  - bard-infra Registry  :8081  (real self-discovery target)
  - fleet projector            (registers ~116 elements + heartbeats)
  - orchestrator         :7090  (telemetry + bring-up/down + faults)
  - console              :5175  (the dashboard)
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1]
BARD_INFRA = DEMO.parent
REGISTRY_PORT = 8081
ORCH_PORT = 7090
CONSOLE_PORT = 5175


def venv_python(root: Path) -> str:
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        p = root / rel
        if p.exists():
            return str(p)
    return sys.executable


def wait_healthy(url: str, name: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    print(f"  ✓ {name} healthy ({url})")
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    raise SystemExit(f"  ✗ {name} did not become healthy at {url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-console", action="store_true", help="skip the node console")
    args = parser.parse_args()

    secret = secrets.token_hex(32)  # ephemeral; never persisted
    demo_py = venv_python(DEMO)
    infra_py = venv_python(BARD_INFRA)
    registry_url = f"http://127.0.0.1:{REGISTRY_PORT}"

    procs: list[subprocess.Popen] = []

    def spawn(cmd: list[str], *, cwd: Path, env_extra: dict[str, str]) -> None:
        env = {**os.environ, **env_extra}
        procs.append(subprocess.Popen(cmd, cwd=str(cwd), env=env))

    try:
        print("Starting bard-infra Registry...")
        spawn(
            [
                infra_py,
                "-m",
                "uvicorn",
                "registry.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(REGISTRY_PORT),
            ],
            cwd=BARD_INFRA,
            env_extra={"BARDPRO_JWT_SECRET": secret, "BARDPRO_ALLOW_INSECURE_HTTP": "true"},
        )
        wait_healthy(f"{registry_url}/healthz", "Registry")

        print("Starting orchestrator...")
        spawn(
            [
                demo_py,
                "-m",
                "uvicorn",
                "refinery.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(ORCH_PORT),
            ],
            cwd=DEMO,
            env_extra={},
        )
        wait_healthy(f"http://127.0.0.1:{ORCH_PORT}/healthz", "Orchestrator")

        print("Starting fleet projector (self-discovery into the Registry)...")
        spawn(
            [demo_py, "scripts/project_fleet.py"],
            cwd=DEMO,
            env_extra={"REFINERY_JWT_SECRET": secret, "REFINERY_REGISTRY_URL": registry_url},
        )

        if not args.no_console:
            npm = shutil.which("npm")
            if npm is None:
                print("  ! npm not found — skipping console")
            else:
                print("Starting console...")
                spawn([npm, "run", "dev"], cwd=DEMO / "console", env_extra={})

        print("\nDemo up:")
        print(f"  Console:       http://127.0.0.1:{CONSOLE_PORT}")
        print(f"  Orchestrator:  http://127.0.0.1:{ORCH_PORT}/state")
        print(f"  Registry:      {registry_url}/agents  (bearer-gated)")
        print("\nCtrl-C to stop.\n")
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()

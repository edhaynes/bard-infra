"""Project the refinery fleet into the real bard-infra Registry.

Loads the topology, then registers every element as a bard-infra agent and (by
default) heartbeats forever. Use ``--once`` to register a single round and exit
(handy for verification). Config comes from the environment / .env (see
``.env.example``); never pass a real secret on the command line.

    REFINERY_JWT_SECRET=... python scripts/project_fleet.py [--once]
"""

from __future__ import annotations

import argparse
import asyncio

import httpx
from refinery.model import default_topology_path, load_topology
from refinery.registry_projector import ProjectorConfig, RegistryProjector


async def _run(once: bool) -> None:
    ref = load_topology(default_topology_path())
    proj = RegistryProjector(ProjectorConfig.from_env())
    elements = ref.all_elements
    async with httpx.AsyncClient() as client:
        token = proj.mint_token()
        n = await proj.register_all(client, elements, token)
        print(f"registered {n} elements into {proj.config.registry_url}")
        if once:
            return
        print(f"heartbeating every {proj.config.heartbeat_seconds}s (Ctrl-C to stop)")
        await proj.heartbeat_loop(client, elements, asyncio.Event())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="register once and exit")
    args = parser.parse_args()
    asyncio.run(_run(args.once))


if __name__ == "__main__":
    main()

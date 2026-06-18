"""Capability-aware placement (demo Phase 1.4).

Picks the best node in the fleet for a workload from the registered agents'
advertised power profiles — GPU-preferred when asked, CPU-fallback otherwise
("any accelerator"). Pure function, unit-tested; the Registry exposes it via
``GET /schedule`` and the demo dashboard shows the chosen node light up.
"""

from __future__ import annotations

from typing import Any

from common.power import parse_memory_bytes


def _has_gpu(agent: dict[str, Any]) -> bool:
    return bool(agent.get("powerProfile", {}).get("gpus"))


def _cpus(agent: dict[str, Any]) -> float:
    return agent.get("powerProfile", {}).get("cpus") or 0


def _memory_bytes(agent: dict[str, Any]) -> int:
    memory = agent.get("powerProfile", {}).get("memory")
    return parse_memory_bytes(memory) if memory else 0


def select_agent(
    agents: list[dict[str, Any]], *, require_gpu: bool = False
) -> dict[str, Any] | None:
    """Choose the best-fit agent, or None when the fleet is empty.

    With ``require_gpu`` we prefer GPU-capable nodes but **fall back** to the
    rest of the fleet rather than fail (the "any accelerator" story). Candidates
    are ranked GPU-first, then by advertised CPUs, then memory.
    """
    if not agents:
        return None
    candidates = [a for a in agents if _has_gpu(a)] if require_gpu else list(agents)
    if require_gpu and not candidates:
        candidates = list(agents)  # CPU fallback — any accelerator beats none
    candidates.sort(key=lambda a: (_has_gpu(a), _cpus(a), _memory_bytes(a)), reverse=True)
    return candidates[0]

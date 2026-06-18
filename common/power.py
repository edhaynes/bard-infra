"""Pydantic projection of ``contracts/power-profile.schema.yaml``.

Used by the registry to validate a power profile at registration time. The YAML
schema is canonical; keep this in sync with it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MEMORY_RE = re.compile(r"^[0-9]+(b|k|m|g)?$")


class PowerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    cpus: float | None = Field(default=None, gt=0)
    memory: str | None = None
    pidsLimit: int | None = Field(default=None, ge=1)
    gpus: str | None = None
    batteryAware: bool = False

    @field_validator("memory")
    @classmethod
    def _check_memory(cls, v: str | None) -> str | None:
        if v is not None and not _MEMORY_RE.match(v):
            raise ValueError("memory must match ^[0-9]+(b|k|m|g)?$ e.g. 2g, 512m")
        return v


_UNIT_BYTES = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def parse_memory_bytes(memory: str) -> int:
    """Parse a power-profile memory string ("2g", "512m", "1024") to bytes."""
    if not _MEMORY_RE.match(memory):
        raise ValueError(f"invalid memory string: {memory!r}")
    suffix = memory[-1]
    if suffix in _UNIT_BYTES:
        return int(memory[:-1]) * _UNIT_BYTES[suffix]
    return int(memory)


def aggregate_pool(profiles: list[dict]) -> dict:
    """Sum a fleet's power profiles into a pooled-capacity view for the demo.

    Returns total advertised CPUs, memory (bytes), the count of GPU-capable
    nodes, and how many of the supplied profiles contributed.
    """
    total_cpus = 0.0
    total_memory_bytes = 0
    gpu_nodes = 0
    for profile in profiles:
        cpus = profile.get("cpus")
        if cpus is not None:
            total_cpus += cpus
        memory = profile.get("memory")
        if memory is not None:
            total_memory_bytes += parse_memory_bytes(memory)
        if profile.get("gpus"):
            gpu_nodes += 1
    return {
        "nodes": len(profiles),
        "cpus": total_cpus,
        "memoryBytes": total_memory_bytes,
        "gpuNodes": gpu_nodes,
    }

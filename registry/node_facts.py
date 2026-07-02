"""Facts projector — ansible fact cache -> the frozen ``NodeFacts`` contract.

Feature #91 / ADR-0018. Ansible's ``setup`` (plus an ``nvidia-smi`` custom
fact) does ALL the gathering; this module only *maps* the huge raw fact blob
down to the five field groups the console renders (CPU, memory, GPU, storage,
networking) and serves them via ``GET /nodes``. The raw blob never reaches the
client.

:func:`project_facts` is a pure mapping (raw dict -> one ``NodeFacts`` dict)
with a defined default for every field, so a node with missing or malformed
facts still yields a full, renderable row rather than crashing the load.
:func:`load_facts_cache` reads the jsonfile cache (one file per host), projects
each entry, and returns the list sorted by ``nodeId``. Both take their clock /
mtime / reader by injection (CLAUDE.md §2/§11) so the suite drives every branch
hermetically — no real filesystem time, no network.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Virtual / pseudo block devices that are not real disks (ADR-0018 storage
# discovery): loopback mounts, ramdisks, device-mapper nodes, optical drives.
_VIRTUAL_DEVICE_PREFIXES = ("loop", "ram", "dm-", "sr")

# The default host-loopback interface is always excluded from the fact view.
_LOOPBACK_IFACE = "lo"

# Size-string unit -> gigabytes multiplier (ansible_devices[*].size, e.g.
# "931.51 GB", "3.64 TB"). GB is the contract unit.
_SIZE_UNIT_TO_GB = {"TB": 1000.0, "GB": 1.0, "MB": 0.001, "KB": 0.000001, "B": 1e-9}


def file_mtime_iso(path: Path) -> str:
    """Cache-file mtime as an ISO-8601 UTC string — the default ``read_mtime``.

    Used as the ``gatheredAt`` fallback when a cache entry carries no
    ``ansible_date_time`` (injected in tests so no real fs time leaks in).
    """
    ts = path.stat().st_mtime
    return _dt.datetime.fromtimestamp(ts, _dt.UTC).isoformat()


def _cpu(raw: dict[str, Any]) -> dict[str, Any]:
    processor = raw.get("ansible_processor")
    model = processor[-1] if isinstance(processor, list) and processor else ""
    arch = raw.get("ansible_architecture")
    cores = raw.get("ansible_processor_cores")
    count = raw.get("ansible_processor_count")
    vcpus = raw.get("ansible_processor_vcpus")
    vcpus_out = vcpus if isinstance(vcpus, int) else 0
    if isinstance(cores, int) and isinstance(count, int):
        cores_out = cores * count
    else:
        cores_out = vcpus_out
    return {
        "model": model if isinstance(model, str) else "",
        "arch": arch if isinstance(arch, str) else "",
        "cores": cores_out,
        "vcpus": vcpus_out,
    }


def _memory(raw: dict[str, Any]) -> dict[str, Any]:
    total = raw.get("ansible_memtotal_mb")
    return {"totalMb": total if isinstance(total, int) else 0}


def _gpu(raw: dict[str, Any]) -> dict[str, Any] | None:
    entries = raw.get("bard_gpu")
    if not (isinstance(entries, list) and entries):
        return None
    # "NVIDIA GB10, 131072" -> (name, memoryMiB). Multiple GPUs: take the first
    # (contract shape is one gpu object; count is not part of the frozen shape).
    first = entries[0]
    parts = str(first).split(",")
    model = parts[0].strip()
    memory_mb = 0
    if len(parts) > 1:
        try:
            memory_mb = int(parts[1].strip())
        except ValueError:
            memory_mb = 0
    return {"model": model, "memoryMb": memory_mb}


def _parse_size_string(size: str) -> float | None:
    parts = size.split()
    if len(parts) != 2:
        return None
    number, unit = parts
    multiplier = _SIZE_UNIT_TO_GB.get(unit)
    if multiplier is None:
        return None
    try:
        return float(number) * multiplier
    except ValueError:
        return None


def _device_size_gb(info: Any) -> float:
    if not isinstance(info, dict):
        return 0.0
    size = info.get("size")
    if isinstance(size, str):
        parsed = _parse_size_string(size)
        if parsed is not None:
            return parsed
    sectors = info.get("sectors")
    sectorsize = info.get("sectorsize")
    try:
        return int(sectors) * int(sectorsize) / 1e9
    except (TypeError, ValueError):
        return 0.0


def _storage(raw: dict[str, Any]) -> list[dict[str, Any]]:
    devices = raw.get("ansible_devices")
    if not isinstance(devices, dict):
        return []
    out: list[dict[str, Any]] = []
    for name in sorted(devices):
        if name.startswith(_VIRTUAL_DEVICE_PREFIXES):
            continue
        out.append({"device": name, "sizeGb": _device_size_gb(devices[name])})
    return out


def _iface_row(name: str, info: Any, *, is_default: bool) -> dict[str, Any] | None:
    ipv4: str | None = None
    speed: int | None = None
    if isinstance(info, dict):
        ipv4_info = info.get("ipv4")
        if isinstance(ipv4_info, dict):
            ipv4 = ipv4_info.get("address")
        raw_speed = info.get("speed")
        if isinstance(raw_speed, int):
            speed = raw_speed
    # List an interface only when it carries an IPv4 or is the default route.
    if ipv4 is None and not is_default:
        return None
    return {"iface": name, "ipv4": ipv4, "speedMbps": speed}


def _networking(raw: dict[str, Any]) -> list[dict[str, Any]]:
    ifaces = raw.get("ansible_interfaces")
    if not isinstance(ifaces, list):
        return []
    default = raw.get("ansible_default_ipv4")
    default_iface = default.get("interface") if isinstance(default, dict) else None
    out: list[dict[str, Any]] = []
    for name in ifaces:
        if name == _LOOPBACK_IFACE:
            continue
        row = _iface_row(name, raw.get(f"ansible_{name}"), is_default=(name == default_iface))
        if row is not None:
            out.append(row)
    return out


def _gathered_at(raw: dict[str, Any], fallback: str) -> str:
    date_time = raw.get("ansible_date_time")
    if isinstance(date_time, dict):
        iso = date_time.get("iso8601")
        if isinstance(iso, str) and iso:
            return iso
    return fallback


def project_facts(raw: dict[str, Any], *, gathered_at: str) -> dict[str, Any]:
    """Map one host's raw ansible facts to a single ``NodeFacts`` dict (pure).

    ``gathered_at`` is the fallback timestamp (typically the cache file mtime)
    used only when the raw facts carry no ``ansible_date_time.iso8601``. Every
    field is emitted with a defined default so a partial/malformed input still
    produces a complete, contract-shaped row.
    """
    node_id = (
        raw.get("ansible_hostname") or raw.get("ansible_fqdn") or raw.get("ansible_nodename") or ""
    )
    return {
        "nodeId": node_id,
        "cpu": _cpu(raw),
        "memory": _memory(raw),
        "gpu": _gpu(raw),
        "storage": _storage(raw),
        "networking": _networking(raw),
        "gatheredAt": _gathered_at(raw, gathered_at),
    }


def _default_read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_facts_cache(
    cache_dir: Path,
    *,
    now_iso: Callable[[], str],
    read_mtime: Callable[[Path], str],
    read_json: Callable[[Path], Any] = _default_read_json,
) -> list[dict[str, Any]]:
    """Project every host file in the ansible fact cache into ``NodeFacts``.

    Returns the list sorted by ``nodeId``. A missing cache directory yields
    ``[]``. A file that fails to parse (bad JSON, unreadable, or not a fact
    mapping) is skipped with a warning — one poisoned file never fails the whole
    load. ``now_iso`` / ``read_mtime`` / ``read_json`` are injected so the load
    is hermetic (no real fs time, no real reads in unit tests).
    """
    if not cache_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(cache_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            raw = read_json(path)
        except (OSError, ValueError) as exc:
            logger.warning("Skipping unreadable facts cache file %s: %s", path, exc)
            continue
        if not isinstance(raw, dict):
            logger.warning("Skipping facts cache file %s: not a fact mapping", path)
            continue
        mtime = read_mtime(path)
        fallback = mtime if mtime else now_iso()
        out.append(project_facts(raw, gathered_at=fallback))
    out.sort(key=lambda facts: facts["nodeId"])
    return out

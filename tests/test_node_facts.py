"""S2 — the facts projector (registry/node_facts.py).

Drives every mapping branch of ``project_facts`` (CPU/memory/GPU/storage/
networking/gatheredAt, each with missing + malformed inputs) and every branch
of ``load_facts_cache`` (missing dir, subdir skip, malformed JSON skip,
non-mapping skip, mtime vs now_iso fallback, sorting). Hermetic: injected clock
+ mtime; real files only under pytest's ``tmp_path``.
"""

from __future__ import annotations

import datetime as _dt

from registry.node_facts import (
    file_mtime_iso,
    load_facts_cache,
    project_facts,
)

FALLBACK = "2026-07-01T00:00:00+00:00"


def _project(raw: dict) -> dict:
    return project_facts(raw, gathered_at=FALLBACK)


# --- CPU --------------------------------------------------------------------


def test_cpu_full_facts():
    cpu = _project(
        {
            "ansible_processor": ["0", "AuthenticAMD", "AMD Ryzen 7 7700"],
            "ansible_architecture": "x86_64",
            "ansible_processor_cores": 8,
            "ansible_processor_count": 1,
            "ansible_processor_vcpus": 16,
        }
    )["cpu"]
    assert cpu == {"model": "AMD Ryzen 7 7700", "arch": "x86_64", "cores": 8, "vcpus": 16}


def test_cpu_missing_everything_defaults_to_zeroes():
    assert _project({})["cpu"] == {"model": "", "arch": "", "cores": 0, "vcpus": 0}


def test_cpu_cores_fall_back_to_vcpus_when_physical_absent():
    # No cores/count -> cores mirrors the logical vcpu count.
    cpu = _project({"ansible_processor_vcpus": 4})["cpu"]
    assert cpu["cores"] == 4
    assert cpu["vcpus"] == 4


def test_cpu_non_string_model_and_arch_are_coerced_to_empty():
    # Malformed facts: processor last element / arch not strings -> "".
    cpu = _project({"ansible_processor": [0, 1], "ansible_architecture": 123})["cpu"]
    assert cpu["model"] == ""
    assert cpu["arch"] == ""


# --- Memory -----------------------------------------------------------------


def test_memory_present():
    assert _project({"ansible_memtotal_mb": 128000})["memory"] == {"totalMb": 128000}


def test_memory_missing_or_malformed_defaults_zero():
    assert _project({"ansible_memtotal_mb": "lots"})["memory"] == {"totalMb": 0}
    assert _project({})["memory"] == {"totalMb": 0}


# --- GPU --------------------------------------------------------------------


def test_gpu_single_entry():
    assert _project({"bard_gpu": ["NVIDIA GB10, 131072"]})["gpu"] == {
        "model": "NVIDIA GB10",
        "memoryMb": 131072,
    }


def test_gpu_multi_takes_first():
    gpu = _project({"bard_gpu": ["NVIDIA GB10, 131072", "NVIDIA A100, 40960"]})["gpu"]
    assert gpu == {"model": "NVIDIA GB10", "memoryMb": 131072}


def test_gpu_empty_list_is_null():
    assert _project({"bard_gpu": []})["gpu"] is None


def test_gpu_absent_is_null():
    assert _project({})["gpu"] is None


def test_gpu_malformed_memory_defaults_zero():
    assert _project({"bard_gpu": ["NVIDIA GB10, huge"]})["gpu"] == {
        "model": "NVIDIA GB10",
        "memoryMb": 0,
    }


def test_gpu_no_comma_defaults_memory_zero():
    assert _project({"bard_gpu": ["NVIDIA GB10"]})["gpu"] == {
        "model": "NVIDIA GB10",
        "memoryMb": 0,
    }


# --- Storage ----------------------------------------------------------------


def test_storage_filters_virtual_and_parses_sizes():
    devices = {
        "sda": {"size": "931.51 GB"},
        "nvme0n1": {"sectors": 1_000_000_000, "sectorsize": 512},
        "sdf": {"size": "bad", "sectors": 2_000_000_000, "sectorsize": 512},
        "sdb": "not-a-dict",
        "sdc": {"size": "931.51GB"},  # no space -> unparseable, no sectors -> 0
        "sdd": {"size": "10 PB"},  # unknown unit -> unparseable, no sectors -> 0
        "sde": {"size": "abc GB"},  # non-numeric -> unparseable, no sectors -> 0
        "loop0": {"size": "1.00 GB"},
        "ram0": {"size": "1.00 GB"},
        "dm-0": {"size": "1.00 GB"},
        "sr0": {"size": "1.00 GB"},
    }
    storage = _project({"ansible_devices": devices})["storage"]
    assert storage == [
        {"device": "nvme0n1", "sizeGb": 512.0},
        {"device": "sda", "sizeGb": 931.51},
        {"device": "sdb", "sizeGb": 0.0},
        {"device": "sdc", "sizeGb": 0.0},
        {"device": "sdd", "sizeGb": 0.0},
        {"device": "sde", "sizeGb": 0.0},
        {"device": "sdf", "sizeGb": 1024.0},
    ]


def test_storage_absent_or_not_a_dict_is_empty():
    assert _project({})["storage"] == []
    assert _project({"ansible_devices": ["sda"]})["storage"] == []


# --- Networking -------------------------------------------------------------


def test_networking_lists_ipv4_and_default_ifaces():
    raw = {
        "ansible_interfaces": ["lo", "eth0", "eth1", "wlan0", "eth2"],
        "ansible_default_ipv4": {"interface": "eth2"},
        "ansible_eth0": {"ipv4": {"address": "10.0.0.5"}, "speed": 1000},
        "ansible_eth1": {"ipv4": {"address": None}},  # no ipv4, not default -> skip
        "ansible_wlan0": "not-a-dict",  # info not a dict, not default -> skip
        "ansible_eth2": {"speed": None},  # default, no ipv4, null speed -> kept
    }
    assert _project(raw)["networking"] == [
        {"iface": "eth0", "ipv4": "10.0.0.5", "speedMbps": 1000},
        {"iface": "eth2", "ipv4": None, "speedMbps": None},
    ]


def test_networking_without_default_keeps_only_ipv4_ifaces():
    raw = {
        "ansible_interfaces": ["eth0"],
        "ansible_eth0": {"ipv4": {"address": "10.0.0.9"}},
    }
    assert _project(raw)["networking"] == [{"iface": "eth0", "ipv4": "10.0.0.9", "speedMbps": None}]


def test_networking_absent_or_not_a_list_is_empty():
    assert _project({})["networking"] == []
    assert _project({"ansible_interfaces": {"eth0": {}}})["networking"] == []


# --- gatheredAt + nodeId ----------------------------------------------------


def test_gathered_at_prefers_ansible_date_time():
    facts = _project({"ansible_date_time": {"iso8601": "2026-06-30T09:00:00Z"}})
    assert facts["gatheredAt"] == "2026-06-30T09:00:00Z"


def test_gathered_at_falls_back_when_date_time_missing_or_empty():
    assert _project({})["gatheredAt"] == FALLBACK
    assert _project({"ansible_date_time": {"iso8601": ""}})["gatheredAt"] == FALLBACK
    assert _project({"ansible_date_time": "not-a-dict"})["gatheredAt"] == FALLBACK


def test_node_id_prefers_hostname_then_fqdn_then_empty():
    assert _project({"ansible_hostname": "gx10"})["nodeId"] == "gx10"
    assert _project({"ansible_fqdn": "gx10.local"})["nodeId"] == "gx10.local"
    assert _project({"ansible_nodename": "gx10.node"})["nodeId"] == "gx10.node"
    assert _project({})["nodeId"] == ""


# --- load_facts_cache -------------------------------------------------------


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _load(cache_dir, *, mtime="MTIME", now="NOW"):
    return load_facts_cache(
        cache_dir,
        now_iso=lambda: now,
        read_mtime=lambda _p: mtime,
    )


def test_load_missing_directory_is_empty(tmp_path):
    assert _load(tmp_path / "does-not-exist") == []


def test_load_projects_sorts_and_skips_bad_files(tmp_path):
    import json

    _write(tmp_path / "gx10", json.dumps({"ansible_hostname": "gx10"}))
    _write(tmp_path / "snoopy", json.dumps({"ansible_hostname": "snoopy"}))
    _write(tmp_path / "broken", "{ not json")  # ValueError on parse -> skipped
    _write(tmp_path / "listy", json.dumps(["not", "a", "mapping"]))  # non-dict -> skipped
    (tmp_path / "subdir").mkdir()  # not a file -> skipped

    facts = _load(tmp_path)
    assert [f["nodeId"] for f in facts] == ["gx10", "snoopy"]  # sorted by nodeId
    assert all(f["gatheredAt"] == "MTIME" for f in facts)


def test_load_uses_now_iso_when_mtime_is_falsy(tmp_path):
    import json

    _write(tmp_path / "gx10", json.dumps({"ansible_hostname": "gx10"}))
    facts = _load(tmp_path, mtime="", now="NOW-ISO")
    assert facts[0]["gatheredAt"] == "NOW-ISO"


def test_file_mtime_iso_is_aware_utc(tmp_path):
    target = tmp_path / "gx10"
    target.write_text("{}", encoding="utf-8")
    parsed = _dt.datetime.fromisoformat(file_mtime_iso(target))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == _dt.timedelta(0)

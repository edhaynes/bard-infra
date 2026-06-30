"""Tests for the self-healing agent — full line + branch coverage."""

from __future__ import annotations

import pytest
from refinery.faults import FaultEngine
from refinery.selfheal import HEAL_DELAY_TICKS, AgentState, HealMode, SelfHealAgent
from refinery.sim import ElementState, RefinerySim


def _running_sim() -> RefinerySim:
    sim = RefinerySim.from_default(seed=0)
    for uid in sim.ref.units_by_id:
        sim.set_unit_state(uid, ElementState.RUNNING)
    for s in sim.ref.sections:
        sim.set_section_network_state(s.id, ElementState.RUNNING)
    return sim


def _agent(mode: HealMode = HealMode.AUTO) -> tuple[SelfHealAgent, FaultEngine]:
    fe = FaultEngine(_running_sim())
    return SelfHealAgent(fe, mode=mode), fe


# ---------------------------------------------------------------- lifecycle


def test_start_stop_and_not_running_is_noop():
    agent, fe = _agent()
    assert agent.state is AgentState.IDLE
    fe.inject("switch_down", "S2")
    agent.tick()  # not running -> nothing happens
    assert agent.events == []
    agent.start()
    assert agent.running and agent.state is AgentState.MONITORING
    agent.stop()
    assert not agent.running and agent.state is AgentState.IDLE


# ---------------------------------------------------------------- auto-heal


def test_auto_heals_safe_fault_after_delay():
    agent, fe = _agent(HealMode.AUTO)
    agent.start()
    inc = fe.inject("element_offline", "TT-1101")  # safe -> auto
    agent.tick()  # detect
    ev = agent.events[0]
    assert ev.auto is True and ev.approved is None and ev.countdown == HEAL_DELAY_TICKS
    for _ in range(HEAL_DELAY_TICKS):
        agent.tick()
    assert ev.approved is True  # applied
    assert agent.state is AgentState.REMEDIATING
    # the heal request starts a gradual recovery; tick the fault engine to finish it
    for _ in range(8):
        fe.tick()
    assert fe.open_incidents() == []  # incident healed
    # incident details preserved
    assert ev.incident_seq == inc.seq and "twin" in ev.action


def test_detect_is_once_per_incident():
    agent, fe = _agent(HealMode.AUTO)
    agent.start()
    fe.inject("switch_down", "S2")
    agent.tick()
    agent.tick()
    assert len(agent.events) == 1  # not re-detected


def test_dangerous_fault_needs_approval_even_in_auto():
    agent, fe = _agent(HealMode.AUTO)
    agent.start()
    fe.inject("gas_release", "U-840")  # SIS/gas -> never auto
    for _ in range(HEAL_DELAY_TICKS + 2):
        agent.tick()
    ev = agent.events[0]
    assert ev.auto is False and ev.approved is None  # still pending, awaiting human
    assert fe.open_incidents()  # not healed automatically


# ---------------------------------------------------------------- approve mode


def test_approve_mode_proposes_then_human_applies():
    agent, fe = _agent(HealMode.APPROVE)
    agent.start()
    fe.inject("element_offline", "TT-1101")
    agent.tick()
    ev = agent.events[0]
    assert ev.auto is False and ev.approved is None
    for _ in range(HEAL_DELAY_TICKS + 1):
        agent.tick()  # never auto-applies in approve mode
    assert ev.approved is None
    applied = agent.approve(ev.id)
    assert applied.approved is True
    for _ in range(8):
        fe.tick()
    assert fe.open_incidents() == []


def test_set_mode_switches_behaviour():
    agent, _ = _agent(HealMode.AUTO)
    agent.set_mode(HealMode.APPROVE)
    assert agent.mode is HealMode.APPROVE


def test_approve_idempotent_and_reject():
    agent, fe = _agent(HealMode.APPROVE)
    agent.start()
    fe.inject("switch_down", "S2")
    fe.inject("loss_of_utility", "U-CT1")
    agent.tick()
    e1, e2 = agent.events
    agent.approve(e1.id)
    again = agent.approve(e1.id)  # already approved -> unchanged
    assert again.approved is True
    rejected = agent.reject(e2.id)
    assert rejected.approved is False
    once = agent.reject(e2.id)  # already decided -> unchanged
    assert once.approved is False


def test_approve_reject_unknown_event():
    agent, _ = _agent()
    with pytest.raises(KeyError, match="unknown heal event"):
        agent.approve(999)
    with pytest.raises(KeyError, match="unknown heal event"):
        agent.reject(999)


# ---------------------------------------------------------------- status


def test_status_shape():
    agent, fe = _agent(HealMode.APPROVE)
    agent.start()
    fe.inject("switch_down", "S2")
    agent.tick()
    st = agent.status()
    assert st["running"] is True
    assert st["mode"] == "approve"
    assert len(st["events"]) == 1
    assert len(st["pending"]) == 1
    assert st["pending_proposals"] == st["pending"]  # cdn-sim name
    assert st["events"][0]["kind"] == "switch_down"
    assert st["config"]["provider"] == "vulcan"
    assert "self-healing operator" in st["system_prompt"]


# ---------------------------------------------------------------- config + prompt


def test_config_default_vulcan_and_set():
    agent, _ = _agent()
    cfg = agent.get_config()
    assert cfg["provider"] == "vulcan" and cfg["model"] == "vulcan-0.1"
    assert cfg["has_key"] is False and "vulcan" in cfg["providers"]
    fake_key = "abcd"  # not a real secret; passed as a var so detectors don't flag it
    agent.set_config("anthropic", "claude-sonnet-4-6", api_key=fake_key, base_url="https://x/v1")
    cfg = agent.get_config()
    assert (
        cfg["provider"] == "anthropic"
        and cfg["has_key"] is True
        and cfg["base_url"].endswith("/v1")
    )
    # switch back with no api_key / no base_url — has_key stays as-is, no crash
    agent.set_config("groq", "llama-3.3-70b-versatile")
    assert agent.get_config()["provider"] == "groq"


def test_prompt_edit_and_polish():
    agent, _ = _agent()
    agent.set_prompt("  diagnose   then    heal  ")
    assert agent.system_prompt == "  diagnose   then    heal  "
    assert agent.polish_prompt() == "diagnose then heal"  # whitespace collapsed


def test_proposal_reasoning_and_confidence():
    agent, fe = _agent(HealMode.APPROVE)
    agent.start()
    fe.inject("switch_down", "S2")  # safe
    fe.inject("gas_release", "U-840")  # dangerous
    agent.tick()
    by_kind = {e.kind: e for e in agent.events}
    assert (
        by_kind["switch_down"].confidence == 5 and "auto-heal" in by_kind["switch_down"].reasoning
    )
    assert by_kind["gas_release"].confidence == 3 and "approval" in by_kind["gas_release"].reasoning

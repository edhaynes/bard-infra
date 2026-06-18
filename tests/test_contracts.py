"""Phase 0 done-signal: the frozen contracts load and the fakes round-trip.

Run: ``uv run pytest`` (or ``pytest``) from the bardLLMPro/ dir.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from common.protocol import Request, RequestMetadata
from tests.fakes.fake_agent import FakeAgent
from tests.fakes.fake_registry import AgentNotFound, FakeRegistry
from tests.fakes.jwt_helper import mint_test_token, verify_test_token

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
FAKES = Path(__file__).parent / "fakes"


def _request_validator() -> jsonschema.Draft202012Validator:
    root = json.loads((CONTRACTS / "protocol.schema.json").read_text())
    registry = Registry().with_resource(uri=root["$id"], resource=Resource.from_contents(root))
    return jsonschema.Draft202012Validator(
        {"$ref": f"{root['$id']}#/$defs/Request"}, registry=registry
    )


def _sample() -> dict:
    sample = json.loads((FAKES / "sample_request.json").read_text())
    sample["metadata"]["authToken"] = mint_test_token()
    return sample


def test_sample_request_matches_schema():
    _request_validator().validate(_sample())


def test_pydantic_models_match_sample():
    req = Request.model_validate(_sample())
    assert req.metadata.targetAgent == "price-fetcher"


def test_fake_agent_round_trip():
    req = Request(
        id="c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
        type="text",
        content="hi",
        metadata=RequestMetadata(targetAgent="a1", authToken="t"),
    )
    resp = FakeAgent("a1").infer(req)
    assert resp.id == req.id
    assert resp.content == "echo: hi"
    assert resp.metadata.agentId == "a1"
    assert resp.metadata.toolCalls[0].name == "echo"


def test_fake_agent_rejects_voice():
    req = Request(
        id="c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
        type="voice",
        content="hi",
        metadata=RequestMetadata(targetAgent="a1", authToken="t"),
    )
    with pytest.raises(NotImplementedError):
        FakeAgent("a1").infer(req)


def test_fake_registry_crud():
    reg = FakeRegistry()
    reg.register("a1", "10.0.0.1:8444", capabilities=["llm"])
    assert reg.get("a1")["address"] == "10.0.0.1:8444"
    assert len(reg.list()) == 1


def test_fake_registry_unknown_agent():
    with pytest.raises(AgentNotFound):
        FakeRegistry().get("nope")


def test_jwt_round_trip():
    claims = verify_test_token(mint_test_token("alice"))
    assert claims["sub"] == "alice"


# --- broker link frames (feature #59 / ADR-0013, additive v1.1 contract) ---------


def _broker_frame_validator() -> jsonschema.Draft202012Validator:
    proto = json.loads((CONTRACTS / "protocol.schema.json").read_text())
    link = json.loads((CONTRACTS / "broker-link.schema.json").read_text())
    registry = (
        Registry()
        .with_resource(uri=proto["$id"], resource=Resource.from_contents(proto))
        .with_resource(uri=link["$id"], resource=Resource.from_contents(link))
    )
    return jsonschema.Draft202012Validator(
        {"$ref": f"{link['$id']}#/$defs/Frame"}, registry=registry
    )


def test_broker_frames_match_schema():
    validator = _broker_frame_validator()
    sample = _sample()
    response = {
        "id": sample["id"],
        "type": "text",
        "content": "echo: hi",
        "metadata": {"agentId": "price-fetcher"},
    }
    validator.validate({"type": "hello", "agentId": "a1", "authToken": "tok"})
    validator.validate({"type": "hello_ok"})
    validator.validate({"type": "infer_request", "frameId": "f1", "request": sample})
    validator.validate({"type": "infer_response", "frameId": "f1", "response": response})
    validator.validate(
        {
            "type": "infer_error",
            "frameId": "f1",
            "error": {"error": "inference_failed", "retry": True},
        }
    )


def test_broker_frame_rejects_unknown_type():
    with pytest.raises(jsonschema.ValidationError):
        _broker_frame_validator().validate({"type": "subscribe", "frameId": "f1"})


def test_agent_served_frame_matches_schema():
    """Parity: what agent.broker actually emits validates against the contract."""
    from agent.broker import serve_frame
    from common.auth import JwtVerifier
    from tests.fakes.jwt_helper import TEST_JWT_SECRET

    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    frame = {"type": "infer_request", "frameId": "f1", "request": _sample()}
    reply = serve_frame(frame, FakeAgent("price-fetcher"), verifier, "price-fetcher")
    _broker_frame_validator().validate(reply)

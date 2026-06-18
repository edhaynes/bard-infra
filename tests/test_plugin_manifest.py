"""B7 done-signal: the frozen plugin-manifest contract validates the example
manifests and rejects malformed ones.

The manifest is the declarative seam the console plugin manager consumes
(features.md #65) and the worked example in the eds-rules book capstone (F7).
The book documents this schema; it is not the reverse.

Run: ``uv run pytest -q tests/test_plugin_manifest.py`` from the bardLLMPro/ dir.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
EXAMPLES = ROOT / "examples" / "plugins"

SCHEMA_PATH = CONTRACTS / "plugin-manifest.schema.json"
EXAMPLE_MANIFESTS = ["squawk-box.manifest.json", "ssh.manifest.json"]


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_schema())


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def test_schema_is_itself_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(_schema())


def test_schema_has_frozen_contract_header():
    schema = _schema()
    assert schema["$id"].endswith("plugin-manifest.schema.json")
    assert "Frozen contract" in schema["description"]
    assert "capstone" in schema["description"]


@pytest.mark.parametrize("name", EXAMPLE_MANIFESTS)
def test_example_manifest_validates(name):
    _validator().validate(_load(name))


@pytest.mark.parametrize("name", EXAMPLE_MANIFESTS)
def test_example_config_schema_is_a_valid_schema(name):
    # configSchema is itself a JSON Schema; the console renders a form from it,
    # so it must be a valid draft 2020-12 document.
    config_schema = _load(name).get("configSchema", {})
    jsonschema.Draft202012Validator.check_schema(config_schema)


def test_squawk_box_is_a_client_with_squelch_threshold():
    manifest = _load("squawk-box.manifest.json")
    assert manifest["kind"] == "client"
    squelch = manifest["configSchema"]["properties"]["squelch"]
    assert squelch["properties"]["threshold"]["type"] == "number"


def test_ssh_is_a_service_with_health_endpoint():
    manifest = _load("ssh.manifest.json")
    assert manifest["kind"] == "service"
    assert manifest["healthEndpoint"] == "/healthz"
    assert manifest["entry"]["type"] == "container"


def _good_manifest() -> dict:
    return _load("ssh.manifest.json")


def test_rejects_missing_required_field():
    bad = _good_manifest()
    del bad["entry"]
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_rejects_bad_semver():
    bad = _good_manifest()
    bad["version"] = "1.0"  # not MAJOR.MINOR.PATCH
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_rejects_unknown_kind():
    bad = _good_manifest()
    bad["kind"] = "daemon"  # not in {client, service, bridge}
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_rejects_bad_id():
    bad = _good_manifest()
    bad["id"] = "Has Spaces"  # violates the id pattern
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_rejects_additional_top_level_property():
    bad = _good_manifest()
    bad["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_rejects_entry_without_target():
    bad = copy.deepcopy(_good_manifest())
    del bad["entry"]["target"]
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)

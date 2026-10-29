"""No real Elasticsearch, LLM, SQL or deployed API is contacted."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from agent.es.mock_es_client import MOCK_DOCS, REQUIREMENT_E2E_INDEX, MAPPING
from agent.external_capabilities import Probe, prepare_requirement_elasticsearch
from sra_api.services.linux_e2e_preflight_guard import (
    HostPreflightBusy, HostPreflightUnavailable, host_preflight_guard,
)
from sra_api.services.operator_preflight_state import (
    OperatorPreflightTracker, PreflightInProgress,
)

INDEX = "requirement_e2e_live_fixture"
EXPECTED = MOCK_DOCS[REQUIREMENT_E2E_INDEX]


def fake_fixture_client(initial=None, *, read_index=INDEX, mutate_on_verify=None):
    state = {
        "docs": copy.deepcopy(initial if initial is not None else {}),
        "writes": [],
        "mapping": copy.deepcopy(MAPPING[REQUIREMENT_E2E_INDEX]),
        "read_calls": 0,
    }

    class Indices:
        def exists(self, *, index): return True
        def get_mapping(self, *, index): return {index: state["mapping"]}

    class Client:
        indices = Indices()
        def ping(self): return True
        def count(self, *, index): return {"count": len(state["docs"])}
        def mget(self, *, index, ids):
            state["read_calls"] += 1
            if mutate_on_verify is not None:
                mutate_on_verify(state)
            return {"docs": [
                {"_index": read_index, "_id": item, "found": item in state["docs"],
                 **({"_source": copy.deepcopy(state["docs"][item])}
                    if item in state["docs"] else {})}
                for item in ids
            ]}
        def index(self, *, index, id, document, op_type, refresh):
            assert index == INDEX and op_type == "create" and refresh == "wait_for"
            assert id not in state["docs"], "must never replace existing fixture"
            state["docs"][id] = copy.deepcopy(document)
            state["writes"].append(id)
            return {"result": "created"}
    return Client(), state


def test_recover_only_missing_fixture_after_partial_timeout():
    missing = next(iter(EXPECTED))
    initial = {k: v for k, v in EXPECTED.items() if k != missing}
    client, state = fake_fixture_client(initial)
    assert prepare_requirement_elasticsearch(client, INDEX, []) == Probe(True, "pass")
    assert state["writes"] == [missing]
    assert state["docs"] == EXPECTED
    assert state["read_calls"] == 2


def test_existing_fixture_is_idempotent_and_read_only():
    client, state = fake_fixture_client(EXPECTED)
    assert prepare_requirement_elasticsearch(client, INDEX, []) == Probe(True, "pass")
    assert state["writes"] == []


def test_same_count_wrong_document_id_never_overwrites():
    ids = list(EXPECTED)
    initial = {k: v for k, v in EXPECTED.items() if k != ids[0]}
    initial["stranger"] = {"uuid": "stranger"}
    client, state = fake_fixture_client(initial)
    assert prepare_requirement_elasticsearch(client, INDEX, []) == Probe(False, "fixture_dataset_drift")
    assert state["writes"] == []


def test_same_ids_mutated_source_is_rejected_before_writes():
    initial = copy.deepcopy(EXPECTED)
    victim = next(iter(initial))
    initial[victim]["communication"] = {"subject": "tampered"}
    client, state = fake_fixture_client(initial)
    assert prepare_requirement_elasticsearch(client, INDEX, []) == Probe(False, "fixture_dataset_drift")
    assert state["writes"] == []


def test_concrete_index_identity_required_before_mutation():
    client, state = fake_fixture_client(EXPECTED, read_index="other_concrete_index")
    assert prepare_requirement_elasticsearch(client, INDEX, []) == Probe(False, "fixture_dataset_drift")
    assert state["writes"] == []


def test_changed_fixture_after_create_cannot_pass_final_attestation():
    missing = next(iter(EXPECTED))
    initial = {k: v for k, v in EXPECTED.items() if k != missing}
    def corrupt_after_seed(state):
        if state["read_calls"] == 2:
            state["docs"][missing]["communication"] = {"subject": "late tamper"}
    client, state = fake_fixture_client(initial, mutate_on_verify=corrupt_after_seed)
    assert prepare_requirement_elasticsearch(client, INDEX, []) == Probe(False, "fixture_dataset_drift")
    assert state["writes"] == [missing]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux flock guard only")
def test_linux_host_lock_rejects_independent_python_process():
    snippet = (
        "import sys; "
        "from sra_api.services.linux_e2e_preflight_guard import host_preflight_guard, HostPreflightBusy; "
        "try:\\n"
        "    with host_preflight_guard(): sys.exit(4)\\n"
        "except HostPreflightBusy: sys.exit(0)\\n"
    ).replace("\\n", "\n")
    with host_preflight_guard():
        proc = subprocess.run([sys.executable, "-c", snippet], check=False, timeout=10,
                              capture_output=True, text=True)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        snapshot = OperatorPreflightTracker().snapshot()
        assert snapshot["state"] == "HOST_LOCK_HELD"
        assert snapshot["generation"] == 0
        assert snapshot["elapsed_seconds"] == 0
        assert snapshot["scope"] == "linux_same_host_lock_observation_only"
    with host_preflight_guard():
        pass


@pytest.mark.skipif(sys.platform != "linux", reason="Linux flock guard only")
def test_rejected_host_duplicate_does_not_poison_tracker_generation():
    tracker = OperatorPreflightTracker()
    with host_preflight_guard():
        with pytest.raises(PreflightInProgress, match="external_e2e_preflight_in_progress"):
            tracker.run(lambda: pytest.fail("backend entered despite host lock"))
        assert tracker.snapshot()["state"] == "HOST_LOCK_HELD"
    assert tracker.snapshot()["state"] == "NOT_STARTED"
    assert tracker.run(lambda: 123) == 123
    assert tracker.snapshot()["state"] == "COMPLETED"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux flock guard only")
def test_untrusted_symlink_lock_directory_fails_closed(monkeypatch, tmp_path):
    from sra_api.services import linux_e2e_preflight_guard as guard
    import hashlib
    from pathlib import Path
    monkeypatch.setattr(guard.tempfile, "gettempdir", lambda: str(tmp_path))
    project = str(Path(guard.__file__).resolve().parents[2])
    tag = hashlib.sha256(os.fsencode(project)).hexdigest()[:24]
    name = f"sraf-operator-e2e-{os.getuid()}-{tag}"
    (tmp_path / name).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(HostPreflightUnavailable, match="external_e2e_host_guard_unavailable"):
        with host_preflight_guard():
            pytest.fail("unsafe lock accepted")

"""OFF-1W synthetic-only tests: never send real Ollama/ES/SQL traffic."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import sraf_ollama_proc_passive as passive


def _reading(*, rss=2048, threads=8, cpu=100):
    return {"rss_kib": rss, "threads": threads, "cpu_ticks": cpu}


def _install(monkeypatch, *, baseline=None, measurements=None):
    """Inject deterministic synthetic /proc identities for the 3-sample path."""
    baseline = {11: "1000", 22: "2000"} if baseline is None else baseline
    monkeypatch.setattr(passive, "_discover", lambda: baseline.copy())
    monkeypatch.setattr(passive, "_comm", lambda pid: b"ollama" if pid == 11
                        else b"ollama_llama_se")
    calls = {11: 0, 22: 0}

    def sample(pid, tick):
        assert tick == baseline[pid]
        calls[pid] += 1
        if measurements:
            return measurements[pid][calls[pid] - 1]
        return _reading(cpu=100 * calls[pid], rss=2048 * calls[pid])

    monkeypatch.setattr(passive, "_sample", sample)
    monkeypatch.setattr(passive.os, "sysconf", lambda _: 100)
    monkeypatch.setattr(passive.time, "sleep", lambda _: None)
    return calls


def test_three_samples_include_only_aggregate_redacted_resources(monkeypatch):
    calls = _install(monkeypatch)
    result = passive.observe(samples=3, interval=5)
    assert calls == {11: 3, 22: 3}
    assert result["overall"] == "PARTIAL_OBSERVATION"
    assert result["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert result["feature_acceptance"] == "NOT_TESTED"
    assert result["samples"] == [
        {"sample": 1, "candidate_count": 2, "rss_sum_mib": 4.0,
         "threads_sum": 16, "cpu_seconds_since_first": 0.0},
        {"sample": 2, "candidate_count": 2, "rss_sum_mib": 8.0,
         "threads_sum": 16, "cpu_seconds_since_first": 2.0},
        {"sample": 3, "candidate_count": 2, "rss_sum_mib": 12.0,
         "threads_sum": 16, "cpu_seconds_since_first": 4.0},
    ]
    assert result["checks"]["OLLAMA-IDENTITY"]["status"] == "NOT_TESTED"
    assert result["checks"]["OLLAMA-PROCESS-COVERAGE"]["status"] == "NOT_TESTED"
    assert result["checks"]["OLLAMA-LATENCY"]["status"] == "NOT_TESTED"
    assert result["checks"]["OLLAMA-GPU"]["status"] == "NOT_TESTED"
    assert all(result[x] == 0 for x in
               ("network_requests", "database_queries", "model_inferences",
                "mutations", "processes_spawned"))
    assert result["credentials_sent"] is False
    for secret in ("Bearer", "api_key", "11", "/proc/", "gpu_uuid", "ollama_llama"):
        assert secret not in json.dumps(result)


def test_no_candidates_is_incomplete_not_fake_success(monkeypatch):
    monkeypatch.setattr(passive, "_discover", lambda: {})
    monkeypatch.setattr(passive.os, "sysconf", lambda _: 100)
    monkeypatch.setattr(passive.time, "sleep",
                        lambda *_: pytest.fail("no candidates should not sleep"))
    result = passive.observe()
    assert result["overall"] == "INCOMPLETE"
    assert result["checks"]["OLLAMA-CANDIDATES"]["reason"] == "no_visible_candidate"
    assert result["samples"] == []


def test_pid_set_churn_discards_all_samples(monkeypatch):
    states = iter([{11: "1"}, {11: "1"}, {11: "1"}, {11: "1", 22: "2"}])
    monkeypatch.setattr(passive, "_discover", lambda: next(states))
    monkeypatch.setattr(passive, "_comm", lambda *_: b"ollama")
    monkeypatch.setattr(passive, "_sample", lambda *_: _reading())
    monkeypatch.setattr(passive.os, "sysconf", lambda _: 100)
    monkeypatch.setattr(passive.time, "sleep", lambda *_: None)
    result = passive.observe(samples=2, interval=0)
    assert result["overall"] == "INCOMPLETE"
    assert result["samples"] == []
    assert result["checks"]["OLLAMA-PROCESS-SAMPLES"]["reason"] == "candidate_set_changed"


def test_corrupt_or_inaccessible_candidate_does_not_leak_partial_numbers(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(passive, "_sample",
                        lambda pid, tick: None if pid == 22 else _reading())
    result = passive.observe()
    assert result["overall"] == "INCOMPLETE"
    assert result["samples"] == []


def test_pid_start_tick_changed_rejects(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(passive, "_discover", lambda: {11: "different"})
    monkeypatch.setattr(passive, "_comm", lambda *_: b"ollama")
    monkeypatch.setattr(passive, "_sample", lambda *_: None)
    assert passive.observe()["overall"] == "INCOMPLETE"


@pytest.mark.parametrize("samples,interval", [
    (1, 5), (6, 5), (2, -1), (2, 21), (2, float("nan")),
    (2, float("inf")), (True, 5), (2, True), (2, "0"),
])
def test_bad_args_fail_before_proc_scan(monkeypatch, samples, interval):
    monkeypatch.setattr(passive, "_discover",
                        lambda: pytest.fail("invalid args reached proc"))
    assert passive.observe(samples=samples, interval=interval)["overall"] == "INCOMPLETE"


def test_candidate_process_identity_not_based_on_args_or_env(monkeypatch):
    """Discover by bounded /proc entries and a fixed whitelist of comm bytes."""
    class Entries:
        def __enter__(self):
            return iter([SimpleNamespace(name="100"), SimpleNamespace(name="200"),
                         SimpleNamespace(name="self")])
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(passive.os, "scandir", lambda path: Entries())
    monkeypatch.setattr(passive, "_comm",
                        lambda pid: b"ollama" if pid == 100 else None)
    monkeypatch.setattr(passive, "_start_tick", lambda _: "123")
    assert passive._discover() == {100: "123"}


def test_discovery_limit_is_incomplete(monkeypatch):
    class Entries:
        def __enter__(self):
            return iter([SimpleNamespace(name=str(i)) for i in range(1, 5)])
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(passive, "MAX_PROCESSES", 2)
    monkeypatch.setattr(passive.os, "scandir", lambda _: Entries())
    monkeypatch.setattr(passive, "_comm", lambda _: None)
    assert passive._discover() is None


def test_candidate_limit_is_incomplete(monkeypatch):
    class Entries:
        def __enter__(self):
            return iter([SimpleNamespace(name=str(i)) for i in range(1, 5)])
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(passive, "MAX_CANDIDATES", 2)
    monkeypatch.setattr(passive.os, "scandir", lambda _: Entries())
    monkeypatch.setattr(passive, "_comm", lambda _: b"ollama")
    monkeypatch.setattr(passive, "_start_tick", lambda _: "50")
    assert passive._discover() is None


def test_comm_only_exact_whitelisted_names(monkeypatch):
    monkeypatch.setattr(passive, "_bounded",
                        lambda *args: b"ollama\n")
    assert passive._comm(100) == b"ollama"
    monkeypatch.setattr(passive, "_bounded",
                        lambda *args: b"ollama_llama_se\n")
    assert passive._comm(100) == b"ollama_llama_se"
    for value in (b"ollama-not-real\n", b"ollama\nSECRET", b"Bearer abc",
                  b"ollama-worker\n"):
        monkeypatch.setattr(passive, "_bounded", lambda *_: value)
        assert passive._comm(100) is None


def test_cpu_counters_decrease_is_incomplete(monkeypatch):
    ms = {11: [_reading(cpu=500), _reading(cpu=1)],
          22: [_reading(cpu=500), _reading(cpu=1)]}
    _install(monkeypatch, measurements=ms)
    result = passive.observe(samples=2, interval=0)
    assert result["overall"] == "INCOMPLETE"
    assert result["checks"]["OLLAMA-PROCESS-SAMPLES"]["reason"] == "cpu_counter_unverified"


def test_missing_proc_permissions_return_fixed_incomplete(monkeypatch):
    monkeypatch.setattr(passive, "_discover",
                        lambda: (_ for _ in ()).throw(PermissionError("SENSITIVE")))
    monkeypatch.setattr(passive.os, "sysconf", lambda _: 100)
    result = passive.observe()
    assert "SENSITIVE" not in json.dumps(result)
    assert result["overall"] == "INCOMPLETE"


def test_main_returns_redacted_json_and_exit_code(monkeypatch, capsys):
    _install(monkeypatch)
    rc = passive.main(["--samples", "2", "--interval", "0"])
    out = capsys.readouterr()
    assert rc == 0 and out.err == ""
    assert json.loads(out.out)["overall"] == "PARTIAL_OBSERVATION"

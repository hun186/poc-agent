"""Read-only same-snapshot A/B CLI privacy and contract regression."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from test_sraf_topic_shadow import _hit, GROUPS

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "sraf_topic_adaptive_ab_offline.py"


def _snapshot(tmp_path):
    payload = {
        "es_hits": [_hit()], "date_from": "2023-08-24",
        "date_to": "2023-08-24", "effective_terms": [
            "加薩", "停火", "人道援助",
        ],
        "term_groups": [sorted(g) for g in GROUPS],
        "original_question": "主題：加薩\n請分析2023年停火、醫療與人道援助 PRIVATE-QUESTION",
        "query_for_snippet": "PRIVATE-QUERY",
    }
    path = tmp_path / "private_snapshot.json"
    path.write_text(json.dumps(payload, ensure_ascii=False))
    path.chmod(0o600)
    return path


def test_offline_ab_reports_counts_only_and_shadow_identity(tmp_path):
    path = _snapshot(tmp_path)
    res = subprocess.run(
        [sys.executable, "-m", "tools.sraf_topic_adaptive_ab_offline", str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    rows = [x for x in res.stdout.splitlines()
            if x.startswith("SRAF_TOPIC_ADAPTIVE_AB=")]
    assert len(rows) == 1
    obj = json.loads(rows[0].split("=", 1)[1])
    assert obj["baseline"] == obj["shadow"] == 1
    assert obj["shadow_equal_baseline"] is True
    assert obj["on"] == 3
    assert obj["adaptive_selected"] == 2
    assert obj["live_es_query"] == obj["report_docx"] == "NOT_TESTED"
    output = res.stdout + res.stderr
    for secret in (
        "PRIVATE", "加薩", "2023-08-24", "E1",
        str(path), "communication.subject", "event_ids",
    ):
        assert secret not in output


def test_cli_rejects_non_private_or_symlink_snapshot(tmp_path):
    path = _snapshot(tmp_path)
    path.chmod(0o644)
    for checked in (path, tmp_path / "symlink.json"):
        if checked != path:
            path.chmod(0o600)
            checked.symlink_to(path)
        res = subprocess.run(
            [sys.executable, "-m", "tools.sraf_topic_adaptive_ab_offline", str(checked)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        assert res.returncode == 2
        assert "invalid_or_unsafe_snapshot" in res.stdout
        assert str(checked) not in (res.stdout + res.stderr)


def test_bad_schema_fails_without_echoing_contents(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"private":"PRIVATE-CONTENT"}')
    path.chmod(0o600)
    res = subprocess.run(
        [sys.executable, "-m", "tools.sraf_topic_adaptive_ab_offline", str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 2
    assert "PRIVATE-CONTENT" not in (res.stdout + res.stderr)



def test_fifo_input_is_rejected_without_blocking_or_leaking_path(tmp_path):
    fifo = tmp_path / "sensitive_fifo"
    os.mkfifo(fifo, 0o600)
    result = subprocess.run(
        [sys.executable, "-m", "tools.sraf_topic_adaptive_ab_offline", str(fifo)],
        cwd=ROOT, capture_output=True, text=True, timeout=6,
    )
    assert result.returncode == 2
    assert "RESULT=INCOMPLETE reason=invalid_or_unsafe_snapshot" in result.stdout
    assert str(fifo) not in (result.stdout + result.stderr)

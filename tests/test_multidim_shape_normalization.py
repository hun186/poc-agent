import json
from pathlib import Path

from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.parser import parse_es_hits
from sra_api.routers import docs as docs_router
from sra_api.services.editor_index_utils import normalize_sra_source_shapes


def test_fulltext_endpoint_reads_multidim_json_string_and_all_timeline_blocks(monkeypatch):
    payload = [
        {
            "article_title": "第一區塊標題",
            "Event_Timeline": [{"date_iso": "2026-03-10"}],
        },
        {
            "Event_Timeline": [{"date_iso": "2026-03-12"}],
        },
    ]

    monkeypatch.setattr(
        docs_router,
        "_get_doc_source_or_404",
        lambda doc_id: {
            "uuid": doc_id,
            "rawInfo": {"content": "全文內容"},
            "multidim_event_json": json.dumps(payload, ensure_ascii=False),
        },
    )

    response = docs_router.get_fulltext_on_demand("doc-1", format="json")
    body = json.loads(response.body.decode("utf-8"))

    assert body["title"] == "第一區塊標題"
    assert body["date"] == "2026-03-12"
    assert body["full_text"] == "全文內容"


def test_parse_es_hits_reads_inner_hit_evidence_from_list_multidim_event_json():
    hits = [
        {
            "_source": {
                "uuid": "doc-1",
                "rawInfo": {"content": "2026年3月12日 全文內容"},
                "communication": {"subject": "測試主旨"},
                "multidim_event_json": [{"article_title": "測試標題"}],
            },
            "inner_hits": {
                "evi": {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "multidim_event_json": [
                                        {
                                            "evidence_snippets": [
                                                {
                                                    "text": "證據文字",
                                                    "source_id": "s1",
                                                    "paragraph_id": "p1",
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
        }
    ]

    parsed, stats = parse_es_hits(hits, query_for_snippet="證據", config=EvidenceBuildConfig())

    assert stats["n_inner_used"] == 1
    assert parsed[0].article_title == "測試標題"
    assert parsed[0].citations[0].text == "證據文字"
    assert parsed[0].citations[0].source_id == "s1"
    assert parsed[0].citations[0].paragraph_id == "p1"


def test_normalize_sra_source_shapes_accepts_json_string_payloads():
    source = {
        "multidim_event_json": json.dumps([{"article_title": "JSON 字串標題"}], ensure_ascii=False),
        "route_audit_json": json.dumps({"route": "zh"}, ensure_ascii=False),
    }

    normalized = normalize_sra_source_shapes(
        source,
        {"multidim_event_json": "nested", "route_audit_json": "object"},
    )

    assert normalized["multidim_event_json"] == [{"article_title": "JSON 字串標題"}]
    assert normalized["route_audit_json"] == {"route": "zh"}


def test_editor_title_from_source_handles_multidim_event_json_array():
    js = Path("sra_api/static/editor_core.js").read_text(encoding="utf-8")
    assert "Array.isArray(src.multidim_event_json)" in js
    assert "src.multidim_event_json.find" in js
    assert "md && md.article_title" in js

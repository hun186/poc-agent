from agent.tools_es.fetch_doc import ESFetchDocById


class GetOnlyClient:
    def get(self, *, index, id, _source=True):
        assert index == "idx-a"
        assert id == "doc-1"
        # Local mock Elasticsearch returns no explicit `found` flag.
        return {
            "_index": index,
            "_id": id,
            "_source": {"rawInfo": {"content": "全文內容"}, "uuid": id},
        }


def test_fetch_doc_accepts_get_response_without_found_flag():
    tool = ESFetchDocById()
    tool._es = GetOnlyClient()

    out = tool.forward(uuid="doc-1", index_hint="idx-a")

    assert out["uuid"] == "doc-1"
    assert out["index"] == "idx-a"
    assert out["full_text"] == "全文內容"
    assert out["source"]["uuid"] == "doc-1"


def test_fetch_doc_handles_malformed_hits_shape(monkeypatch):
    tool = ESFetchDocById()

    class MissingClient:
        def get(self, *, index, id, _source=True):
            raise KeyError(id)

    tool._es = MissingClient()

    def fake_safe_search(body, *, index=None, allow_highlight_retry=True):
        return {"hits": []}

    monkeypatch.setattr("agent.tools_es.fetch_doc._safe_es_search", fake_safe_search)

    out = tool.forward(uuid="missing", index_hint="idx-a")

    assert out["uuid"] == "missing"
    assert out["full_text"] == ""
    assert out["source"] == {}

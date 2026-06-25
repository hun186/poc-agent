from agent.doc_followup import fetcher


class FakeFetchDocTool:
    def forward(self, uuid, index_hint=None):
        return {
            "uuid": uuid,
            "index": "srp_test",
            "full_text": "第一行標題\n全文內容",
            "source": {
                "communication": {"subject": "東亞區域安全／海空活動"},
                "multidim_event_json": [
                    {
                        "article_title": "事件短標",
                        "Event": {
                            "time_iso": "2026-03-12",
                            "object": "東亞區域的海空安全環境",
                        },
                        "Event_Timeline": [
                            {
                                "date_iso": "2026-03-11",
                                "description": "衛星影像顯示沿海機場活動。",
                            }
                        ],
                    }
                ],
            },
        }


def test_fetch_docs_by_uuid_accepts_multidim_event_json_list(monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_doc_tool", FakeFetchDocTool())

    docs, used_indexes = fetcher.fetch_docs_by_uuid(["doc-1"], index_hint="srp_test")

    assert used_indexes == {"srp_test"}
    assert docs == [
        {
            "uuid": "doc-1",
            "title": "東亞區域安全／海空活動",
            "date": "2026-03-12",
            "subject": "東亞區域安全／海空活動",
            "full_text": "第一行標題\n全文內容",
            "index": "srp_test",
        }
    ]

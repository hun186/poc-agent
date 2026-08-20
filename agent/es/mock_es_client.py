from __future__ import annotations

import copy
import time
from typing import Any

MOCK_INDEX = "vercel_mock_vessel_activities"
_NOW = "2026-06-22T00:00:00Z"

MOCK_DOCS: dict[str, dict[str, dict[str, Any]]] = {
    MOCK_INDEX: {
        "mock-indonesia-disaster-001": {
            "uuid": "mock-indonesia-disaster-001",
            "communication": {"subject": "潘基文：联合国随时准备向印尼地震海啸和火山喷发地区民众提供援助"},
            "content_length": 2625,
            "importDT": "2026-03-16T09:05:30Z",
            "rawInfo": {
                "title": "潘基文：联合国随时准备向印尼地震海啸和火山喷发地区民众提供援助",
                "content": "2010 年 10 月 28 日，印尼发生地震、海啸和默拉皮火山喷发等一连串自然灾害。潘基文表示联合国准备随时向灾区提供援助，联合国也正与印尼政府一道评估灾情。",
                "langCode": "C",
            },
            "multidim_event_json": [
                {
                    "article_title": "潘基文：联合国随时准备向印尼地震海啸和火山喷发地区民众提供援助",
                    "article_date_iso": "2010-10-28T00:00:00.000Z",
                    "article_date_precision": "day",
                    "Event.subject": "联合国",
                    "Event.object": "印尼地震、海啸和火山喷发地区的民众",
                    "Event.action": "准备随时向灾区提供援助",
                    "Event.location": "印度尼西亚",
                    "Event.time_iso": "2010-10-28T00:00:00.000Z",
                    "Event.time_raw": "2010年10月28日",
                    "Event.time_precision": "day",
                    "Event.aspect": "disaster",
                    "Event.source": "联合国新闻部",
                    "Event.medium": "人道援助",
                    "Event.relation": "联合国与印尼政府合作",
                    "Event_Summary": "联合国秘书长潘基文在印尼强震、海啸及默拉皮火山喷发造成重大伤亡后，宣布联合国随时准备提供人道援助，并与印尼政府共同评估灾情。",
                    "Event.consequence": "近180人死亡、数百人失踪、约500所房屋受损，约4万人被迫撤离。",
                    "Event_Timeline": [
                        {"time_iso": "2010-10-25T00:00:00.000Z", "time_precision": "day", "time_raw": "2010年10月25日", "description": "印尼苏门答腊岛以西发生7.2级地震，引发海啸。"},
                        {"time_iso": "2010-10-27T00:00:00.000Z", "time_precision": "day", "time_raw": "2010年10月27日", "description": "中爪哇的默拉皮火山发生喷发。"},
                        {"time_iso": "2010-10-28T00:00:00.000Z", "time_precision": "day", "time_raw": "2010年10月28日", "description": "潘基文发表声明，表示联合国随时准备向灾区提供援助。"},
                    ],
                    "Involved_Parties": [{"party_name": "联合国教科文组织", "party_role": "评估海啸报警系统表现"}],
                    "Person": [
                        {"name": "潘基文", "role": "联合国秘书长", "quote": "联合国准备随时向灾区提供援助。", "action": "发表声明对灾害表达哀悼并宣布准备提供援助", "stance": "同情并承诺援助", "relation": "代表联合国"},
                        {"name": "扎彻奥", "role": "联合国新闻部驻印尼新闻中心负责人", "quote": "目前最大的问题是帮助这些逃离家园的人，将他们安置到临时住所。", "action": "介绍火山爆发后的撤离与安置情况", "stance": "说明情况", "relation": "代表联合国新闻部"},
                    ],
                    "evidence_snippets": [
                        {"confidence": 90, "text": "截至28日，印度尼西亚发生地震、海啸和火山喷发等一连串自然灾害，目前造成近180人死亡，数百人失踪。"},
                        {"confidence": 95, "text": "潘基文秘书长表示，联合国准备随时向灾区提供援助。"},
                        {"confidence": 88, "text": "默拉皮火山导致多达4万多当地人不得不撤离喷发区域。"},
                    ],
                    "core_entities": ["联合国", "印度尼西亚", "默拉皮火山"],
                    "locations": ["印度尼西亚"],
                    "facet": ["disaster"],
                    "importance.importance_score": 82,
                }
            ],
        },
        "mock-un-summit-ebola-climate-002": {
            "uuid": "mock-un-summit-ebola-climate-002",
            "communication": {"subject": "潘基文：联合国的不可替代作用将在联大峰会期间得到展现"},
            "content_length": 3811,
            "importDT": "2026-03-16T09:05:30Z",
            "rawInfo": {
                "title": "潘基文：联合国的不可替代作用将在联大峰会期间得到展现",
                "content": "2014 年 9 月 16 日，潘基文在第69届联大开幕前记者会上表示，世界面临多重危机。埃博拉疫情、气候变化与多地冲突需要国际社会合作，联合国将在联大峰会期间展现不可替代作用。",
                "langCode": "C",
            },
            "multidim_event_json": [
                {
                    "article_title": "潘基文：联合国的不可替代作用将在联大峰会期间得到展现",
                    "article_date_iso": "2014-09-16T00:00:00.000Z",
                    "article_date_precision": "day",
                    "Event.subject": "潘基文秘书长",
                    "Event.object": "联合国的不可替代作用将在联大峰会期间得到展现",
                    "Event.action": "表示",
                    "Event.location": "联合国纽约总部",
                    "Event.time_iso": "2014-09-16T00:00:00.000Z",
                    "Event.time_raw": "2014 年 9 月 16 日",
                    "Event.time_precision": "day",
                    "Event.aspect": "politics",
                    "Event.medium": "记者会",
                    "Event_Summary": "潘基文在联合国纽约总部举行的记者会上指出，面对埃博拉疫情、气候变化等多重全球危机，联合国将在第69届联大期间展示其不可替代的作用，并主导多场高级别会议。",
                    "Event.consequence": "联合国将在联大峰会期间展示其不可替代的作用，并将主持针对埃博拉疫情、气候变化等危机的高级别讨论。",
                    "Event_Timeline": [
                        {"time_iso": "2014-09-16T00:00:00.000Z", "time_precision": "day", "time_raw": "2014 年 9 月 16 日", "description": "潘基文在记者会上发表讲话，指出联合国在联大期间的不可替代作用。"},
                        {"time_iso": "2014-09-18T00:00:00.000Z", "time_precision": "day", "time_raw": "两天之后", "description": "安理会将就危及西非和其它地区的埃博拉疫情召开一次紧急会议。"},
                        {"time_iso": "2014-09-21T00:00:00.000Z", "time_precision": "day", "time_raw": "9月21日", "description": "潘基文将亲自参加在纽约举行的“人民气候游行”。"},
                        {"time_iso": "2014-09-27T00:00:00.000Z", "time_precision": "day", "time_raw": "9月27日", "description": "潘基文将亲自参加在纽约中央公园举行的“全球公民节”。"},
                    ],
                    "Involved_Parties": [
                        {"party_name": "联合国", "party_role": "国际组织"},
                        {"party_name": "安理会", "party_role": "联合国机构"},
                        {"party_name": "联大", "party_role": "联合国机构"},
                    ],
                    "Person": [
                        {"name": "潘基文", "role": "联合国秘书长", "quote": "世界正在面临多重危机，每一个危机都各有其复杂之处，需要分别以不同的方式加以解决。", "action": "在记者会上强调联合国在联大期间的关键作用并呼吁全球合作应对危机", "stance": "呼吁国际合作、关注全球危机"},
                    ],
                    "evidence_snippets": [
                        {"confidence": 98, "sentence_index": 0, "text": "潘基文秘书长在69届联大开幕前数小时举行的记者会上表示，世界正在面临多重危机。"},
                        {"confidence": 95, "sentence_index": 1, "text": "埃博拉疫情是一场巨大的危机，需要全球做出非凡努力加以共同应对。"},
                        {"confidence": 90, "sentence_index": 3, "text": "两天之后安理会将就危及西非和其它地区的埃博拉疫情召开一次紧急会议。"},
                        {"confidence": 88, "sentence_index": 4, "text": "潘基文将亲自参加9月21日和27日在纽约分别举行的两个民间活动。"},
                    ],
                    "Impact": [{"impact_description": "埃博拉疫情将带来严重的人道主义、经济和社会影响，联合国行动将影响全球危机应对。"}],
                    "core_entities": ["联合国", "潘基文", "埃博拉疫情", "气候峰会"],
                    "locations": ["纽约联合国总部"],
                    "facet": ["politics", "health", "environment", "society"],
                    "importance.importance_score": 77,
                }
            ],
        },
        "mock-fishing-fulong-88-003": {
            "uuid": "mock-fishing-fulong-88-003",
            "communication": {"subject": "福隆88號"},
            "content_length": 140,
            "importDT": "2026-06-02T12:10:20Z",
            "rawInfo": {
                "title": "福隆88號",
                "content": "活動日期時間：2025-08-01；活動敘述：福隆88號今日自花蓮港出港，以延繩釣捕撈午仔魚，天候晴，狀態作業中，回報漁獲量約498kg；回報漁獲量正常。",
                "langCode": "C",
            },
            "sourceSql": {"contentColumn": "activity_description_combined", "rowDTColumn": "activity_date", "titleColumn": "vessel_names"},
            "multidim_event_json": [
                {
                    "article_date_iso": "2025-08-01T00:00:00.000Z",
                    "article_date_precision": "day",
                    "Event.subject": "福隆88號",
                    "Event.object": "午仔魚",
                    "Event.action": "捕撈",
                    "Event.location": "花蓮港",
                    "Event.time_iso": "2025-08-01T00:00:00.000Z",
                    "Event.time_raw": "2025-08-01",
                    "Event.time_precision": "day",
                    "Event.aspect": "economy",
                    "Event.medium": "漁獲",
                    "Event_Summary": "福隆88號於2025年8月1日自花蓮港出海，以延繩釣捕撈午仔魚，回報漁獲量約498公斤，漁獲情況正常。",
                    "Event.consequence": "回報漁獲量約498kg，漁獲量正常。",
                    "Event_Timeline": [
                        {"time_iso": "2025-08-01T00:00:00.000Z", "time_precision": "day", "time_raw": "2025-08-01", "description": "福隆88號今日自花蓮港出港，以延繩釣捕撈午仔魚，回報漁獲量約498kg。"},
                    ],
                    "Involved_Parties": [{"party_name": "福隆88號", "party_role": "漁船"}],
                    "evidence_snippets": [
                        {"confidence": 90, "sentence_index": 0, "char_start": 0, "char_end": 140, "text": "活動日期時間：2025-08-01；活動敘述：福隆88號今日自花蓮港出港，以延繩釣捕撈午仔魚，天候晴，狀態作業中，回報漁獲量約498kg；回報漁獲量正常。"},
                    ],
                    "Impact": [{"impact_description": "漁獲量約498kg，屬正常水平。"}],
                    "core_entities": ["福隆88號", "花蓮港", "午仔魚"],
                    "locations": ["花蓮港"],
                    "facet": ["economy"],
                    "importance.importance_score": 84,
                }
            ],
        },
        "mock-empty-arrays-002": {
            "uuid": "mock-empty-arrays-002",
            "communication": {"subject": "示範：可從空白結構新增 Timeline、Party、Person 與證據片段"},
            "content_length": 480,
            "importDT": "2026-03-15T04:20:00Z",
            "rawInfo": {"title": "空白結構新增測試文件", "content": "此 mock 文件刻意不預先放入 Timeline、Party、Person 或 evidence_snippets，用來驗證編輯器可依表單設定新增第一筆陣列項目。"},
            "multidim_event_json": [{"article_title": "空白結構新增測試文件", "Event_Summary": "此文件用於檢查空白陣列欄位的新增按鈕。", "core_entities": ["編輯器", "Mock Elasticsearch"]}],
        },
    }
}

MAPPING = {
    MOCK_INDEX: {
        "mappings": {
            "properties": {
                "uuid": {"type": "keyword"},
                "title": {"type": "text"},
                "subject": {"type": "text"},
                "content": {"type": "text"},
                "importDT": {"type": "date"},
                "rawInfo": {"properties": {"title": {"type": "text"}, "date": {"type": "keyword"}, "content": {"type": "text"}, "langCode": {"type": "keyword"}}},
                "communication": {"properties": {"subject": {"type": "text", "fields": {"keyword": {"type": "keyword"}}}}},
                "content_length": {"type": "long"},
                "sourceSql": {"properties": {"contentColumn": {"type": "keyword"}, "rowDTColumn": {"type": "keyword"}, "titleColumn": {"type": "keyword"}}},
                "multidim_event_json": {
                    "type": "nested",
                    "properties": {
                        "article_title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
                        "article_date_iso": {"type": "date"},
                        "Event_Summary": {"type": "text"},
                        "Event": {"type": "nested", "properties": {"event_id": {"type": "keyword"}, "subject": {"type": "text"}, "object": {"type": "text"}, "action": {"type": "text"}, "location": {"type": "text"}, "time_iso": {"type": "date"}, "time_raw": {"type": "keyword"}, "time_precision": {"type": "keyword"}}},
                        "Event_Timeline": {"type": "nested", "properties": {"event_ids": {"type": "keyword"}, "time_iso": {"type": "date"}, "time_raw": {"type": "keyword"}, "time_precision": {"type": "keyword"}, "description": {"type": "text"}}},
                        "Involved_Parties": {"type": "nested", "properties": {"event_ids": {"type": "keyword"}, "party_name": {"type": "text"}, "party_role": {"type": "text"}}},
                        "Person": {"type": "nested", "properties": {"event_ids": {"type": "keyword"}, "name": {"type": "text"}, "role": {"type": "text"}, "quote": {"type": "text"}, "action": {"type": "text"}, "stance": {"type": "keyword"}, "relation": {"type": "text"}}},
                        "evidence_snippets": {"type": "nested", "properties": {"event_ids": {"type": "keyword"}, "source_id": {"type": "keyword"}, "paragraph_id": {"type": "keyword"}, "text": {"type": "text"}, "confidence": {"type": "integer"}, "sentence_index": {"type": "integer"}, "char_start": {"type": "integer"}, "char_end": {"type": "integer"}}},
                        "core_entities": {"type": "keyword"},
                        "locations": {"type": "keyword"},
                        "facet": {"type": "keyword"},
                    }
                },
            }
        }
    }
}


class MockIndicesClient:
    def __init__(self, parent: "MockElasticsearch") -> None:
        self._parent = parent

    def exists(self, index: str) -> bool:
        return index in self._parent.docs

    def get_alias(self, index: str = "*") -> dict[str, Any]:
        return {name: {"aliases": {}} for name in self._parent.docs}

    def get_mapping(self, index: str) -> dict[str, Any]:
        if index not in self._parent.docs:
            return {}
        return copy.deepcopy(MAPPING.get(index, {"mappings": {"properties": {}}}))


class MockElasticsearch:
    is_sra_mock = True

    def __init__(self) -> None:
        self.docs = copy.deepcopy(MOCK_DOCS)
        self.indices = MockIndicesClient(self)

    def ping(self) -> bool:
        return True

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        docs = self.docs.get(index, {})
        query_text = _extract_query_text(body).lower()
        rows = []
        for doc_id, source in docs.items():
            haystack = " ".join(str(v) for v in _flatten_values(source)).lower()
            if query_text and query_text not in haystack:
                continue
            rows.append({"_id": doc_id, "_index": index, "_score": 1.0, "_source": copy.deepcopy(source)})
        rows.sort(key=lambda hit: str(hit["_source"].get("importDT") or ""), reverse=True)
        offset = int(body.get("from") or 0)
        size = int(body.get("size") or 20)
        return {"hits": {"total": {"value": len(rows)}, "hits": rows[offset: offset + size]}, "_mock": True}

    def get(self, *, index: str, id: str, _source: bool = True) -> dict[str, Any]:
        if id not in self.docs.get(index, {}):
            raise KeyError(id)
        return {"_index": index, "_id": id, "_source": copy.deepcopy(self.docs[index][id])}

    def index(self, *, index: str, id: str, document: dict[str, Any], refresh: str = "") -> dict[str, Any]:
        bucket = self.docs.setdefault(index, {})
        created = id not in bucket
        bucket[id] = copy.deepcopy(document)
        bucket[id].setdefault("importDT", _NOW)
        return {"_index": index, "_id": id, "result": "created" if created else "updated"}

    def delete(self, *, index: str, id: str, refresh: str = "") -> dict[str, Any]:
        if id not in self.docs.get(index, {}):
            raise KeyError(id)
        del self.docs[index][id]
        return {"_index": index, "_id": id, "result": "deleted"}


def _extract_query_text(body: dict[str, Any]) -> str:
    try:
        must = body.get("query", {}).get("bool", {}).get("must", [])
        for item in must:
            if "simple_query_string" in item:
                return str(item["simple_query_string"].get("query") or "")
    except Exception:
        return ""
    return ""


def _flatten_values(value: Any):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _flatten_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _flatten_values(nested)
    else:
        yield value

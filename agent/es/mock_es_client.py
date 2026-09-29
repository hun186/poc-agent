from __future__ import annotations

import copy
import fnmatch
import re
import time
from typing import Any

from agent.es.reference_text import add_reference_text_mapping, get_reference_text, set_reference_text

MOCK_INDEX = "vercel_mock_vessel_activities"
REQUIREMENT_E2E_INDEX = "requirement_e2e_semantic"
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

# Dedicated Requirement acceptance mapping. The root fields below are the SRA
# retrieval subset; REQUIREMENT_MULTIDIM_MAPPING is the separate czjLLM
# writeback subtree and deliberately does not pretend to be a complete index
# mapping.
REQUIREMENT_MULTIDIM_MAPPING = {
    "type": "nested", "dynamic": "strict", "properties": {
        "article_date_iso": {"type": "date", "format": "yyyy-MM-dd"},
        "article_date_precision": {"type": "keyword"},
        "article_title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
        "Event_Summary": {"type": "text"}, "facet": {"type": "keyword"},
        "core_entities": {"type": "keyword"}, "locations": {"type": "keyword"},
        "Event": {"type": "nested", "properties": {
            "event_id": {"type": "keyword"}, "subject": {"type": "keyword"},
            "object": {"type": "keyword"}, "aspect": {"type": "keyword"},
            "medium": {"type": "keyword"}, "action": {"type": "keyword"},
            "time_iso": {"type": "date", "format": "strict_date_optional_time||yyyy-MM-dd"},
            "time_raw": {"type": "keyword"}, "time_precision": {"type": "keyword"},
            "location": {"type": "keyword"}, "consequence": {"type": "text"},
            "relation": {"type": "text"}, "source": {"type": "keyword"},
        }},
        "Person": {"type": "nested", "properties": {
            "event_ids": {"type": "keyword"}, "name": {"type": "keyword"},
            "role": {"type": "keyword"}, "action": {"type": "text"},
            "quote": {"type": "text"}, "stance": {"type": "keyword"},
            "relation": {"type": "text"},
        }},
        "Involved_Parties": {"type": "nested", "properties": {
            "event_ids": {"type": "keyword"}, "party_name": {"type": "keyword"},
            "party_role": {"type": "keyword"},
        }},
        "Impact": {"type": "nested", "properties": {
            "event_ids": {"type": "keyword"}, "impact_description": {"type": "text"},
        }},
        "Event_Timeline": {"type": "nested", "properties": {
            "event_ids": {"type": "keyword"},
            "time_iso": {"type": "date", "format": "strict_date_optional_time||yyyy-MM-dd"},
            "time_raw": {"type": "keyword"}, "time_precision": {"type": "keyword"},
            "description": {"type": "text"},
        }},
        "evidence_snippets": {"type": "nested", "properties": {
            "event_ids": {"type": "keyword"}, "text": {"type": "text"},
            "source_id": {"type": "keyword"}, "char_start": {"type": "integer"},
            "char_end": {"type": "integer"}, "paragraph_id": {"type": "keyword"},
            "sentence_index": {"type": "integer"}, "confidence": {"type": "integer"},
        }},
        "importance": {"properties": {
            "coverage": {"type": "integer"}, "novelty": {"type": "integer"},
            "impact": {"type": "integer"}, "credibility": {"type": "integer"},
            "importance_score": {"type": "integer"},
        }},
    },
}

REQUIREMENT_E2E_MAPPING = {"mappings": add_reference_text_mapping({
    "_meta": {"requirement_e2e_fixture": "v1"},
    "properties": {
    "uuid": {"type": "keyword"},
    "communication": {"properties": {"subject": {"type": "text", "fields": {"keyword": {"type": "keyword"}}}}},
    "rawInfo": {"properties": {"content": {"type": "text"}}},
    "selectedMessage": {"type": "boolean"},
    "ai": {"properties": {"classLabels": {"properties": {"highValue": {"type": "boolean"}}}}},
    "importDT": {"type": "date"},
    "multidim_event_json": REQUIREMENT_MULTIDIM_MAPPING,
}})}
MAPPING[REQUIREMENT_E2E_INDEX] = REQUIREMENT_E2E_MAPPING

_REQUIREMENT_DOCUMENTS = (
    {
        "id": "requirement-gaza-001", "date": "2025-10-08",
        "title": "加薩停火談判與人道援助准入",
        "content": "2025年10月8日，加薩停火談判聚焦人質釋放與人道援助准入。卡達與埃及參與調解，聯合國表示食品、藥品與帳篷已備妥，但邊境准入與安全通行仍限制物資送達。",
        "subject": "加薩停火談判", "object": "人質釋放與人道援助准入",
        "action": "持續協商", "location": "加薩", "facet": ["politics", "humanitarian"],
        "entities": ["加薩", "聯合國", "卡達", "埃及"],
        "parties": [("卡達", "調解方"), ("埃及", "調解方"), ("聯合國", "人道援助機構")],
    },
    {
        "id": "requirement-taiwan-strait-002", "date": "2026-09-04",
        "title": "臺灣海峽軍事與灰色地帶活動",
        "content": "2026年9月4日，臺灣海峽周邊持續出現軍機、軍艦、海警船與無人機活動。相關聯合戰備警巡跨越海峽中線，增加灰色地帶壓力與海空交通風險。",
        "subject": "臺灣海峽周邊軍事與海警力量", "object": "灰色地帶活動",
        "action": "實施聯合戰備警巡", "location": "臺灣海峽", "facet": ["security", "military"],
        "entities": ["臺灣海峽", "軍機", "軍艦", "海警船"],
        "parties": [("海警", "海上執法力量")],
    },
    {
        "id": "requirement-us-china-003", "date": "2026-09-04",
        "title": "美中戰略競爭與美軍印太部署",
        "content": "2026年9月4日，美中戰略競爭涵蓋臺灣、科技管制、軍事互動與盟友協調。美國持續強化印太基地、聯合演訓與後勤節點，並與日本、澳洲及菲律賓推進安全合作。",
        "subject": "美國與中國", "object": "印太戰略競爭",
        "action": "調整安全政策與軍力部署", "location": "印太地區", "facet": ["security", "geopolitics"],
        "entities": ["美國", "中國", "印太", "日本", "澳洲", "菲律賓"],
        "parties": [("美國", "印太安全政策參與方"), ("中國", "戰略競爭參與方")],
    },
)
MOCK_DOCS[REQUIREMENT_E2E_INDEX] = {}
for _fixture in _REQUIREMENT_DOCUMENTS:
    _event_id = "E1"
    _source_text = _fixture["content"]
    _document = {
        "uuid": _fixture["id"], "communication": {"subject": _fixture["title"]},
        "rawInfo": {"content": _source_text}, "importDT": f'{_fixture["date"]}T00:00:00Z',
        "selectedMessage": True, "ai": {"classLabels": {"highValue": True}},
        "multidim_event_json": [{
            "article_title": _fixture["title"], "article_date_iso": _fixture["date"],
            "article_date_precision": "day", "facet": _fixture["facet"],
            "core_entities": _fixture["entities"], "locations": [_fixture["location"]],
            "Event_Summary": _source_text,
            "Event": [{"event_id": _event_id, "subject": _fixture["subject"],
                "object": _fixture["object"], "aspect": _fixture["facet"][0],
                "medium": "公開資訊", "action": _fixture["action"],
                "time_iso": _fixture["date"], "time_raw": _fixture["date"],
                "time_precision": "day", "location": _fixture["location"],
                "consequence": "", "relation": ""}],
            "Person": [],
            "Involved_Parties": [{"party_name": name, "party_role": role, "event_ids": [_event_id]}
                                 for name, role in _fixture["parties"]],
            "Impact": [{"impact_description": _source_text, "event_ids": [_event_id]}],
            "Event_Timeline": [{"time_iso": _fixture["date"], "time_raw": _fixture["date"],
                "time_precision": "day", "description": _source_text, "event_ids": [_event_id]}],
            "evidence_snippets": [{"source_id": _fixture["id"], "paragraph_id": "P1",
                "sentence_index": 0, "char_start": 0, "char_end": len(_source_text),
                "text": _source_text, "confidence": 100, "event_ids": [_event_id]}],
            "importance": {"coverage": 5, "novelty": 3, "impact": 5,
                           "credibility": 4, "importance_score": 85},
        }],
    }
    set_reference_text(_document, _source_text)
    MOCK_DOCS[REQUIREMENT_E2E_INDEX][_fixture["id"]] = _document


def validate_requirement_fixture(source: dict[str, Any]) -> None:
    """Fail closed when a semantic fixture would violate strict writeback shape."""
    date_only = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    date_time = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T.*)?$")

    def validate_value(value: Any, mapping: dict[str, Any], field: str) -> None:
        kind = mapping.get("type")
        if kind == "nested":
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError("semantic_fixture_nested_shape_invalid")
            allowed_children = mapping["properties"]
            for item in value:
                if set(item) - set(allowed_children):
                    raise ValueError("semantic_fixture_strict_mapping_violation")
                for child, child_value in item.items():
                    validate_value(child_value, allowed_children[child], f"{field}.{child}")
        elif "properties" in mapping:
            if not isinstance(value, dict) or set(value) - set(mapping["properties"]):
                raise ValueError("semantic_fixture_strict_mapping_violation")
            for child, child_value in value.items():
                validate_value(child_value, mapping["properties"][child], f"{field}.{child}")
        elif kind in {"keyword", "text"}:
            values = value if isinstance(value, list) else [value]
            if any(not isinstance(item, str) for item in values):
                raise ValueError("semantic_fixture_scalar_type_invalid")
        elif kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError("semantic_fixture_scalar_type_invalid")
        elif kind == "date":
            pattern = date_only if mapping.get("format") == "yyyy-MM-dd" else date_time
            if not isinstance(value, str) or not pattern.fullmatch(value):
                raise ValueError("semantic_fixture_date_invalid")

    allowed = REQUIREMENT_MULTIDIM_MAPPING["properties"]
    blocks = source.get("multidim_event_json")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("semantic_fixture_multidim_invalid")
    for block in blocks:
        extras = set(block) - set(allowed)
        if extras:
            raise ValueError("semantic_fixture_strict_mapping_violation")
        if not date_only.fullmatch(str(block.get("article_date_iso") or "")):
            raise ValueError("semantic_fixture_article_date_invalid")
        for field, value in block.items():
            validate_value(value, allowed[field], field)
        events = block["Event"]
        ids = [event.get("event_id") for event in events]
        if not ids or None in ids or len(ids) != len(set(ids)):
            raise ValueError("semantic_fixture_event_ids_invalid")
        linked_fields = ("Person", "Involved_Parties", "Impact", "Event_Timeline", "evidence_snippets")
        for field in linked_fields:
            if any(not item.get("event_ids") or not set(item["event_ids"]) <= set(ids)
                   for item in block[field]):
                raise ValueError("semantic_fixture_event_reference_invalid")
        supported = {event_id for item in block["evidence_snippets"] for event_id in item["event_ids"]}
        if set(ids) - supported:
            raise ValueError("semantic_fixture_event_evidence_missing")
        reference = get_reference_text(source)
        if any(item["text"] not in reference for item in block["evidence_snippets"]):
            raise ValueError("semantic_fixture_evidence_not_verbatim")


for _source in MOCK_DOCS[REQUIREMENT_E2E_INDEX].values():
    validate_requirement_fixture(_source)


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

    def search(self, *, index: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
        indexes = [item.strip() for item in index.split(",") if item.strip()]
        if not indexes or any(item not in self.docs for item in indexes):
            return {"hits": {"total": {"value": 0}, "hits": []}, "_mock": True}
        rows = []
        for target in indexes:
            for doc_id, source in self.docs[target].items():
                matched, score, inner = _evaluate_query(body.get("query", {}), source)
                if not matched:
                    continue
                row = {"_id": doc_id, "_index": target, "_score": score,
                       "_source": copy.deepcopy(source)}
                if inner:
                    row["inner_hits"] = inner
                rows.append(row)
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


def _path_values(source: Any, path: str) -> list[Any]:
    parts = path.split(".")
    values = [source]
    for part in parts:
        next_values = []
        for value in values:
            if isinstance(value, dict) and part in value:
                child = value[part]
                next_values.extend(child if isinstance(child, list) else [child])
        values = next_values
    return values


def _terms(value: Any) -> list[str]:
    # Chinese phrases stay intact while Latin phrases get useful token matching.
    text = str(value or "").strip().lower()
    pieces = [piece for piece in text.split() if piece]
    if len(pieces) > 1:
        return pieces
    latin = re.findall(r"[a-z0-9]+", text)
    return latin or ([text] if text else [])


def _text_match(query: Any, values: list[Any], operator: str = "or", phrase: bool = False) -> bool:
    needle = str(query or "").strip().lower()
    haystack = " ".join(str(value) for value in values).lower()
    if not needle:
        return False
    if phrase:
        return needle in haystack
    terms = _terms(needle)
    return all(term in haystack for term in terms) if operator == "and" else any(term in haystack for term in terms)


def _evaluate_query(query: dict[str, Any], source: dict[str, Any]) -> tuple[bool, float, dict[str, Any]]:
    """Evaluate only the bounded DSL emitted by the production retrieval builder."""
    if not query:
        raise ValueError("semantic_mock_unsupported_query")
    if "function_score" in query:
        spec = query["function_score"]
        matched, score, inner = _evaluate_query(spec["query"], source)
        if not matched:
            return False, 0.0, {}
        for function in spec.get("functions", []):
            if "filter" in function and _evaluate_query(function["filter"], source)[0]:
                score += float(function.get("weight", 0))
            elif "gauss" in function:
                score += 0.01
            elif "filter" not in function:
                raise ValueError("semantic_mock_unsupported_function_score")
        return True, score, inner
    if "bool" in query:
        spec = query["bool"]
        inner: dict[str, Any] = {}
        for key in ("must", "filter"):
            clauses = spec.get(key, [])
            clauses = clauses if isinstance(clauses, list) else [clauses]
            for clause in clauses:
                ok, _, found = _evaluate_query(clause, source)
                if not ok:
                    return False, 0.0, {}
                inner.update(found)
        should = spec.get("should", [])
        should = should if isinstance(should, list) else [should]
        matched_should = 0
        score = 1.0
        for clause in should:
            ok, clause_score, found = _evaluate_query(clause, source)
            if ok:
                matched_should += 1
                score += clause_score
                inner.update(found)
        required = int(spec.get("minimum_should_match", 0 if (spec.get("must") or spec.get("filter")) else bool(should)))
        return matched_should >= required, score, inner
    if "term" in query:
        field, expected = next(iter(query["term"].items()))
        if isinstance(expected, dict):
            expected = expected.get("value")
        return any(value == expected for value in _path_values(source, field)), 1.0, {}
    if "multi_match" in query or "simple_query_string" in query:
        spec = query.get("multi_match") or query.get("simple_query_string")
        fields = [field.split("^", 1)[0] for field in spec.get("fields", [])]
        values = [value for field in fields for value in _path_values(source, field)]
        ok = _text_match(spec.get("query"), values, str(spec.get("operator") or spec.get("default_operator") or "or").lower())
        return ok, 1.0, {}
    if "match" in query or "match_phrase" in query:
        phrase = "match_phrase" in query
        field, expected = next(iter((query.get("match_phrase") or query.get("match")).items()))
        operator = "or"
        if isinstance(expected, dict):
            operator, expected = str(expected.get("operator", "or")).lower(), expected.get("query")
        return _text_match(expected, _path_values(source, field), operator, phrase), 1.0, {}
    if "wildcard" in query:
        field, expected = next(iter(query["wildcard"].items()))
        pattern = str(expected.get("value") if isinstance(expected, dict) else expected).lower()
        ok = any(fnmatch.fnmatch(str(value).lower(), pattern) for value in _path_values(source, field.removesuffix(".keyword").removesuffix(".raw")))
        return ok, 1.0, {}
    if "range" in query:
        field, bounds = next(iter(query["range"].items()))
        values = [str(value)[:10] for value in _path_values(source, field)]
        ok = any((not bounds.get("gte") or value >= str(bounds["gte"])[:10]) and
                 (not bounds.get("lte") or value <= str(bounds["lte"])[:10]) for value in values)
        return ok, 1.0, {}
    if "nested" in query:
        spec = query["nested"]
        ok, score, inner = _evaluate_query(spec["query"], source)
        config = spec.get("inner_hits")
        if ok and config and spec.get("path") == "multidim_event_json.evidence_snippets":
            snippets = [item for block in source.get("multidim_event_json", [])
                        for item in block.get("evidence_snippets", [])
                        if _evaluate_query(spec["query"], {"multidim_event_json": {"evidence_snippets": item}})[0]]
            name = config.get("name", "evi")
            inner[name] = {"hits": {"hits": [
                {"_nested": {"field": spec["path"], "offset": offset},
                 "_score": 1.0, "_source": copy.deepcopy(item)}
                for offset, item in enumerate(snippets[:int(config.get("size", 3))])
            ]}}
        return ok, score, inner
    raise ValueError(f"semantic_mock_unsupported_query:{next(iter(query), 'empty')}")


def _flatten_values(value: Any):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _flatten_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _flatten_values(nested)
    else:
        yield value

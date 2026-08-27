# agent/es/query_body.py
import re
from typing import Any, Dict, List, Optional

from .reference_text import get_reference_text_field


MD_PATH = "multidim_event_json"


def _nested(path: str, query: Dict[str, Any], **options: Any) -> Dict[str, Any]:
    """Build a nested clause and make the nested boundary explicit."""
    nested = {"path": path, "query": query, **options}
    return {"nested": nested}


def _in_multidim(query: Dict[str, Any], **options: Any) -> Dict[str, Any]:
    return _nested(MD_PATH, query, **options)


def _in_multidim_child(
    child: str, query: Dict[str, Any], *, outer_options: Optional[Dict[str, Any]] = None,
    **child_options: Any,
) -> Dict[str, Any]:
    """Query a nested child below the nested multidim event document.

    Elasticsearch requires both nested levels to be entered.  Querying the child
    path directly worked with the old object Event mapping but is invalid once
    Event (and the other event-linked arrays) are nested below
    ``multidim_event_json``.
    """
    return _in_multidim(
        _nested(f"{MD_PATH}.{child}", query, **child_options),
        **(outer_options or {}),
    )

def build_main_query_body(
    query: Optional[str],
    must_high_value: Optional[bool],
    must_selected: Optional[bool],
    size: Optional[int],
    date_from: Optional[str],
    date_to: Optional[str],
    selected_boost: Optional[float],
    high_value_boost: Optional[float],
    recency_boost: Optional[bool],
    recency_field: Optional[str],
    recency_scale: Optional[str],
    with_date: bool = True,
    effective_terms: Optional[List[str]] = None,
    core_terms: Optional[List[str]] = None,
    syn_terms: Optional[List[str]] = None,
    all_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    reference_text_field = get_reference_text_field()
    core_terms = core_terms or []
    syn_terms = syn_terms or []
    all_terms = all_terms or []

    filters = []
    if must_high_value:
        filters.append({"term": {"ai.classLabels.highValue": True}})
    if must_selected:
        filters.append({"term": {"selectedMessage": True}})

    q = (query or "").strip()
    years_in_q = list(dict.fromkeys(re.findall(r'(?:19|20)\d{2}', q)))

    # 日期過濾：nested range
    if with_date and (date_from or date_to):
        rng = {"range": {"multidim_event_json.Event_Timeline.time_iso": {}}}
        if date_from:
            rng["range"]["multidim_event_json.Event_Timeline.time_iso"]["gte"] = date_from
        if date_to:
            rng["range"]["multidim_event_json.Event_Timeline.time_iso"]["lte"] = date_to
        filters.append(_in_multidim_child(
            "Event_Timeline", rng,
            outer_options={"score_mode": "none"}, score_mode="none",
        ))
    elif with_date and years_in_q:
        year_should = [{
            "range": {"multidim_event_json.Event_Timeline.time_iso": {
                "gte": f"{y}-01-01", "lte": f"{y}-12-31"
            }}
        } for y in years_in_q]
        filters.append(_in_multidim_child(
            "Event_Timeline",
            {"bool": {"should": year_should, "minimum_should_match": 1}},
            outer_options={"score_mode": "none"}, score_mode="none",
        ))

    shoulds: List[Dict[str, Any]] = []

    # === ① 主力檢索欄位：以解析後欄位為主，原文 content 不參與第一階段 ===
    structured_fields_main = [
        # 事件與實體（主力）
        "multidim_event_json.Event.subject^8",
        "multidim_event_json.Event.object^7",
        "multidim_event_json.Event.location^7",
        "multidim_event_json.core_entities^7",
        "multidim_event_json.locations^7",

        # 時間線描述（次要，但常有關鍵敘述）
        "multidim_event_json.Event_Timeline.description^5",

        # 人物 / 涉入方
        "multidim_event_json.Person.name^5",
        "multidim_event_json.Person.role^4",
        "multidim_event_json.Involved_Parties.party_name^4",

        # 標題與主旨
        "multidim_event_json.article_title^4",
        "communication.subject^4",

        # 證據 snippet（給語意與說明用）
        "multidim_event_json.evidence_snippets.text^3",
    ]

    structured_fields_sqs = [
        # simple_query_string 版本，權重略降
        "multidim_event_json.Event.subject^5",
        "multidim_event_json.Event.object^4",
        "multidim_event_json.Event.location^4",
        "multidim_event_json.core_entities^4",
        "multidim_event_json.locations^4",
        "multidim_event_json.Event_Timeline.description^3",
        "multidim_event_json.Person.name^3",
        "multidim_event_json.Person.role^2",
        "multidim_event_json.Involved_Parties.party_name^2",
        "multidim_event_json.article_title^3",
        "communication.subject^3",
        "multidim_event_json.evidence_snippets.text^2",
    ]
    
    # 1) 一般語義檢索。nested 欄位必須在各自的 nested context 查詢，
    # 不可再把 root / outer nested / child nested 欄位放在同一個 multi_match。
    outer_fields = [f for f in structured_fields_main if not any(
        f.startswith(f"{MD_PATH}.{child}.")
        for child in ("Event", "Event_Timeline", "Person", "Involved_Parties", "evidence_snippets")
    ) and f.startswith(f"{MD_PATH}.")]
    root_fields = [f for f in structured_fields_main if not f.startswith(f"{MD_PATH}.")]
    if root_fields:
        shoulds.append({"multi_match": {
            "query": q, "fields": root_fields, "type": "best_fields", "operator": "or"
        }})
    shoulds.append(_in_multidim({
        "multi_match": {
            "query": q,
            "fields": outer_fields,
            "type": "best_fields",
            "operator": "or"
        }
    }))
    child_fields_main = {
        child: [f for f in structured_fields_main if f.startswith(f"{MD_PATH}.{child}.")]
        for child in ("Event", "Event_Timeline", "Person", "Involved_Parties")
    }
    for child, fields in child_fields_main.items():
        shoulds.append(_in_multidim_child(child, {"multi_match": {
            "query": q, "fields": fields, "type": "best_fields", "operator": "or"
        }}))

    root_sqs = [f for f in structured_fields_sqs if not f.startswith(f"{MD_PATH}.")]
    outer_sqs = [f for f in structured_fields_sqs if f.startswith(f"{MD_PATH}.") and not any(
        f.startswith(f"{MD_PATH}.{child}.")
        for child in ("Event", "Event_Timeline", "Person", "Involved_Parties", "evidence_snippets")
    )]
    if root_sqs:
        shoulds.append({"simple_query_string": {"query": q, "fields": root_sqs, "default_operator": "and"}})
    shoulds.append(_in_multidim({"simple_query_string": {
        "query": q, "fields": outer_sqs, "default_operator": "and"
    }}))

    # 2) 精準加分（keyword/wildcard）
    if q:
        def wc(field, pat): return {"wildcard": {field: {"value": pat}}}
        shoulds.append(wc("communication.subject.keyword", f"*{q}*"))
        shoulds.append(_in_multidim(wc("multidim_event_json.article_title.raw", f"*{q}*")))

    # 3) 直接命中證據段落（nested + inner_hits）
    evidence_child: Dict[str, Any] = {
        "nested": {
            "path": "multidim_event_json.evidence_snippets",
            "query": {
                "bool": {
                    "should": [
                        {
                            "match_phrase": {
                                "multidim_event_json.evidence_snippets.text": q
                            }
                        },
                        {
                            "match": {
                                "multidim_event_json.evidence_snippets.text": {
                                    "query": q,
                                    "operator": "and"
                                }
                            }
                        }
                    ],
                    "minimum_should_match": 1
                }
            },
            "score_mode": "avg",
            "inner_hits": {
                "name": "evi",
                "size": 3,
                "_source": [
                    "multidim_event_json.evidence_snippets.text",
                    "multidim_event_json.evidence_snippets.source_id",
                    "multidim_event_json.evidence_snippets.paragraph_id",
                    "multidim_event_json.evidence_snippets.event_ids"
                ],
                "highlight": {
                    "fields": {
                        "multidim_event_json.evidence_snippets.text": {
                            "fragment_size": 180,
                            "number_of_fragments": 1
                        }
                    }
                }
            }
        }
    }
    evidence_nested = _in_multidim(evidence_child)

    # ★ 在 nested 裡也加入 all_terms，強化 snippet 命中
    if all_terms:
        ev_should = evidence_child["nested"]["query"]["bool"]["should"]
        for t in all_terms:
            ev_should.append({
                "match_phrase": {
                    "multidim_event_json.evidence_snippets.text": t
                }
            })
    
    # ★ 4) 人工同義詞 / 主題詞加分：rawInfo / subject / title
    if core_terms or syn_terms:
        entity_shoulds: List[Dict[str, Any]] = []
    
        # 核心主題詞：match_phrase（精準）
        for t in core_terms:
            entity_shoulds.append({"match_phrase": {reference_text_field: t}})
            entity_shoulds.append({"match_phrase": {"communication.subject": t}})
            entity_shoulds.append(_in_multidim({"match_phrase": {"multidim_event_json.article_title": t}}))
    
        # 同義詞：用 match（OR），當加分用
        for t in syn_terms:
            entity_shoulds.append({
                "match": {
                    reference_text_field: {
                        "query": t,
                        "operator": "or"
                    }
                }
            })
    
        if entity_shoulds:
            shoulds.append({
                "bool": {
                    "should": entity_shoulds,
                    "minimum_should_match": 1
                }
            })

    # 把 nested evidence 放進 should
    shoulds.append(evidence_nested)

    base_bool = {
        "bool": {
            "should": shoulds,
            "minimum_should_match": 1,
            "filter": filters
        }
    }

    # 4) function_score：人審/AI 加權 +（可選）新鮮度
    functions: List[Dict[str, Any]] = [
        {"filter": {"term": {"selectedMessage": True}}, "weight": (selected_boost or 6.0)},
        {"filter": {"term": {"ai.classLabels.highValue": True}}, "weight": (high_value_boost or 2.5)},
    ]
    if recency_boost:
        functions.append({"gauss": {(recency_field or "importDT"): {
            "scale": (recency_scale or "30d"),
            "decay": 0.5
        }}})

    body = {
        "size": size or 5,
        "_source": [
            "uuid",
            "communication.subject",
            #"rawInfo.content",
            "multidim_event_json.article_title",
            "multidim_event_json.article_date_iso",
            "multidim_event_json.evidence_snippets",
            "multidim_event_json.Event_Timeline",
            "selectedMessage",
            "ai.classLabels.highValue",
            "importDT",
            "update_time_ai"
        ],
        "query": {
            "function_score": {
                "query": base_bool,
                "boost_mode": "sum",
                "score_mode": "sum",
                "functions": functions
            }
        },
        "highlight": {
            "fields": {
                "communication.subject": {"fragment_size": 100, "number_of_fragments": 1},
                "multidim_event_json.article_title": {"fragment_size": 100, "number_of_fragments": 1}
            },
            "require_field_match": False
        },
        "sort": [
            "_score",
            {
              "multidim_event_json.Event_Timeline.time_iso": {
                  "order": "desc",
                  "mode": "max",
                  "nested": {
                      "path": "multidim_event_json",
                      "nested": {"path": "multidim_event_json.Event_Timeline"}
                  }
              }
            },
            {"importDT": {"order": "desc"}}
        ],
        "track_total_hits": True
    }
    '''
    print("[_build_query_body] q=", q,
          "core_terms=", core_terms,
          "syn_terms=", syn_terms,
          "num_all_terms=", len(all_terms))
    '''
    return body

def build_fallback_query_body(
    query: str,
    must_high_value: Optional[bool],
    must_selected: Optional[bool],
    size: Optional[int],
) -> Dict[str, Any]:
    reference_text_field = get_reference_text_field()
    filters: List[Dict[str, Any]] = []
    if must_high_value:
        filters.append({"term": {"ai.classLabels.highValue": True}})
    if must_selected:
        filters.append({"term": {"selectedMessage": True}})

    q = (query or "").strip()
    shoulds = [
        {"simple_query_string": {
            "query": q,
            "fields": ["communication.subject^3", reference_text_field]
        }},
        _in_multidim({"match": {"multidim_event_json.article_title": q}}),
        _in_multidim_child("evidence_snippets", {"match": {
            "multidim_event_json.evidence_snippets.text": {
            "query": q,
            "operator": "or"
        }}})
    ]
    if q:
        def wc(field, pat): return {"wildcard": {field: {"value": pat}}}
        shoulds.append(wc("communication.subject.keyword", f"*{q}*"))
        shoulds.append(_in_multidim(wc("multidim_event_json.article_title.raw", f"*{q}*")))

    return {
        "size": size or 5,
        "_source": [
            "uuid",
            "communication.subject",
            reference_text_field,
            "multidim_event_json.evidence_snippets",
            "multidim_event_json.article_title",
            "multidim_event_json.article_date_iso",
            "multidim_event_json.Event_Timeline"
        ],
        "query": {"bool": {"should": shoulds, "minimum_should_match": 1, "filter": filters}},
        "highlight": {
            "fields": {reference_text_field: {"fragment_size": 200, "number_of_fragments": 2}},
            "require_field_match": False
        }
    }

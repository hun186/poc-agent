# agent/es/query_terms.py
import os
import json
import logging
import re
import textwrap
from typing import List, Dict, Tuple
from agent.llm_utils.ollama_client import call_llm
from agent.es.synonyms import (
    expand_manual_terms,
    extract_manual_terms_from_query,
)
from agent.es.zh_variants import expand_zh_script_variants

logger = logging.getLogger(__name__)

KEYWORD_EXTRACTION_MAX_CHARS = max(
    512, int(os.getenv("KEYWORD_EXTRACTION_MAX_CHARS", "6000"))
)


def _build_keyword_extraction_input(q: str) -> str:
    """Build a bounded, temporary view used only by the keyword extractor LLM."""
    cleaned = (q or "").strip()
    if len(cleaned) <= KEYWORD_EXTRACTION_MAX_CHARS:
        return cleaned

    marker = "\n\n【中間大量任務資料已省略，完整查詢仍供後續檢索流程使用】\n\n"
    available = KEYWORD_EXTRACTION_MAX_CHARS - len(marker)
    head_chars = int(available * 0.75)
    tail_chars = available - head_chars
    logger.warning(
        "[keywords] 輸入過長，已啟動關鍵字提取裁切機制：original_chars=%d "
        "extractor_chars=%d；只裁切關鍵字提取器的暫時輸入。",
        len(cleaned),
        KEYWORD_EXTRACTION_MAX_CHARS,
    )
    return f"{cleaned[:head_chars]}{marker}{cleaned[-tail_chars:]}"


_EXPLICIT_REPORT_CORE_QUERY_RE = re.compile(
    r"^\s*核心關鍵詞組如下\s*[：:]\s*(.*?)\s*$",
    re.DOTALL,
)


def _parse_explicit_core_terms_query(q: str) -> List[str] | None:
    """Parse only the structured core query emitted by the Report Data Agent.

    ``None`` means the query is not in the Report format.  An empty list means
    that the Report prefix was present but did not contain any usable terms.
    """
    match = _EXPLICIT_REPORT_CORE_QUERY_RE.fullmatch(q or "")
    if match is None:
        return None

    terms: List[str] = []
    seen: set[str] = set()
    for raw_term in re.split(r"[、，,]", match.group(1)):
        term = raw_term.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


# ===== LLM：抽主題詞 =====

def extract_topic_terms_llm(q: str) -> List[str]:
    """
    通用關鍵字萃取器：
    使用 LLM 從自然語言查詢中抽取「重要主題詞 / 關鍵詞」，
    可用在任何領域。

    - 回傳：list[str]，每個元素是一個關鍵詞或短語
    - 若無法判斷關鍵詞，回傳空陣列 []
    """
    q = (q or "").strip()
    if not q:
        return []

    # 視為「有沒有啟用這個功能」的總開關
    if not os.getenv("TOPIC_LLM_URL"):
        return []

    system_prompt = textwrap.dedent("""
    你是一個「通用查詢關鍵字萃取器」。
    使用者會給你一段查詢句子或自然語言描述，請只做一件事：

    從內容中找出最重要的「關鍵詞 / 主題詞」，例如：
    - 專有名詞：人名、地名（國家、城市、海域、基地、港口等）、組織、機構
    - 事件 / 政策名稱：某事件、A政策、B制度
    - 重要概念：具明確檢索價值的技術、制度或專業概念
    - 產品 / 人工同義詞 / 型號：某種設備、產品型號等

    規則：
    1. 僅輸出一個 JSON 陣列（array of string），不得有任何多餘文字。
       例：["甲主題", "乙制度", "丙技術"]
    2. 每個元素應是短語或名詞，不要整句話。
    3. 優先挑選具體、可檢索的詞：
       - 例如「A政策」「乙地」「某種設備X型」
       - 比起「影響」「變化」「情勢」這種抽象詞更重要。
    4. 不要輸出：
       - 功能詞：的、和、是否、以及、影響、分析、情況、趨勢 等
       - 純時間或日期：如 2025年1月、近年來、今天
       - 單獨的數字：如 15、2025 等
       - 過於籠統的地理詞：如 世界、全球、國際、亞洲、歐洲（除非明顯是查詢核心）
    5. 若覺得沒有明顯的關鍵詞，可以輸出空陣列 []。
    6. 原則上不超過 8 個，沒有最低數量要求；寧可少給也不要亂給。
    """).strip()

    user_prompt = textwrap.dedent(f"""
    使用者查詢如下：
    {q}
    """).strip()

    try:
        raw = call_llm(user_prompt, system_prompt=system_prompt)
        if not raw:
            return []

        data = json.loads(raw)
        if not isinstance(data, list):
            return []

        out: List[str] = []
        for x in data:
            if isinstance(x, str):
                s = x.strip()
                if not s:
                    continue
                out.append(s)
        #print("out in _extract_topic_terms_llm", out)
        return out
    except Exception as e:
        print(f"[ES tools] LLM topic extractor 失敗：{e}")
        return []

def expand_synonyms_grouped_llm(q: str, core_terms: List[str]) -> Dict[str, List[str]]:
    """
    用既有 LLM 呼叫依完整 query context，針對核心詞產生等價或近等價
    名稱變體，並合併真正等價的語意軸。

    要求 LLM：
    - 若覺得某些 core term 其實是互為同義詞（或其中一個只是別名 / 英譯），
      請只保留一個代表核心詞當 key，其餘全部放到該 key 的同義詞陣列中。
    """
    q = (q or "").strip()
    core_terms = [t.strip() for t in (core_terms or []) if t and t.strip()]
    if not q or not core_terms:
        return {}

    if not os.getenv("TOPIC_LLM_URL"):
        return {}

    core_list = ", ".join(f'"{t}"' for t in core_terms)

    system_prompt = textwrap.dedent("""
    你是一個「文本檢索查詢關鍵詞同義詞擴充器」。

    使用者會提供：
    - 一段查詢句子（query）
    - 一組核心關鍵詞（core_terms）

    你的工作只有一件事：在完整 query 與全部 core_terms 的共同語境下，
    建立「語意軸 → 等價／近等價名稱列表」的映射。這不是主題擴張工作。
    若多個核心關鍵詞確實是同一概念（例如正式名稱 + 外文名 + 簡寫），
       請把它們「合併成同一語意軸」，只保留一個代表核心詞當 key，其餘全部放進 value 的陣列裡。

    具體規則：

    【輸出格式】
    - 僅輸出一個 JSON 物件（object），不得有任何多餘文字。
      key: 代表核心詞（string）
      value: 該語意軸的同義詞陣列（array of string）

    【語意軸合併規則】
    1. 只有同一實體、全名／縮寫、同一名稱的不同語言，或在本 query
       語境下高度可互換的明確等價名稱，才可合併。
    2. 若你判定它們是同一個概念，請：
       - 從中挑一個代表核心詞作為 key
         （優先選用 core_terms 中出現較早、且較常用的寫法）
       - 其他同義寫法（包含原本的核心詞、別名、縮寫）全部放進該 key 的 value 陣列。
    3. 不得因上下位、子類、組成關係、共同出現、同一政策的不同機制，
       或同一文件常一起出現而合併。

    【同義詞擴充】
    1. value 陣列中可以包含：
       - 其他 core_terms 中的同義寫法
       - 同一實體的正式名稱、別名、全名、縮寫、精確外文名稱、常見譯名
       - 轉寫、拼寫或標點差異，以及本 query 語境中的高度等價表述
       - 文種／風格詞可包含實際資料中合理且常用的近等價文種名稱
    2. 「高度相關」不等於同義。不要加入上下位概念、兄弟類別、元件、
       原因、結果、影響、對策、關聯人物／組織／事件／地點、歷史或類比案例，
       也不要加入只因媒體共現、同一地區或同一技術體系而相關的詞。
    3. 文種近等價彈性不得跨到不同主題、政策、事件，或只是用途相關、常共同出現的文件。
    4. 不要發明名稱；沒有最低數量要求，value 可以是 []。不確定就省略，precision 優先。

    【完整語境消歧】
    1. 判斷依序以本次 query、全部 core_terms 的共同語意、現代新聞／情報／文件
       語境中的主要義項為準，不做脫離 query 的單詞字典式展開。
    2. 古語、罕見歷史義項、其他專業領域義項、在本 query 中不自然或可能大量
       命中不同領域文件的候選都不要加入；需要特殊字典知識才勉強相關時也省略。
    3. 對每個候選做取代測試：若在與 query 相關的正常新聞／文件句子中取代原詞，
       無法穩定維持相同或高度等價概念且不改變檢索主題，就不要加入。

    【子型號 / 子類的嚴謹規則】
    1. 若核心關鍵詞包含明確子類或型號資訊（例如「某種設備X型」「某類疾病A型」），
       同義詞必須保留相同的子類或型號，不可以退化成更廣泛的類別。
    2. 類似地，若關鍵詞包含明確型號、版本號、系列編號，
       同義詞中也必須保留對應的識別資訊（數字或等價符號），不要只給「坦克」「手機」「戰機」這類籠統詞。

    【代表核心詞的選擇原則（說明用，不用輸出）】
    - 優先選 core_terms 列表中較前面出現，且較自然、常用的寫法。
    - key 必須逐字來自 core_terms；不得自行創造 representative key。
    """).strip()

    user_prompt = textwrap.dedent(f"""
    查詢句子（query）：
    {q}

    核心關鍵詞（core_terms）：
    [{core_list}]
    """).strip()

    try:
        raw = call_llm(user_prompt, system_prompt=system_prompt)
        if not raw:
            return {}

        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}

        # Python 端只做「防呆 + 清洗」
        final: Dict[str, List[str]] = {}

        for k, v in data.items():
            if not isinstance(k, str):
                continue
            k = k.strip()
            if not k:
                continue

            syns: List[str] = []
            seen: set[str] = set()
            if isinstance(v, list):
                for x in v:
                    if not isinstance(x, str):
                        continue
                    s = x.strip()
                    if not s:
                        continue
                    if s == k:
                        # 不要把自己塞回同義詞
                        continue
                    if s in seen:
                        continue
                    seen.add(s)
                    syns.append(s)

            # 若你只想保留「至少有一個同義詞」的語意軸
            if syns:
                final[k] = syns

        # （可選）如果你希望最後的 key 一定要是原本的 core_terms 之一，可以在這裡再過一層：
        core_set = set(core_terms)
        filtered: Dict[str, List[str]] = {}
        for k, syns in final.items():
            if k in core_set:
                filtered[k] = syns
        return filtered

    except Exception as e:
        print(f"[ES tools] LLM grouped synonym expander 失敗：{e}")
        return {}

#不使用
def extract_topic_terms_rules(q: str) -> List[str]:
    s = (q or "").strip()
    if not s:
        return []

    terms = set()

    # (1) 先抓「連續兩字以上」的中文詞
    zh_terms = re.findall(r'[\u4e00-\u9fff]{2,}', s)
    terms.update(zh_terms)

    # (2) 再抓數字 / 英數混合（長度 >= 2）
    #     e.g. "055", "DF-17", "BZK-005"
    for tok in re.split(r"\s+", s):
        tok = tok.strip(" ，,。.;；:：()（）[]【】")
        if not tok:
            continue
        # 年份 / 月份 之類不要當主題詞
        if re.fullmatch(r'(19|20)\d{2}', tok):
            continue
        if re.fullmatch(r'\d{1,2}', tok):     # 單純 1~2 位數字，當月/日處理，不當主題
            continue
        if len(tok) >= 2:
            terms.add(tok)

    # (3) 停用詞（盡量排掉不是「對象」的字）
    stop = {
        "請整理", "相關", "重點", "事件", "活動", "趨勢", "情勢", "狀況", "局勢",
        "態勢",
        "偵獲", "情況", "情勢摘要", "活動特徵", "特徵",
        "變化", "綜整", "報告", "情監偵", "回報",
        "分析",
        "年", "月份", "月", "日",
        "防治",
        # 常見地理詞：這些多半是「範圍」，不是你要的「055 / 遼寧號」之類主體
        #"台灣海峽", "臺灣海峽", "台海", "臺海",
        #"東海", "南海", "黃海", "渤海"
    }
    return [t for t in terms if t not in stop]


def compute_effective_terms(q: str) -> Tuple[
    List[str], Dict[str, List[str]], bool, List[str], List[str], List[set[str]]
]:
    """
    回傳：
    - core_terms
    - grouped_synonyms
    - is_manual_entity_query
    - manual_terms_in_q
    - effective_terms
    - term_groups（list[set]）
    """
    q = (q or "").strip()
    if not q:
        return [], {}, False, [], [], []

    # 1) LLM 主題詞
    # Only the extraction LLM receives a bounded temporary view. Keep ``q``
    # unchanged for manual-term matching, synonym expansion, and ES retrieval.
    explicit_core_terms = _parse_explicit_core_terms_query(q)
    if explicit_core_terms is not None:
        llm_terms_raw = explicit_core_terms
    else:
        keyword_extraction_input = _build_keyword_extraction_input(q)
        llm_terms_raw = extract_topic_terms_llm(keyword_extraction_input)
    llm_terms: List[str] = []
    seen: set[str] = set()
    for t in llm_terms_raw:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        llm_terms.append(s)

    # 2) query 內直接命中的人工同義詞
    manual_terms_in_q = extract_manual_terms_from_query(q)

    # 3) 人工同義詞家族展開
    base_terms_for_family: List[str] = []
    seen_base: set[str] = set()
    for lst in (llm_terms, manual_terms_in_q):
        for t in lst:
            t = (t or "").strip()
            if t and t not in seen_base:
                seen_base.add(t)
                base_terms_for_family.append(t)

    manual_family_terms = (
        expand_manual_terms(base_terms_for_family) if base_terms_for_family else []
    )

    is_manual_entity_query = bool(manual_family_terms)

    # 4) 初步核心候選詞
    ordered_core_candidates: List[str] = []
    seen_core: set[str] = set()
    for lst in (llm_terms, manual_terms_in_q, manual_family_terms):
        for t in lst:
            t = (t or "").strip()
            if t and t not in seen_core:
                seen_core.add(t)
                ordered_core_candidates.append(t)

    if not ordered_core_candidates:
        return [], {}, is_manual_entity_query, manual_terms_in_q, [], []

    # 5) LLM 做 group 同義詞
    raw_grouped = expand_synonyms_grouped_llm(q, ordered_core_candidates) or {}

    grouped_synonyms: Dict[str, List[str]] = {}
    for k, syns in raw_grouped.items():
        if not isinstance(k, str):
            continue
        k = k.strip()
        if not k:
            continue
        clean_syns: List[str] = []
        seen_syn: set[str] = set()
        for x in syns:
            if not isinstance(x, str):
                continue
            s = x.strip()
            if not s or s == k or s in seen_syn:
                continue
            seen_syn.add(s)
            clean_syns.append(s)
        if clean_syns:
            grouped_synonyms[k] = clean_syns

    # 5.1) 補上中文關鍵詞的簡繁變體（含沒有 LLM 同義詞的核心詞）
    zh_augmented: Dict[str, List[str]] = {}
    # 來源同時包含：
    # - grouped_synonyms（LLM 已分組）
    # - ordered_core_candidates（LLM 未分組或無同義詞的核心詞）
    seed_items: List[Tuple[str, List[str]]] = []
    for k, syns in grouped_synonyms.items():
        seed_items.append((k, syns))
    for core in ordered_core_candidates:
        if core not in grouped_synonyms:
            seed_items.append((core, []))

    for k, syns in seed_items:
        expanded: List[str] = []
        for t in [k, *syns]:
            for v in expand_zh_script_variants(t):
                if v != k and v not in expanded:
                    expanded.append(v)
        if expanded:
            zh_augmented[k] = expanded

    grouped_synonyms = zh_augmented

    rep_keys = list(grouped_synonyms.keys())
    rep_key_set = set(rep_keys)

    all_syn_values: set[str] = set()
    for syns in grouped_synonyms.values():
        for s in syns:
            all_syn_values.add(s)

    isolated_cores: List[str] = []
    for t in ordered_core_candidates:
        if t in rep_key_set:
            continue
        if t in all_syn_values:
            continue
        isolated_cores.append(t)

    core_terms: List[str] = rep_keys + [
        t for t in isolated_cores if t not in rep_key_set
    ]
    if not core_terms:
        core_terms = ordered_core_candidates

    grouped_synonyms = {k: v for k, v in grouped_synonyms.items() if k in core_terms}

    # 扁平化同義詞
    syn_terms_flat: List[str] = []
    seen_syn2: set[str] = set()
    for syns in grouped_synonyms.values():
        for s in syns:
            s = s.strip()
            if s and s not in seen_syn2:
                seen_syn2.add(s)
                syn_terms_flat.append(s)

    # effective_terms = 核心 + 扁平同義詞
    effective_terms: List[str] = []
    seen_all: set[str] = set()
    for t in core_terms + syn_terms_flat:
        t = t.strip()
        if t and t not in seen_all:
            seen_all.add(t)
            effective_terms.append(t)

    # term_groups
    term_groups: List[set[str]] = []
    if core_terms:
        for core in core_terms:
            core = (core or "").strip()
            if not core:
                continue
            g: set[str] = {core}
            for s in grouped_synonyms.get(core, []):
                ss = (s or "").strip()
                if ss:
                    g.add(ss)
            if g:
                term_groups.append(g)
    elif effective_terms:
        term_groups = [set(effective_terms)]

    return core_terms, grouped_synonyms, is_manual_entity_query, manual_terms_in_q, effective_terms, term_groups

# SRAF validated Evidence and fair-source budget — experimental / default OFF

Existing flag `SRAF_EVIDENCE_SHARED_SOURCE_BUDGET=1` (#411) fixes the rigid
single-document 20-citation cap within a 1024-candidate budget. It consumes
candidate slots **before** date/topic postfilter and in ES hit order.

This next separate opt-in requires BOTH flags:

```text
SRAF_EVIDENCE_SHARED_SOURCE_BUDGET=1
SRAF_EVIDENCE_VALID_FAIR_BUDGET=1
```

The parser then has a fixed **2048 examined/parsed candidate** ceiling,
**2048 source item** ceiling, and **1,048,576 shared source text characters**
ceiling, plus **4096 source snippet characters**. It reserves parser, source
scan and character shares by ES hit ordinal so the first large source cannot
silently use all slots when later documents have candidates. Unused count
quota is redistributed to larger sources (water-fill), not a fixed per-document
cap. The eventual strict Event/Timeline date, topic and weak/strong policy
remain the existing canonical code.

After canonical date/topic validation and existing bounded low-count rescue
branches, at most **1024 validated Evidence** are returned. If there is room,
the original source order is unchanged. If capped, deterministic source
round-robin within strong then weak Evidence preserves source diversity; **ES
hit ordinal**, not UUID, defines a separate source. The output traces emit
`valid_budget.eligible`, `valid_budget.selected`,
`valid_budget.not_selected` as fixed numeric counters with no private content.

Caveats: these are bounded *returned ES hits*, not an exhaustive search
across all ES pages, and the per-hit source scan still stops at its assigned
prefix/bytes cap even when later items may be relevant. Estimated quota
distribution is NOT an exact token budget or semantic quality score.
The Report Agent still has a separate normally-120-snippet total LLM limit.
Test OFF / #411-only / both-on against the same *authorized private* ES
index/query/date, multi-Event and mismatched-date cases, actual report
citations, p50/p95 wall time, memory, model token counts and DOCX before
any production enablement. Do not log source payloads or credentials.

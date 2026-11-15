# SRAF shared source candidate budget — experimental / default OFF

For large structured server documents with hundreds of Evidence rows, the
legacy parser may take only three nested `inner_hits` or 20 `_source` rows per
document, **even if the request has unused total budget**. This opt-in mode
scans the already-returned structured `_source` and uses one shared global
candidate allocation across documents instead of the 20-row cap. It does not
issue extra ES queries, rerun an LLM or modify source data.

Setting (opt-in only after operator comparison):

```text
SRAF_EVIDENCE_SHARED_SOURCE_BUDGET=1
```

The versioned hard limits are **1024 parsed citations per builder request**,
**2048 source rows inspected**, **1,048,576 source-text characters examined**
and **4096 characters per accepted source snippet**. Limits are safety ceilings
and could be reached before all source material is examined; the output is
NOT an exhaustive query guarantee. The final Report LLM limit remains the
separate `REPORT_MAX_EVIDENCE_SNIPS` (normally 120). Data Agent Event/Timeline
and topic filters still run on each selected candidate. If the source is not
usable, existing inner_hits can still be used. Unstructured legacy documents
retain the 20-per-document source fallback.

Do not enable simply because hosted synthetic tests pass. Compare the same
question/index/time range on private ES with flag OFF vs ON, verify source IDs,
Event/Timeline date linkage, 500-row and small-row cases, actual report
citations, p50/p95 latency, memory and DOCX accuracy. For very large records,
consider explicitly partitioning data into smaller documents keyed by day,
event and source instead of indefinitely increasing candidate quotas.

No private IP, credentials, unredacted source snippets or user prompts should
be committed to the repository.

The opt-in scanner accepts the historical one-element array text representation
(`text: ["內容"]`) with the same per-snippet and shared-text ceilings; arbitrary
nested or multi-valued text arrays are not accepted by this experimental path.

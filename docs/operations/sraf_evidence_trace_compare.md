# SRAF Report Evidence count-only comparison (#397)

This optional **read-only** operator utility compares the numeric report-stage
`SRAF_REPORT_EVIDENCE_TRACE=` records produced by `SRAF_EVIDENCE_TRACE=1`.
It is useful for comparing the default strong-first selection with the opt-in
`SRAF_REPORT_DIVERSE_EVIDENCE=1` strategy from PR #407. PR #408 adds known
source counts at incoming, picked and actual pre-report-LLM stages.

Each input must be a separate, locally saved text file with **exactly one**
`SRAF_REPORT_EVIDENCE_TRACE=` JSON log record. Do not supply full unredacted
application logs; copy only the individual count-only record into each file.
The tool rejects ambiguous multi-record inputs. Use Python 3.10+:

```bash
python tools/sraf_evidence_trace_compare.py \
  --baseline path/to/default-count-only.txt \
  --candidate path/to/diverse-count-only.txt
```

The output is one `SRAF_EVIDENCE_TRACE_COMPARISON=` line containing allowlisted
counts and after-minus-before deltas. It never outputs source IDs, trace IDs,
local file names, original questions, titles or Evidence text. It does not
contact Elasticsearch, SQL, an LLM, or write any result files. Inputs must be
regular files no larger than 64 KiB; symlinks are rejected where supported.
POSIX FIFO input is opened nonblocking and refused instead of hanging.

**Interpretation:** `PASS_PARTIAL` confirms only that two individually
well-formed count records were compared. It does **not** establish that runs
used the same question, index, time range, corpus, ES state or model; it does
not show that citations were correct or source/issue coverage improved in
quality. `prompt_chars` is **not** token usage. Unknown-ID documents are not
counted in identified-source totals. Full private `news_test`, report LLM,
DOCX, precision/recall and p50/p95 remain separate operator acceptance gates.
No Linux `git fetch`/pull is needed: use the established one-way Windows
Robocopy/7z release transfer for any reviewed tool delivery.

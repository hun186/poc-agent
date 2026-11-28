# SRAF PR #396 — ES date-only IP SAN warning probe (OPEN / SECURITY GATED)

## Scope
Keep production Elasticsearch TLS identity policy unchanged. #396 changes only the narrowly scoped read-only date acceptance sidecar and operator docs/tests to distinguish CA chain validation from IP SAN mismatch and provide a visible operator warning.

## Security gate
A CA-signed certificate with mismatching IP SAN does NOT prove the requested peer's identity. Read-only probes still carry credentials. Warning/PASS_PARTIAL is never production TLS identity or FULL_LIVE. Independent explicit security risk acceptance and authorized real LAN operator verification remain required before any merge or enablement. Never bypass the gate because synthetic CI succeeded.

## Integration history
Earlier active .codex/memory.md, decisions.md, known_issues.md and backlog.md appends repeatedly conflicted with newer PRs. Preserve current-main active .codex docs unmodified, storing this risk/status in a per-PR change log. On a future approved merge, separately sync final status to canonical memory.

## Status
Hosted synthetic tests only; no private news_test TLS query or Linux deployment claimed. No Linux git fetch (Windows-to-Linux one-way 7z operator process).

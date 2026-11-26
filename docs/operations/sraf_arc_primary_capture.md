# ARC A9 operator-only primary sample capture

Default no network. From a private deployed repository with dependencies:

```bash
python -m agent.es.evidence_core.arc_primary_capture --run PRIVATE_SPEC.json PRIVATE_CASES.json
python -m agent.es.evidence_core.arc_relax_annotation_cli PRIVATE_CASES.json PRIVATE_ANNOTATION.json
python -m agent.es.evidence_core.arc_eval_cli relax-replay PRIVATE_ANNOTATION.json
```

Before the last command, label every gold field relevant/uncertain/unrelated.
The source and annotation files contain private text, IDs and question; use
a protected local directory outside Git, CI, logs and shared storage. Never
upload them. No overwrite; POSIX initial file mode 0600, Windows requires
a private directory ACL. A write failure may leave a partial file.

Explicitly configure the dedicated read-only ES principal and trusted CA
with SRAF_ARC_CAPTURE_ES_URL, SRAF_ARC_CAPTURE_ES_USERNAME,
SRAF_ARC_CAPTURE_ES_PASSWORD and SRAF_ARC_CAPTURE_ES_CA_FILE in the local
environment. Do not put credentials in the JSON specification, commands,
Git or shell history. URL must be private numeric HTTPS with explicit port
and no userinfo/path/query/fragment. Strict CA and IP SAN identity is required;
no hostname-disable fallback, proxy, redirects, compression or retries.
The principal must have only the necessary read/search/mapping permissions
on news_test; the command verifies the authenticated username and a single
concrete mapping target, not the principal's full role privileges or mapping
compatibility.

The specification contains exactly question (explicit required subject),
query (operator-written search string), groups (ordered lists of aliases;
first term represents each group), date_from/date_to (ISO day range), size
(1–32). Example synthetic shape:

```json
{"question":"主題：甲軸","query":"甲軸乙軸丙軸","groups":[["甲軸"],["乙軸"],["丙軸"]],"date_from":"2023-08-24","date_to":"2023-08-24","size":8}
```

The command uses the existing canonical main query builder with fixed
default scoring, the explicit date range and operator-supplied terms, not
an LLM-generated rewrite or a recording of an actual production request.
Local query-builder configuration may influence the request. Two preflight
GETs (authentication, mapping) and one read-only POST to the fixed
/news_test/_search endpoint. No writes, fallback, pagination, PIT open or
LLM call. Rejects incomplete shard results, timeouts, duplicate/mismatched
hit identities and empty results. ES timeout 5s; socket timeout 8s per
operation (not a hard overall deadline); maximum response 1 MiB and saved
file 2 MiB. These are small operator samples, not corpus recall. The
separate annotation preparation may reject a captured case that is not
low-volume or has a truncated/ambiguous canonical parsed slice.

Stdout only reports counts, observed search elapsed milliseconds and
request attempts on successful capture. Preflight attempts are separate;
no actual paired full-production latency or token usage is measured here.
Both offline A6 arms replay the same frozen single response. Live private
TLS/mapping/load and human labeling have not been verified by Hosted CI.

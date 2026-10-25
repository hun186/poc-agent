# OFF-1P — Operator-only published DOCX byte integrity vs SQL checkpoint

**Scope:** one existing, already completed Report Job item for one named Schedule. OFF-1P adds real Linux local filesystem byte inspection after OFF-1O's persisted SQL checkpoint. It is NOT a remote Report Job API status check, not evidence that Agent/LLM/Elasticsearch really ran, not proof of an entire successful batch and not full network airgap acceptance.

## Prerequisites and consent

Run on an authorized **Linux deployment host with the real published output root mounted locally**, from the deployed repository root. Use a separately DBA-granted SELECT-only SQL principal under OFF-1G, numeric private IPv4, ODBC18 strict TLS CA + IP SAN. Set the one canonical schedule ID, the real existing output root, and optionally the independently verified Schedule schema:

```bash
export SRAF_OFF1L_SCHEDULE_ID='sch_<32-lowercase-hex-digits>'
export SRAF_OFF1P_ARTIFACT_ROOT='/absolute/path/to/existing/report/output-root'
# Optional for a real non-default Schedule schema:
export SRAF_OFF1I_SQL_SCHEMA='tenant_sched'

python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-identities \
  --probe-schedule-claim --probe-schedule-link \
  --probe-handoff-ack --probe-report-checkpoint --probe-docx-bytes
```

Eight explicit flags and the **actual** upstream SQL-READ / WORKERS / SCHEDULE-CLAIM / SCHEDULE-LINK / HANDOFF-ACK / REPORT-CHECKPOINT PASS results are necessary. By default, no extra SQL or artifact bytes are read. The operator root setting is not read unless all eight flags have been supplied. The root must be an absolute existing non-symlink directory and its normalized path fingerprint must match the SQL persisted output-root fingerprint. The tool makes one additional parameterized, bounded `SELECT TOP(2)` and picks a single previously completed selected item in the latest actor-labelled scheduled batch. It reads only the already recorded relative path, run-item ID, digest and frozen root fingerprint **in memory**, never prints them or persists copies.

## Local hardening and interpretation

The checked relative path is exactly two POSIX segments: publisher-issued safe run-item folder and a `.docx` filename, length-bounded. Root folder, item directory, and file are opened with Linux fd-relative `O_NOFOLLOW`; file is required to be regular, sized 1–16MiB, with stable fstat size and modification/change timestamps during the bounded read. DOCX ZIP validation requires `[Content_Types].xml`, a nonempty `word/document.xml`, no duplicate or traversing entries, no ZIP symlink entries, at most 1000 members, at most 64MiB summed uncompressed size, and successful CRC test. Actual file SHA-256 is computed from read bytes and compared with a SQL-persisted 64-char lowercase digest.

`DOCX-BYTES: PASS` means **the bytes of one existing locally published DOCX at this instant match the database's recorded digest and basic DOCX container structure**. It does NOT prove remote authenticated Report Job GET, any network provenance, report accuracy, a second selected item, or actual physically isolated deployment. `docx_digest_mismatch` and `docx_structure_invalid` are FAIL; missing/unavailable/malformed SQL/root/file/symlinks are conservative SKIP. No path, digest, ID, sensitive SQL-native error, or file content enters the JSON result.

`overall` remains `INCOMPLETE` for clean partial observations, and `feature_acceptance=NOT_TESTED` always. CI mocks ODBC but does real local temporary DOCX byte tests. Real database, deployed published output root, DBA rights, and network isolation must be independently verified. No production schedule/job may be triggered merely to make this diagnostic pass.

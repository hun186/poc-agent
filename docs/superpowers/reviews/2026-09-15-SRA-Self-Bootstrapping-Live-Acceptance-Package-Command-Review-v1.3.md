# SRA Self-Bootstrapping Live-Acceptance Package — Command Review v1.3

## Review control

- Repository: `hun186/poc-agent`
- Hosted branch: `main`
- Hosted baseline supplied and locally matched: `d21ce42c4abd740a50cb7d4d076bb04253cd2dca`
- Hosted refresh attempt: blocked by the environment's HTTP 403 CONNECT proxy; no newer hosted SHA is claimed excluded.
- Previous baseline: `30c5c918ff83a9f4f238383419b0db9886d0b872`
- Reviewed runtime baseline: `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`
- Input/output versions: v1.2 → v1.3
- Scope: documentation and project memory only; runtime code changed: **NO**.

Static command review is not live deployment acceptance. SD-1 through SD-7 were not executed and remain **PENDING**.

## Source evidence and dispositions

### CLR3-001 — BLOCKER — CONFIRMED; FIXED

`run_sra_api.sh` invokes deployment bootstrap and imports generated state before launcher takeover, orphan reclamation, and `inspect_port`. The v1.2 first-run precheck lacked a port observation. v1.3 adds a five-second bounded `lsof` LISTEN query immediately before `./run_sra_api.sh`. Listener absence continues; an existing listener returns `SD_3_PRECHECK=BLOCKED_PORT_IN_USE` without signalling it or invoking bootstrap. Authority failure fails closed.

### CLR3-002 — MAJOR — CONFIRMED; FIXED

`config/deployment_bootstrap.py::_read_state()` rejects symlinks, wrong type/owner/mode, invalid UTF-8, NUL/CR, unknown or duplicate keys, incomplete fields, and wrong state version. The v1.2 dictionary comprehension overwrote duplicates. v1.3 explicitly mirrors those non-secret invariants for the state directory/file and output directory, requires the exact parent, then proves one active canonical public key ID and exact scopes. It never prints the credential.

### CLR3-003 — BLOCKER — CONFIRMED; FIXED

`RequirementHandoffCoordinator.run()` releases its lease in `finally`; `ScheduleStore.acquire_lease()` can also advance generation after expiry. Generation alone was therefore ambiguous. v1.3 captures SQL-authoritative UTC and the old `expires_at`, requires a source-derived 40-second remaining-lifetime margin, and requires the after SQL clock to be strictly before the old expiry while generation increases and owner semantics match. The query remains read-only and never selects the lease token.

The 40-second budget derives from the reviewed defaults: 10-second launcher shutdown, 20-second action observation, five-second OpenAPI timeout, and five-second SQL connection timeout. The lease defaults to 45 seconds and heartbeat to 10 seconds. Changed timing configuration requires a newly reviewed margin and blocks this procedure rather than weakening proof.

### Package/overlay identity clarification

An acceptable manifest must be release-produced, immutable or tamper-evident relative to the package, bound to reviewed runtime source identity, and accompanied by evidence that deployed bytes correspond to it. A host-created file or incidental `.git/HEAD` is insufficient. With no such current manifest, package/overlay SD-1 remains safely BLOCKED.

### Additional findings

No CLR3-004 or later finding was identified in the narrowly reviewed command paths.

## Static validation

The review validation extracts every Bash fence for `bash -n`, extracts and compiles every Python heredoc, audits function bodies and forbidden patterns, exercises an isolated fake-`lsof` occupied-port path, exercises duplicate/wrong-version/wrong-mode state cases, and checks both branches of the temporal predicate. These checks do not start SRA or contact private SQL.

## Live boundary

- SD-1 through SD-7 executed: **NO**
- Private SQL live acceptance: **NO**
- SRA lifecycle changed: **NO**
- Credentials mutated: **NO**
- Golden Path replayed: **NO**
- Agent/ES/LLM/DOCX: **NO**

## Decision

`COMMAND-LEVEL REVIEW v1.3 = PASS`

`SD-1 THROUGH SD-7 LIVE EXECUTION = PENDING`

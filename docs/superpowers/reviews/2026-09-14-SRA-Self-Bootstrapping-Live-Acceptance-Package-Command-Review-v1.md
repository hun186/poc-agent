# SRA Self-Bootstrapping Live Acceptance Package — Command Review v1

## Baseline and scope

- Repository: `hun186/poc-agent`
- Issuance/actual reviewed SHA: `2ef993e34629828128ff5244422c3440a4e305f3`
- Hosted refresh: attempted with `git ls-remote`; failed with HTTP CONNECT 403.
  No newer hosted SHA is claimed.
- Runtime parent: `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`
- Original target: `docs/operations/sra-self-bootstrap-live-acceptance-v1.md`
- Corrected target: same path, content version **v1.1**, which supersedes v1.
- Runtime code changed: **NO**.
- Live gate, private SQL, runtime lifecycle, credential, Golden Path, Agent,
  Elasticsearch, LLM, and DOCX operations executed: **NONE**.

The review compared every operator block with the launcher/bootstrap, Service Key,
SQL registry, coordinator lease/fencing, Handoff/reconciliation, artifact binding,
API OpenAPI, and relevant regression implementations. The corrected commands were
then checked as extracted snippets rather than executed against a deployment.

## Findings

### CLR-001 — BLOCKER — SD-1 — deployment identity was not authoritative

- **Section:** v1 `SD-1 — DEPLOYMENT_SOURCE_GATE`.
- **Source evidence:** v1 bound `edcbc744...`, although the reviewed runbook was
  merged by `2ef993e...`. Repository source contains no generated
  `DEPLOYMENT_COMMIT.txt` contract. The documented deployment can be a Windows
  package plus Linux overlay, for which incidental Linux `.git/HEAD` is not proof
  of package bytes.
- **Why it matters:** the command could false-PASS a stale/mixed deployment or
  false-FAIL the reviewed merge merely because `.git` describes a parent/runtime
  checkout.
- **Exact correction:** v1.1 binds the PR #240 merge, permits the Git command only
  for an intact Git-worktree install, and returns
  `BLOCKED reason=no_authoritative_package_identity` for package/overlay installs
  until a reviewed tamper-evident package/overlay manifest exists.
- **Disposition:** corrected documentation; deployment-release identity remains a
  fail-closed live precondition, not a runtime-source change.

### CLR-002 — BLOCKER — SD-4 — crash/recovery could not safely prove its signal and result

- **Section:** v1 `SD-4` precheck, mutation, and unwrapped recovery commands.
- **Source evidence:** `run_sra_api.sh` itself binds launcher records by type,
  owner, mode, PID/start, effective UID, cwd, resolved script argv, and lock. v1's
  crash script omitted record type/owner/mode and signalled a numeric PID after
  `/proc` validation; its top-level recovery tail branch could end successfully
  after `kill -0` failed.
- **Why it matters:** PID reuse is a wrong-process signal risk, and the recovery
  block could present a non-failing shell status after launcher exit.
- **Exact correction:** v1.1 uses exact record/process validation plus Linux pidfd
  signalling, separates crash from recovery, wraps both in functions, checks
  invocation start time, and requires the complete exact runtime verifier after
  recovery.
- **Disposition:** corrected.

### CLR-003 — MAJOR — SD-5 — PID and HTTP evidence was weaker than source identity

- **Section:** v1 `SD-5` process and OpenAPI checks.
- **Source evidence:** launcher records include start times and role; launcher
  safety code validates cwd, UID, argv, parent-owned records, and LISTEN ownership.
  v1 checked only `/proc/<pid>` existence. It searched raw response bytes for
  `"openapi"` rather than parsing JSON and did not bind the lease owner to the
  recorded Handoff process.
- **Why it matters:** stale records, PID reuse, an unrelated process, or unrelated
  HTTP responder could false-PASS.
- **Exact correction:** v1.1 validates record shape/permissions, PID start time,
  UID, cwd, parent launcher, exact role argv, API LISTEN socket, parsed bounded
  OpenAPI JSON, and the source-derived Handoff owner.
- **Disposition:** corrected.

### CLR-004 — MAJOR — SD-6 — restart assertions contradicted configurable owner semantics

- **Section:** v1 `SD-6` snapshots/action/PASS criteria.
- **Source evidence:** `requirement_scheduler.cli.build_coordinator_from_env()` uses
  `REQUIREMENT_HANDOFF_OWNER_ID` when explicitly configured and otherwise uses
  `handoff-<pid>`. `ScheduleStore.release_lease()` expires the fenced row and the
  next acquisition increments its generation. Therefore owner change is not
  guaranteed under the supported explicit owner override. v1 also reduced child
  verification to PID existence.
- **Why it matters:** a valid graceful takeover could false-FAIL, while PID reuse
  or mismatched workers could false-PASS.
- **Exact correction:** v1.1 adds before/after state/key/identity/lease snapshots,
  applies the exact runtime verifier, always requires increasing live generation,
  and makes owner-change expectation conditional on the configured owner contract.
- **Disposition:** corrected.

### CLR-005 — BLOCKER — SD-7 — cleanup/revocation authorization was incomplete

- **Section:** v1 `SD-7` artifact terminal set and revocation phase.
- **Source evidence:** `_terminal_run_recompute()` recognizes active item states and
  terminal selected-item states; `completed_with_failures` is a Batch state, while
  `not_selected` is not a selected execution terminal. `ServiceKeyStore.revoke()`
  revokes the supplied ID and the CLI does not independently protect the canonical
  runtime key. v1 separated identity proof from mutation without requiring an
  administration freeze or a complete fresh guard immediately before revocation.
- **Why it matters:** artifact cleanup could be approved against the wrong rows,
  and stale evidence/shell variables could authorize revoking a now-canonical or
  otherwise wrong credential.
- **Exact correction:** v1.1 uses the exact selected-item SQL projection and state
  vocabulary, forbids legacy-root deletion/repair, and requires external positive
  legacy-file/key/job identity. Because the generic CLI cannot encode all those
  guards atomically, the package contains no naked revocation command: applicable
  cleanup is BLOCKED pending an instance-bound reviewed addendum with a credential-
  administration freeze, fresh guards, one exact supported-CLI mutation, immediate
  401/store/canonical/runtime verification, and variable cleanup. Missing proof is
  `BLOCKED`, never inferred cleanup.
- **Disposition:** corrected.

### CLR-006 — MINOR — SD-3 — “read-only” overstated Service Key listing behavior

- **Section:** v1 `SD-3` precheck label.
- **Source evidence:** `ServiceKeyStore.list_keys()` takes `exclusive_file_lock`, so
  the supported metadata read can create its lock file even though it does not
  mutate key records.
- **Why it matters:** the state effect is low risk but the operator label was not
  exact.
- **Exact correction:** v1.1 calls it a state-neutral supported-interface check and
  discloses the possible lock-file creation. Existing provisioning maps to
  `NOT_EXECUTABLE_ON_THIS_INSTANCE`, not failure or fabricated first-run evidence.
- **Disposition:** corrected.

## Gate disposition after correction

| Gate | Command-level result | Live status |
| --- | --- | --- |
| SD-1 | PASS, fail-closed for package/overlay without authoritative manifest | PENDING |
| SD-2 | PASS; read-only LF/CR detection | PENDING |
| SD-3 | PASS; existing deployment becomes NOT EXECUTABLE, not failed | PENDING |
| SD-4 | PASS; explicit pidfd-bound crash injection only | PENDING |
| SD-5 | PASS; exact processes/listener/OpenAPI/lease binding | PENDING |
| SD-6 | PASS; source-correct owner/generation semantics | PENDING |
| SD-7 | PASS; generic cleanup fails closed and applicable revocation requires a reviewed instance addendum | PENDING |

## Decision

All BLOCKER, MAJOR, and MINOR command defects found in v1 were corrected in v1.1.
No runtime implementation defect was required to produce a safe fail-closed
procedure. A package/overlay deployment without authoritative release identity
will correctly remain blocked at SD-1; this review does not fabricate that
evidence.

**COMMAND-LEVEL REVIEW = PASS**

**SD-1 through SD-7 live execution remains PENDING.**

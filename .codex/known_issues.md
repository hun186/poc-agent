# Known Issues

## 2026-09-16 Remote Deployment Acceptance configuration unavailable

- The fresh Remote Harness invocation is blocked at `CONFIG_PREFLIGHT` / `configuration_file_missing`: this operator checkout has neither ignored `operator_e2e/e2e.env.local` nor complete process configuration for the actual deployment URL, model, and required superuser user-session credential.
- The harness failed before contacting the deployment, so deployment Git identity, clean source state, worker identities, artifact-root fingerprint, functional flow, artifacts, and cleanup could not be verified. The safe next action is to provision the authorized ignored configuration and rerun Remote mode once; do not substitute a Service Key or ordinary Editor credential.

## 2026-09-15 Requirement harness verification limits

- The private deployment, SQL Server, Elasticsearch, LLM, and launcher-managed workers are unavailable in this repository environment. The new harness was not executed live and no fresh Requirement E2E PASS is claimed; run the documented command on the authorized deployment host.
- The required combined regression set passed 195 tests but one launcher SIGINT cleanup case exceeded its 10-second test timeout. The exact failed case passed in 0.96 seconds on immediate isolated rerun, consistent with existing launcher timing sensitivity rather than the harness/projection change.
- Package-index access remains blocked by the environment proxy (HTTP 403); all declared requirements were already installed, so repository tests could run.

## 2026-09-14 Package/overlay deployment identity gap

- Current repository source does not emit or validate an authoritative deployment
  identity artifact such as `DEPLOYMENT_COMMIT.txt`. For a Windows package plus
  Linux overlay deployment, incidental Linux `.git/HEAD` cannot prove deployed
  bytes. Live SD-1 must remain BLOCKED until the release owner supplies a reviewed,
  tamper-evident package/overlay manifest; intact Git-worktree deployments can use
  the exact commit/worktree gate in acceptance package v1.1.

## Current Summary

- Hosted GitHub refresh/publication may fail when the environment proxy returns HTTP 403; installed Python requirements are currently sufficient, but package-index upgrade checks can emit the same warning.
- Private SRA/Elasticsearch and authorized Requirement SQL Server environments are not available here. Repository fake-transport/DB-API tests are not live deployment acceptance.
- Playwright/browser runtime is unavailable; static DOM/JavaScript and API tests are substitutes for UI work.
- Direct `pytest` may omit the repository root from `sys.path` in this container; `python -m pytest` is the verified invocation.
- Excel-to-SQL can emit `datetime.utcnow` deprecation warnings, and FastAPI/Starlette TestClient can emit compatibility warnings.

## Open Issues

### Live rewritten-title takeover validation pending

- Repository tests model the externally observed `SRA-API | port=9002 | pid=<container-pid> | <container-hostname>` cmdline and fail-closed identity boundary, but cannot prove the deployed Docker instance.
- After merge, run `./run_sra_api.sh` inside the actual SRA container against the existing listener. Confirm the namespace-visible listener receives TERM first, port 9002 is released, API/Schedule/Handoff replacements start, and no unrelated process is signaled. Deployment recognition remains NOT PASS until then.

### Requirement deployment acceptance remains incomplete

- The single-item live Requirement Golden Path and externally reported three-item automatic technical path do not prove fresh/migrated schema acceptance, rollback/failure injection, fencing/failover, concurrency/races, HA, credential rotation, or production content-quality acceptance.
- Live SQL Server catalog/migration/locking checks and private Report Job + Agent + Elasticsearch + DOCX acceptance require authorized operator environments.

### Retrieval exclusion directive is not propagated to the ES Tool

- Report instructions can keep an excluded term out of core-term selection, but downstream synonym expansion lacks a structured exclusion boundary. Current contextual disambiguation is mitigation, not a hard exclusion guarantee.

### Environment limitations

- Browser screenshots/E2E require a browser-capable environment.
- New package downloads and hosted GitHub operations may require a network/proxy-enabled environment.
- Signed URLs remain bearer capabilities until expiry; service-key persistence is single-machine owner-only state; Report Job SQLite/local artifacts are not multi-machine HA.

## Recent Changes

- 2026-09-10: Recorded the required post-merge SRA-container launcher validation; unit tests must not self-award deployment PASS.
- 2026-09-10: The dependency preflight found requirements installed; the pip version-index check retried through the known HTTP 403 proxy limitation without blocking installation verification.

## Archived History

- `.codex/archive/known_issues.md-20260910-070805.md`: complete known-issues history before 2026-09-10 compaction, including prior SQL, deployment, pip, browser, and hosted-refresh evidence.
- Older archive references remain discoverable from that preserved file.

## 2026-09-10 Deployment bootstrap acceptance boundary

- Repository automation verifies provisioning, restart reuse, launcher ordering, identity safety, LF policy, and syntax. Private SQL Server and deployed runtime access are unavailable, so live acceptance Gates SD-1 through SD-7 remain operator work and no Golden Path was replayed.
- `pip --upgrade` retried against the configured package-index proxy and received HTTP 403; required dependencies were already installed and requirements validation completed without adding packages.

## 2026-09-10 Safe restart live acceptance pending

- Repository process regressions verify launcher replacement, fail-closed identity mismatches/timeouts, concurrent contenders, orphan recovery, and Handoff lease-release control flow. The private deployed SQL/runtime environment remains unavailable, so an operator must still confirm real SQL lease release/reacquisition and `/openapi.json` readiness during a live restart; no lease row or production process was modified here.

## 2026-09-14 Hosted baseline refresh limitation (v1.2 review)

- `git ls-remote https://github.com/hun186/poc-agent.git refs/heads/main` was attempted before edits and failed with `CONNECT tunnel failed, response 403`; the repository has no configured Git remote and GitHub CLI has no authentication. The v1.2 static review therefore uses the task-supplied hosted authority `30c5c918ff83a9f4f238383419b0db9886d0b872` and does not claim that a newer hosted SHA was excluded.
- Alternative evidence: the local HEAD exactly matched that supplied hosted merge, and its source/runtime objects were reviewed statically. An authorized network environment must independently refresh hosted `main` before live execution.

## 2026-09-14 Hosted baseline refresh limitation (v1.3 review)

- `git ls-remote https://github.com/hun186/poc-agent.git refs/heads/main` was attempted before edits and failed with `CONNECT tunnel failed, response 403`; no configured remote was available. Local HEAD exactly matched the task-supplied hosted authority `d21ce42c4abd740a50cb7d4d076bb04253cd2dca`, but this environment cannot independently exclude a newer hosted `main` SHA.
- Alternative validation used the matching local source objects and static, non-live command tests. An authorized network environment must refresh hosted `main` before live execution or merge.

## 2026-09-15 Hosted baseline refresh limitation (v1.4 review)

- `git ls-remote https://github.com/hun186/poc-agent.git refs/heads/main` was attempted before edits and failed with `CONNECT tunnel failed, response 403`; the repository has no configured remote. Local HEAD exactly matched the task-supplied hosted authority `548b08a4fb0ee719ed15dba91260db7ce0612201`, but this environment cannot independently exclude a newer hosted `main` SHA.
- Alternative validation used the matching local source objects and static, non-live command tests. An authorized network environment must independently refresh hosted `main` before live execution or merge.

## 2026-09-15 SD-1 manifest implementation and hosted refresh boundary

- The package/overlay identity implementation is now available in repository release tooling, but no manifest-enabled package has been built/deployed and no live SD-1 evidence exists. SD-1 through SD-7 remain PENDING; the current Linux tree must not be retroactively blessed.
- Before edits, `git fetch origin main` could not run because this checkout has no configured `origin`; direct `git ls-remote https://github.com/hun186/poc-agent.git refs/heads/main` failed with `CONNECT tunnel failed, response 403`. Local history contains supplied baseline `ffac2f87ffb20d5314b50e6582ce1a6bfd483523`, but this environment cannot independently exclude a newer hosted `main`. An authorized network environment must refresh and review before merge/live execution.

## 2026-09-15 SD-1 trust-chain v1.1 environment and live status

- Hosted `main` refresh was unavailable because this checkout has no `origin` remote: `fatal: 'origin' does not appear to be a git repository` followed by `fatal: Could not read from remote repository.` Local starting SHA `c133bcbd2866d419a9d89dfa1bf04d0d515179e6` contains supplied baseline `7a54f182d9c1b6d18234d6e8085b163880b26db0`; no newer hosted SHA is claimed.
- Package-index access still returned `Tunnel connection failed: 403 Forbidden` while pip checked for upgrades; required dependencies were already installed.
- SD-1 through SD-7 live gates remain PENDING. No production package verification, SQL access, SRA lifecycle operation, credential mutation, Golden Path replay, or Agent/ES/LLM/DOCX acceptance was performed.
- An extra all-five-files combined pytest invocation produced 11 cascading launcher timeouts after `test_identified_stale_api_gets_term_before_any_kill` missed its 3-second synthetic-worker deadline (106 passed, 11 failed). The contract-required clean standalone deployment regression invocation passed all 67 tests, and the first failed case passed alone after synthetic-process cleanup; treat the combined high-load result as an environment timing warning, not a runtime regression PASS.

## 2026-09-16 Harness v2 verification environment

- `python -m pip install --upgrade pip` retried the configured package-index proxy and received HTTP 403, while the installed pip and all `requirements.txt` dependencies were already satisfied. Focused and broad repository tests therefore ran successfully without fetching packages.
- Live Agent/Elasticsearch/LLM/DOCX acceptance was intentionally not run from this environment; execute either documented mode only in an authorized deployment/operator environment with externally reviewed runtime SHA.

# Known Issues

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

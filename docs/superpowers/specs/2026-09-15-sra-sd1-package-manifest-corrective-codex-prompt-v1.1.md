# Codex Execution Contract — Correct SD-1 Package Manifest Trust Chain v1.1

Implement the approved corrective Design v1.1 and Implementation Plan v1.1 for:

```text
Repository: hun186/poc-agent
Branch target: main
```

## 1. Authoritative Starting Baseline

At prompt issuance, independently verified hosted `main` is:

```text
7a54f182d9c1b6d18234d6e8085b163880b26db0
```

This is the merge commit of PR #245.

Reviewed SRA runtime baseline remains:

```text
edcbc744f71374eaa839b0a31e0cd125fcb6fe52
```

Before modifying anything:

```bash
git rev-parse HEAD
git status --short
git log -1 --oneline
```

Attempt to refresh hosted `main`.

If hosted GitHub refresh is unavailable:

* record the exact error;
* compare local HEAD against the supplied hosted baseline;
* do not invent a newer hosted SHA;
* do not silently substitute stale source.

If local source does not contain the supplied baseline in its history, stop and report:

```text
BASELINE_NOT_AVAILABLE
```

---

# 2. Read Required Context

Read completely before edits:

```text
AGENTS.md
.codex/memory.md
.codex/architecture.md
.codex/api_contract.md
.codex/known_issues.md
.codex/decisions.md
.codex/backlog.md
```

Then read:

```text
docs/superpowers/specs/2026-09-15-sra-sd1-package-manifest-design-v1.md
docs/superpowers/specs/2026-09-15-sra-sd1-package-manifest-design-v1.1.md
docs/superpowers/plans/2026-09-15-sra-sd1-package-manifest-implementation-plan-v1.md
docs/superpowers/plans/2026-09-15-sra-sd1-package-manifest-implementation-plan-v1.1.md
docs/operations/sra-self-bootstrap-live-acceptance-v1.md
```

Design v1.1 supersedes Design v1 where they conflict.

Plan v1.1 supersedes Plan v1 for corrective implementation.

Latest source wins over stale path assumptions.

---

# 3. Why This Corrective Patch Exists

Merged PR #245 implemented the main release-manifest architecture correctly but post-merge review found trust-boundary gaps:

```text
CLR5-001 BLOCKER
source commit can shrink manifest policy scope

CLR5-002 BLOCKER
unverified __pycache__ / .pyc is allowed

CLR5-003 MAJOR
parent-directory symlink traversal is insufficiently constrained

CLR5-004 MAJOR
release-tool implementation lacks a separate reviewed baseline

CLR5-005 MAJOR
runbook provenance predates manifest implementation

CLR5-006 MAJOR
deployed executable semantics are not checked
```

Fix those issues only.

Do not redesign SRA runtime.

---

# 4. Runtime Scope Prohibition

Do NOT modify runtime behavior under:

```text
agent/
api/
batch_scheduler/
config/
data_ingestion/
requirement_scheduler/
shared/
sra_api/
run_sra_api.sh
app.py
requirements.txt
```

Also do not modify:

```text
SQL schema
Service Key semantics
Requirement scheduler behavior
Handoff lease behavior
Report Job behavior
FastAPI behavior
Agent
Elasticsearch
LLM
DOCX
```

If source inspection demonstrates a runtime modification is genuinely necessary, STOP and report:

```text
RUNTIME_BLOCKER_FOUND
```

Do not silently redesign.

---

# 5. Required Trust Model

The corrected release chain has two independent reviewed baselines:

```text
reviewed_runtime_commit
reviewed_manifest_commit
```

The runtime baseline is fixed:

```text
edcbc744f71374eaa839b0a31e0cd125fcb6fe52
```

The manifest implementation baseline is created by this task.

Do not guess its SHA.

After Tasks 1–4 are implemented and tested, create the coherent final manifest-tool implementation commit and run:

```bash
git rev-parse HEAD
```

That real SHA becomes:

```text
REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT
```

Later docs/runbook commits may be newer.

Do not modify manifest tool files after capturing this baseline unless you intentionally create a new implementation commit and update the recorded baseline accordingly.

---

# 6. Policy Authority — Mandatory Fix

Current v1 allows source commit policy to define the comparison scope.

Correct this.

The authoritative policy must come from:

```text
reviewed_manifest_commit
```

The candidate source commit policy must have identical Git blob and mode.

Failure:

```text
manifest_policy_not_reviewed
```

Do not merely compare semantic JSON objects.

Exact source-controlled identity is required.

Canonical v1.1 policy must contain:

```json
"allowed_runtime_extra_globs": []
```

No unmanaged runtime extras.

---

# 7. Ancestry — Mandatory Fix

Authoritative release creation must require:

```text
reviewed_runtime_commit is ancestor of source_commit
reviewed_manifest_commit is ancestor of source_commit
```

Use explicit Git object/history operations.

Failures:

```text
reviewed_runtime_not_ancestor
reviewed_manifest_not_ancestor
```

No unrelated release history may PASS.

---

# 8. Runtime Equivalence

Enumerate runtime scope using the policy from:

```text
reviewed_manifest_commit
```

Compare:

```text
reviewed_runtime_commit
source_commit
```

Require exact:

```text
path set
blob SHA
Git mode
```

Failure:

```text
runtime_source_not_equivalent
```

The source policy must never reduce this comparison.

---

# 9. Release-Tool Equivalence

Using reviewed policy:

```text
release_tool_files
```

compare:

```text
reviewed_manifest_commit
source_commit
```

Require exact:

```text
path set
blob SHA
Git mode
```

Failure:

```text
release_tool_source_not_equivalent
```

This means changing:

```text
tools/deployment_manifest.py
tools/deployment_manifest_policy.json
tools/__init__.py
```

requires a new reviewed manifest implementation baseline.

---

# 10. Builder Self-Identity

The authoritative release ceremony is CLI build.

Before release evidence generation, verify actual running:

```text
tools/deployment_manifest.py
```

equals:

```text
source_commit:tools/deployment_manifest.py
```

byte-for-byte.

Failure:

```text
builder_source_identity
```

Do not claim this defends against total release-host compromise.

It is a source-integrity check inside the trusted release environment.

---

# 11. Correct Build CLI

Require:

```bash
python tools/deployment_manifest.py build \
  --repo-root . \
  --package-root <package-root> \
  --source-commit <source-sha> \
  --reviewed-runtime-commit edcbc744f71374eaa839b0a31e0cd125fcb6fe52 \
  --reviewed-manifest-commit <actual-reviewed-manifest-sha> \
  --receipt-out <external-receipt-path>
```

`--reviewed-manifest-commit` is mandatory.

No default.

---

# 12. Manifest / Receipt Schema

Add required manifest field:

```text
reviewed_manifest_commit
```

Add same to receipt.

Advance:

```text
builder_version = 2
```

Keep deterministic canonical manifest encoding.

Manifest still contains no timestamp.

---

# 13. Prohibit `__pycache__`

Delete the v1 behavior that permits:

```text
**/__pycache__/**
```

Correct policy:

```json
"allowed_runtime_extra_globs": []
```

Build and verify must reject:

```text
__pycache__
.pyc
or any other undeclared managed-root file
```

with:

```text
unexpected_managed_file
```

Do not delete these files automatically.

---

# 14. Root-Anchored No-Symlink Access

Do not validate only the final path component.

Implement a component-by-component no-follow walk anchored at the package/deployment root.

Preferred Linux pattern:

```python
os.open(..., dir_fd=..., O_DIRECTORY | O_NOFOLLOW)
```

for each parent directory, then:

```python
os.open(..., dir_fd=..., O_RDONLY | O_NOFOLLOW)
```

for final file.

Validate `fstat`.

Reject parent symlink traversal.

Do not use `.resolve()` as the security authority for managed file reads.

---

# 15. Executable Mode Semantics

Manifest `git_mode` must affect deployed verification.

Rules:

```text
100755 => deployed file has executable bit
100644 => deployed file has no executable bit
```

Failure:

```text
managed_file_mode_mismatch
```

Do not require exact 0755/0644 permission values.

---

# 16. Strict TDD

Follow Plan v1.1 task order.

For every fix:

```text
write RED test
run and confirm failure
implement minimal correction
run and confirm GREEN
commit coherent task
```

Mandatory RED cases include:

```text
policy shrink + runtime change
policy formatting change
runtime ancestry failure
manifest ancestry failure
release-tool drift
pycache extra
parent symlink
nested parent symlink
100755 without x bit
100644 with x bit
modified running builder
```

Do not write implementation first and backfill tests.

---

# 17. Required Implementation Commit Boundary

After Tasks 1–4 are complete and focused tests pass, commit the final tool implementation.

Then execute:

```bash
git rev-parse HEAD
```

Call that exact SHA:

```text
REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT
```

From that point forward, do not change:

```text
tools/__init__.py
tools/deployment_manifest.py
tools/deployment_manifest_policy.json
tests/test_deployment_manifest.py
```

while preparing runbook/project docs.

If they must change, create a new implementation commit and recapture the SHA.

---

# 18. Runbook v1.6

Update:

```text
docs/operations/sra-self-bootstrap-live-acceptance-v1.md
```

to content version:

```text
v1.6
```

Supersedes:

```text
v1.5
```

Record exactly:

```text
Corrective implementation baseline:
7a54f182d9c1b6d18234d6e8085b163880b26db0

Reviewed runtime baseline:
edcbc744f71374eaa839b0a31e0cd125fcb6fe52

Reviewed manifest implementation commit:
<actual SHA captured after Task 4>
```

The final runbook file must contain the real SHA.

Do not leave `<actual SHA>` placeholder text.

Runbook status must be:

```text
SOURCE IMPLEMENTED; POST-MERGE REVIEW REQUIRED;
SD-1 THROUGH SD-7 PENDING
```

It must not self-award review PASS.

---

# 19. Existing Worktree Mode

Retain worktree mode.

It may exclude exactly:

```text
docs/**
.codex/**
tools/**
```

from runtime equality.

Do not broaden those exclusions.

Do not change runtime baseline.

---

# 20. Required Tests

Run at minimum:

```bash
python -m pytest \
  tests/test_deployment_manifest.py \
  tests/test_sd1_deployment_manifest_runbook.py \
  -v
```

Then:

```bash
python -m pytest \
  tests/test_deployment_bootstrap.py \
  tests/test_run_sra_api_launcher.py \
  tests/test_requirement_handoff_coordinator.py \
  -v
```

Then:

```bash
python -m py_compile tools/deployment_manifest.py
bash -n run_sra_api.sh
git diff --check
```

Do not convert warnings or unavailable external services into PASS claims.

---

# 21. No Live Acceptance

Do not execute the corrected manifest against the current Linux production tree.

Do not:

```text
build a retroactive manifest from current production bytes
run live SD-1
run SD-2
start/stop/restart SRA
connect private SQL for acceptance
rotate credentials
run Agent
run Elasticsearch acceptance
invoke LLM
generate DOCX for acceptance
replay Golden Path
clean production caches
delete production files
git reset/pull/clean deployed Linux
```

Synthetic temporary test trees are allowed.

---

# 22. Project Record Updates

Update:

```text
.codex/architecture.md
.codex/decisions.md
.codex/known_issues.md
.codex/memory.md
```

Record:

```text
dual reviewed baselines
immutable reviewed policy
no unmanaged runtime extras
root-anchored no-symlink verification
executable mode verification
actual reviewed manifest implementation commit
live SD gates still pending
```

Never record secrets.

---

# 23. Git / PR Contract

Use a feature branch.

Suggested branch:

```text
fix/sd1-manifest-trust-chain-v1.1
```

Suggested PR title:

```text
fix(deployment): close SD-1 manifest trust-boundary gaps
```

Create PR against:

```text
main
```

You may create the PR.

**DO NOT MERGE.**

Do not enable auto-merge.

If an external system merges it despite this contract, report that fact explicitly.

---

# 24. Completion Report

Report:

## Baseline

```text
Repository
Actual hosted baseline used
Local starting SHA
Reviewed runtime baseline
Design v1.1 path
Plan v1.1 path
```

## Corrective implementation

```text
Changed files
CLR5-001 disposition
CLR5-002 disposition
CLR5-003 disposition
CLR5-004 disposition
CLR5-005 disposition
CLR5-006 disposition
Runtime behavior changed: YES/NO
Design deviations
```

## Critical SHA

Report exact:

```text
REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT=<sha>
```

and prove current HEAD has not changed the release-tool implementation since that SHA.

## TDD evidence

For every task:

```text
RED command/result
GREEN command/result
```

## Final verification

Exact commands, exit results, test counts.

## Live boundary

Exactly:

```text
SD-1 live execution: NO
SD-2 through SD-7 live execution: NO
Private SQL live acceptance: NO
SRA lifecycle changed: NO
Credential mutation: NO
Golden Path replayed: NO
Agent/ES/LLM/DOCX: NO
```

## Git / PR

```text
Branch
Resulting HEAD
PR number
PR URL
Hosted PR head SHA
Merge status
```

Do not invent unavailable values.

## Final state

Exactly one:

```text
IMPLEMENTATION HANDOFF = READY_FOR_REVIEW
```

or:

```text
IMPLEMENTATION HANDOFF = NOT_READY
```

or:

```text
RUNTIME_BLOCKER_FOUND
```

`READY_FOR_REVIEW` does not mean live SD-1 PASS.

After PR creation, stop.

# SRA SD-1 Package Manifest Corrective Implementation Plan v1.1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the merged SD-1 manifest subsystem so release policy, release tooling, executable bytes, and filesystem traversal are all bound to independently reviewed authority.

**Architecture:** Keep the existing deterministic manifest + external SHA-256 model, but add a second reviewed baseline for manifest tooling, freeze the policy to that baseline, prohibit unmanaged runtime extras, perform root-anchored no-symlink reads, and verify deployed executable semantics. SRA runtime remains untouched.

**Tech Stack:** Python 3 standard library, Git CLI on release builder, pytest, Bash/Markdown runbook.

**Spec:** `docs/superpowers/specs/2026-09-15-sra-sd1-package-manifest-design-v1.1.md`

## Global Constraints

* Repository: `hun186/poc-agent`.
* Authoritative implementation starting baseline: `7a54f182d9c1b6d18234d6e8085b163880b26db0`.
* Reviewed runtime baseline: `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`.
* Supersedes Design/Plan v1.
* No SRA runtime behavior changes.
* Do not modify production SQL.
* Do not mutate Service Keys.
* Do not execute live SD-1 through SD-7.
* Do not replay Golden Path.
* No new third-party dependency.
* Strict TDD.
* Create PR; do not merge.

---

## File Structure

Modify:

```text
tools/deployment_manifest.py
tools/deployment_manifest_policy.json
tests/test_deployment_manifest.py
tests/test_sd1_deployment_manifest_runbook.py
docs/operations/sra-self-bootstrap-live-acceptance-v1.md
.codex/architecture.md
.codex/decisions.md
.codex/known_issues.md
.codex/memory.md
```

Add:

```text
docs/superpowers/specs/2026-09-15-sra-sd1-package-manifest-design-v1.1.md
docs/superpowers/plans/2026-09-15-sra-sd1-package-manifest-implementation-plan-v1.1.md
```

Do not modify:

```text
run_sra_api.sh
config/deployment_bootstrap.py
requirement_scheduler/
sra_api/
agent/
api/
data_ingestion/
batch_scheduler/
shared/
```

If implementation requires such a change, stop and report `RUNTIME_BLOCKER_FOUND`.

---

# Task 1 — Freeze Policy Authority and Remove Runtime Extras

**Files**

* Modify: `tools/deployment_manifest_policy.json`
* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Interfaces**

Produces:

```python
def require_exact_policy_identity(
    repo_root: Path,
    source_commit: str,
    reviewed_manifest_commit: str,
) -> tuple[dict[str, Any], bytes]:
    ...
```

The returned policy is the reviewed manifest policy.

* [ ] **Step 1: Write policy-authority RED tests**

Add a temporary Git repo test where base commit contains:

```json
"managed_roots": ["agent"]
```

and later source commit changes policy to:

```json
"managed_roots": []
```

while changing:

```text
agent/runtime.py
```

Test must require:

```python
with pytest.raises(ManifestError, match="manifest_policy_not_reviewed"):
    ...
```

Also test formatting-only source policy mutation.

* [ ] **Step 2: Write cache RED tests**

Change canonical test policy:

```json
"allowed_runtime_extra_globs": []
```

Add:

```python
def test_build_rejects_pycache_extra(...):
    cache = package / "agent/__pycache__/runtime.cpython-313.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"bytecode")
    with pytest.raises(ManifestError, match="unexpected_managed_file"):
        ...
```

Add equivalent deployed verify test.

* [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "policy_not_reviewed or pycache" -v
```

Expected: FAIL.

* [ ] **Step 4: Implement exact policy authority**

Read exact policy bytes from:

```text
reviewed_manifest_commit
source_commit
```

Require identical Git blob and Git mode.

Do not semantically normalize source policy before authority comparison.

Failure:

```text
manifest_policy_not_reviewed
```

Parse and return the reviewed policy.

* [ ] **Step 5: Remove allowed-extra behavior**

Canonical policy:

```json
"allowed_runtime_extra_globs": []
```

Replace `_allowed_extra()` behavior so v1.1 never permits unmanaged runtime files.

The policy validator must require:

```python
value["allowed_runtime_extra_globs"] == []
```

* [ ] **Step 6: Run GREEN**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "policy or pycache or unexpected" -v
```

Expected: PASS.

* [ ] **Step 7: Commit**

```bash
git add tools/deployment_manifest.py \
  tools/deployment_manifest_policy.json \
  tests/test_deployment_manifest.py
git commit -m "fix(deployment): freeze manifest policy authority"
```

---

# Task 2 — Add Dual Reviewed Commit Authority

**Files**

* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Interfaces**

Produce:

```python
def require_ancestor(
    repo_root: Path,
    ancestor: str,
    descendant: str,
    *,
    reason: str,
) -> None:
    ...

def require_release_tool_equivalence(
    reviewed: dict[str, GitFile],
    source: dict[str, GitFile],
) -> None:
    ...
```

Extend:

```python
def build_manifest(
    *,
    repo_root: Path,
    package_root: Path,
    source_commit: str,
    reviewed_runtime_commit: str,
    reviewed_manifest_commit: str,
    receipt_out: Path,
) -> tuple[Path, Path, str]:
    ...
```

* [ ] **Step 1: Write ancestry RED tests**

Create unrelated Git histories and assert:

```text
reviewed_runtime_not_ancestor
reviewed_manifest_not_ancestor
```

are distinct failures.

* [ ] **Step 2: Write release-tool drift RED test**

Base reviewed manifest commit contains:

```text
tools/deployment_manifest.py = TOOL=1
```

Later source commit changes it to:

```text
TOOL=2
```

while runtime remains unchanged.

Require:

```text
release_tool_source_not_equivalent
```

* [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "ancestor or release_tool_source" -v
```

Expected: FAIL.

* [ ] **Step 4: Implement ancestry check**

Use:

```bash
git merge-base --is-ancestor <ancestor> <descendant>
```

through the existing bounded Git helper.

Do not use working-tree ancestry.

* [ ] **Step 5: Implement release-tool equivalence**

Enumerate release tools using the reviewed policy for:

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

* [ ] **Step 6: Update manifest and receipt schema**

Add mandatory:

```json
"reviewed_manifest_commit": "<40 hex>"
```

Receipt:

```json
"builder_version": 2
```

and:

```json
"reviewed_manifest_commit": "<40 hex>"
```

Update parser and canonical-schema tests.

* [ ] **Step 7: Run GREEN**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "ancestor or release_tool or reviewed_manifest" -v
```

Expected: PASS.

* [ ] **Step 8: Commit**

```bash
git add tools/deployment_manifest.py tests/test_deployment_manifest.py
git commit -m "fix(deployment): bind releases to reviewed manifest tooling"
```

---

# Task 3 — Bind the Running Release Builder to Source Git Bytes

**Files**

* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Interfaces**

Produce:

```python
def require_running_builder_identity(
    repo_root: Path,
    source_commit: str,
    running_tool_path: Path,
) -> None:
    ...
```

The authoritative CLI passes:

```python
Path(__file__).resolve()
```

* [ ] **Step 1: Write RED test for modified builder**

Create a temporary repo where:

```text
source commit tool bytes = A
running tool bytes       = B
```

Assert:

```text
builder_source_identity
```

* [ ] **Step 2: Write positive test**

Exact running bytes equal source Git blob.

Expected PASS.

* [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k builder_source_identity -v
```

Expected: FAIL.

* [ ] **Step 4: Implement builder identity check**

Read expected Git blob from:

```text
source_commit:tools/deployment_manifest.py
```

Read actual running builder bytes from supplied path.

Require exact byte equality.

* [ ] **Step 5: Wire only authoritative CLI build**

Before `build_manifest()` in CLI build path:

```python
require_running_builder_identity(
    args.repo_root,
    resolved_source_commit,
    Path(__file__).resolve(),
)
```

Ensure the source commit is resolved once and passed consistently.

Library-level helpers remain test primitives; documentation must state only CLI build is an authoritative release ceremony.

* [ ] **Step 6: Run GREEN**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k builder -v
```

Expected: PASS.

* [ ] **Step 7: Commit**

```bash
git add tools/deployment_manifest.py tests/test_deployment_manifest.py
git commit -m "fix(deployment): bind release builder to source commit"
```

---

# Task 4 — Reject Parent Symlinks and Verify Executable Semantics

**Files**

* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Interfaces**

Produce:

```python
def read_regular_beneath_root(
    root: Path,
    relative_path: str,
    *,
    reason: str,
) -> tuple[bytes, os.stat_result]:
    ...

def require_mode_semantics(
    git_mode: str,
    stat_mode: int,
) -> None:
    ...
```

* [ ] **Step 1: Write parent-symlink RED tests**

Build package:

```text
package/
  agent -> outside/agent
```

with real expected file in outside directory.

Require FAIL.

Add nested parent symlink test.

* [ ] **Step 2: Write mode RED tests**

Cases:

```text
Git 100755 + deployed no executable bits => FAIL
Git 100644 + deployed executable bit     => FAIL
```

Expected reason:

```text
managed_file_mode_mismatch
```

* [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "parent_symlink or mode_mismatch" -v
```

Expected: FAIL.

* [ ] **Step 4: Implement root-anchored component walk**

Use directory file descriptors.

For each parent:

```python
os.open(
    component,
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    dir_fd=current_fd,
)
```

Open final file:

```python
os.open(
    final_component,
    os.O_RDONLY | os.O_NOFOLLOW,
    dir_fd=current_fd,
)
```

Validate with `fstat`.

Close all descriptors deterministically.

Where `O_NOFOLLOW` is unavailable, fail closed rather than silently follow symlinks in authoritative Linux verification.

* [ ] **Step 5: Implement executable semantics**

```python
is_executable = bool(stat_mode & 0o111)

if git_mode == "100755" and not is_executable:
    raise ManifestError("managed_file_mode_mismatch")

if git_mode == "100644" and is_executable:
    raise ManifestError("managed_file_mode_mismatch")
```

Apply to staged-package validation and deployed verification.

* [ ] **Step 6: Run GREEN**

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "symlink or mode" -v
```

Expected: PASS.

* [ ] **Step 7: Full focused suite**

```bash
python -m pytest tests/test_deployment_manifest.py -v
```

Expected: PASS.

* [ ] **Step 8: Commit the final manifest-tool implementation**

```bash
git add tools/deployment_manifest.py \
  tools/deployment_manifest_policy.json \
  tests/test_deployment_manifest.py
git commit -m "fix(deployment): harden deployed path and mode verification"
```

* [ ] **Step 9: Capture the real reviewed-manifest implementation SHA**

Immediately run:

```bash
git rev-parse HEAD
```

Record that exact 40-character SHA as:

```text
REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT
```

Do not invent it.

From this point onward, Tasks 5–7 must not modify:

```text
tools/**
tests/test_deployment_manifest.py
```

unless review discovers a blocker. If they are modified, a new implementation commit must be created and the recorded reviewed manifest SHA must move to that new real commit.

---

# Task 5 — Update Runbook to v1.6

**Files**

* Modify: `docs/operations/sra-self-bootstrap-live-acceptance-v1.md`
* Modify: `tests/test_sd1_deployment_manifest_runbook.py`

**Interfaces**

Runbook must contain the concrete SHA captured in Task 4.

* [ ] **Step 1: Write RED static tests**

Assert:

```text
Package v1.6
Supersedes v1.5
Corrective implementation baseline = 7a54f182...
Reviewed runtime baseline = edcbc744...
Reviewed manifest implementation commit = exact Task 4 SHA
```

Assert package mode does not contain:

```text
git rev-parse
git merge-base
git status
.git/HEAD
```

Assert no `__pycache__` allowance appears in the package-manifest contract.

* [ ] **Step 2: Add precheck schema expectations**

Runbook precheck must require manifest entry:

```text
reviewed_manifest_commit
```

and the verifier must print:

```text
SD_1_REVIEWED_MANIFEST_COMMIT=<sha>
```

* [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_sd1_deployment_manifest_runbook.py -v
```

Expected: FAIL against v1.5.

* [ ] **Step 4: Update to v1.6**

Document:

```text
Corrective implementation baseline:
7a54f182d9c1b6d18234d6e8085b163880b26db0

Reviewed manifest implementation commit:
<exact SHA captured in Task 4>

Reviewed runtime baseline:
edcbc744f71374eaa839b0a31e0cd125fcb6fe52
```

The actual file must contain the real SHA, not angle-bracket placeholder text.

Status:

```text
SOURCE IMPLEMENTED; POST-MERGE REVIEW REQUIRED;
SD-1 THROUGH SD-7 PENDING
```

* [ ] **Step 5: Update release-build example**

Require:

```bash
--reviewed-manifest-commit "$REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT"
```

* [ ] **Step 6: Keep one-gate rule**

Do not invoke SD-2 from SD-1.

Do not introduce cleanup.

* [ ] **Step 7: Run GREEN**

```bash
python -m pytest tests/test_sd1_deployment_manifest_runbook.py -v
```

Expected: PASS.

* [ ] **Step 8: Commit**

```bash
git add docs/operations/sra-self-bootstrap-live-acceptance-v1.md \
  tests/test_sd1_deployment_manifest_runbook.py
git commit -m "docs(deployment): harden SD-1 acceptance package v1.6"
```

---

# Task 6 — Corrective Regression Verification

**Files**

* Test only unless defect discovered.

* [ ] **Step 1: Run manifest + runbook suite**

```bash
python -m pytest \
  tests/test_deployment_manifest.py \
  tests/test_sd1_deployment_manifest_runbook.py \
  -v
```

Require zero failures.

* [ ] **Step 2: Run deployment runtime regression suite**

```bash
python -m pytest \
  tests/test_deployment_bootstrap.py \
  tests/test_run_sra_api_launcher.py \
  tests/test_requirement_handoff_coordinator.py \
  -v
```

Require zero failures aside from already documented warnings.

* [ ] **Step 3: Compile/syntax**

```bash
python -m py_compile tools/deployment_manifest.py
bash -n run_sra_api.sh
```

* [ ] **Step 4: Diff checks**

```bash
git diff --check
git status --short
```

* [ ] **Step 5: Runtime scope audit**

Compare to baseline:

```bash
git diff --name-only \
  7a54f182d9c1b6d18234d6e8085b163880b26db0...HEAD
```

No file under these runtime namespaces may be changed:

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

If any appear unexpectedly:

```text
RUNTIME_BLOCKER_FOUND
```

---

# Task 7 — Synthetic Security Regression Cases

**Files**

* Tests only.

* [ ] **Step 1: Execute exact-source positive package flow**

Build from a temporary Git repository with:

```text
reviewed runtime ancestor
reviewed manifest ancestor
source descendant
identical runtime/tool bytes
```

Expected:

```text
RELEASE_MANIFEST=PASS
```

and deployed verify:

```text
SD_1=PASS identity_mode=release_manifest
```

* [ ] **Step 2: Execute policy-shrink negative case**

Candidate source:

```text
removes managed root
changes a file in removed root
```

Expected:

```text
FAIL manifest_policy_not_reviewed
```

* [ ] **Step 3: Execute release-tool drift case**

Expected:

```text
FAIL release_tool_source_not_equivalent
```

* [ ] **Step 4: Execute cache case**

Add:

```text
agent/__pycache__/x.pyc
```

Expected:

```text
FAIL unexpected_managed_file
```

* [ ] **Step 5: Execute parent-symlink case**

Expected FAIL.

* [ ] **Step 6: Execute mode case**

Expected:

```text
FAIL managed_file_mode_mismatch
```

---

# Task 8 — Project Records

**Files**

* Modify: `.codex/architecture.md`

* Modify: `.codex/decisions.md`

* Modify: `.codex/known_issues.md`

* Modify: `.codex/memory.md`

* [ ] **Step 1: Record dual-baseline architecture**

```text
reviewed runtime commit
          │
          ├── runtime authority
          │
reviewed manifest commit
          │
          ├── policy + release-tool authority
          │
source release commit
          ↓
staged package
          ↓
external manifest digest
          ↓
Linux SD-1
```

* [ ] **Step 2: Record cache decision**

`__pycache__` is prohibited during SD-1 because it contains executable bytecode potential.

* [ ] **Step 3: Record symlink decision**

All managed path components are no-follow.

* [ ] **Step 4: Record live status**

Keep:

```text
SD-1 through SD-7 = PENDING
```

* [ ] **Step 5: Commit**

```bash
git add .codex/architecture.md .codex/decisions.md \
  .codex/known_issues.md .codex/memory.md
git commit -m "docs(project): record corrected SD-1 trust chain"
```

---

# Task 9 — PR Handoff

* [ ] **Step 1: Final verification**

Re-run:

```bash
python -m pytest \
  tests/test_deployment_manifest.py \
  tests/test_sd1_deployment_manifest_runbook.py \
  tests/test_deployment_bootstrap.py \
  tests/test_run_sra_api_launcher.py \
  tests/test_requirement_handoff_coordinator.py \
  -v
```

* [ ] **Step 2: Verify reviewed manifest commit still applies**

Read the SHA captured in Task 4.

Compare release tool files between it and current HEAD:

```bash
git diff --quiet \
  "$REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT" HEAD -- \
  tools/deployment_manifest.py \
  tools/deployment_manifest_policy.json \
  tools/__init__.py \
  tests/test_deployment_manifest.py
```

Require exit 0.

If not:

```text
REVIEWED_MANIFEST_BASELINE_STALE
```

and create a new real implementation commit before handoff.

* [ ] **Step 3: Create PR**

Suggested title:

```text
fix(deployment): close SD-1 manifest trust-boundary gaps
```

Base:

```text
main
```

Do NOT merge.

Do NOT enable auto-merge.

* [ ] **Step 4: Completion report**

Report exact:

```text
repository
actual hosted baseline
branch
resulting HEAD
reviewed runtime commit
reviewed manifest implementation commit
changed files
tests and counts
design deviations
PR number
PR URL
hosted PR head SHA
merge status
```

Live boundary:

```text
SD-1 live execution: NO
SD-2 through SD-7 live execution: NO
Private SQL: NO
SRA lifecycle mutation: NO
Credential mutation: NO
Golden Path replay: NO
Agent/ES/LLM/DOCX: NO
```

Final status:

```text
IMPLEMENTATION HANDOFF = READY_FOR_REVIEW
```

or:

```text
IMPLEMENTATION HANDOFF = NOT_READY
```

Never report live SD-1 PASS.

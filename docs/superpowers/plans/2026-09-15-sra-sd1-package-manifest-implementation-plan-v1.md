# SRA SD-1 Package Manifest Implementation Plan v1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a Git-anchored, externally attested package/overlay deployment manifest so SD-1 can prove deployed runtime bytes without trusting the Linux host's historical `.git`.

**Architecture:** A standalone standard-library Python tool builds and verifies deterministic deployment manifests. Release creation binds staged package bytes to Git objects and proves runtime-managed paths are unchanged from the reviewed runtime baseline; Linux verification requires an independently retained manifest SHA-256 and never uses local Git metadata as package identity.

**Tech Stack:** Python 3 standard library, Git CLI on release builder only, pytest, Markdown runbook.

**Spec:** `docs/superpowers/specs/2026-09-15-sra-sd1-package-manifest-design-v1.md`

## Global Constraints

* Repository: `hun186/poc-agent`.
* Hosted baseline at plan issuance: `ffac2f87ffb20d5314b50e6582ce1a6bfd483523`.
* Reviewed SRA runtime baseline: `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`.
* No SRA runtime behavior change.
* No change to `run_sra_api.sh` or `config/deployment_bootstrap.py`.
* No private SQL.
* No SRA lifecycle mutation.
* No credential mutation.
* No Golden Path replay.
* No new third-party dependency.
* Package-mode verification must not trust local `.git`.
* `PASS` requires externally supplied manifest SHA-256.
* `FAIL` or `BLOCKED` must stop before SD-2.
* Strict TDD is mandatory.

---

## Planned File Structure

Create:

```text
tools/__init__.py
tools/deployment_manifest.py
tools/deployment_manifest_policy.json
tests/test_deployment_manifest.py
tests/test_sd1_deployment_manifest_runbook.py
docs/superpowers/specs/2026-09-15-sra-sd1-package-manifest-design-v1.md
docs/superpowers/plans/2026-09-15-sra-sd1-package-manifest-implementation-plan-v1.md
```

Modify:

```text
docs/operations/sra-self-bootstrap-live-acceptance-v1.md
.codex/memory.md
.codex/architecture.md
.codex/known_issues.md
.codex/decisions.md
```

Do not modify runtime behavior files unless source inspection proves a blocker; if so, stop.

---

# Task 1 — Add Reviewed Deployment Manifest Policy

**Files:**

* Create: `tools/__init__.py`
* Create: `tools/deployment_manifest_policy.json`
* Create: `tests/test_deployment_manifest.py`

**Produces:**

* source-controlled runtime/release-tool scope;
* reusable policy loader contract.

### Step 1 — Write failing policy tests

Add tests equivalent to:

```python
def test_policy_declares_expected_runtime_and_release_tool_scope():
    policy = load_policy(POLICY_PATH)

    assert policy["schema_version"] == 1
    assert policy["repository"] == "hun186/poc-agent"
    assert "agent" in policy["managed_roots"]
    assert "sra_api" in policy["managed_roots"]
    assert "requirement_scheduler" in policy["managed_roots"]
    assert "run_sra_api.sh" in policy["managed_files"]
    assert "tools/deployment_manifest.py" in policy["release_tool_files"]


def test_policy_has_no_overlap_or_unsafe_paths():
    policy = load_policy(POLICY_PATH)
    all_paths = (
        policy["managed_roots"]
        + policy["managed_files"]
        + policy["release_tool_files"]
    )
    assert all(not item.startswith("/") for item in all_paths)
    assert all(".." not in item.split("/") for item in all_paths)
    assert len(all_paths) == len(set(all_paths))
```

### Step 2 — Run RED

```bash
python -m pytest tests/test_deployment_manifest.py -k policy -v
```

Expected: FAIL because policy/tool loader does not exist.

### Step 3 — Add policy

Create `tools/deployment_manifest_policy.json` with the exact Design v1 policy.

Create an empty:

```python
"""Release/deployment tooling package."""
```

in `tools/__init__.py`.

### Step 4 — Add minimal loader

Begin `tools/deployment_manifest.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ManifestError(RuntimeError):
    pass


def load_policy(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("policy_invalid_json") from exc

    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ManifestError("policy_schema")

    return value
```

### Step 5 — Run GREEN

```bash
python -m pytest tests/test_deployment_manifest.py -k policy -v
```

Expected: PASS.

### Step 6 — Commit

```bash
git add tools/__init__.py tools/deployment_manifest.py \
  tools/deployment_manifest_policy.json tests/test_deployment_manifest.py
git commit -m "feat(deployment): define release manifest policy"
```

---

# Task 2 — Canonical Path, Manifest, and Digest Primitives

**Files:**

* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Produces:**

* canonical path validation;
* canonical JSON;
* deterministic aggregate hash.

### Step 1 — Write RED tests

Add:

```python
def test_normalize_manifest_path_rejects_traversal_and_absolute():
    for value in ("../x.py", "a/../x.py", "/tmp/x.py", ""):
        with pytest.raises(ManifestError):
            normalize_manifest_path(value)


def test_manifest_bytes_are_deterministic():
    a = canonical_json_bytes({"b": 2, "a": 1})
    b = canonical_json_bytes({"a": 1, "b": 2})
    assert a == b
    assert a.endswith(b"\n")


def test_files_root_is_order_independent():
    entries = [
        {
            "class": "runtime",
            "path": "b.py",
            "git_mode": "100644",
            "size": 1,
            "sha256": "b" * 64,
        },
        {
            "class": "runtime",
            "path": "a.py",
            "git_mode": "100644",
            "size": 1,
            "sha256": "a" * 64,
        },
    ]
    assert compute_files_root(entries) == compute_files_root(list(reversed(entries)))


def test_casefold_collisions_fail():
    with pytest.raises(ManifestError, match="path_case_collision"):
        validate_unique_paths(["agent/X.py", "agent/x.py"])
```

### Step 2 — Run RED

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "normalize or deterministic or files_root or casefold" -v
```

Expected: FAIL.

### Step 3 — Implement primitives

Implement exact functions:

```python
def normalize_manifest_path(value: str) -> str:
    ...

def canonical_json_bytes(value: object) -> bytes:
    ...

def sha256_bytes(data: bytes) -> str:
    ...

def validate_unique_paths(paths: list[str]) -> None:
    ...

def compute_files_root(entries: list[dict[str, object]]) -> str:
    ...
```

Requirements:

* POSIX `/` separators;
* relative path only;
* no empty path component;
* no `.` or `..`;
* duplicate rejection;
* case-fold collision rejection;
* lower-case SHA-256;
* deterministic sorting.

### Step 4 — Run GREEN

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "normalize or deterministic or files_root or casefold" -v
```

Expected: PASS.

### Step 5 — Commit

```bash
git add tools/deployment_manifest.py tests/test_deployment_manifest.py
git commit -m "feat(deployment): add canonical manifest primitives"
```

---

# Task 3 — Git Source Map and Runtime-Equivalence Proof

**Files:**

* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Produces:**

* exact Git blob map;
* runtime equivalence check.

### Step 1 — Add temporary-repository test helper

Use a real temporary Git repository, not mocks:

```python
def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
    ).strip()
```

Initialize test repos with:

```python
git(repo, "init")
git(repo, "config", "user.email", "test@example.invalid")
git(repo, "config", "user.name", "Deployment Manifest Test")
```

### Step 2 — Write RED tests

Required cases:

```python
def test_runtime_equivalence_accepts_release_tool_only_change(tmp_path):
    # Commit A contains runtime files.
    # Commit B changes only tools/deployment_manifest.py.
    # Comparison across runtime policy must pass.
    ...


def test_runtime_equivalence_rejects_runtime_blob_change(tmp_path):
    # Commit B changes agent/agent.py.
    # Comparison must raise runtime_source_not_equivalent.
    ...


def test_runtime_equivalence_rejects_runtime_path_addition(tmp_path):
    # Commit B adds sra_api/new_runtime.py.
    # Comparison must fail.
    ...


def test_runtime_equivalence_rejects_mode_change(tmp_path):
    # Change a managed Git mode 100644 -> 100755.
    # Comparison must fail.
    ...
```

### Step 3 — Run RED

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k runtime_equivalence -v
```

Expected: FAIL.

### Step 4 — Implement Git inspection

Implement:

```python
@dataclass(frozen=True)
class GitFile:
    path: str
    mode: str
    blob_sha: str
    data: bytes


def resolve_commit(repo_root: Path, ref: str) -> str:
    ...

def source_tree_sha(repo_root: Path, commit: str) -> str:
    ...

def read_policy_from_commit(
    repo_root: Path,
    commit: str,
    policy_path: str,
) -> dict[str, object]:
    ...

def git_file_map(
    repo_root: Path,
    commit: str,
    policy: dict[str, object],
    *,
    file_class: str,
) -> dict[str, GitFile]:
    ...

def require_runtime_equivalence(
    reviewed: dict[str, GitFile],
    source: dict[str, GitFile],
) -> None:
    ...
```

Use Git plumbing commands only against explicit commits.

Do not derive package authority from the current checkout.

### Step 5 — Run GREEN

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k runtime_equivalence -v
```

Expected: PASS.

### Step 6 — Commit

```bash
git add tools/deployment_manifest.py tests/test_deployment_manifest.py
git commit -m "feat(deployment): bind manifest scope to git objects"
```

---

# Task 4 — Validate Staged Package and Build Deterministic Manifest

**Files:**

* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Produces:**

* `build` operation;
* `DEPLOYMENT_MANIFEST.json`;
* external receipt.

### Step 1 — Write RED tests

Cover:

```python
def test_build_accepts_exact_staged_package(...):
    ...


def test_build_rejects_crlf_or_other_byte_change(...):
    ...


def test_build_rejects_missing_managed_file(...):
    ...


def test_build_rejects_managed_symlink(...):
    ...


def test_build_rejects_unexpected_python_file(...):
    ...


def test_build_allows_only_declared_cache_extra(...):
    ...


def test_receipt_must_be_outside_package_root(...):
    ...


def test_repeated_builds_produce_identical_manifest_bytes(...):
    ...
```

The byte-change test must specifically cover:

```python
b"#!/usr/bin/env bash\n"
```

becoming:

```python
b"#!/usr/bin/env bash\r\n"
```

### Step 2 — Run RED

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "build or staged or receipt" -v
```

Expected: FAIL.

### Step 3 — Implement staging validation

Implement:

```python
def validate_package_root(
    package_root: Path,
    expected_files: dict[str, GitFile],
    policy: dict[str, object],
) -> list[dict[str, object]]:
    ...
```

Rules:

* `lstat`, not implicit symlink following;
* exact regular file;
* exact bytes;
* exact size;
* exact SHA-256;
* runtime namespace extra scan;
* root guarded-extension scan;
* bounded error reporting.

### Step 4 — Implement manifest builder

Implement:

```python
def build_manifest(
    *,
    repo_root: Path,
    package_root: Path,
    source_commit: str,
    reviewed_runtime_commit: str,
    receipt_out: Path,
) -> tuple[Path, Path, str]:
    ...
```

Write manifest atomically:

```python
tmp = manifest_path.with_name(manifest_path.name + ".tmp")
tmp.write_bytes(manifest_bytes)
os.replace(tmp, manifest_path)
```

Receipt output must resolve outside `package_root`.

### Step 5 — Add CLI build mode

Use `argparse`.

Required invocation:

```bash
python tools/deployment_manifest.py build \
  --repo-root . \
  --package-root dist/poc-agent-overlay \
  --source-commit <sha> \
  --reviewed-runtime-commit <sha> \
  --receipt-out dist/poc-agent-overlay.release.json
```

Required final output:

```text
RELEASE_MANIFEST_SOURCE_COMMIT=<sha>
RELEASE_MANIFEST_RUNTIME_COMMIT=<sha>
RELEASE_MANIFEST_SHA256=<digest>
RELEASE_MANIFEST_FILES=<count>
RELEASE_MANIFEST=PASS
```

No source failure may later print PASS.

### Step 6 — Run GREEN

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k "build or staged or receipt" -v
```

Expected: PASS.

### Step 7 — Commit

```bash
git add tools/deployment_manifest.py tests/test_deployment_manifest.py
git commit -m "feat(deployment): build source-bound deployment manifests"
```

---

# Task 5 — Implement Fail-Closed Linux Verifier

**Files:**

* Modify: `tools/deployment_manifest.py`
* Modify: `tests/test_deployment_manifest.py`

**Produces:**

* package-mode SD-1 verifier independent of local Git.

### Step 1 — Write RED tests

Required tests:

```python
def test_verify_without_trusted_digest_is_blocked(...):
    assert main([...]) == 2
    assert "trusted_manifest_digest_missing" in captured.out


def test_verify_wrong_manifest_digest_fails(...):
    assert main([...wrong digest...]) == 1


def test_verify_tampered_file_fails(...):
    ...


def test_verify_unexpected_managed_file_fails(...):
    ...


def test_verify_ignores_unrelated_historical_git_metadata(...):
    # Create bogus .git or unrelated marker.
    # Verification result must depend only on trusted manifest + deployed bytes.
    ...


def test_verify_exact_release_passes(...):
    assert main([...]) == 0
    assert "SD_1=PASS identity_mode=release_manifest" in captured.out
```

### Step 2 — Run RED

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k verify -v
```

Expected: FAIL.

### Step 3 — Implement manifest parser

Implement strict schema validation:

```python
def parse_manifest_bytes(raw: bytes) -> dict[str, object]:
    ...
```

Require exact v1 top-level keys.

Reject unknown or missing required fields.

Validate all hashes, commits, paths, counts, classes, modes, and aggregate digest.

### Step 4 — Implement no-follow file hashing

Linux verification should use `lstat`.

Where available:

```python
flags = os.O_RDONLY
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
```

Hash using the opened descriptor.

### Step 5 — Implement verifier

```python
def verify_deployment(
    *,
    deployment_root: Path,
    manifest_path: Path,
    expected_manifest_sha256: str | None,
) -> int:
    ...
```

Exit semantics:

```text
0 = PASS
1 = FAIL
2 = BLOCKED
```

### Step 6 — Run GREEN

```bash
python -m pytest tests/test_deployment_manifest.py \
  -k verify -v
```

Expected: PASS.

### Step 7 — Commit

```bash
git add tools/deployment_manifest.py tests/test_deployment_manifest.py
git commit -m "feat(deployment): verify manifest-bound deployed bytes"
```

---

# Task 6 — Add Verifier Self-Integrity Bootstrap to SD-1 Runbook

**Files:**

* Modify: `docs/operations/sra-self-bootstrap-live-acceptance-v1.md`
* Create: `tests/test_sd1_deployment_manifest_runbook.py`

**Produces:**

* manifest-enabled SD-1 v1.5 operator procedure.

### Step 1 — Write RED static tests

Test the runbook text for required ordering.

Example:

```python
def test_package_sd1_checks_external_digest_before_project_verifier():
    text = RUNBOOK.read_text(encoding="utf-8")

    digest_check = text.index("SD_1_MANIFEST_PRECHECK=PASS")
    verifier_call = text.index("tools/deployment_manifest.py verify")

    assert digest_check < verifier_call


def test_package_sd1_does_not_use_local_git_as_package_authority():
    section = extract_sd1_package_section()
    assert "git rev-parse" not in section
    assert "git merge-base" not in section


def test_sd1_does_not_chain_sd2():
    section = extract_sd1_package_section()
    assert "sd2_" not in section.lower()
```

Also assert:

* v1.5 supersedes v1.4;
* expected digest missing → BLOCKED wording;
* manifest mismatch → FAIL wording;
* no `git clean`, `git reset`, `git pull`, `rm -rf`.

### Step 2 — Run RED

```bash
python -m pytest tests/test_sd1_deployment_manifest_runbook.py -v
```

Expected: FAIL.

### Step 3 — Update runbook

Add package/overlay flow.

The first precheck must be standard-library-only and must:

1. validate `EXPECTED_MANIFEST_SHA256`;
2. hash `DEPLOYMENT_MANIFEST.json`;
3. compare exact digest;
4. parse manifest;
5. find `tools/deployment_manifest.py`;
6. hash the tool;
7. compare it to manifest declaration;
8. print:

```text
SD_1_MANIFEST_PRECHECK=PASS
```

only after both checks pass.

Then invoke:

```bash
python tools/deployment_manifest.py verify \
  --deployment-root /mntCZJ/TopicClassification/poc-agent \
  --manifest /mntCZJ/TopicClassification/poc-agent/DEPLOYMENT_MANIFEST.json \
  --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
```

Do not source manifest data into shell.

### Step 4 — Adjust worktree-mode exclusion

Because `tools/**` is release tooling, update intact-worktree runtime comparison to exclude:

```text
tools/**
```

in addition to existing documentation/project-memory exclusions.

Do not weaken comparison for runtime-managed paths.

### Step 5 — Run GREEN

```bash
python -m pytest tests/test_sd1_deployment_manifest_runbook.py -v
```

Expected: PASS.

### Step 6 — Commit

```bash
git add docs/operations/sra-self-bootstrap-live-acceptance-v1.md \
  tests/test_sd1_deployment_manifest_runbook.py
git commit -m "docs(deployment): enable manifest-backed SD-1 acceptance"
```

---

# Task 7 — Full Security and Regression Validation

**Files:**

* Tests only unless a discovered defect requires correction.

### Step 1 — Run focused suite

```bash
python -m pytest \
  tests/test_deployment_manifest.py \
  tests/test_sd1_deployment_manifest_runbook.py \
  -v
```

Expected: all PASS.

### Step 2 — Run deployment/bootstrap regression subset

```bash
python -m pytest \
  tests/test_deployment_bootstrap.py \
  tests/test_run_sra_api_launcher.py \
  tests/test_requirement_handoff_coordinator.py \
  -v
```

Expected: existing behavior remains PASS.

### Step 3 — Static syntax

```bash
python -m py_compile tools/deployment_manifest.py
bash -n run_sra_api.sh
```

Expected: PASS.

### Step 4 — Diff validation

```bash
git diff --check
git diff --cached --check
```

Expected: no output.

### Step 5 — Scope audit

Verify no changes under runtime implementation paths other than the new `tools/` subsystem:

```bash
git diff --name-only <baseline>...HEAD
```

Explicitly inspect for accidental changes to:

```text
run_sra_api.sh
config/deployment_bootstrap.py
requirement_scheduler/
sra_api/
agent/
data_ingestion/
```

Expected: none.

---

# Task 8 — Project Memory and Decision Record

**Files:**

* Modify: `.codex/memory.md`
* Modify: `.codex/architecture.md`
* Modify: `.codex/known_issues.md`
* Modify: `.codex/decisions.md`

### Step 1 — Update architecture

Record:

```text
release source commit
        ↓
Git object runtime equivalence
        ↓
staged package validation
        ↓
DEPLOYMENT_MANIFEST.json
        ↓
external manifest digest
        ↓
Linux no-Git verifier
        ↓
SD-1 PASS / FAIL / BLOCKED
```

### Step 2 — Update decision record

Record why v1 uses:

```text
out-of-band manifest SHA-256
```

instead of:

```text
host-created DEPLOYMENT_COMMIT.txt
manifest-only self-attestation
asymmetric release signing
```

State that asymmetric signing is deferred, not forbidden.

### Step 3 — Update known issue

Change package/overlay identity gap from:

```text
implementation missing
```

to:

```text
implementation available; live deployment evidence still pending
```

Do not mark SD-1 PASS.

### Step 4 — Update memory

Record:

* exact changed files;
* test commands/results;
* no live SD gate executed;
* no SRA lifecycle;
* no SQL;
* no credential mutation;
* no Golden Path.

### Step 5 — Commit

```bash
git add .codex/memory.md .codex/architecture.md \
  .codex/known_issues.md .codex/decisions.md
git commit -m "docs(project): record deployment manifest architecture"
```

---

# Task 9 — Final Verification and PR Handoff

### Step 1 — Run all manifest tests again

```bash
python -m pytest \
  tests/test_deployment_manifest.py \
  tests/test_sd1_deployment_manifest_runbook.py \
  -v
```

### Step 2 — Re-run relevant deployment regressions

```bash
python -m pytest \
  tests/test_deployment_bootstrap.py \
  tests/test_run_sra_api_launcher.py \
  tests/test_requirement_handoff_coordinator.py \
  -v
```

### Step 3 — Verify no live actions occurred

Completion report must explicitly state:

```text
SD-1 live execution: NO
SD-2 through SD-7: NO
Private SQL: NO
SRA lifecycle mutation: NO
Credential mutation: NO
Golden Path replay: NO
Agent/ES/LLM/DOCX: NO
```

### Step 4 — Create PR

Suggested title:

```text
feat(deployment): add manifest-backed SD-1 package identity
```

Create PR against hosted `main`.

**DO NOT MERGE.**

### Step 5 — Completion report

Report:

```text
Repository
Actual hosted baseline used
Actual local baseline
Resulting local commit
Branch
PR number
PR URL
Hosted PR head SHA
Merge status
Changed files
Runtime behavior changed: YES/NO
Exact tests and results
Design deviations
Remaining risks
Live execution boundary
```

Do not call SD-1 live PASS.

The next action after PR creation is independent hosted-source review.

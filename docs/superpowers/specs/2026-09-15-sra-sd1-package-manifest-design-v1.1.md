# SRA SD-1 Package / Overlay Deployment Manifest Design v1.1

## 1. Document Control

| Field                                                 | Value                                                                            |
| ----------------------------------------------------- | -------------------------------------------------------------------------------- |
| Repository                                            | `hun186/poc-agent`                                                               |
| Hosted branch                                         | `main`                                                                           |
| Authoritative hosted baseline at Design v1.1 issuance | `7a54f182d9c1b6d18234d6e8085b163880b26db0`                                       |
| Source event                                          | PR #245 merged                                                                   |
| Reviewed SRA runtime baseline                         | `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`                                       |
| Existing manifest Design                              | `2026-09-15-sra-sd1-package-manifest-design-v1.md`                               |
| Existing manifest implementation                      | PR #245 / merge `7a54f182d9c1b6d18234d6e8085b163880b26db0`                       |
| Design version                                        | v1.1                                                                             |
| Supersedes                                            | Design v1                                                                        |
| Existing runbook                                      | `docs/operations/sra-self-bootstrap-live-acceptance-v1.md`, content version v1.5 |
| New runbook target                                    | v1.6                                                                             |
| Current SD-1 status                                   | `BLOCKED — corrective implementation required`                                   |
| Runtime SRA behavior change intended                  | **NO**                                                                           |
| Golden Path replay                                    | **NO**                                                                           |

Design v1.1 is a corrective trust-chain revision. It does not redesign SRA runtime or the overall release-manifest architecture introduced by v1.

---

# 2. Review Findings Addressed

Design v1.1 closes the following post-merge findings.

## CLR5-001 — BLOCKER — Policy scope is mutable by source commit

The v1 builder loads the deployment-manifest policy from the candidate `source_commit` and uses that policy to enumerate both:

```text
source runtime
reviewed runtime
```

Therefore a candidate source commit could narrow:

```text
managed_roots
managed_files
```

and simultaneously change files that were removed from scope.

Both runtime maps would then omit those files and runtime-equivalence could falsely PASS.

### Required correction

The manifest policy itself becomes reviewed security authority.

A candidate `source_commit` MUST NOT choose its own runtime scope.

---

## CLR5-002 — BLOCKER — `__pycache__` / `.pyc` cannot be an unverified allowed extra

v1 permits:

```text
**/__pycache__/**
```

as an unmanaged runtime extra.

Python bytecode may participate in module execution and therefore cannot be treated as harmless release debris for deployed-byte identity.

### Required correction

v1.1 canonical policy:

```json
"allowed_runtime_extra_globs": []
```

No undeclared regular file or symlink is permitted under managed runtime roots.

The verifier does not delete caches. A clean release/deployment tree is an operator/release responsibility.

---

## CLR5-003 — MAJOR — Parent-directory symlinks are insufficiently constrained

Checking only the final expected file component is not enough.

For example:

```text
agent -> /other/location/agent
agent/agent.py
```

may expose a regular final file through a symlinked parent.

### Required correction

Every managed file must be accessed through a root-anchored, no-symlink component walk.

No component between deployment root and target may resolve through a symlink.

---

## CLR5-004 — MAJOR — Release-tool authority is incomplete

v1 proves runtime equality but does not separately freeze:

```text
tools/deployment_manifest.py
tools/deployment_manifest_policy.json
tools/__init__.py
```

to a reviewed release-tool implementation baseline.

### Required correction

Introduce:

```text
reviewed_manifest_commit
```

as a second reviewed source authority.

The release must prove:

```text
reviewed runtime commit
          ↓ ancestor
source commit

reviewed manifest commit
          ↓ ancestor
source commit
```

and:

```text
source runtime scope
    ==
reviewed runtime scope

source release-tool scope
    ==
reviewed manifest-tool scope
```

---

## CLR5-005 — MAJOR — Runbook provenance is stale

v1.5 identifies an older runbook review baseline that predates the actual manifest implementation.

### Required correction

Advance the operator runbook to:

```text
v1.6
```

and bind it to a concrete reviewed manifest-tool implementation commit created during corrective implementation.

Do not attempt to encode a future merge commit inside files that must exist before that merge.

---

## CLR5-006 — MAJOR — Git mode is recorded but deployed executable semantics are not verified

Manifest entries include:

```text
git_mode
```

but v1 deployed verification checks only byte size and SHA-256.

### Required correction

For deployed regular files:

```text
git_mode == 100755
```

requires at least one executable permission bit.

```text
git_mode == 100644
```

requires no executable permission bit.

The verifier does not require exact owner/group/read permission parity because packaging, extraction, and local umask may legitimately change non-executable permission bits.

---

# 3. Goals

v1.1 MUST provide:

1. immutable reviewed policy authority;
2. reviewed release-tool authority;
3. runtime ancestry proof;
4. manifest-tool ancestry proof;
5. runtime path/blob/mode equality;
6. release-tool path/blob/mode equality;
7. no unverified runtime extras;
8. no parent-directory symlink traversal;
9. deployed executable-bit verification;
10. deterministic manifest;
11. external manifest SHA-256 trust anchor;
12. verifier self-integrity precheck;
13. read-only live SD-1;
14. no dependency on deployed `.git`;
15. no SRA runtime changes.

---

# 4. Non-Goals

v1.1 does NOT:

* introduce asymmetric release signing;
* create deployment archives;
* deploy the package;
* clean the live Linux deployment automatically;
* delete `__pycache__`;
* modify SQL;
* start or stop SRA;
* modify credentials;
* replay Golden Path;
* change Scheduler/Handoff behavior;
* change Report Job;
* change Agent/ES/LLM/DOCX behavior.

---

# 5. Two Independent Reviewed Baselines

The release trust chain now distinguishes:

```text
REVIEWED_RUNTIME_COMMIT
REVIEWED_MANIFEST_COMMIT
```

## 5.1 Reviewed runtime baseline

Remains:

```text
edcbc744f71374eaa839b0a31e0cd125fcb6fe52
```

It controls the allowed SRA runtime bytes.

## 5.2 Reviewed manifest baseline

This is a concrete implementation commit created during the v1.1 corrective branch after:

```text
tools/deployment_manifest.py
tools/deployment_manifest_policy.json
tools/__init__.py
tests/test_deployment_manifest.py
```

have reached their final reviewed implementation state.

The commit SHA MUST be obtained with:

```bash
git rev-parse HEAD
```

after that implementation commit exists.

It MUST NOT be guessed in advance.

The later runbook/documentation commit may be newer.

---

# 6. Source Commit Requirements

For an authoritative release:

```text
reviewed_runtime_commit
    must be ancestor of
source_commit
```

AND:

```text
reviewed_manifest_commit
    must be ancestor of
source_commit
```

Failure markers:

```text
RELEASE_MANIFEST=FAIL reason=reviewed_runtime_not_ancestor
RELEASE_MANIFEST=FAIL reason=reviewed_manifest_not_ancestor
```

This prevents release construction from unrelated Git histories.

---

# 7. Policy Authority

## 7.1 Canonical v1.1 policy

`tools/deployment_manifest_policy.json` remains source-controlled.

Canonical v1.1:

```json
{
  "schema_version": 1,
  "repository": "hun186/poc-agent",
  "managed_roots": [
    "agent",
    "api",
    "batch_scheduler",
    "config",
    "data_ingestion",
    "requirement_scheduler",
    "shared",
    "sra_api"
  ],
  "managed_files": [
    ".gitattributes",
    "__init__.py",
    "app.py",
    "python_compat.py",
    "requirements.txt",
    "run_sra_api.sh",
    "telemetry.py"
  ],
  "release_tool_files": [
    "tools/__init__.py",
    "tools/deployment_manifest.py",
    "tools/deployment_manifest_policy.json"
  ],
  "allowed_runtime_extra_globs": [],
  "guarded_root_extensions": [
    ".py",
    ".sh",
    ".pth"
  ]
}
```

## 7.2 Authority rule

The policy used for release construction MUST be loaded from:

```text
reviewed_manifest_commit
```

not selected by the candidate source commit.

The builder also reads:

```text
source_commit:tools/deployment_manifest_policy.json
```

and requires its exact Git blob/mode identity to equal the reviewed manifest version.

If different:

```text
RELEASE_MANIFEST=FAIL reason=manifest_policy_not_reviewed
```

The source commit therefore cannot silently narrow its own verification boundary.

---

# 8. Runtime Equivalence

The runtime map is enumerated using the reviewed policy.

Compare:

```text
reviewed_runtime_commit
        vs
source_commit
```

for all runtime-managed paths.

Required equality:

```text
exact path set
exact Git blob SHA
exact Git executable mode
```

Failure:

```text
runtime_source_not_equivalent
```

No policy from the source commit may reduce this comparison.

---

# 9. Release-Tool Equivalence

Using the reviewed policy's:

```text
release_tool_files
```

compare:

```text
reviewed_manifest_commit
        vs
source_commit
```

Required equality:

```text
exact release-tool path set
exact Git blob SHA
exact Git mode
```

Failure:

```text
release_tool_source_not_equivalent
```

A future modification to manifest tooling therefore requires a new reviewed manifest baseline instead of silently inheriting the previous approval.

---

# 10. Authoritative Builder Contract

The authoritative release path is the CLI:

```text
python tools/deployment_manifest.py build ...
```

Before constructing evidence, CLI build MUST verify that the actual running:

```text
tools/deployment_manifest.py
```

has exact bytes equal to:

```text
source_commit:tools/deployment_manifest.py
```

Otherwise:

```text
RELEASE_MANIFEST=FAIL reason=builder_source_identity
```

This is an additional build-environment integrity check.

It does not claim to defend against a fully compromised release builder environment; that remains outside v1.1 threat scope.

Direct Python calls to lower-level helper functions are test/library interfaces and are not an authoritative release ceremony.

---

# 11. Corrected Build CLI

Canonical release command becomes:

```bash
python tools/deployment_manifest.py build \
  --repo-root . \
  --package-root <staged-package-root> \
  --source-commit <release-source-commit> \
  --reviewed-runtime-commit edcbc744f71374eaa839b0a31e0cd125fcb6fe52 \
  --reviewed-manifest-commit <reviewed-manifest-tool-commit> \
  --receipt-out <path-outside-package-root>
```

`--reviewed-manifest-commit` is required.

No implicit default.

---

# 12. Manifest Schema v1.1

Keep:

```text
schema_version = 1
```

because the serialized artifact remains the same family, but add the mandatory field:

```json
"reviewed_manifest_commit": "<40 lowercase hex>"
```

Canonical identity fields become:

```text
repository
source_commit
source_tree
reviewed_runtime_commit
reviewed_manifest_commit
policy_sha256
files_root_sha256
```

`policy_sha256` is SHA-256 over the exact reviewed manifest policy bytes.

The source policy must have identical blob/mode identity.

---

# 13. External Receipt v1.1

Receipt MUST contain:

```json
{
  "schema_version": 1,
  "repository": "hun186/poc-agent",
  "source_commit": "<sha>",
  "reviewed_runtime_commit": "<sha>",
  "reviewed_manifest_commit": "<sha>",
  "manifest_sha256": "<sha256>",
  "files_root_sha256": "<sha256>",
  "created_at_utc": "<UTC>",
  "builder_version": 2
}
```

`builder_version` advances to:

```text
2
```

The external:

```text
manifest_sha256
```

remains the live deployment trust anchor.

---

# 14. No Runtime Extras

v1.1 package creation and deployed verification MUST reject every undeclared entry beneath managed roots.

There is no:

```text
__pycache__
.pyc
temporary Python module
backup .py
alternate shell launcher
```

exception.

Expected behavior:

```text
agent/__pycache__/agent.cpython-*.pyc
    => FAIL unexpected_managed_file
```

Generated caches must be absent at SD-1 execution time.

The verifier never deletes them.

---

# 15. Root-Anchored No-Symlink Traversal

Implement an anchored path walk.

For target:

```text
agent/report_agent.py
```

the verifier must establish:

```text
deployment root     regular directory / trusted root
agent               real directory, not symlink
report_agent.py     real regular file, not symlink
```

Recommended Linux implementation:

1. open deployment root directory descriptor;
2. open each parent component relative to the previous descriptor using:

   * `O_DIRECTORY`;
   * `O_NOFOLLOW` where available;
3. open final file relative to its parent descriptor using:

   * `O_RDONLY`;
   * `O_NOFOLLOW`;
4. validate `fstat`;
5. hash from the open file descriptor.

This prevents a parent symlink from escaping the deployment tree.

Build-side staged-package validation must apply equivalent parent-component checks.

---

# 16. Deployed Mode Semantics

For each manifest entry:

```text
100755
```

requires:

```python
bool(mode & 0o111) is True
```

For:

```text
100644
```

requires:

```python
bool(mode & 0o111) is False
```

Failure:

```text
managed_file_mode_mismatch
```

Do not require exact `0755` / `0644`, because owner/group write/read policy is deployment-environment specific.

---

# 17. Linux Verifier

Package-mode verifier continues to require:

```text
EXPECTED_MANIFEST_SHA256
```

from an independently retained release record.

Verification sequence:

```text
external manifest SHA
       ↓
manifest bytes authenticated
       ↓
manifest schema/policy checked
       ↓
deployed verifier pre-hashed
       ↓
root-anchored managed file reads
       ↓
size/hash/mode check
       ↓
managed-root exhaustive unexpected-file scan
       ↓
PASS
```

No package-mode step uses deployed `.git`.

---

# 18. Runbook v1.6

Advance:

```text
v1.5 → v1.6
```

v1.6 MUST record:

```text
Corrective implementation baseline:
7a54f182d9c1b6d18234d6e8085b163880b26db0

Reviewed manifest implementation commit:
<actual concrete implementation commit created during this corrective branch>

Reviewed runtime baseline:
edcbc744f71374eaa839b0a31e0cd125fcb6fe52
```

The second SHA is written only after the implementation commit actually exists.

It is not a future merge SHA.

Post-merge review then proves that commit is present in hosted `main` and its manifest-tool bytes remain unchanged.

Runbook status before independent post-merge review must remain:

```text
SOURCE IMPLEMENTED; POST-MERGE REVIEW REQUIRED;
SD-1 THROUGH SD-7 PENDING
```

It must not self-declare static approval.

---

# 19. Existing Git-Worktree Mode

Retain Git-worktree identity mode as an alternative.

Continue excluding non-runtime:

```text
docs/**
.codex/**
tools/**
```

from runtime equality.

Do not broaden exclusions.

---

# 20. Test Requirements

## Policy authority

Test:

```text
source policy removes agent
source changes agent/runtime.py
```

Expected:

```text
FAIL manifest_policy_not_reviewed
```

Also test:

```text
source changes only policy formatting
```

Expected:

```text
FAIL manifest_policy_not_reviewed
```

because v1.1 uses exact reviewed policy identity.

## Release-tool authority

Test:

```text
source modifies tools/deployment_manifest.py
without moving reviewed_manifest_commit
```

Expected:

```text
FAIL release_tool_source_not_equivalent
```

## Ancestry

Test unrelated source histories.

Both runtime and manifest ancestry failures must fail.

## Cache

Test:

```text
managed/__pycache__/x.pyc
```

Expected:

```text
FAIL unexpected_managed_file
```

during build and verify.

## Symlink parents

Test:

```text
agent -> external/agent
```

Expected FAIL.

Test nested parent symlink as well.

## Modes

Test:

```text
100755 manifest entry
deployed non-executable
```

Expected FAIL.

Test `100644` made executable -> FAIL.

## Existing positive path

Exact reviewed package still PASS.

---

# 21. Current Production Deployment

The existing Linux deployment remains:

```text
SD-1 = BLOCKED
```

Do not create a manifest against the existing overlay after the fact.

After corrective merge and review:

```text
reviewed source
     ↓
new staged package
     ↓
manifest build
     ↓
external receipt retention
     ↓
package deployment
     ↓
SD-1 v1.6
```

Only that flow may establish SD-1 PASS.

---

# 22. Acceptance Criteria

Corrective implementation is review-ready only if:

```text
policy authority cannot be narrowed by source commit
release tooling is bound to reviewed_manifest_commit
both ancestry checks exist
runtime equivalence remains fixed to edcbc744...
release-tool equivalence is enforced
no __pycache__ allowance remains
parent symlink traversal fails
Git executable semantics are verified
manifest contains reviewed_manifest_commit
receipt contains reviewed_manifest_commit
runbook is v1.6
runbook binds a real manifest implementation commit
all new RED→GREEN tests pass
existing deployment tests remain green
runtime SRA files remain unchanged
live SD-1 is not executed
```

No Golden Path replay is required.

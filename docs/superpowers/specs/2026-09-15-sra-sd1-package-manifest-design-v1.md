# SRA SD-1 Package / Overlay Deployment Manifest Design v1

## 1. Document Control

| Field                                                         | Value                                                                            |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Repository                                                    | `hun186/poc-agent`                                                               |
| Hosted branch                                                 | `main`                                                                           |
| Authoritative hosted baseline at design issuance              | `ffac2f87ffb20d5314b50e6582ce1a6bfd483523`                                       |
| Reviewed SRA runtime baseline                                 | `edcbc744f71374eaa839b0a31e0cd125fcb6fe52`                                       |
| Existing acceptance package                                   | `docs/operations/sra-self-bootstrap-live-acceptance-v1.md`, content version v1.4 |
| Design version                                                | v1                                                                               |
| Supersedes                                                    | None                                                                             |
| Current live SD-1 disposition                                 | `BLOCKED reason=no_authoritative_package_identity`                               |
| Runtime code behavior change intended                         | **NO**                                                                           |
| Private SQL / SRA lifecycle / credential / Golden Path impact | **NONE**                                                                         |

This design adds a release/deployment identity mechanism only. It must not modify SRA process supervision, deployment bootstrap behavior, Report Job, Requirement scheduling, SQL lease semantics, Agent, Elasticsearch, LLM, or DOCX generation.

---

## 2. Problem Statement

The deployed Linux directory is not an intact Git deployment.

The real deployment model is effectively:

```text
historical Linux Git checkout
        +
one or more Windows-built package / overlay updates
        =
actual deployed runtime tree
```

Therefore:

```text
local .git/HEAD
```

does not prove:

```text
actual deployed runtime bytes
        ==
reviewed GitHub runtime bytes
```

A manually created file such as:

```text
DEPLOYMENT_COMMIT.txt
```

would also be insufficient because an operator could create it after deployment without proving that the deployed files came from that commit.

SD-1 therefore needs an independently generated and externally anchored release manifest.

---

## 3. Goals

The implementation MUST provide all of the following:

1. A release-side tool that binds package bytes to a real Git source commit.
2. A distinction between:

   * actual release source commit; and
   * reviewed SRA runtime baseline.
3. Proof that runtime-managed files in the chosen release source commit are byte-equivalent to the reviewed runtime baseline.
4. A deterministic `DEPLOYMENT_MANIFEST.json`.
5. An external release receipt containing the manifest SHA-256.
6. A Linux read-only verifier that does not trust local `.git`.
7. A trust boundary requiring an expected manifest SHA-256 obtained from the release record outside the deployed tree.
8. Exact file hashing with SHA-256.
9. Rejection of:

   * missing files;
   * modified files;
   * symlinks in managed paths;
   * unexpected executable/import-affecting files;
   * malformed manifests;
   * duplicate paths;
   * path traversal;
   * runtime source drift.
10. Stable `PASS`, `FAIL`, and `BLOCKED` markers for SD-1.
11. No external Python dependency.
12. No secret values in manifest, receipt, logs, or verifier output.

---

## 4. Non-Goals

v1 does NOT:

* cryptographically sign releases with an asymmetric private key;
* replace GitHub as source authority;
* modify production runtime files automatically;
* clean the Linux deployment directory;
* delete historical or untracked files;
* perform deployment;
* create ZIP/7z archives;
* change SQL;
* start or stop SRA;
* rotate credentials;
* replay the Golden Path;
* prove host compromise resistance if both the release builder and independent release record are compromised.

Digital signing may be considered in a future v2. It is not required to close the present SD-1 operational gap.

---

## 5. Trust Model

### 5.1 Trusted authorities

SD-1 package mode trusts:

1. the reviewed GitHub source history;
2. the reviewed release-manifest implementation;
3. the release build environment;
4. an independently retained expected manifest SHA-256 produced before deployment.

The Linux deployment's historical `.git` metadata is explicitly **not** trusted.

### 5.2 Critical rule

A manifest located only inside:

```text
/mntCZJ/TopicClassification/poc-agent
```

is not sufficient evidence.

The operator MUST supply:

```text
EXPECTED_MANIFEST_SHA256
```

from a release record retained outside the deployed tree, such as:

* Windows release output;
* deployment ticket;
* change record;
* archived release receipt;
* other independently retained release evidence.

The Linux verifier MUST NOT derive the expected digest from the deployed manifest itself.

### 5.3 Threats covered

The mechanism detects:

* stale overlay;
* mixed-version overlay;
* CRLF/content mutation;
* partial copy;
* wrong package;
* post-release file edit;
* host-created fake manifest whose digest does not match the trusted release record;
* unexpected Python or shell files inside managed runtime namespaces;
* source commit that changed runtime bytes after the reviewed runtime baseline.

---

## 6. Approaches Considered

### Approach A — Plain `DEPLOYMENT_COMMIT.txt`

Rejected.

It declares a commit but does not bind actual bytes to the commit.

### Approach B — Manifest containing hashes, stored only inside package

Better, but still insufficient.

An operator could regenerate both the manifest and hashes against whatever files happen to exist on the host.

### Approach C — Git-anchored deterministic manifest + out-of-band digest

**Selected.**

The release tool:

1. reads source bytes from Git objects;
2. validates the staged package bytes against those Git bytes;
3. proves the runtime scope is unchanged from the reviewed runtime baseline;
4. emits a deterministic manifest;
5. emits an external receipt containing the manifest SHA-256;
6. prints the manifest SHA-256 for retention in the release record.

Linux acceptance then verifies the deployed manifest against that independently retained digest.

---

## 7. Component Architecture

New files:

```text
tools/
├── __init__.py
├── deployment_manifest.py
└── deployment_manifest_policy.json

tests/
├── test_deployment_manifest.py
└── test_sd1_deployment_manifest_runbook.py
```

Existing files updated:

```text
docs/operations/sra-self-bootstrap-live-acceptance-v1.md
.codex/memory.md
.codex/architecture.md
.codex/known_issues.md
.codex/decisions.md
```

The implementation MUST NOT require modifications to:

```text
run_sra_api.sh
config/deployment_bootstrap.py
requirement_scheduler/
sra_api runtime behavior
SQL schema
Service Key behavior
```

If source inspection shows such a runtime modification is actually necessary, implementation must stop and report `RUNTIME_BLOCKER_FOUND`.

---

## 8. Deployment Manifest Policy

The release policy is source-controlled at:

```text
tools/deployment_manifest_policy.json
```

v1 canonical content:

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
  "allowed_runtime_extra_globs": [
    "**/__pycache__/**"
  ],
  "guarded_root_extensions": [
    ".py",
    ".sh",
    ".pth"
  ]
}
```

The implementation may correct a listed path only when fresh source inspection proves that the path does not exist or another source-required runtime path is missing. Any such deviation must be reported explicitly.

### Runtime-managed scope

Runtime-managed bytes are:

* all tracked files beneath `managed_roots`;
* all tracked paths in `managed_files`.

### Release-tool scope

`release_tool_files` are reviewed release/verification tooling.

They are bound to the release source commit but are not compared against the older reviewed SRA runtime baseline.

---

## 9. Source Commit vs Reviewed Runtime Commit

The manifest MUST carry both:

```text
source_commit
reviewed_runtime_commit
```

Example:

```text
source_commit            = <future manifest implementation/release commit>
reviewed_runtime_commit  = edcbc744f71374eaa839b0a31e0cd125fcb6fe52
```

The build operation must compare the complete runtime-managed file map at both commits.

For every runtime-managed path:

```text
source_commit path set
        ==
reviewed_runtime_commit path set

source blob
        ==
reviewed runtime blob

git mode
        ==
reviewed runtime git mode
```

Any difference must fail release creation:

```text
RELEASE_MANIFEST=FAIL reason=runtime_source_not_equivalent
```

This allows documentation and release-tool additions after `edcbc744...` without silently approving an unreviewed SRA runtime change.

---

## 10. Canonical Manifest Schema

`DEPLOYMENT_MANIFEST.json` is deterministic UTF-8 JSON.

It MUST contain no timestamp.

Canonical shape:

```json
{
  "schema_version": 1,
  "repository": "hun186/poc-agent",
  "source_commit": "<40 lowercase hex>",
  "source_tree": "<40 lowercase hex>",
  "reviewed_runtime_commit": "<40 lowercase hex>",
  "policy_sha256": "<64 lowercase hex>",
  "managed_roots": [],
  "managed_files": [],
  "release_tool_files": [],
  "allowed_runtime_extra_globs": [],
  "guarded_root_extensions": [],
  "files_root_sha256": "<64 lowercase hex>",
  "files": [
    {
      "class": "runtime",
      "path": "run_sra_api.sh",
      "git_mode": "100755",
      "size": 12345,
      "sha256": "<64 lowercase hex>"
    }
  ]
}
```

`class` is exactly one of:

```text
runtime
release_tool
```

### Canonical encoding

Manifest bytes are produced with semantics equivalent to:

```python
json.dumps(
    manifest,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

Entries in `files` are sorted by normalized POSIX path.

Paths:

* are repo-relative;
* use `/`;
* cannot be absolute;
* cannot contain `..`;
* cannot contain empty components;
* cannot duplicate;
* cannot collide under Windows case folding.

---

## 11. File Digest Root

Each file uses SHA-256 over its exact bytes.

`files_root_sha256` is:

```text
SHA256(
  for every sorted file entry:
    class + NUL +
    path + NUL +
    git_mode + NUL +
    decimal_size + NUL +
    sha256 + LF
)
```

The exact byte serialization must be implemented once and tested deterministically.

---

## 12. External Release Receipt

The builder writes an external file:

```text
DEPLOYMENT_RELEASE_RECEIPT.json
```

The builder MUST reject a receipt output path located under the package root.

Receipt shape:

```json
{
  "schema_version": 1,
  "repository": "hun186/poc-agent",
  "source_commit": "<40 hex>",
  "reviewed_runtime_commit": "<40 hex>",
  "manifest_sha256": "<64 hex>",
  "files_root_sha256": "<64 hex>",
  "created_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "builder_version": 1
}
```

The receipt may contain a timestamp because it is not part of deterministic manifest identity.

The builder prints:

```text
RELEASE_MANIFEST_SOURCE_COMMIT=<sha>
RELEASE_MANIFEST_RUNTIME_COMMIT=<sha>
RELEASE_MANIFEST_SHA256=<sha256>
RELEASE_MANIFEST_FILES=<count>
RELEASE_MANIFEST=PASS
```

That SHA-256 must be retained outside the deployed Linux tree.

---

## 13. Release-Side Build Contract

Canonical command:

```bash
python tools/deployment_manifest.py build \
  --repo-root . \
  --package-root <staged-package-root> \
  --source-commit <release-source-commit> \
  --reviewed-runtime-commit edcbc744f71374eaa839b0a31e0cd125fcb6fe52 \
  --receipt-out <path-outside-package-root>
```

The builder must:

1. resolve both Git commits;
2. load policy from the **source commit**, not an uncommitted working-tree copy;
3. build the runtime file map from Git objects;
4. compare it against the reviewed runtime commit;
5. build the release-tool file map from the source commit;
6. inspect the staged package root;
7. reject symlinks in managed files;
8. require every declared file;
9. compare exact staged bytes with source Git blobs;
10. reject unexpected files beneath runtime-managed roots except allowed `__pycache__`;
11. reject undeclared guarded root `.py`, `.sh`, or `.pth` files;
12. write `DEPLOYMENT_MANIFEST.json` atomically;
13. write the receipt outside the package root;
14. never read or emit secrets.

The build must not depend on the current working tree being deployed.

Git objects are the source authority.

---

## 14. Linux SD-1 Verification Contract

Canonical acceptance input:

```text
deployment root
manifest path
EXPECTED_MANIFEST_SHA256 from trusted release record
```

Canonical command:

```bash
python tools/deployment_manifest.py verify \
  --deployment-root /mntCZJ/TopicClassification/poc-agent \
  --manifest /mntCZJ/TopicClassification/poc-agent/DEPLOYMENT_MANIFEST.json \
  --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
```

The verifier MUST NOT use:

```text
git rev-parse
git status
git merge-base
local .git/HEAD
```

for package/overlay identity.

---

## 15. Verifier Self-Integrity Bootstrap

Because `tools/deployment_manifest.py` itself is deployed code, SD-1 must not blindly execute it.

The runbook must first use a short standard-library-only Python precheck that:

1. hashes `DEPLOYMENT_MANIFEST.json`;
2. compares it to the externally supplied expected digest;
3. parses the now-trusted manifest;
4. extracts the declared SHA-256 of:

```text
tools/deployment_manifest.py
```

5. hashes that verifier file directly;
6. fails before executing project verifier code if it does not match.

Only then may SD-1 invoke:

```text
python tools/deployment_manifest.py verify ...
```

This breaks the otherwise circular trust problem.

---

## 16. Linux Verification Rules

The verifier must fail closed on:

* missing manifest;
* missing expected digest;
* malformed expected digest;
* manifest digest mismatch;
* malformed JSON;
* unknown schema version;
* wrong repository;
* duplicate file path;
* invalid path;
* invalid digest;
* wrong aggregate digest;
* missing managed file;
* symlink managed file;
* non-regular managed file;
* size mismatch;
* SHA-256 mismatch;
* unexpected file beneath a managed runtime root;
* unexpected guarded `.py`, `.sh`, or `.pth` root file;
* modified release verifier;
* policy inconsistency.

Where Linux supports it, regular managed files should be opened without following symlinks.

No verifier path may mutate the deployment.

---

## 17. Exit Codes and Stable Markers

### PASS

Exit code:

```text
0
```

Required final marker:

```text
SD_1=PASS identity_mode=release_manifest
```

Also output:

```text
SD_1_SOURCE_COMMIT=<sha>
SD_1_REVIEWED_RUNTIME_COMMIT=<sha>
SD_1_MANIFEST_SHA256=<sha256>
SD_1_FILES_EXPECTED=<n>
SD_1_FILES_MATCHED=<n>
SD_1_UNEXPECTED_MANAGED=0
```

### FAIL

Exit code:

```text
1
```

Examples:

```text
SD_1=FAIL reason=manifest_digest_mismatch
SD_1=FAIL reason=managed_file_hash_mismatch
SD_1=FAIL reason=unexpected_managed_file
SD_1=FAIL reason=manifest_schema
```

### BLOCKED

Exit code:

```text
2
```

Used only when required authority is absent rather than contradicted.

Examples:

```text
SD_1=BLOCKED reason=no_authoritative_package_identity
SD_1=BLOCKED reason=trusted_manifest_digest_missing
```

A `BLOCKED` or `FAIL` result stops acceptance. SD-2 must not begin.

---

## 18. Unexpected File Policy

The verifier must not merely verify listed files.

Under every `managed_root`, every regular file and symlink must be classified.

Allowed:

```text
manifest-declared file
**/__pycache__/**
```

Everything else is unexpected.

This intentionally catches historical overlay residue such as:

```text
agent_new.py
backup .py files
old copied modules
alternate runtime implementations
```

At deployment-root level, any undeclared file ending in:

```text
.py
.sh
.pth
```

is also a failure.

This is required because extra executable/import-affecting files can change Python or shell behavior even when all expected files are present.

---

## 19. Current Deployment Consequence

The currently running Linux tree must NOT be retroactively blessed by generating a manifest against it.

The first authoritative manifest must come from a new reviewed release package.

The current instance therefore remains:

```text
SD-1 = BLOCKED
```

until a manifest-enabled package is built and deployed.

If the new verifier discovers unexpected historical runtime files, SD-1 remains `FAIL` or `BLOCKED` as appropriate.

The verifier must never clean them automatically.

Any cleanup/redeployment procedure is a separate operator decision.

---

## 20. Runbook Changes

`docs/operations/sra-self-bootstrap-live-acceptance-v1.md` should advance from content version v1.4 to v1.5.

v1.5:

* supersedes v1.4;
* retains SD-1 through SD-7 as live evidence gates;
* adds package/overlay manifest mode;
* retains intact-worktree mode as an alternative;
* explicitly excludes `tools/**` from the old SRA runtime-tree equivalence comparison because release tooling is not SRA runtime;
* does not weaken any existing live gate;
* does not execute SD-2 automatically;
* does not self-award SD-1 PASS.

---

## 21. Intact Git Worktree Compatibility

The existing intact-worktree route may remain.

Because the manifest implementation adds non-runtime tooling under `tools/**`, its runtime-equivalence comparison must treat these paths as non-runtime:

```text
docs/**
.codex/**
tools/**
```

The reviewed SRA runtime baseline remains `edcbc744...` unless implementation unexpectedly changes a runtime-managed path.

If any runtime-managed path changes, `edcbc744...` can no longer be used as the reviewed runtime baseline and implementation must stop for a new runtime review.

---

## 22. Testing Requirements

All implementation must follow strict TDD.

Tests must cover at least:

### Manifest canonicalization

* deterministic bytes;
* stable ordering;
* UTF-8 paths;
* duplicate rejection;
* traversal rejection;
* absolute path rejection;
* case-fold collision rejection;
* invalid digest rejection.

### Git source binding

* source commit exists;
* runtime commit exists;
* runtime path sets match;
* runtime blob hashes match;
* runtime Git modes match;
* release-tool changes do not invalidate runtime equivalence;
* real runtime drift is rejected.

### Package build

* exact staged files pass;
* CRLF/content mutation fails;
* missing file fails;
* symlink fails;
* unexpected `.py` in managed root fails;
* unexpected root `.sh` fails;
* `__pycache__` allowance works;
* receipt inside package root is rejected;
* manifest is deterministic across repeated builds.

### Linux verify

* expected digest missing → BLOCKED;
* expected digest malformed → FAIL;
* wrong expected digest → FAIL;
* tampered manifest → FAIL;
* tampered runtime file → FAIL;
* missing runtime file → FAIL;
* symlink → FAIL;
* unexpected managed file → FAIL;
* matching deployment → PASS;
* local `.git` state is irrelevant.

### Runbook static tests

* manifest digest is checked before executing project verifier;
* verifier file hash is checked before executing it;
* package verifier contains no `git` authority dependency;
* `BLOCKED` and `FAIL` return before PASS;
* SD-2 is not chained;
* no destructive cleanup command exists.

---

## 23. Security Constraints

The implementation must not:

* read `.env`;
* read Service Key secrets;
* print environment variables wholesale;
* print Authorization headers;
* hash secret runtime state as release identity;
* inspect SQL;
* alter SQL;
* use `git clean`;
* use `git reset`;
* use `git pull`;
* use `git checkout .`;
* delete deployment files;
* revoke keys;
* restart SRA.

Manifest and receipt contain source metadata and file hashes only.

---

## 24. Acceptance Criteria

Implementation-level completion requires:

```text
1. release builder exists
2. manifest is deterministic
3. staged package is source-bound
4. reviewed runtime equivalence is enforced
5. external manifest digest is produced
6. Linux verifier ignores local Git identity
7. verifier self-integrity bootstrap exists
8. unexpected runtime code is rejected
9. all unit/static tests pass
10. runtime SRA code remains unchanged
11. v1.5 runbook is source-aligned
12. SD-1 live execution remains PENDING
```

After merge and independent post-merge review, the next operator sequence is:

```text
build manifest-enabled release
        ↓
retain RELEASE_MANIFEST_SHA256 outside deployment root
        ↓
deploy overlay/package
        ↓
run only SD-1 package-manifest verification
        ↓
review evidence
        ↓
only after SD-1 PASS proceed to SD-2
```

No Golden Path replay is required.

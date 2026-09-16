# Requirement Automatic Operator E2E Harness Implementation Plan v2

## Control

- Repository: `hun186/poc-agent`
- Branch: `work`
- Authoritative hosted baseline: `919422bce992e757a89767f66beb8e042707a976`
- Design: Requirement Automatic Operator E2E Harness Design v2
- Plan version: v2
- Supersedes: Requirement Automatic Operator E2E Harness Implementation Plan v1

## TDD sequence

1. Add RED tests for CLI defaults, canonical SHA binding, mode-aware configuration/platform/lock,
   source evidence, remote workers, endpoint authentication/RBAC/redaction, remote DOCX failures,
   and a single shared `Harness.run` orchestration.
2. Add the read-only runtime-evidence router/service using existing editor superuser RBAC,
   launcher identity verifier, Git worktree proof, and authoritative Handoff output-root setting.
3. Extract provider/support primitives. Preserve local checks exactly; implement remote preflight,
   Report Job download, DOCX/path/SHA checks, and root-fingerprint comparison.
4. Wire `--mode`, optional canonical `--excel`, required reviewed runtime SHA, schema v2, summary
   mode/PASS marker, cross-platform local operator lock, and mode-specific diagnostics.
5. Update the env example and runbook with both complete acceptance workflows, trust boundaries,
   decision policy, failure categories, and no automatic fallback.
6. Run focused tests, compilation, the current broad Requirement-family regression, protected
   XLSX digest verification, and `git diff --check`. Do not execute live acceptance.

## Source/deployment evidence corrective hotfix

Classify committed and dirty paths by repository role rather than requiring literal SHA equality
and an empty worktree. Incremental deployments use machine-generated deterministic provenance and
active-module/path checks, without a deleted-file ledger or clean-slate copy. The external reviewed
SHA and locally reconstructed reviewed hashes remain authoritative. Inactive residue warns; active,
resolved, discovered, shadowing, or replacement code blocks.

## Production scope

Only a bounded authenticated read-only evidence surface and its router registration are allowed.
There are no DB migrations and no scheduler/Handoff/Report Job execution changes.

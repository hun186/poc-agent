# SRA Self-Bootstrapping Live Acceptance Package — Command Review v1.2

## Decision and scope

**COMMAND-LEVEL REVIEW v1.2 = PASS**

**SD-1 THROUGH SD-7 LIVE EXECUTION = PENDING**

This is a static, post-merge corrective review of the v1.1 operator commands at the supplied hosted `main` baseline `30c5c918ff83a9f4f238383419b0db9886d0b872`. Network policy returned CONNECT 403 when refreshing GitHub, so this review does not claim a newer hosted SHA. Runtime code was not changed. No gate, private SQL, runtime lifecycle, credential mutation, Golden Path, Agent, Elasticsearch, LLM, or DOCX operation was executed.

## Findings and dispositions

| ID | Severity | Gate | Source evidence / risk | Correction | Disposition |
| --- | --- | --- | --- | --- | --- |
| CLR2-001 | BLOCKER | SD-1 | v1.1 equated its own older documentation merge with deployed artifact identity. Runtime implementation remains rooted at `edcbc744...`; package overlays have no source manifest. | Separated review identity from deployed runtime-tree identity. Intact worktrees prove the runtime ancestor, unchanged non-documentation tree, and clean deployed bytes. Package/overlay mode remains BLOCKED without a reviewed manifest. | CONFIRMED; FIXED |
| CLR2-002 | BLOCKER | SD-2 / shared functions | The Python CR scan could fail and a later `bash -n` could print PASS without interactive `set -e`. | Captured heredoc status and returned explicitly; audited every Python heredoc and PASS path. | CONFIRMED; FIXED |
| CLR2-003 | BLOCKER | SD-4 | v1.1 pidfd validation omitted complete record schema/UID/argv and positive flock ownership. | Immediately before pidfd SIGKILL, validate exact five-field owner/mode record, live non-zombie PID/start/EUID/cwd/bash-script argv, FD 9 lock inode, `/proc/locks` FLOCK ownership, and unchanged identity record. Any ambiguity sends no signal. | CONFIRMED; FIXED |
| CLR2-004 | BLOCKER | SD-6 | v1.1 printed snapshots but had no executable comparison. | Added before JSON and after verifier for protected-state/key stability; four PID/start replacements; listener/OpenAPI/flock via shared verifier; live lease; increased generation; configured/default owner semantics; old-launcher termination; and supported takeover audit with no KILL/ABORT. | CONFIRMED; FIXED |
| CLR2-005 | MAJOR | SD-6 | Predictable `/tmp/sra-sd6-before` could be copied into before authority checks. | `mktemp -d`, immediate nonsymlink/EUID/0700 checks before writes, non-secret JSON only, and identity-bound cleanup. | CONFIRMED; FIXED |
| CLR2-006 | MAJOR | SD-4–SD-6 | v1.1 accepted extra identity fields and did not bind stored launcher UID/cwd or flock. | Shared verifier now enforces exact schemas, owner/mode, stored/live UID/cwd/path, bash launcher argv, PID/start/non-zombie, launcher-child relations, listener, flock, worker argv, and OpenAPI JSON. | CONFIRMED; FIXED |
| CLR2-007 | MAJOR | SD-3/SD-4 | Predictable evidence/log paths were inconsistent with the runbook's owner-bound temporary-evidence rule. | Replaced them with `mktemp` paths and immediate owner/mode/type validation. | NEW; FIXED |

## Whole-runbook safety review

The v1.2 snippets use bounded output, function-local `return`, explicit fallible-command propagation, exact process records, and read-only SQL. They contain no global interactive `set -e`, persistent trap, `pkill`, `killall`, broad `pgrep -f`, `sed -i`, `dos2unix`, credential dump, SQL mutation, generic key revocation, or Golden Path command. SD-7 retains instance-bound BLOCKED disposition where revocation authority cannot be proven.

v1.2 supersedes v1.1. v1.1 must not be used for live execution. Static command review is not deployment acceptance.

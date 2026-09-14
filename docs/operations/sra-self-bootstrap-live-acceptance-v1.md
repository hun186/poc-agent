# SRA Self-Bootstrapping Deployment Live Acceptance Package v1.1

> **Supersedes v1.** The post-merge command review found source-identity,
> process-binding, restart-evidence, and cleanup authorization defects in v1.
> Do not execute the v1 commands from repository history.

## Document control

| Field | Bound value |
| --- | --- |
| Repository | `hun186/poc-agent` |
| Hosted branch | `main` |
| Reviewed source | `2ef993e34629828128ff5244422c3440a4e305f3` (PR #240 merge) |
| Runtime parent | `edcbc744f71374eaa839b0a31e0cd125fcb6fe52` |
| Version | `v1.1` |
| Status | **STATICALLY REVIEWED; SD-1 THROUGH SD-7 PENDING** |

The command reviewer attempted `git ls-remote` on 2026-09-14 and received
`CONNECT tunnel failed, response 403`. The hosted SHA could not be refreshed, so
no SHA newer than the issuance baseline is claimed. The local object at the
issuance SHA was used only because it exactly matched that supplied hosted
baseline.

## Universal rules

Execute one gate, return its bounded evidence for review, and wait. Never chain
gates. A `FAIL`, `BLOCKED`, or `NOT_EXECUTABLE_ON_THIS_INSTANCE` result means
**STOP**. These functions use `return`, not top-level `exit`; do not enable
interactive-shell `set -e`, `set -x`, or a persistent `trap`.

Do not run these gates as root. Do not print or copy `.env`, the SQL registry,
Service Key store, generated/legacy Handoff state, an Authorization header, a
lease token, or any raw credential. Do not use `env`, `printenv`, `set`, `pkill`,
`killall`, `pgrep -f`, `sed -i`, or `dos2unix`. Do not edit SQL, remove state,
start a worker manually, rotate the canonical key, or replay the Requirement /
Agent / Elasticsearch / LLM / DOCX Golden Path.

Run this separately in each new SSH session:

```bash
accept_setup() {
  BASE=/mntCZJ/TopicClassification/poc-agent
  [ "$(id -un)" = aiuser ] || { echo 'ACCEPT_SETUP=FAIL reason=wrong_user'; return 1; }
  [ -d "$BASE" ] || { echo 'ACCEPT_SETUP=FAIL reason=project_missing'; return 1; }
  cd "$BASE" || { echo 'ACCEPT_SETUP=FAIL reason=cannot_cd'; return 1; }
  printf 'ACCEPT_SETUP=PASS user=%s root=%s\n' "$(id -un)" "$BASE"
}
accept_setup
```

If `aiuser` is not the configured owner, stop and review a revised owner binding.

## Shared exact runtime verifier (read-only)

Define this helper only for SD-4 through SD-6. It validates owner-only identity
records, PID/start time, effective UID, cwd, parent launcher, exact worker argv,
API listener ownership, and parsed OpenAPI content. PID existence alone never
passes. `lsof` is the same listener authority used by the launcher.

```bash
verify_sra_runtime() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'RUNTIME_VERIFY=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import json, os, stat, subprocess, urllib.request
from pathlib import Path
root=Path.cwd().resolve(); uid=os.geteuid()
def record(role):
 p=Path(f'.run_sra_api_{role}.identity')
 if p.is_symlink() or not p.is_file(): raise RuntimeError(f'{role}_record_type')
 s=p.stat()
 if s.st_uid!=uid or stat.S_IMODE(s.st_mode)!=0o600: raise RuntimeError(f'{role}_record_owner_mode')
 rows=p.read_text().splitlines(); d={}
 for row in rows:
  k,sep,v=row.partition('=')
  if not sep or k in d: raise RuntimeError(f'{role}_record_shape')
  d[k]=v
 return d
def proc(pid, start, role, parent=None):
 if not pid.isdigit() or not start.isdigit(): raise RuntimeError(f'{role}_pid_shape')
 p=Path('/proc')/pid
 fields=(p/'stat').read_text().split()
 status=(p/'status').read_text().splitlines()
 euid=int(next(x.split()[2] for x in status if x.startswith('Uid:')))
 argv=[x.decode() for x in (p/'cmdline').read_bytes().split(b'\0') if x]
 if fields[21]!=start or fields[2]=='Z' or euid!=uid or Path(os.readlink(p/'cwd')).resolve()!=root:
  raise RuntimeError(f'{role}_process_identity')
 if parent is not None and int(fields[3])!=parent: raise RuntimeError(f'{role}_wrong_parent')
 return argv
l=record('launcher'); lpid=l['pid']; largv=proc(lpid,l['process_start_time'],'launcher')
if len(largv)<2: raise RuntimeError('launcher_argv')
script=(root/largv[1]).resolve() if not Path(largv[1]).is_absolute() else Path(largv[1]).resolve()
if Path(l['launcher_path']).resolve()!=root/'run_sra_api.sh' or script!=root/'run_sra_api.sh':
 raise RuntimeError('launcher_argv')
lp=int(lpid)
a=record('api'); apid=a['api_pid']; proc(apid,a['api_start_time'],'api',lp)
if a.get('port')!='9002': raise RuntimeError('api_port_record')
listeners=subprocess.check_output(['lsof','-t','-nP','-a','-p',apid,'-iTCP:9002','-sTCP:LISTEN'],text=True).split()
if listeners!=[apid]: raise RuntimeError('api_listener')
for role,command in [('schedule','schedule-worker'),('handoff','handoff-worker')]:
 d=record(role); argv=proc(d['pid'],d['process_start_time'],role,lp)
 if d.get('role')!=role or 'requirement_scheduler.cli' not in ' '.join(argv) or command not in argv:
  raise RuntimeError(f'{role}_argv')
try:
 with urllib.request.urlopen('http://127.0.0.1:9002/openapi.json',timeout=5) as r:
  body=r.read(2_000_001); spec=json.loads(body)
  if r.status!=200 or len(body)>2_000_000 or spec.get('openapi') is None: raise RuntimeError('openapi_content')
except Exception as exc: raise RuntimeError('openapi_readiness') from exc
print(f'RUNTIME_LAUNCHER_PID={lpid}')
print(f'RUNTIME_API_PID={apid}')
print('RUNTIME_VERIFY=PASS')
PY
}
```

## SD-1 — DEPLOYMENT_SOURCE_GATE

### Contract and result

The deployment can be a Windows-built package plus Linux overlay. Current source
does not create or validate `DEPLOYMENT_COMMIT.txt`, and therefore does **not**
guarantee that a deployed `.git/HEAD` identifies deployed bytes. v1's unconditional
`git rev-parse HEAD == runtime parent` was both the wrong commit and an invalid
artifact-identity assumption.

Only a deployment installed as an intact Git worktree may use the command below.
For a package/overlay deployment, do not substitute its incidental `.git` state:
report `SD_1=BLOCKED reason=no_authoritative_package_identity` until the release
owner supplies a reviewed, tamper-evident manifest binding the package and overlay
to commit `2ef993e...`. This does not weaken the source gate.

### Git-worktree action (read-only)

```bash
sd1_git_worktree() {
  local expected=2ef993e34629828128ff5244422c3440a4e305f3 head
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_1=FAIL reason=cannot_cd'; return 1; }
  [ -d .git ] || { echo 'SD_1=BLOCKED reason=no_authoritative_package_identity'; return 2; }
  head=$(git rev-parse HEAD 2>/dev/null) || { echo 'SD_1=FAIL reason=git_unreadable'; return 1; }
  [ "$head" = "$expected" ] || { printf 'SD_1_HEAD=%s\nSD_1=FAIL reason=baseline_mismatch\n' "$head"; return 1; }
  git diff --quiet "$expected" -- || { echo 'SD_1=FAIL reason=tracked_bytes_differ'; return 1; }
  [ -z "$(git status --porcelain=v1 --untracked-files=no)" ] || { echo 'SD_1=FAIL reason=tracked_changes'; return 1; }
  for f in run_sra_api.sh config/deployment_bootstrap.py requirement_scheduler/cli.py .gitattributes; do
    [ -f "$f" ] || { echo "SD_1=FAIL reason=missing_file file=$f"; return 1; }
  done
  git show -s --format='SD_1_COMMIT=%H%nSD_1_SUBJECT=%s' HEAD
  echo 'SD_1=PASS identity_mode=intact_git_worktree'
}
sd1_git_worktree
```

PASS requires the exact reviewed merge commit and byte-clean tracked worktree.
Package/overlay identity remains a deployment-release BLOCKER; do not pull/reset.

## SD-2 — LF_PACKAGE_GATE

This gate is entirely read-only. `.gitattributes` applies `text eol=lf` to
`*.sh`; acceptance detects rather than repairs CRLF.

```bash
sd2_lf() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_2=FAIL reason=cannot_cd'; return 1; }
  git check-attr text eol -- run_sra_api.sh
  git check-attr text -- run_sra_api.sh | grep -q ': text: set$' || { echo 'SD_2=FAIL reason=text_attribute'; return 1; }
  git check-attr eol -- run_sra_api.sh | grep -q ': eol: lf$' || { echo 'SD_2=FAIL reason=eol_attribute'; return 1; }
  python - <<'PY'
import pathlib, subprocess
files=subprocess.check_output(['git','ls-files','*.sh'],text=True).splitlines()
if not files: raise SystemExit('SD_2=FAIL reason=no_shell_files')
bad=[p for p in files if b'\r' in pathlib.Path(p).read_bytes()]
print(f'SD_2_FILES={len(files)} CR_FILES={len(bad)}')
for p in bad[:10]: print('SD_2_BAD_FILE='+p)
raise SystemExit(1 if bad else 0)
PY
  bash -n run_sra_api.sh || { echo 'SD_2=FAIL reason=bash_syntax'; return 1; }
  echo 'SD_2=PASS'
}
sd2_lf
```

## SD-3 — BOOTSTRAP_FIRST_RUN_GATE

This is executable only on a genuinely unprovisioned instance. Never remove or
rename state and never use repair to manufacture first run. Listing uses the
supported store interface and may create only its lock file; it does not create,
revoke, or expose a key.

```bash
sd3_precheck() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_3_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from config.deployment_bootstrap import KEY_NAME
from sra_api.security.service_key_store import ServiceKeyStore
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
p=d/'requirement_handoff.env'
keys=[x for x in ServiceKeyStore(Path(os.getenv('SRA_SERVICE_KEYS_FILE','.sra_service_keys.json'))).list_keys() if x.get('name')==KEY_NAME and x.get('status')=='active']
print('SD_3_STATE_PRESENT='+('YES' if p.exists() or p.is_symlink() else 'NO'))
print(f'SD_3_ACTIVE_CANONICAL_COUNT={len(keys)}')
if p.exists() or p.is_symlink() or keys:
 print('SD_3_PRECHECK=BLOCKED_ALREADY_PROVISIONED'); raise SystemExit(2)
print('SD_3_PRECHECK=PASS')
PY
}
sd3_precheck
```

If blocked, record `SD_3=NOT_EXECUTABLE_ON_THIS_INSTANCE`; only contemporaneous,
authentic installation evidence can later close it. Do not call it a deployment
failure and do not invent historical evidence.

On an accepted first-run instance only, start the normal entrypoint:

```bash
sd3_start() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_3_ACTION=FAIL reason=cannot_cd'; return 1; }
  umask 077
  nohup ./run_sra_api.sh > /tmp/sra-sd3-launcher.log 2>&1 </dev/null &
  local pid=$! start
  start=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null) || { echo 'SD_3_ACTION=FAIL reason=launcher_exited'; return 1; }
  printf 'pid=%s\nstart=%s\n' "$pid" "$start" > /tmp/sra-sd3-invocation.identity
  sleep 18
  [ "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$start" ] || { echo 'SD_3_ACTION=FAIL reason=launcher_exited_or_reused'; tail -n 30 /tmp/sra-sd3-launcher.log; return 1; }
  echo 'SD_3_ACTION=PASS'
}
sd3_start
```

Verify only approved metadata:

```bash
sd3_verify() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_3_VERIFY=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import os, stat
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from config.deployment_bootstrap import KEY_NAME,KEY_SCOPES,STATE_KEYS
from sra_api.security.service_key_store import ServiceKeyStore
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
p=d/'requirement_handoff.env'; raw=p.read_bytes(); values=dict(x.split('=',1) for x in raw.decode().splitlines())
out=Path(values['REQUIREMENT_HANDOFF_OUTPUT_ROOT'])
store=ServiceKeyStore(Path(os.getenv('SRA_SERVICE_KEYS_FILE','.sra_service_keys.json')))
active=[x for x in store.list_keys() if x.get('name')==KEY_NAME and x.get('status')=='active']
selected=[x for x in active if x.get('key_id')==values.get('SRA_BOOTSTRAP_HANDOFF_KEY_ID')]
mode=lambda x: format(stat.S_IMODE(x.stat().st_mode),'04o')
ok=(set(values)==set(STATE_KEYS) and b'\r' not in raw and b'\0' not in raw and not d.is_symlink() and not p.is_symlink() and not out.is_symlink() and mode(d)=='0700' and mode(p)=='0600' and mode(out)=='0700' and out.parent.resolve()==d.resolve() and len(active)==len(selected)==1 and frozenset(selected[0]['scopes'])==KEY_SCOPES)
print(f'SD_3_STATE_DIR_MODE={mode(d)} STATE_FILE_MODE={mode(p)} OUTPUT_DIR_MODE={mode(out)}')
print(f'SD_3_ACTIVE_CANONICAL_COUNT={len(active)} SELECTED_MATCH={len(selected)}')
print('SD_3_SCOPES='+(','.join(selected[0]['scopes']) if selected else 'UNAVAILABLE'))
print('SD_3_VERIFY='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
}
sd3_verify
```

PASS also requires bounded logs proving bootstrap precedes takeover/start and no
`/tmp/auto3-handoff.env` dependency. Redact `sra_sk_...` defensively before
sharing logs. Do not run `repair-handoff-credential` on failure.

## SD-4 — FLOCK_ORPHAN_RECOVERY_GATE

This is an explicitly authorized availability fault injection, not normal
shutdown. First run `verify_sra_runtime` and review its PASS. Then use a Linux
pidfd so PID reuse between validation and SIGKILL cannot redirect the signal.

```bash
sd4_crash_exact_launcher() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_4_CRASH=FAIL reason=cannot_cd'; return 1; }
  verify_sra_runtime || return 1
  python - <<'PY'
import os, signal, stat
from pathlib import Path
p=Path('.run_sra_api_launcher.identity')
if p.is_symlink() or stat.S_IMODE(p.stat().st_mode)!=0o600 or p.stat().st_uid!=os.geteuid(): raise SystemExit('SD_4_CRASH=FAIL reason=record')
d=dict(x.split('=',1) for x in p.read_text().splitlines()); pid=int(d['pid'])
fd=os.pidfd_open(pid)
try:
 proc=Path('/proc')/str(pid); argv=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
 start=(proc/'stat').read_text().split()[21]; cwd=Path(os.readlink(proc/'cwd')).resolve()
 script=(cwd/argv[1]).resolve() if not Path(argv[1]).is_absolute() else Path(argv[1]).resolve()
 ok=(start==d['process_start_time'] and cwd==Path.cwd().resolve() and script==Path('run_sra_api.sh').resolve() and Path(d['launcher_path']).resolve()==script)
 if not ok: raise SystemExit('SD_4_CRASH=FAIL reason=identity_changed_no_signal')
 signal.pidfd_send_signal(fd,signal.SIGKILL)
 print(f'SD_4_CRASH=PASS pid={pid} start={start}')
finally: os.close(fd)
PY
}
sd4_crash_exact_launcher
```

Start recovery as a separate operator step only after the crash PASS:

```bash
sd4_recover() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_4_RECOVERY=FAIL reason=cannot_cd'; return 1; }
  umask 077
  nohup ./run_sra_api.sh > /tmp/sra-sd4-recovery.log 2>&1 </dev/null &
  local pid=$! start
  start=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null) || { echo 'SD_4_RECOVERY=FAIL reason=exited'; return 1; }
  sleep 18
  [ "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$start" ] || { echo 'SD_4_RECOVERY=FAIL reason=exited_or_reused'; tail -n 40 /tmp/sra-sd4-recovery.log; return 1; }
  verify_sra_runtime || return 1
  echo 'SD_4_RECOVERY=PASS'
}
sd4_recover
```

PASS requires audit evidence that each recorded orphan was revalidated before
TERM/KILL, flock transferred, the API listener transferred, and no `ABORT` or
unverified signal occurred. Logs are bounded with `tail -n 80` and redacted before
sharing.

## SD-5 — LIVE_RUNTIME_START_GATE

The runtime was started only by `./run_sra_api.sh`; neither worker may be started
manually. Run the exact verifier, then this read-only SQL observation. It selects
only owner/generation/expiry and never selects the lease token.

```bash
sd5_observe() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_5=FAIL reason=cannot_cd'; return 1; }
  verify_sra_runtime || return 1
  python - <<'PY'
import os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from data_ingestion.requirements.connections import SqlRegistry
r=SqlRegistry.load(os.getenv('REQUIREMENT_SQL_REGISTRY_FILE','config/requirements/sql_registry.json'))
c=r.open_named_connection(os.getenv('REQUIREMENT_CONTROL_DB_CONNECTION','requirement_control')); s=os.getenv('REQUIREMENT_SCHEDULE_DB_SCHEMA','sra_schedule')
try:
 q=c.cursor(); q.execute(f"SELECT owner_id,fencing_generation,CASE WHEN expires_at>SYSDATETIMEOFFSET() THEN 1 ELSE 0 END FROM [{s}].[requirement_handoff_coordinator_leases] WHERE control_domain=?",'requirement-report-v1'); row=q.fetchone()
finally: c.close()
h=dict(x.split('=',1) for x in Path('.run_sra_api_handoff.identity').read_text().splitlines())
expected=os.getenv('REQUIREMENT_HANDOFF_OWNER_ID') or 'handoff-'+h['pid']
ok=bool(row) and row[0]==expected and int(row[2])==1
if row: print(f'SD_5_LEASE_OWNER={row[0]} GENERATION={int(row[1])} LIVE={int(row[2])}')
print('SD_5='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
}
sd5_observe
```

PASS also requires unchanged protected-state SHA/key ID from SD-3 and bounded
worker logs without startup/invariant errors. HTTP 200 or live PIDs alone fail.

## SD-6 — RESTART_IDEMPOTENCY_GATE

Run `verify_sra_runtime`, then capture: exact identity records, protected-state
SHA-256 and selected public key ID, and the read-only lease projection used by
SD-5. Store the evidence in owner-only `/tmp/sra-sd6-before` (`umask 077`). Never
store a raw credential or lease token.

```bash
sd6_snapshot() {
  local label="$1"
  [ "$label" = before ] || [ "$label" = after ] || { echo 'SD_6_SNAPSHOT=FAIL reason=label'; return 1; }
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_SNAPSHOT=FAIL reason=cannot_cd'; return 1; }
  verify_sra_runtime || return 1
  SD6_LABEL="$label" python - <<'PY'
import hashlib, os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
p=d/'requirement_handoff.env'; values=dict(x.split('=',1) for x in p.read_text().splitlines())
label=os.environ['SD6_LABEL'].upper()
print(f'SD_6_{label}_KEY_ID='+values['SRA_BOOTSTRAP_HANDOFF_KEY_ID'])
print(f'SD_6_{label}_STATE_SHA256='+hashlib.sha256(p.read_bytes()).hexdigest())
for role in ('launcher','api','schedule','handoff'):
 x=dict(line.split('=',1) for line in Path(f'.run_sra_api_{role}.identity').read_text().splitlines())
 print(f'SD_6_{label}_{role.upper()}_PID='+x.get('api_pid',x.get('pid','')))
PY
  # Run the read-only lease projection from SD-5 and retain its owner,
  # generation, and live fields with this snapshot's evidence.
  sd5_observe || return 1
  echo "SD_6_${label}=PASS"
}
sd6_snapshot before
```

Invoke only the supported takeover path:

```bash
sd6_restart() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_ACTION=FAIL reason=cannot_cd'; return 1; }
  verify_sra_runtime || return 1
  umask 077
  cp .run_sra_api_{launcher,api,schedule,handoff}.identity /tmp/sra-sd6-before/ 2>/dev/null || { mkdir -m 700 -p /tmp/sra-sd6-before; cp .run_sra_api_{launcher,api,schedule,handoff}.identity /tmp/sra-sd6-before/; }
  nohup ./run_sra_api.sh > /tmp/sra-sd6-restart.log 2>&1 </dev/null &
  local pid=$! start
  start=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null) || { echo 'SD_6_ACTION=FAIL reason=contender_exited'; return 1; }
  sleep 20
  [ "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$start" ] || { echo 'SD_6_ACTION=FAIL reason=contender_exited_or_reused'; tail -n 50 /tmp/sra-sd6-restart.log; return 1; }
  verify_sra_runtime || return 1
  echo 'SD_6_ACTION=PASS'
}
sd6_restart
```

Before executing, run `sd6_snapshot before`; afterward run `sd6_snapshot after`.
PASS requires all
four exact identities to change, old launcher TERM only through the new launcher,
no timeout/SIGKILL, listener transfer, OpenAPI readiness, unchanged state SHA and
key ID, and a greater live lease generation. Source allows an explicit
`REQUIREMENT_HANDOFF_OWNER_ID`; when configured, owner equality is expected rather
than false failure. Without it, owner must change to `handoff-<new-pid>`.

## SD-7 — MIGRATION_CLEANUP_GATE

### Fail-closed boundary

Current source defines the new root beneath `SRA_DEPLOYMENT_STATE_DIR`, freezes its
canonical-path SHA-256 on each Batch Run, and has no universal legacy path, output
migration, or SQL fingerprint repair. Never guess a legacy root. Never delete an
old root: terminal artifacts remain bound to it. Any nonterminal item bound to an
old fingerprint is `SD_7=BLOCKED`.

`/tmp/auto3-handoff.env` is not intrinsically authoritative. Use it only when an
external acceptance record positively identifies that exact owner-only, non-
symlink file. Parse only named fields in-process; never source or display it.
Validate artifacts only for selected items. Item terminal states are exactly
`completed`, `failed`, `recovery_required`, and `expired`; `completed_with_failures`
is a Batch state and `not_selected` is not a selected terminal execution state.

The read-only SQL projection is:

```sql
SELECT r.batch_run_id,i.run_item_id,i.execution_state,
       i.artifact_relative_path,i.artifact_sha256
FROM [<validated-schema>].[requirement_batch_runs] r
JOIN [<validated-schema>].[requirement_batch_run_items] i
  ON i.batch_run_id=r.batch_run_id
WHERE r.phase1a_output_root_fingerprint=?
  AND i.selection_status='selected'
ORDER BY r.batch_run_id,i.run_item_id;
```

The operator parser must then prove containment beneath the exact legacy root,
regular-file status, DOCX package validity, and persisted SHA-256 for every row
with an artifact. A completed item without an artifact is FAIL. A nonterminal row,
missing digest, symlink, missing file, traversal, or mismatch is BLOCKED/FAIL; no
SQL or filesystem repair is authorized. The durable current root must be the
exact value in protected generated state, owner-controlled, mode `0700`, writable,
and have a distinct fingerprint. If no authenticated legacy evidence exists,
record `SD_7=NOT_APPLICABLE`; do not manufacture it.

### Legacy credential revocation

Revocation is optional unless an independently recorded acceptance-only key and
an existing job owned by it both exist. Similar name, scopes, creator, hint, or
age are insufficient. Before mutation, require a credential-administration freeze
and repeat all checks in the same gate session:

1. protected legacy credential resolves through `ServiceKeyStore.resolve()` to
   the exact recorded key ID;
2. it differs from the current protected canonical key ID;
3. it obtains HTTP 200 for the exact recorded, already-existing owned Report Job;
4. `verify_sra_runtime` and the durable-root/artifact checks pass;
5. `python -m api.security.cli list-service-keys` reports that exact ID active.

The generic package intentionally does **not** provide a pasteable revocation
command. The current supported CLI accepts an arbitrary key ID and does not itself
assert “noncanonical + resolves from this legacy file + owns this existing job.”
Splitting those guards from a naked CLI invocation leaves a time-of-check/time-of-
use authorization gap. If cleanup applies, stop here and obtain an instance-bound,
separately reviewed revocation addendum that repeats the five guards immediately
before its one exact CLI mutation and immediately proves: the same credential no
longer resolves; the same request returns 401; the exact public status is revoked;
the canonical selected key remains active; and `verify_sra_runtime` still passes.
The raw credential and Authorization header must remain inside the verifier process.

```bash
sd7_revocation_disposition() {
  echo 'SD_7=BLOCKED reason=instance_bound_revocation_addendum_required'
  return 2
}
sd7_revocation_disposition
```

This BLOCKED result is the safe gate outcome, not a runtime failure. If no legacy
credential exists, record revocation `NOT_APPLICABLE` after the durable root and
artifact evidence is reviewed; do not run the blocking function merely to create
a blocker.

After the gate, remove only non-secret shell variables:

```bash
unset LEGACY_ENV_FILE LEGACY_KEY_ID LEGACY_REPORT_JOB_ID
```

## Evidence and final report

Share at most the last 80 relevant log lines after redacting
`sra_sk_[A-Za-z0-9_-]+`. Do not use `cat` on secret-bearing files. Report:

```text
Repository: hun186/poc-agent
Reviewed commit: 2ef993e34629828128ff5244422c3440a4e305f3
Runbook: v1.1
Gate executed:
Identity mode:
Precheck/action/verify marker:
Observed FAIL/BLOCKED marker:
Golden Path replayed: NO
Raw credential included: NO
Approval requested for next gate: YES/NO
```

All gates remain **PENDING** until their live evidence is separately reviewed.

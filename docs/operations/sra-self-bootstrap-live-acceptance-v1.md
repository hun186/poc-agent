# SRA Self-Bootstrapping Deployment Live Acceptance Package v1

## Document control

| Field | Bound value |
| --- | --- |
| Repository | `hun186/poc-agent` |
| Reviewed hosted branch | `main` |
| Reviewed baseline commit | `edcbc744f71374eaa839b0a31e0cd125fcb6fe52` |
| Baseline identity | Merge commit for PR #239, `Clarify bootstrap_env() profile logging (operator-readable precedence)` |
| Implementation lineage | PRs #233 through #238 (bootstrap, corrective hardening, graceful takeover, and Handoff shutdown/lease handoff); PR #239 is logging-only |
| Document version | `v1` |
| Status | **OPERATOR LIVE ACCEPTANCE PACKAGE / NOT YET EXECUTED** |

Hosted GitHub refresh was attempted while preparing this package, but failed with
`CONNECT tunnel failed, response 403`. The checked-out commit was independently
verified with `git rev-parse HEAD` and `git show` to be the issuance baseline above.
No newer hosted SHA is claimed.

## Authority, scope, and hard stops

The exact gate identifiers and names come from the post-merge, source-grounded
**SRA Self-Bootstrapping Deployment — Corrective Implementation Review v5**. That
review is authoritative for gate identity; current source is authoritative for
commands and expected behavior. No competing gate definitions were found.

This is a runbook, not evidence that any gate passed. Execute **one gate at a
time**, paste its bounded evidence back for review, and do not begin the next gate
until the current gate has been accepted. A `FAIL` or `BLOCKED` marker means
**STOP**. Commands never perform automatic SQL repair or automatic credential
rotation.

The already proven three-item Requirement automatic technical Golden Path is not
to be rerun as part of the seven deployment gates unless a newly discovered
blocker makes replay unavoidable and the operator explicitly approves it. Do not
create Requirement Sets, Schedules, Batch Runs, Report Jobs, Agent runs,
Elasticsearch queries, or DOCX files merely to test bootstrap plumbing.

Security rules for every gate:

* Work as the normal deployment user (`aiuser`), not root. Do not use `set -x`.
* Never paste raw Service Keys, passwords, Elasticsearch credentials, signed URL
  secrets, bootstrap secrets, cookies, or Authorization headers.
* Never `cat` `.env`, the generated `requirement_handoff.env`, a legacy Handoff
  env file, the Service Key store, or the SQL registry.
* Never use `pkill`, `killall`, broad `pgrep -f`, or a blind signal. Gate 4's
  deliberate crash signal is authorized only after exact launcher identity is
  revalidated immediately before the signal.
* Do not delete durable state to simulate first run. Do not edit SQL lease,
  fingerprint, or artifact rows. Do not manually start either worker.

Unless deployment configuration intentionally overrides them, source defaults are:

```text
project root: /mntCZJ/TopicClassification/poc-agent
port:         9002
state dir:    /mntCZJ/TopicClassification/poc-agent/.sra_runtime (0700)
state file:   .sra_runtime/requirement_handoff.env (0600)
output root:  .sra_runtime/requirement_handoff_output
key name:     requirement-handoff-runtime
key scopes:   report:job:create, report:job:download, report:job:read
lease domain: requirement-report-v1
SQL schema:   sra_schedule (unless REQUIREMENT_SCHEDULE_DB_SCHEMA overrides it)
```

The generated state file is the deployed authority when an allowed path override
is present. It contains a credential, so the commands below parse only named
non-secret fields and never display its contents.

## Common shell setup (read-only)

Run this at the beginning of each SSH session. It changes only the shell's working
directory and variables.

```bash
accept_setup() {
  BASE=/mntCZJ/TopicClassification/poc-agent
  [ "$(id -un)" = aiuser ] || { echo 'ACCEPT_SETUP=FAIL reason=wrong_user'; return 1; }
  [ -d "$BASE/.git" ] || { echo 'ACCEPT_SETUP=FAIL reason=project_missing'; return 1; }
  cd "$BASE" || { echo 'ACCEPT_SETUP=FAIL reason=cannot_cd'; return 1; }
  printf 'ACCEPT_SETUP=PASS user=%s root=%s\n' "$(id -un)" "$BASE"
}
accept_setup
```

If `aiuser` is not the intentionally configured runtime owner, STOP and have the
deployment owner amend/review this package; do not substitute root casually.

---

## SD-1 — DEPLOYMENT_SOURCE_GATE

### Purpose

Prove that the deployed checkout is the reviewed repository, branch baseline, and
clean source artifact before any launcher mutation occurs.

### Preconditions

* The checkout exists at the expected project root.
* No command in this gate starts or stops a process.
* The deployment owner has intentionally installed the issuance commit. Because
  hosted refresh was unavailable during package preparation, a different SHA is
  not implicitly accepted.

### Read-only precheck

```bash
sd1_precheck() {
  local expected=edcbc744f71374eaa839b0a31e0cd125fcb6fe52 head branch dirty
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_1_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  head=$(git rev-parse HEAD 2>/dev/null) || { echo 'SD_1_PRECHECK=FAIL reason=not_git'; return 1; }
  branch=$(git branch --show-current 2>/dev/null)
  dirty=$(git status --porcelain=v1 --untracked-files=no)
  printf 'SD_1_HEAD=%s\nSD_1_BRANCH=%s\n' "$head" "$branch"
  [ "$head" = "$expected" ] || { echo 'SD_1_PRECHECK=FAIL reason=baseline_mismatch'; return 1; }
  [ -z "$dirty" ] || { echo 'SD_1_PRECHECK=FAIL reason=tracked_changes'; return 1; }
  git cat-file -e "$expected^{commit}" 2>/dev/null || { echo 'SD_1_PRECHECK=FAIL reason=commit_unreadable'; return 1; }
  for f in run_sra_api.sh config/deployment_bootstrap.py requirement_scheduler/cli.py .gitattributes; do
    [ -f "$f" ] || { echo "SD_1_PRECHECK=FAIL reason=missing_file file=$f"; return 1; }
  done
  echo 'SD_1_PRECHECK=PASS'
}
sd1_precheck
```

### Operator action

No durable mutation is required. Record a bounded source identity:

```bash
sd1_action() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_1_ACTION=FAIL'; return 1; }
  git show -s --format='SD_1_COMMIT=%H%nSD_1_SUBJECT=%s%nSD_1_PARENTS=%P' HEAD
  printf 'SD_1_TRACKED_RUNTIME_FILES='; git ls-files run_sra_api.sh config/deployment_bootstrap.py requirement_scheduler/cli.py | wc -l
  echo 'SD_1_ACTION=PASS'
}
sd1_action
```

### Expected evidence and PASS criteria

`SD_1_HEAD` and `SD_1_COMMIT` equal the bound 40-character commit, tracked source
is clean, all four files exist, and both final markers are `PASS`. A local branch
name other than `main` is acceptable only when HEAD is exact (detached deployment
checkouts are common); it must be recorded.

### FAIL criteria and stop condition

Any SHA mismatch, missing file, unreadable commit, or tracked change is FAIL.
STOP without launching. Collect `git status --short --branch` and `git log -3
--oneline --decorate`; do not reset or pull automatically.

### Evidence to paste back into ChatGPT

```bash
{ git status --short --branch; git show -s --format='commit=%H%nparents=%P%nsubject=%s' HEAD; } 2>&1 | tail -n 12
```

---

## SD-2 — LF_PACKAGE_GATE

### Purpose

Prove non-mutatively that every tracked shell launcher in the deployed artifact
uses LF and that the checked-in attributes require LF. CRLF is a packaging failure,
not something acceptance may repair with `sed -i`.

### Preconditions

Gate 1 is accepted and the checkout is still unchanged.

### Read-only precheck

```bash
sd2_precheck() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_2_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  git check-attr text eol -- '*.sh'
  git check-attr eol -- run_sra_api.sh | grep -q 'eol: lf' || { echo 'SD_2_PRECHECK=FAIL reason=lf_attribute_missing'; return 1; }
  echo 'SD_2_PRECHECK=PASS'
}
sd2_precheck
```

### Operator action

```bash
sd2_action() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_2_ACTION=FAIL reason=cannot_cd'; return 1; }
  local failed=0 count=0 f
  while IFS= read -r f; do
    count=$((count + 1))
    if python - "$f" <<'PY'
import pathlib, sys
raise SystemExit(1 if b'\r\n' in pathlib.Path(sys.argv[1]).read_bytes() else 0)
PY
    then printf 'SD_2_FILE=PASS path=%s\n' "$f"
    else printf 'SD_2_FILE=FAIL path=%s reason=crlf\n' "$f"; failed=1
    fi
  done < <(git ls-files '*.sh')
  [ "$count" -gt 0 ] || { echo 'SD_2_ACTION=FAIL reason=no_shell_files'; return 1; }
  [ "$failed" -eq 0 ] || { echo 'SD_2_ACTION=FAIL reason=crlf_detected'; return 1; }
  bash -n run_sra_api.sh || { echo 'SD_2_ACTION=FAIL reason=bash_syntax'; return 1; }
  printf 'SD_2_ACTION=PASS checked=%s\n' "$count"
}
sd2_action
```

### Expected evidence and PASS criteria

The attribute is `eol: lf`, every tracked `*.sh` produces `SD_2_FILE=PASS`, Bash
syntax passes, and the final marker passes.

### FAIL criteria and stop condition

Any CRLF, missing LF attribute, unreadable file, zero checked shell files, or Bash
syntax error is FAIL. STOP. Preserve the artifact and correct the repository or
packaging pipeline; do not mutate deployed scripts in place.

### Evidence to paste back into ChatGPT

```bash
{ git check-attr text eol -- '*.sh'; python - <<'PY'
import pathlib, subprocess
files=subprocess.check_output(['git','ls-files','*.sh'], text=True).splitlines()
bad=[p for p in files if b'\r\n' in pathlib.Path(p).read_bytes()]
print(f'SD_2_EVIDENCE_checked={len(files)} crlf={len(bad)}')
for p in bad[:10]: print('CRLF_FILE='+p)
PY
} 2>&1 | tail -n 30
```

---

## SD-3 — BOOTSTRAP_FIRST_RUN_GATE

### Purpose

On a genuinely unprovisioned authorized deployment, prove that the normal
operator entrypoint performs server-owned first-run provisioning, creates one
dedicated minimum-scope Handoff key, writes persistent owner-only state/output
directories, and fails closed if prerequisite configuration is invalid.

### Preconditions

* Gates 1 and 2 are accepted.
* This deployment is genuinely first-run: the configured state file does not
  exist and there is no active key named `requirement-handoff-runtime`.
* SQL registry settings, referenced secret environment variables, ODBC driver,
  and stable signed-URL secret are configured. Private SQL is reachable so the
  workers can initialize.
* Port 9002 has no unrelated listener.
* **Do not delete, rename, or back up-and-remove existing durable state to force
  this precondition.** If state or the canonical key already exists, emit
  `BLOCKED_ALREADY_PROVISIONED` and use contemporaneous first-run operator evidence
  from the deployment installation; a restart is not first-run proof.

### Read-only precheck

This parser prints metadata only. It never prints key material or config values.

```bash
sd3_precheck() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_3_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from sra_api.security.service_key_store import ServiceKeyStore
state_dir=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR', '.sra_runtime'))
if not state_dir.is_absolute(): state_dir=Path.cwd()/state_dir
store=ServiceKeyStore(Path(os.getenv('SRA_SERVICE_KEYS_FILE', '.sra_service_keys.json')))
active=[k for k in store.list_keys() if k.get('name')=='requirement-handoff-runtime' and k.get('status')=='active']
state=state_dir/'requirement_handoff.env'
print('SD_3_STATE_PRESENT='+('YES' if state.exists() or state.is_symlink() else 'NO'))
print('SD_3_ACTIVE_CANONICAL_COUNT='+str(len(active)))
required=['REQUIREMENT_SQL_REGISTRY_FILE','SRA_SIGNED_URL_SECRET']
for name in required: print(f'SD_3_ENV_{name}='+('SET' if os.getenv(name) else 'DEFAULT_OR_MISSING'))
if state.exists() or state.is_symlink() or active:
    print('SD_3_PRECHECK=BLOCKED_ALREADY_PROVISIONED')
    raise SystemExit(2)
print('SD_3_PRECHECK=PASS')
PY
}
sd3_precheck
```

### Operator action

Start **only** the supervisor; it starts both workers. Keep this SSH terminal open,
or use the deployment's existing service manager to run this exact entrypoint. The
background form below is safe for an interactive acceptance terminal and records
only launcher console output.

```bash
sd3_action() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_3_ACTION=FAIL reason=cannot_cd'; return 1; }
  umask 077
  nohup ./run_sra_api.sh > /tmp/sra-sd3-launcher.log 2>&1 </dev/null &
  printf '%s\n' "$!" > /tmp/sra-sd3-invocation.pid
  sleep 18
  if kill -0 "$!" 2>/dev/null; then echo "SD_3_ACTION=PASS launcher_pid=$!"
  else echo 'SD_3_ACTION=FAIL reason=launcher_exited'; tail -n 30 /tmp/sra-sd3-launcher.log; return 1
  fi
}
sd3_action
```

Then inspect durable metadata without showing the credential:

```bash
sd3_verify() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_3_VERIFY=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import os, stat
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from config.deployment_bootstrap import KEY_NAME, KEY_SCOPES, STATE_KEYS
from sra_api.security.service_key_store import ServiceKeyStore
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
p=d/'requirement_handoff.env'; out=d/'requirement_handoff_output'
def mode(path): return format(stat.S_IMODE(path.stat().st_mode),'04o')
try:
    raw=p.read_bytes()
    values=dict(line.split('=',1) for line in raw.decode().splitlines())
except Exception:
    print('SD_3_VERIFY=FAIL reason=state_unreadable'); raise SystemExit(1)
if set(values)!=set(STATE_KEYS) or b'\r' in raw or b'\0' in raw:
    print('SD_3_VERIFY=FAIL reason=state_shape'); raise SystemExit(1)
store=ServiceKeyStore(Path(os.getenv('SRA_SERVICE_KEYS_FILE','.sra_service_keys.json')))
keys=[k for k in store.list_keys() if k.get('name')==KEY_NAME and k.get('status')=='active']
selected=[k for k in keys if k.get('key_id')==values.get('SRA_BOOTSTRAP_HANDOFF_KEY_ID')]
print(f'SD_3_STATE_DIR_MODE={mode(d)}')
print(f'SD_3_STATE_FILE_MODE={mode(p)}')
print(f'SD_3_OUTPUT_DIR_MODE={mode(out)}')
print(f'SD_3_ACTIVE_CANONICAL_COUNT={len(keys)}')
print('SD_3_SELECTED_KEY_MATCH='+('YES' if len(selected)==1 else 'NO'))
print('SD_3_SCOPES='+(','.join(selected[0]['scopes']) if selected else 'UNAVAILABLE'))
print('SD_3_OPENWEBUI_SEPARATE='+('YES' if not any(k.get('name','').lower().startswith('openwebui') and k.get('key_id')==values.get('SRA_BOOTSTRAP_HANDOFF_KEY_ID') for k in store.list_keys()) else 'NO'))
ok=(mode(d)=='0700' and mode(p)=='0600' and mode(out)=='0700' and len(keys)==1 and len(selected)==1 and frozenset(selected[0]['scopes'])==KEY_SCOPES)
print('SD_3_VERIFY='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
}
sd3_verify
```

### Expected evidence and PASS criteria

First-run logs show bootstrap before runtime startup without a secret value; state
and output are persistent beneath the configured state directory; modes are
`0700/0600/0700`; exactly one active canonical key is selected; its scopes are
exactly `report:job:create,report:job:download,report:job:read`; it is distinct
from OpenWebUI; the launcher remains live. No `/tmp/auto3-handoff.env` or manual
Handoff exports are used.

### FAIL criteria and stop condition

Existing provisioning makes the gate BLOCKED, not PASS. Any bootstrap error,
launcher exit, wrong permissions, missing output root, ambiguous key, extra/missing
scope, or printed secret is FAIL. STOP; do not invoke `repair-handoff-credential`
or rotate anything. Collect the safe error category and bounded logs.

### Evidence to paste back into ChatGPT

```bash
{ tail -n 35 /tmp/sra-sd3-launcher.log 2>/dev/null; tail -n 20 SRA-API_output.txt 2>/dev/null; tail -n 20 SRA-ScheduleWorker_output.txt 2>/dev/null; tail -n 20 SRA-HandoffWorker_output.txt 2>/dev/null; } | sed -E 's/sra_sk_[A-Za-z0-9_-]+/[REDACTED_SERVICE_KEY]/g' | tail -n 80
```

---

## SD-4 — FLOCK_ORPHAN_RECOVERY_GATE

### Purpose

Prove the reviewed crash boundary: a killed launcher releases `flock`, while the
replacement launcher positively identifies and reclaims only its recorded orphan
API/workers before starting one healthy replacement runtime.

### Preconditions

* Gate 3 is accepted (or equivalent genuine first-run evidence was reviewed).
* The runtime is healthy and owned by the exact launcher identity record.
* No Requirement acceptance workload is being created or intentionally processed.
* The operator explicitly authorizes a deliberate launcher crash. This is a
  destructive availability test; verification and mutation are separated below.

### Read-only precheck (verification phase)

```bash
sd4_precheck() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_4_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import os
from pathlib import Path
p=Path('.run_sra_api_launcher.identity')
try: v=dict(x.split('=',1) for x in p.read_text().splitlines()); pid=int(v['pid']); start=v['process_start_time']
except Exception: print('SD_4_PRECHECK=FAIL reason=identity_invalid'); raise SystemExit(1)
proc=Path('/proc')/str(pid)
try:
    actual=(proc/'stat').read_text().split()[21]
    uid=next(x.split()[1] for x in (proc/'status').read_text().splitlines() if x.startswith('Uid:'))
    argv=(proc/'cmdline').read_bytes().split(b'\0')
    script=(Path(os.readlink(proc/'cwd'))/argv[1].decode()).resolve() if not argv[1].decode().startswith('/') else Path(argv[1].decode()).resolve()
    ok=(actual==start and int(uid)==os.geteuid() and Path(os.readlink(proc/'cwd')).resolve()==Path.cwd().resolve() and script==Path('run_sra_api.sh').resolve() and Path(v['launcher_path'])==Path('run_sra_api.sh').resolve())
except Exception: ok=False
print(f'SD_4_VERIFIED_LAUNCHER_PID={pid}')
print(f'SD_4_VERIFIED_LAUNCHER_START={start}')
print('SD_4_PRECHECK='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
  for f in .run_sra_api_api.identity .run_sra_api_schedule.identity .run_sra_api_handoff.identity; do
    [ -f "$f" ] || { echo "SD_4_PRECHECK=FAIL reason=missing_identity file=$f"; return 1; }
  done
}
sd4_precheck
```

### Operator action (mutation phase)

Run only after reviewing the preceding exact PID/start-time evidence. The Python
code revalidates the same UID, start time, cwd, launcher path, and argv immediately
before sending SIGKILL; it refuses on drift. It does not signal by name pattern.

```bash
sd4_crash_verified_launcher() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_4_CRASH=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import os, signal
from pathlib import Path
p=Path('.run_sra_api_launcher.identity')
try:
    v=dict(x.split('=',1) for x in p.read_text().splitlines()); pid=int(v['pid']); proc=Path('/proc')/str(pid)
    actual=(proc/'stat').read_text().split()[21]
    uid=int(next(x.split()[1] for x in (proc/'status').read_text().splitlines() if x.startswith('Uid:')))
    argv=(proc/'cmdline').read_bytes().split(b'\0'); cwd=Path(os.readlink(proc/'cwd')).resolve()
    script=(cwd/argv[1].decode()).resolve() if not argv[1].decode().startswith('/') else Path(argv[1].decode()).resolve()
    ok=(actual==v['process_start_time'] and uid==os.geteuid() and cwd==Path.cwd().resolve() and script==Path('run_sra_api.sh').resolve() and Path(v['launcher_path'])==script)
except Exception: ok=False
if not ok: print('SD_4_CRASH=FAIL reason=identity_changed_no_signal'); raise SystemExit(1)
os.kill(pid, signal.SIGKILL)
print(f'SD_4_CRASH=PASS exact_pid={pid} exact_start={actual}')
PY
}
sd4_crash_verified_launcher
sleep 2
umask 077
nohup ./run_sra_api.sh > /tmp/sra-sd4-recovery.log 2>&1 </dev/null &
printf 'SD_4_RECOVERY_INVOCATION_PID=%s\n' "$!"
sleep 18
kill -0 "$!" 2>/dev/null && echo 'SD_4_ACTION=PASS' || { echo 'SD_4_ACTION=FAIL reason=recovery_exited'; tail -n 40 /tmp/sra-sd4-recovery.log; }
```

### Expected evidence and PASS criteria

The runtime lock becomes available after the exact launcher crash; the recovery
audit positively identifies stale worker and API PIDs/start times before signals;
the old API releases port 9002; one replacement API and two replacement workers
remain; and no audit `ABORT ... unverified` entry occurs. SIGKILL of the deliberately
crashed launcher is not a substitute for Gate 6's graceful restart proof.

### FAIL criteria and stop condition

Identity revalidation failure, busy lock after launcher death, unverified live
identity, unrelated port owner, recovery timeout/exit, or evidence that an unrelated
PID was signaled is FAIL. STOP. Do not broaden matching or kill remaining processes.

### Evidence to paste back into ChatGPT

```bash
{ tail -n 45 /tmp/sra-sd4-recovery.log 2>/dev/null; tail -n 60 SRA-API_kill_audit.log 2>/dev/null; for f in .run_sra_api_launcher.identity .run_sra_api_api.identity .run_sra_api_schedule.identity .run_sra_api_handoff.identity; do printf '%s ' "$f"; awk -F= '$1=="pid"||$1=="api_pid"||$1=="process_start_time"||$1=="role"||$1=="port"{print}' "$f" 2>/dev/null; done; } | tail -n 120
```

---

## SD-5 — LIVE_RUNTIME_START_GATE

### Purpose

Prove the live supervisor-owned API, OpenAPI readiness, both workers, canonical
credential metadata, durable state reuse, and active SQL Handoff lease without
executing a Golden Path workload.

### Preconditions

* Gates 1–4 are accepted and one recovered runtime is running.
* Private SQL is reachable and the deployed user may read the Handoff lease row.
* No manual worker process exists. Existing durable state is not modified.

### Read-only precheck

```bash
sd5_precheck() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_5_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  for f in .run_sra_api_launcher.identity .run_sra_api_api.identity .run_sra_api_schedule.identity .run_sra_api_handoff.identity; do
    [ -f "$f" ] || { echo "SD_5_PRECHECK=FAIL reason=missing_identity file=$f"; return 1; }
  done
  python - <<'PY'
import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:9002/openapi.json', timeout=5) as r:
        body=r.read(2_000_000); ok=r.status==200 and b'"openapi"' in body
except Exception: ok=False
print('SD_5_OPENAPI='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
  echo 'SD_5_PRECHECK=PASS'
}
sd5_precheck
```

### Operator action

This is a read-only live observation; it opens the configured SQL connection and
prints no connection string, password, or lease token.

```bash
sd5_action() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_5_ACTION=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from data_ingestion.requirements.connections import SqlRegistry
reg=SqlRegistry.load(os.getenv('REQUIREMENT_SQL_REGISTRY_FILE','config/requirements/sql_registry.json'))
name=os.getenv('REQUIREMENT_CONTROL_DB_CONNECTION','requirement_control')
schema=os.getenv('REQUIREMENT_SCHEDULE_DB_SCHEMA','sra_schedule')
conn=reg.open_named_connection(name)
try:
    c=conn.cursor(); c.execute(f"SELECT owner_id,fencing_generation,CASE WHEN expires_at>SYSDATETIMEOFFSET() THEN 1 ELSE 0 END FROM [{schema}].[requirement_handoff_coordinator_leases] WHERE control_domain=?",'requirement-report-v1')
    row=c.fetchone()
finally: conn.close()
if not row: print('SD_5_LEASE=FAIL reason=missing'); raise SystemExit(1)
print(f'SD_5_LEASE_OWNER={row[0]}')
print(f'SD_5_LEASE_GENERATION={int(row[1])}')
print(f'SD_5_LEASE_LIVE={"YES" if int(row[2]) else "NO"}')
print('SD_5_ACTION='+('PASS' if int(row[2]) else 'FAIL'))
raise SystemExit(0 if int(row[2]) else 1)
PY
  python - <<'PY'
from pathlib import Path
for role in ('api','schedule','handoff'):
 p=Path(f'.run_sra_api_{role}.identity'); v=dict(x.split('=',1) for x in p.read_text().splitlines()); pid=v.get('api_pid',v.get('pid',''))
 live=pid.isdigit() and (Path('/proc')/pid).exists()
 print(f'SD_5_PROCESS_{role.upper()}={"PASS" if live else "FAIL"} pid={pid}')
 if not live: raise SystemExit(1)
print('SD_5_PROCESSES=PASS')
PY
}
sd5_action
```

### Expected evidence and PASS criteria

`/openapi.json` is HTTP 200 and valid OpenAPI JSON; the recorded API, Schedule
Worker, and Handoff Worker PIDs are live; SQL has one unexpired
`requirement-report-v1` lease owned by the Handoff PID-derived owner; canonical
state/key metadata remains exactly as proven in Gate 3. Merely exiting zero is not
sufficient.

### FAIL criteria and stop condition

Readiness failure, any dead/changed recorded child, missing/expired lease, SQL
connection failure, or credential/state drift is FAIL. STOP. Do not alter the SQL
row, manually launch a worker, or rotate a credential. Collect safe logs only.

### Evidence to paste back into ChatGPT

```bash
{ curl -sS -o /dev/null -w 'SD_5_OPENAPI_HTTP=%{http_code}\n' http://127.0.0.1:9002/openapi.json; for f in .run_sra_api_{launcher,api,schedule,handoff}.identity; do echo "FILE=$f"; awk -F= '$1=="pid"||$1=="api_pid"||$1=="process_start_time"||$1=="role"||$1=="port"{print}' "$f" 2>/dev/null; done; tail -n 20 SRA-ScheduleWorker_output.txt; tail -n 20 SRA-HandoffWorker_output.txt; } 2>&1 | tail -n 80
```

---

## SD-6 — RESTART_IDEMPOTENCY_GATE

### Purpose

Prove repeated invocation is a verified graceful restart/takeover: only the exact
old launcher receives TERM; its coordinator reaches normal lease release; lock and
port hand off; replacement API becomes OpenAPI-ready; workers are healthy; durable
state/key identity is reused; and SQL lease is reacquired with new owner/generation.

### Preconditions

* Gate 5 is accepted and the runtime is healthy.
* No unrelated listener or manual worker exists.
* Keep a second SSH terminal available for observation. No workload is submitted.

### Read-only precheck

Capture non-secret before evidence:

```bash
sd6_precheck() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import hashlib, os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
p=d/'requirement_handoff.env'; v=dict(x.split('=',1) for x in p.read_text().splitlines())
print('SD_6_BEFORE_KEY_ID='+v['SRA_BOOTSTRAP_HANDOFF_KEY_ID'])
print('SD_6_BEFORE_STATE_SHA256='+hashlib.sha256(p.read_bytes()).hexdigest())
for role in ('launcher','api','schedule','handoff'):
 q=Path(f'.run_sra_api_{role}.identity'); x=dict(line.split('=',1) for line in q.read_text().splitlines()); print(f'SD_6_BEFORE_{role.upper()}_PID='+x.get('api_pid',x.get('pid','')))
print('SD_6_PRECHECK=PASS')
PY
  python - <<'PY' > /tmp/sra-sd6-lease-before.txt
import os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from data_ingestion.requirements.connections import SqlRegistry
r=SqlRegistry.load(os.getenv('REQUIREMENT_SQL_REGISTRY_FILE','config/requirements/sql_registry.json')); c=r.open_named_connection(os.getenv('REQUIREMENT_CONTROL_DB_CONNECTION','requirement_control')); s=os.getenv('REQUIREMENT_SCHEDULE_DB_SCHEMA','sra_schedule')
try:
 q=c.cursor(); q.execute(f"SELECT owner_id,fencing_generation,CASE WHEN expires_at>SYSDATETIMEOFFSET() THEN 1 ELSE 0 END FROM [{s}].[requirement_handoff_coordinator_leases] WHERE control_domain=?",'requirement-report-v1'); row=q.fetchone()
finally: c.close()
if not row: print('SD_6_BEFORE_LEASE=FAIL'); raise SystemExit(1)
print(f'SD_6_BEFORE_LEASE_OWNER={row[0]}\nSD_6_BEFORE_LEASE_GENERATION={int(row[1])}\nSD_6_BEFORE_LEASE_LIVE={int(row[2])}')
PY
  cat /tmp/sra-sd6-lease-before.txt
}
sd6_precheck
```

### Operator action

Invoke the same entrypoint again. Do not signal anything yourself.

```bash
sd6_action() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_ACTION=FAIL reason=cannot_cd'; return 1; }
  umask 077
  nohup ./run_sra_api.sh > /tmp/sra-sd6-restart.log 2>&1 </dev/null &
  local contender=$!
  sleep 20
  if kill -0 "$contender" 2>/dev/null; then echo "SD_6_ACTION=PASS replacement_launcher=$contender"
  else echo 'SD_6_ACTION=FAIL reason=replacement_exited'; tail -n 50 /tmp/sra-sd6-restart.log; return 1
  fi
}
sd6_action
```

Capture after evidence:

```bash
sd6_verify() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_VERIFY=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import hashlib, os, urllib.request
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
p=d/'requirement_handoff.env'; v=dict(x.split('=',1) for x in p.read_text().splitlines())
print('SD_6_AFTER_KEY_ID='+v['SRA_BOOTSTRAP_HANDOFF_KEY_ID'])
print('SD_6_AFTER_STATE_SHA256='+hashlib.sha256(p.read_bytes()).hexdigest())
for role in ('launcher','api','schedule','handoff'):
 q=Path(f'.run_sra_api_{role}.identity'); x=dict(line.split('=',1) for line in q.read_text().splitlines()); pid=x.get('api_pid',x.get('pid','')); print(f'SD_6_AFTER_{role.upper()}_PID={pid}');
 if not pid.isdigit() or not (Path('/proc')/pid).exists(): print('SD_6_VERIFY=FAIL reason=dead_child'); raise SystemExit(1)
try:
 with urllib.request.urlopen('http://127.0.0.1:9002/openapi.json',timeout=5) as r: ok=r.status==200 and b'"openapi"' in r.read(2_000_000)
except Exception: ok=False
print('SD_6_AFTER_OPENAPI='+('PASS' if ok else 'FAIL'))
if not ok: raise SystemExit(1)
PY
  python - <<'PY'
import os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from data_ingestion.requirements.connections import SqlRegistry
r=SqlRegistry.load(os.getenv('REQUIREMENT_SQL_REGISTRY_FILE','config/requirements/sql_registry.json')); c=r.open_named_connection(os.getenv('REQUIREMENT_CONTROL_DB_CONNECTION','requirement_control')); s=os.getenv('REQUIREMENT_SCHEDULE_DB_SCHEMA','sra_schedule')
try:
 q=c.cursor(); q.execute(f"SELECT owner_id,fencing_generation,CASE WHEN expires_at>SYSDATETIMEOFFSET() THEN 1 ELSE 0 END FROM [{s}].[requirement_handoff_coordinator_leases] WHERE control_domain=?",'requirement-report-v1'); row=q.fetchone()
finally: c.close()
before=dict(x.split('=',1) for x in Path('/tmp/sra-sd6-lease-before.txt').read_text().splitlines())
ok=bool(row) and int(row[2])==1 and row[0]!=before['SD_6_BEFORE_LEASE_OWNER'] and int(row[1])>int(before['SD_6_BEFORE_LEASE_GENERATION'])
if row:
 print(f'SD_6_AFTER_LEASE_OWNER={row[0]}\nSD_6_AFTER_LEASE_GENERATION={int(row[1])}\nSD_6_AFTER_LEASE_LIVE={int(row[2])}')
print('SD_6_LEASE_HANDOFF='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
  echo 'SD_6_VERIFY=PASS'
}
sd6_verify
```

### Expected evidence and PASS criteria

The console and permanent audit show `Existing verified launcher detected`, one
SIGTERM to that exact launcher, `Previous runtime stopped`, and replacement start;
there is no broad/fuzzy kill and no graceful-timeout escalation. Launcher/API/
worker PIDs change; port 9002 belongs to the recorded replacement API;
`/openapi.json` returns 200; both workers remain live. Key ID and complete protected
state SHA-256 are unchanged. SQL shows a different Handoff owner, a greater fencing
generation, and a live lease. These together are the required normal lease release/
reacquisition evidence; process replacement alone is insufficient.

### FAIL criteria and stop condition

Unverified-owner abort, timeout, SIGKILL during the graceful launcher takeover,
unchanged launcher/API identity, readiness failure, dead worker, changed state/key,
unchanged lease owner/generation, expired lease, or signal to an unrelated PID is
FAIL. STOP; do not retry automatically and do not edit the lease.

### Evidence to paste back into ChatGPT

```bash
{ cat /tmp/sra-sd6-lease-before.txt 2>/dev/null; tail -n 60 /tmp/sra-sd6-restart.log 2>/dev/null; tail -n 80 SRA-API_kill_audit.log 2>/dev/null; curl -sS -o /dev/null -w 'SD_6_OPENAPI_HTTP=%{http_code}\n' http://127.0.0.1:9002/openapi.json; } | sed -E 's/sra_sk_[A-Za-z0-9_-]+/[REDACTED_SERVICE_KEY]/g' | tail -n 150
```

---

## SD-7 — MIGRATION_CLEANUP_GATE

### Purpose

Prove durable transition away from acceptance-only temporary Handoff configuration,
preserve all previously bound artifacts, and—only after positive identity and
canonical runtime health—revoke one exact legacy acceptance credential through the
supported Service Key CLI and prove it no longer authenticates.

### Source-derived migration boundary and known gap

Current source deterministically defaults the **new** root to
`/mntCZJ/TopicClassification/poc-agent/.sra_runtime/requirement_handoff_output`
(or the same child beneath an explicitly configured `SRA_DEPLOYMENT_STATE_DIR`).
The acceptance boundary identifies `/tmp/auto3-handoff.env` as possible legacy
acceptance state, but current repository source does **not** encode one universal
old output-root path. Therefore this package does not invent one. The exact old
root for this deployment is the `REQUIREMENT_HANDOFF_OUTPUT_ROOT` value inside that
positively identified legacy file, read in-process without displaying it.

Current code has no automatic output-root migration and no SQL fingerprint repair.
Each Batch Run freezes SHA-256 of the resolved root and later Handoff stages reject
drift. Consequently:

* a nonterminal Run bound to the old fingerprint is a **BLOCKER**; STOP rather than
  editing SQL or silently redirecting it;
* terminal legacy artifacts must remain at their original root and validate against
  their persisted relative paths/digests; do not delete that root;
* new work uses the generated durable root, but this gate creates no new work;
* if no legacy file/key/artifact exists, record `NOT_APPLICABLE` for cleanup rather
  than manufacturing legacy state. Gate review decides whether the durable-state
  proof is sufficient for the deployment.

### Preconditions

* Gate 6 is accepted, including unchanged canonical key/state and live workers/lease.
* `/tmp/auto3-handoff.env`, if present, is owned by the operator and is the known
  legacy acceptance file. It is never sourced or displayed.
* For key revocation, the operator has an independently recorded **exact legacy key
  ID** and one existing legacy-key-owned Report Job ID. Similar name/scopes alone
  are not positive identity.
* Revocation occurs only after identification and verification below pass.

### Read-only precheck — durable roots and SQL bindings

The command reports only fingerprints, counts, relative paths, and validation
results. It does not display either root or a credential. Set `LEGACY_ENV_FILE` only
to the exact reviewed legacy file.

```bash
export LEGACY_ENV_FILE=/tmp/auto3-handoff.env
sd7_precheck() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_7_PRECHECK=FAIL reason=cannot_cd'; return 1; }
  [ -f "$LEGACY_ENV_FILE" ] || { echo 'SD_7_PRECHECK=NOT_APPLICABLE reason=no_legacy_file'; return 2; }
  LEGACY_ENV_FILE="$LEGACY_ENV_FILE" python - <<'PY'
import hashlib, os, zipfile
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from requirement_scheduler.artifacts import output_root_fingerprint
from data_ingestion.requirements.connections import SqlRegistry
def envfile(path):
 d={}
 for line in Path(path).read_text().splitlines():
  if line and not line.lstrip().startswith('#') and '=' in line:
   k,v=line.split('=',1); d[k.strip()]=v
 return d
legacy=envfile(os.environ['LEGACY_ENV_FILE'])
old=Path(legacy.get('REQUIREMENT_HANDOFF_OUTPUT_ROOT',''))
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
current=envfile(d/'requirement_handoff.env'); new=Path(current['REQUIREMENT_HANDOFF_OUTPUT_ROOT'])
if not str(old) or old==Path('.'):
 print('SD_7_PRECHECK=FAIL reason=legacy_root_missing'); raise SystemExit(1)
oldfp=output_root_fingerprint(old); newfp=output_root_fingerprint(new)
print('SD_7_OLD_ROOT_FINGERPRINT='+oldfp)
print('SD_7_NEW_ROOT_FINGERPRINT='+newfp)
print('SD_7_ROOTS_DISTINCT='+('YES' if oldfp!=newfp else 'NO'))
r=SqlRegistry.load(os.getenv('REQUIREMENT_SQL_REGISTRY_FILE','config/requirements/sql_registry.json')); c=r.open_named_connection(os.getenv('REQUIREMENT_CONTROL_DB_CONNECTION','requirement_control')); s=os.getenv('REQUIREMENT_SCHEDULE_DB_SCHEMA','sra_schedule')
try:
 q=c.cursor(); q.execute(f"SELECT r.batch_run_id,r.state,i.run_item_id,i.execution_state,i.artifact_relative_path,i.artifact_sha256 FROM [{s}].[requirement_batch_runs] r LEFT JOIN [{s}].[requirement_batch_run_items] i ON i.batch_run_id=r.batch_run_id WHERE r.phase1a_output_root_fingerprint=? ORDER BY r.batch_run_id,i.run_item_id",oldfp); rows=q.fetchall()
finally: c.close()
terminal={'completed','completed_with_failures','failed','recovery_required','expired','not_selected'}
nonterminal=[]; artifact_fail=[]; artifacts=0
for run_id,run_state,item_id,item_state,rel,digest in rows:
 if item_state and item_state not in terminal: nonterminal.append((run_id,item_id,item_state))
 if rel:
  artifacts+=1; p=(old/str(rel)).resolve(strict=False)
  try: p.relative_to(old.resolve(strict=False)); data=p.read_bytes(); ok=zipfile.is_zipfile(p) and hashlib.sha256(data).hexdigest()==digest
  except Exception: ok=False
  if not ok: artifact_fail.append((run_id,item_id))
print(f'SD_7_OLD_BOUND_ROWS={len(rows)}')
print(f'SD_7_OLD_BOUND_NONTERMINAL={len(nonterminal)}')
print(f'SD_7_OLD_ARTIFACTS_CHECKED={artifacts}')
print(f'SD_7_OLD_ARTIFACT_FAILURES={len(artifact_fail)}')
for x in nonterminal[:10]: print('SD_7_BLOCKED_NONTERMINAL='+'|'.join(map(str,x)))
for x in artifact_fail[:10]: print('SD_7_BAD_ARTIFACT='+'|'.join(map(str,x)))
ok=(not nonterminal and not artifact_fail and new.is_dir() and os.access(new,os.W_OK))
print('SD_7_PRECHECK='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
}
sd7_precheck
```

### Operator action — phase A: identify and verify (read-only)

Set IDs from the deployment acceptance record, never by a name-pattern search.
The command verifies that the credential inside the exact legacy file resolves to
that exact ID, is not the canonical selected ID, and authenticates an existing
legacy-owned job. It prints no token or header.

```bash
export LEGACY_KEY_ID='<exact-key-id-from-acceptance-record>'
export LEGACY_REPORT_JOB_ID='<existing-job-id-owned-by-that-key>'
sd7_identify_legacy_key() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_7_IDENTIFY=FAIL reason=cannot_cd'; return 1; }
  LEGACY_ENV_FILE="$LEGACY_ENV_FILE" LEGACY_KEY_ID="$LEGACY_KEY_ID" LEGACY_REPORT_JOB_ID="$LEGACY_REPORT_JOB_ID" python - <<'PY'
import json, os, urllib.error, urllib.request
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from sra_api.security.service_key_store import ServiceKeyStore
def envfile(path):
 d={}
 for line in Path(path).read_text().splitlines():
  if line and not line.lstrip().startswith('#') and '=' in line:
   k,v=line.split('=',1); d[k.strip()]=v
 return d
legacy=envfile(os.environ['LEGACY_ENV_FILE']); raw=legacy.get('REQUIREMENT_HANDOFF_CREDENTIAL','')
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
current=envfile(d/'requirement_handoff.env'); expected=os.environ['LEGACY_KEY_ID']
store=ServiceKeyStore(Path(os.getenv('SRA_SERVICE_KEYS_FILE','.sra_service_keys.json'))); meta=store.resolve(raw)
ok=bool(meta) and meta['key_id']==expected and expected!=current['SRA_BOOTSTRAP_HANDOFF_KEY_ID']
print('SD_7_LEGACY_RESOLVES='+('YES' if meta else 'NO'))
print('SD_7_EXACT_ID_MATCH='+('YES' if meta and meta['key_id']==expected else 'NO'))
print('SD_7_SEPARATE_FROM_CANONICAL='+('YES' if expected!=current['SRA_BOOTSTRAP_HANDOFF_KEY_ID'] else 'NO'))
if not ok: print('SD_7_IDENTIFY=FAIL'); raise SystemExit(1)
req=urllib.request.Request('http://127.0.0.1:9002/v1/report/jobs/'+os.environ['LEGACY_REPORT_JOB_ID'],headers={'Authorization':'Bearer '+raw})
try:
 with urllib.request.urlopen(req,timeout=10) as response: code=response.status; response.read(1024)
except urllib.error.HTTPError as e: code=e.code
print(f'SD_7_LEGACY_PRE_REVOKE_HTTP={code}')
print('SD_7_IDENTIFY='+('PASS' if code==200 else 'FAIL'))
raise SystemExit(0 if code==200 else 1)
PY
}
sd7_identify_legacy_key
```

If the exact key ID or an existing owned job cannot be supplied, STOP. Do not infer
identity from key name, creator, hint, age, or scopes.

### Operator action — phase B: revocation (irreversible mutation)

Only after the durable-root precheck and phase A both pass, review the exact ID on
screen and invoke the repository-supported CLI. The CLI response contains public
metadata only.

```bash
sd7_revoke_exact_legacy_key() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_7_REVOKE=FAIL reason=cannot_cd'; return 1; }
  [ -n "${LEGACY_KEY_ID:-}" ] && [ "$LEGACY_KEY_ID" != '<exact-key-id-from-acceptance-record>' ] || { echo 'SD_7_REVOKE=FAIL reason=exact_id_missing'; return 1; }
  python -m api.security.cli revoke-service-key "$LEGACY_KEY_ID" || { echo 'SD_7_REVOKE=FAIL reason=cli_failed'; return 1; }
  echo 'SD_7_REVOKE=PASS'
}
sd7_revoke_exact_legacy_key
```

### Operator action — phase C: post-revocation validation (read-only)

```bash
sd7_post_revoke() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_7_POST=FAIL reason=cannot_cd'; return 1; }
  LEGACY_ENV_FILE="$LEGACY_ENV_FILE" LEGACY_KEY_ID="$LEGACY_KEY_ID" LEGACY_REPORT_JOB_ID="$LEGACY_REPORT_JOB_ID" python - <<'PY'
import os, urllib.error, urllib.request
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from sra_api.security.service_key_store import ServiceKeyStore
d={}
for line in Path(os.environ['LEGACY_ENV_FILE']).read_text().splitlines():
 if line and not line.lstrip().startswith('#') and '=' in line:
  k,v=line.split('=',1); d[k.strip()]=v
raw=d.get('REQUIREMENT_HANDOFF_CREDENTIAL',''); store=ServiceKeyStore(Path(os.getenv('SRA_SERVICE_KEYS_FILE','.sra_service_keys.json')))
public=next((k for k in store.list_keys() if k.get('key_id')==os.environ['LEGACY_KEY_ID']),None)
req=urllib.request.Request('http://127.0.0.1:9002/v1/report/jobs/'+os.environ['LEGACY_REPORT_JOB_ID'],headers={'Authorization':'Bearer '+raw})
try:
 with urllib.request.urlopen(req,timeout=10) as response: code=response.status; response.read(1024)
except urllib.error.HTTPError as e: code=e.code
ok=bool(public) and public.get('status')=='revoked' and store.resolve(raw) is None and code==401
print('SD_7_STORE_STATUS='+(public.get('status','MISSING') if public else 'MISSING'))
print('SD_7_LEGACY_POST_REVOKE_HTTP='+str(code))
print('SD_7_POST='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
  curl -sS -o /dev/null -w 'SD_7_CANONICAL_OPENAPI_HTTP=%{http_code}\n' http://127.0.0.1:9002/openapi.json
}
sd7_post_revoke
```

### Expected evidence and PASS criteria

The new generated root is durable/writable; all old-root-bound rows are terminal;
every persisted old relative artifact that exists in SQL remains confined, readable,
valid DOCX, and SHA-256-equal; no old root is deleted; the canonical runtime remains
healthy. If cleanup applies, the exact legacy credential first resolves to the
operator-recorded noncanonical key and returns 200 for its owned existing job; the
supported CLI revokes only that ID; the same protected request then returns 401;
the canonical API remains ready. No new job or Golden Path is created.

### FAIL criteria and stop condition

Missing exact old-root evidence, any nonterminal old-root-bound Run Item, artifact
failure, root/fingerprint ambiguity, exact key mismatch, inability to prove legacy
ownership with HTTP 200, accidental selection of the canonical/OpenWebUI key,
revocation failure, post-revocation response other than 401, or canonical runtime
regression is FAIL. STOP. Do not delete files/stores, revoke another key, rotate the
canonical key, or edit SQL.

### Evidence to paste back into ChatGPT

```bash
{ printf 'LEGACY_KEY_ID=%s\n' "$LEGACY_KEY_ID"; python -m api.security.cli list-service-keys | python -c 'import json,sys; xs=json.load(sys.stdin); print(json.dumps([{"key_id":x.get("key_id"),"name":x.get("name"),"scopes":x.get("scopes"),"status":x.get("status"),"created_by":x.get("created_by"),"revoked_by":x.get("revoked_by")} for x in xs],indent=2))'; curl -sS -o /dev/null -w 'OPENAPI_HTTP=%{http_code}\n' http://127.0.0.1:9002/openapi.json; } 2>&1 | tail -n 100
```

---

## Final operator report template

Do not fill `PASS` until each gate's evidence has been reviewed. Paste only bounded,
redacted evidence.

```text
Repository: hun186/poc-agent
Baseline branch: main
Baseline commit: edcbc744f71374eaa839b0a31e0cd125fcb6fe52
Deployed root: /mntCZJ/TopicClassification/poc-agent
Operator user: aiuser
Execution UTC:
Gate executed:
Precheck marker:
Action marker:
Durable evidence marker(s):
Observed FAIL/BLOCKED marker (if any):
Golden Path replayed: NO
Raw credential included: NO
Approval requested for next gate: YES/NO
```

Until reviewed operator evidence exists, all seven live gates remain **PENDING**.
This package prepares execution only and does not self-award deployment PASS.

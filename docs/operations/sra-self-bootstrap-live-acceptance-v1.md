# SRA Self-Bootstrapping Deployment Live Acceptance Package v1.6

> **Supersedes v1.5. Do not use v1 through v1.5 for live execution.**
> The v1.6 release closes the package-manifest trust-boundary gaps while retaining
> intact Git-worktree identity as an alternative. Static review is not deployment
> acceptance; SD-1 through SD-7 remain **PENDING**.

## Document control

| Field | Bound value |
| --- | --- |
| Repository | `hun186/poc-agent` |
| Hosted branch | `main` |
| Corrective implementation baseline | `7a54f182d9c1b6d18234d6e8085b163880b26db0` (PR #245 merge) |
| Reviewed runtime baseline | `edcbc744f71374eaa839b0a31e0cd125fcb6fe52` (runtime tree; see SD-1) |
| Reviewed manifest implementation commit | `d170dc7c42cdfc5f454aa00f0ef37743aba34fd7` |
| Runtime parent | `edcbc744f71374eaa839b0a31e0cd125fcb6fe52` |
| Version | `v1.6` |
| Status | **SOURCE IMPLEMENTED; POST-MERGE REVIEW REQUIRED; SD-1 THROUGH SD-7 PENDING** |

The corrective implementation baseline is the supplied PR #245 merge. The
reviewed manifest implementation commit is the concrete Task 4 commit above;
it is not a predicted merge SHA.
Runbook identity and deployed-byte identity are deliberately separate: a future
documentation-only merge changes the former without invalidating the latter.

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

## Shared source-aligned runtime verifier (read-only)

Define this helper only for SD-4 through SD-6. It validates owner-only identity
records, their exact schemas, PID/start time, non-zombie state, effective UID,
cwd, parent launcher, worker argv, API identity/listener ownership, and parsed
OpenAPI content. It also proves the launcher owns the configured flock. PID
existence alone never passes. `lsof` is the same listener authority used by the
launcher. Each Python invocation is explicitly connected to `return 1`; no
function relies on interactive `set -e`.

```bash
verify_sra_runtime() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'RUNTIME_VERIFY=FAIL reason=cannot_cd'; return 1; }
  python - <<'PY'
import json, os, socket, stat, subprocess, urllib.request
from pathlib import Path
root=Path.cwd().resolve(); uid=os.geteuid()
def record(role, expected, exact_mode=None):
 p=Path(f'.run_sra_api_{role}.identity')
 if p.is_symlink() or not p.is_file(): raise RuntimeError(f'{role}_record_type')
 s=p.stat()
 if s.st_uid!=uid or (exact_mode is not None and stat.S_IMODE(s.st_mode)!=exact_mode): raise RuntimeError(f'{role}_record_owner_mode')
 rows=p.read_text().splitlines(); d={}
 for row in rows:
  k,sep,v=row.partition('=')
  if not sep or k in d: raise RuntimeError(f'{role}_record_shape')
  d[k]=v
 if len(rows)!=len(expected) or set(d)!=set(expected): raise RuntimeError(f'{role}_record_schema')
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
l=record('launcher',('pid','process_start_time','effective_uid','cwd','launcher_path'),0o600)
lpid=l['pid']; largv=proc(lpid,l['process_start_time'],'launcher')
if l['effective_uid']!=str(uid) or Path(l['cwd']).resolve()!=root: raise RuntimeError('launcher_stored_identity')
if len(largv)<2 or Path(largv[0]).name!='bash': raise RuntimeError('launcher_argv')
script=(root/largv[1]).resolve() if not Path(largv[1]).is_absolute() else Path(largv[1]).resolve()
if Path(l['launcher_path']).resolve()!=root/'run_sra_api.sh' or script!=root/'run_sra_api.sh':
 raise RuntimeError('launcher_argv')
# FD 9 and /proc/locks jointly bind the exact launcher to the launcher flock.
lock=(root/'.run_sra_api.lock').stat(); fd=(Path('/proc')/lpid/'fd/9')
if fd.stat().st_ino!=lock.st_ino or fd.stat().st_dev!=lock.st_dev: raise RuntimeError('launcher_lock_fd')
needle=f'{os.major(lock.st_dev):02x}:{os.minor(lock.st_dev):02x}:{lock.st_ino}'
locks=Path('/proc/locks').read_text().splitlines()
if not any(x.split()[1:4]==['FLOCK','ADVISORY','WRITE'] and x.split()[4]==lpid and x.split()[5].lower()==needle.lower() for x in locks):
 raise RuntimeError('launcher_flock_owner')
lp=int(lpid)
a=record('api',('api_pid','api_start_time','port')); apid=a['api_pid']; aargv=proc(apid,a['api_start_time'],'api',lp)
if a.get('port')!='9002': raise RuntimeError('api_port_record')
listeners=subprocess.check_output(['lsof','-t','-nP','-a','-p',apid,'-iTCP:9002','-sTCP:LISTEN'],text=True).split()
if listeners!=[apid]: raise RuntimeError('api_listener')
for role,command in [('schedule','schedule-worker'),('handoff','handoff-worker')]:
 d=record(role,('role','pid','process_start_time'),0o600); argv=proc(d['pid'],d['process_start_time'],role,lp)
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
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'RUNTIME_VERIFY=FAIL reason=source_aligned_identity'; return 1; }
}
```

## SD-1 — DEPLOYMENT_SOURCE_GATE

### Reviewed release construction (release environment only)

The authoritative release ceremony is the CLI build below. It is not a live SD-1
command and must run only against a newly staged package in the trusted release
environment. The receipt remains outside that package.

```bash
REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT=d170dc7c42cdfc5f454aa00f0ef37743aba34fd7
python tools/deployment_manifest.py build \
  --repo-root . \
  --package-root "$STAGED_PACKAGE_ROOT" \
  --source-commit "$SOURCE_COMMIT" \
  --reviewed-runtime-commit edcbc744f71374eaa839b0a31e0cd125fcb6fe52 \
  --reviewed-manifest-commit "$REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT" \
  --receipt-out "$EXTERNAL_RECEIPT_PATH"
```

The reviewed policy permits no unmanaged runtime extras. Release construction
must fail rather than remove an undeclared cache, bytecode, backup, or launcher.

### Contract and result

Package/overlay and intact Git-worktree deployments use separate, read-only
identity modes. Package mode requires `EXPECTED_MANIFEST_SHA256` copied from an
independently retained release record. Never derive it from the deployed manifest,
a release receipt copied into the same deployment, or local Git metadata. Missing
trusted authority is BLOCKED; contradictory or corrupt evidence is FAIL. Any
nonzero result stops acceptance, and SD-2 is a separate later reviewed gate.

### Package/overlay manifest action (read-only)

```bash
sd1_release_manifest() {
  local root=/mntCZJ/TopicClassification/poc-agent
  local manifest="$root/DEPLOYMENT_MANIFEST.json"
  cd "$root" || { echo 'SD_1=FAIL reason=cannot_cd'; return 1; }
  [ -n "${EXPECTED_MANIFEST_SHA256:-}" ] || {
    echo 'SD_1=BLOCKED reason=trusted_manifest_digest_missing'; return 2;
  }
  EXPECTED_MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" python - "$root" "$manifest" <<'PY'
import hashlib, json, os, re, stat, sys
from pathlib import Path
root=Path(sys.argv[1]); manifest=Path(sys.argv[2])
expected=os.environ['EXPECTED_MANIFEST_SHA256']
def exact_bytes(path, reason):
 info=path.lstat()
 if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode): raise RuntimeError(reason)
 fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
 try:
  opened=os.fstat(fd)
  if (info.st_dev,info.st_ino)!=(opened.st_dev,opened.st_ino) or not stat.S_ISREG(opened.st_mode): raise RuntimeError(reason)
  chunks=[]
  while True:
   chunk=os.read(fd,1024*1024)
   if not chunk: break
   chunks.append(chunk)
  return b''.join(chunks)
 finally: os.close(fd)
try:
 if re.fullmatch(r'[0-9a-f]{64}',expected) is None: raise RuntimeError('trusted_manifest_digest_invalid')
 raw=exact_bytes(manifest,'manifest_file_type')
 if hashlib.sha256(raw).hexdigest()!=expected: raise RuntimeError('manifest_digest_mismatch')
 value=json.loads(raw)
 reviewed_manifest=value.get('reviewed_manifest_commit') if isinstance(value,dict) else None
 if re.fullmatch(r'[0-9a-f]{40}',str(reviewed_manifest or '')) is None: raise RuntimeError('manifest_schema')
 files=value.get('files') if isinstance(value,dict) else None
 if not isinstance(files,list): raise RuntimeError('manifest_schema')
 entries=[x for x in files if isinstance(x,dict) and x.get('path')=='tools/deployment_manifest.py']
 if len(entries)!=1 or entries[0].get('class')!='release_tool' or re.fullmatch(r'[0-9a-f]{64}',str(entries[0].get('sha256',''))) is None: raise RuntimeError('verifier_manifest_identity')
 verifier=exact_bytes(root/'tools/deployment_manifest.py','verifier_file_type')
 if hashlib.sha256(verifier).hexdigest()!=entries[0]['sha256']: raise RuntimeError('verifier_hash_mismatch')
except (OSError,UnicodeDecodeError,json.JSONDecodeError,RuntimeError) as exc:
 raise SystemExit('SD_1=FAIL reason='+str(exc))
print('SD_1_MANIFEST_PRECHECK=PASS')
PY
  local rc=$?
  [ "$rc" -eq 0 ] || return "$rc"
  python tools/deployment_manifest.py verify \
    --deployment-root "$root" \
    --manifest "$manifest" \
    --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
  rc=$?
  [ "$rc" -eq 0 ] || return "$rc"
  # Success includes SD_1_REVIEWED_MANIFEST_COMMIT=<sha> from the verifier.
}
sd1_release_manifest
```

### Git-worktree action (read-only)

```bash
sd1_git_worktree() {
  local runtime=edcbc744f71374eaa839b0a31e0cd125fcb6fe52 head
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_1=FAIL reason=cannot_cd'; return 1; }
  [ -d .git ] || { echo 'SD_1=BLOCKED reason=no_authoritative_package_identity'; return 2; }
  head=$(git rev-parse HEAD 2>/dev/null) || { echo 'SD_1=FAIL reason=git_unreadable'; return 1; }
  git merge-base --is-ancestor "$runtime" "$head" || { echo 'SD_1=FAIL reason=runtime_not_ancestor'; return 1; }
  git diff --quiet "$runtime" "$head" -- . ':(exclude)docs/**' ':(exclude).codex/**' ':(exclude)tools/**' || {
    echo 'SD_1=FAIL reason=runtime_tree_changed_after_reviewed_runtime'; return 1;
  }
  git diff --quiet "$head" -- . ':(exclude)docs/**' ':(exclude).codex/**' ':(exclude)tools/**' || {
    echo 'SD_1=FAIL reason=deployed_runtime_bytes_dirty'; return 1;
  }
  for f in run_sra_api.sh config/deployment_bootstrap.py requirement_scheduler/cli.py .gitattributes; do
    [ -f "$f" ] || { echo "SD_1=FAIL reason=missing_file file=$f"; return 1; }
  done
  printf 'SD_1_WORKTREE_HEAD=%s\nSD_1_RUNTIME_TREE=%s\n' "$head" "$runtime"
  echo 'SD_1=PASS identity_mode=intact_git_worktree_runtime_tree'
}
sd1_git_worktree
```

PASS requires that the runtime commit is an ancestor, all tracked non-documentation/non-project-memory/non-release-tool
bytes equal its runtime tree, and those deployed bytes are clean. Documentation-
only commits therefore do not recursively invalidate SD-1. Unreviewed runtime
changes fail. Package/overlay mode uses its external trust anchor instead; do not mutate the worktree.

## SD-2 — LF_PACKAGE_GATE

This gate is entirely read-only. `.gitattributes` applies `text eol=lf` to
`*.sh`; acceptance detects rather than repairs CRLF.

```bash
sd2_lf() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_2=FAIL reason=cannot_cd'; return 1; }
  git check-attr text eol -- run_sra_api.sh || { echo 'SD_2=FAIL reason=attribute_scan'; return 1; }
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
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'SD_2=FAIL reason=crlf_or_scan'; return 1; }
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
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'SD_3_PRECHECK=FAIL_OR_BLOCKED'; return "$rc"; }
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
  SD3_DIR=$(mktemp -d "${TMPDIR:-/tmp}/sra-sd3.XXXXXXXX") || { echo 'SD_3_ACTION=FAIL reason=mktemp'; return 1; }
  export SD3_DIR
  [ -d "$SD3_DIR" ] && [ ! -L "$SD3_DIR" ] && [ "$(stat -c%u "$SD3_DIR")" = "$(id -u)" ] && [ "$(stat -c%a "$SD3_DIR")" = 700 ] || { echo 'SD_3_ACTION=FAIL reason=evidence_dir'; return 1; }
  # State-neutral last precondition before the first mutating launcher call.
  local runtime_port="${PORT:-9002}" port_rc
  case "$runtime_port" in
    ''|*[!0-9]*) echo 'SD_3_PRECHECK=FAIL reason=invalid_runtime_port'; return 1 ;;
  esac
  [ "${#runtime_port}" -le 5 ] && [ "$runtime_port" -ge 1 ] && [ "$runtime_port" -le 65535 ] || { echo 'SD_3_PRECHECK=FAIL reason=invalid_runtime_port'; return 1; }
  command -v python >/dev/null 2>&1 || { echo 'SD_3_PRECHECK=FAIL reason=listener_authority'; return 1; }
  timeout 5 python - "$runtime_port" <<'PY'
import sys
port = int(sys.argv[1])
try:
    for path in ('/proc/net/tcp', '/proc/net/tcp6'):
        with open(path, encoding='ascii') as stream:
            next(stream)
            for line in stream:
                fields = line.split()
                if len(fields) < 4:
                    raise RuntimeError('malformed_listener_authority')
                _address, port_hex = fields[1].rsplit(':', 1)
                if fields[3] == '0A' and int(port_hex, 16) == port:
                    raise SystemExit(2)
except (OSError, UnicodeError, ValueError, RuntimeError):
    raise SystemExit(1)
PY
  port_rc=$?
  [ "$port_rc" -ne 2 ] || { echo "SD_3_PRECHECK=BLOCKED_PORT_IN_USE port=$runtime_port"; return 2; }
  [ "$port_rc" -eq 0 ] || { echo 'SD_3_PRECHECK=FAIL reason=listener_authority'; return 1; }
  echo "SD_3_PORT_PRECHECK=PASS port=$runtime_port"
  nohup ./run_sra_api.sh > "$SD3_DIR/launcher.log" 2>&1 </dev/null &
  local pid=$! start
  start=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null) || { echo 'SD_3_ACTION=FAIL reason=launcher_exited'; return 1; }
  printf 'pid=%s\nstart=%s\n' "$pid" "$start" > "$SD3_DIR/invocation.identity" || { echo 'SD_3_ACTION=FAIL reason=evidence_write'; return 1; }
  sleep 18
  [ "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$start" ] || { echo 'SD_3_ACTION=FAIL reason=launcher_exited_or_reused'; tail -n 30 "$SD3_DIR/launcher.log"; return 1; }
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
from config.deployment_bootstrap import KEY_NAME,KEY_SCOPES,STATE_KEYS,STATE_VERSION
from sra_api.security.service_key_store import ServiceKeyStore
d=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); d=d if d.is_absolute() else Path.cwd()/d
p=d/'requirement_handoff.env'
def secure(path, kind, expected_mode):
 if path.is_symlink(): raise SystemExit(f'SD_3_VERIFY=FAIL reason={kind}_symlink')
 try: info=path.stat()
 except OSError: raise SystemExit(f'SD_3_VERIFY=FAIL reason={kind}_missing')
 wanted=stat.S_ISDIR if kind!='state_file' else stat.S_ISREG
 if not wanted(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=expected_mode:
  raise SystemExit(f'SD_3_VERIFY=FAIL reason={kind}_owner_mode_type')
secure(d,'state_dir',0o700); secure(p,'state_file',0o600)
raw=p.read_bytes()
if b'\0' in raw or b'\r' in raw: raise SystemExit('SD_3_VERIFY=FAIL reason=state_parser')
try: lines=raw.decode('utf-8').splitlines()
except UnicodeDecodeError: raise SystemExit('SD_3_VERIFY=FAIL reason=state_utf8')
values={}
for line in lines:
 key,sep,value=line.partition('=')
 if sep!='=' or key not in STATE_KEYS or key in values or '\n' in value:
  raise SystemExit('SD_3_VERIFY=FAIL reason=state_schema')
 values[key]=value
if set(values)!=set(STATE_KEYS) or values['SRA_BOOTSTRAP_STATE_VERSION']!=STATE_VERSION:
 raise SystemExit('SD_3_VERIFY=FAIL reason=state_schema_or_version')
out=Path(values['REQUIREMENT_HANDOFF_OUTPUT_ROOT']); secure(out,'output_dir',0o700)
store=ServiceKeyStore(Path(os.getenv('SRA_SERVICE_KEYS_FILE','.sra_service_keys.json')))
active=[x for x in store.list_keys() if x.get('name')==KEY_NAME and x.get('status')=='active']
selected=[x for x in active if x.get('key_id')==values.get('SRA_BOOTSTRAP_HANDOFF_KEY_ID')]
mode=lambda x: format(stat.S_IMODE(x.stat().st_mode),'04o')
ok=(out.parent.resolve()==d.resolve() and len(active)==len(selected)==1 and frozenset(selected[0]['scopes'])==KEY_SCOPES)
print(f'SD_3_STATE_DIR_MODE={mode(d)} STATE_FILE_MODE={mode(p)} OUTPUT_DIR_MODE={mode(out)}')
print(f'SD_3_ACTIVE_CANONICAL_COUNT={len(active)} SELECTED_MATCH={len(selected)}')
print('SD_3_SCOPES='+(','.join(selected[0]['scopes']) if selected else 'UNAVAILABLE'))
print('SD_3_VERIFY='+('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
PY
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'SD_3_VERIFY=FAIL reason=metadata_invariant'; return 1; }
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
root=Path.cwd().resolve(); uid=os.geteuid()
if p.is_symlink() or not p.is_file() or stat.S_IMODE(p.stat().st_mode)!=0o600 or p.stat().st_uid!=uid:
 raise SystemExit('SD_4_CRASH=FAIL reason=record')
rows=p.read_text().splitlines(); d={}
for row in rows:
 k,sep,v=row.partition('=')
 if not sep or k in d: raise SystemExit('SD_4_CRASH=FAIL reason=record_schema')
 d[k]=v
if len(rows)!=5 or set(d)!= {'pid','process_start_time','effective_uid','cwd','launcher_path'}:
 raise SystemExit('SD_4_CRASH=FAIL reason=record_schema')
if d['effective_uid']!=str(uid) or Path(d['cwd']).resolve()!=root or Path(d['launcher_path']).resolve()!=root/'run_sra_api.sh':
 raise SystemExit('SD_4_CRASH=FAIL reason=stored_identity')
pid=int(d['pid'])
fd=os.pidfd_open(pid)
try:
 proc=Path('/proc')/str(pid); argv=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
 fields=(proc/'stat').read_text().split(); start=fields[21]; cwd=Path(os.readlink(proc/'cwd')).resolve()
 status=(proc/'status').read_text().splitlines(); euid=next(x.split()[2] for x in status if x.startswith('Uid:'))
 if fields[2]=='Z' or len(argv)<2 or Path(argv[0]).name!='bash': raise SystemExit('SD_4_CRASH=FAIL reason=process_shape')
 script=(cwd/argv[1]).resolve() if not Path(argv[1]).is_absolute() else Path(argv[1]).resolve()
 lock=(root/'.run_sra_api.lock').stat(); lockfd=(proc/'fd/9').stat()
 needle=f'{os.major(lock.st_dev):02x}:{os.minor(lock.st_dev):02x}:{lock.st_ino}'
 owns=any(x.split()[1:4]==['FLOCK','ADVISORY','WRITE'] and x.split()[4]==str(pid) and x.split()[5].lower()==needle.lower() for x in Path('/proc/locks').read_text().splitlines())
 ok=(start==d['process_start_time'] and euid==str(uid) and cwd==root and script==root/'run_sra_api.sh' and lockfd.st_dev==lock.st_dev and lockfd.st_ino==lock.st_ino and owns)
 if not ok: raise SystemExit('SD_4_CRASH=FAIL reason=identity_changed_no_signal')
 # Re-read the complete record after opening pidfd and immediately before signal.
 if p.read_text().splitlines()!=rows: raise SystemExit('SD_4_CRASH=FAIL reason=record_drift_no_signal')
 signal.pidfd_send_signal(fd,signal.SIGKILL)
 print(f'SD_4_CRASH=PASS pid={pid} start={start}')
finally: os.close(fd)
PY
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'SD_4_CRASH=FAIL_OR_BLOCKED no_signal_if_unproven'; return 1; }
}
sd4_crash_exact_launcher
```

Start recovery as a separate operator step only after the crash PASS:

```bash
sd4_recover() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_4_RECOVERY=FAIL reason=cannot_cd'; return 1; }
  umask 077
  local log
  log=$(mktemp "${TMPDIR:-/tmp}/sra-sd4-recovery.XXXXXXXX.log") || { echo 'SD_4_RECOVERY=FAIL reason=mktemp'; return 1; }
  [ ! -L "$log" ] && [ "$(stat -c%u "$log")" = "$(id -u)" ] && [ "$(stat -c%a "$log")" = 600 ] || { echo 'SD_4_RECOVERY=FAIL reason=log_owner_mode'; return 1; }
  nohup ./run_sra_api.sh > "$log" 2>&1 </dev/null &
  local pid=$! start
  start=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null) || { echo 'SD_4_RECOVERY=FAIL reason=exited'; return 1; }
  sleep 18
  [ "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$start" ] || { echo 'SD_4_RECOVERY=FAIL reason=exited_or_reused'; tail -n 40 "$log"; return 1; }
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
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'SD_5=FAIL reason=lease_observation'; return 1; }
}
sd5_observe
```

PASS also requires unchanged protected-state SHA/key ID from SD-3 and bounded
worker logs without startup/invariant errors. HTTP 200 or live PIDs alone fail.

## SD-6 — RESTART_IDEMPOTENCY_GATE

Use one new SSH session, define `accept_setup`, `verify_sra_runtime`, and all four functions below, then run exactly: `accept_setup`, `sd6_prepare`, `sd6_snapshot_before`, `sd6_restart`, `sd6_verify_after`, and `sd6_cleanup`. `SD6_DIR` is the only documented cross-step shell state. It is unique, owner-only, and contains no credential, token, password, Authorization header, or signed URL.

The reviewed operational execution budget is 40 seconds: launcher graceful shutdown
is bounded at 10 seconds, the action observation sleeps 20 seconds, OpenAPI
verification is bounded at 5 seconds, and the configured SQL connect timeout is
5 seconds. The default lease duration is 45 seconds. A configured
`heartbeat_interval` of 10 seconds exists, but it is not evidence of a fixed,
independent renewal loop: after the initial acquisition, the current coordinator
renews when `run_once()` begins, and the actual interval depends on the preceding
runtime/workload cycle plus the configured polling interval. The before step
therefore requires strictly more than 40 seconds remaining according to SQL
Server's clock only to give the operator enough practical time to attempt this
bounded procedure. This operational safety margin is separate from lease-renewal
semantics and is not the correctness proof. Insufficient margin is **BLOCKED** and
must be retried later without mutation. If any acceptance-procedure timing bound
differs, stop and obtain a recalculated reviewed budget; do not lower it ad hoc.
PASS remains governed by the final temporal proof: `after_generation >
before_generation` **and** `after_sql_now < before_expires_at`. Scheduling delay
can only block the gate, never create a false PASS.

```bash
sd6_prepare() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_PREPARE=FAIL reason=cannot_cd'; return 1; }
  umask 077
  SD6_DIR=$(mktemp -d "${TMPDIR:-/tmp}/sra-sd6.XXXXXXXX") || { echo 'SD_6_PREPARE=FAIL reason=mktemp'; return 1; }
  export SD6_DIR
  [ -d "$SD6_DIR" ] && [ ! -L "$SD6_DIR" ] || { echo 'SD_6_PREPARE=FAIL reason=directory_type'; return 1; }
  [ "$(stat -c%u "$SD6_DIR")" = "$(id -u)" ] && [ "$(stat -c%a "$SD6_DIR")" = 700 ] || { echo 'SD_6_PREPARE=FAIL reason=directory_owner_mode'; return 1; }
  echo 'SD_6_PREPARE=PASS'
}
```

```bash
sd6_snapshot_before() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_BEFORE=FAIL reason=cannot_cd'; return 1; }
  [ -n "${SD6_DIR:-}" ] && [ -d "$SD6_DIR" ] && [ ! -L "$SD6_DIR" ] || { echo 'SD_6_BEFORE=FAIL reason=evidence_dir'; return 1; }
  [ "$(stat -c%u "$SD6_DIR")" = "$(id -u)" ] && [ "$(stat -c%a "$SD6_DIR")" = 700 ] || { echo 'SD_6_BEFORE=FAIL reason=evidence_owner_mode'; return 1; }
  verify_sra_runtime || return 1
  python - <<'PY'
import hashlib,json,os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from data_ingestion.requirements.connections import SqlRegistry
root=Path.cwd(); out=Path(os.environ['SD6_DIR'])/'before.json'
def rec(role):
 d=dict(x.split('=',1) for x in (root/f'.run_sra_api_{role}.identity').read_text().splitlines())
 return {'pid':d.get('api_pid',d.get('pid')),'start':d.get('api_start_time',d.get('process_start_time'))}
state_dir=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); state_dir=state_dir if state_dir.is_absolute() else root/state_dir
state=state_dir/'requirement_handoff.env'; values=dict(x.split('=',1) for x in state.read_text().splitlines())
r=SqlRegistry.load(os.getenv('REQUIREMENT_SQL_REGISTRY_FILE','config/requirements/sql_registry.json'))
c=r.open_named_connection(os.getenv('REQUIREMENT_CONTROL_DB_CONNECTION','requirement_control')); schema=os.getenv('REQUIREMENT_SCHEDULE_DB_SCHEMA','sra_schedule')
try:
 q=c.cursor(); q.execute(f"SELECT owner_id,fencing_generation,expires_at,TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00') FROM [{schema}].[requirement_handoff_coordinator_leases] WHERE control_domain=?",'requirement-report-v1'); row=q.fetchone()
finally: c.close()
if not row or row[2]<=row[3]: raise SystemExit('SD_6_BEFORE=FAIL reason=no_live_lease')
remaining=(row[2]-row[3]).total_seconds()
if remaining<=40: raise SystemExit('SD_6_BEFORE=BLOCKED reason=insufficient_lease_margin')
audit=root/'SRA-API_kill_audit.log'
data={'state_sha256':hashlib.sha256(state.read_bytes()).hexdigest(),'key_id':values['SRA_BOOTSTRAP_HANDOFF_KEY_ID'],'identity':{x:rec(x) for x in ('launcher','api','schedule','handoff')},'lease':{'owner':row[0],'generation':int(row[1]),'expires_at':row[2].isoformat(),'sql_now':row[3].isoformat(),'remaining_seconds':remaining},'audit_size':audit.stat().st_size if audit.exists() else 0}
out.write_text(json.dumps(data,sort_keys=True)+'\n')
print('SD_6_BEFORE=PASS')
PY
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'SD_6_BEFORE=FAIL reason=snapshot'; return 1; }
}
```

Invoke only the supported takeover path; this function contains no signal command:

```bash
sd6_restart() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_ACTION=FAIL reason=cannot_cd'; return 1; }
  [ -r "${SD6_DIR:-}/before.json" ] || { echo 'SD_6_ACTION=FAIL reason=missing_before'; return 1; }
  verify_sra_runtime || return 1
  umask 077
  nohup ./run_sra_api.sh > "$SD6_DIR/restart.log" 2>&1 </dev/null &
  local pid=$! start
  start=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null) || { echo 'SD_6_ACTION=FAIL reason=contender_exited'; return 1; }
  sleep 20
  [ "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$start" ] || { echo 'SD_6_ACTION=FAIL reason=contender_exited_or_reused'; return 1; }
  verify_sra_runtime || return 1
  echo 'SD_6_ACTION=PASS supported_takeover_only'
}
```

The final verifier independently captures after-state and compares it. Identity is the `(PID, process-start-time)` pair. The old launcher must be gone; the shared verifier proves new flock/listener/OpenAPI ownership. The bounded audit slice must prove graceful SIGTERM with no `SIGKILL` or `ABORT`. An explicit configured owner may remain equal; otherwise it must be `handoff-<new-worker-pid>`.

```bash
sd6_verify_after() {
  cd /mntCZJ/TopicClassification/poc-agent || { echo 'SD_6_VERIFY=FAIL reason=cannot_cd'; return 1; }
  [ -r "${SD6_DIR:-}/before.json" ] || { echo 'SD_6_VERIFY=FAIL reason=missing_before'; return 1; }
  verify_sra_runtime || return 1
  python - <<'PY'
import hashlib,json,os
from pathlib import Path
from config.bootstrap import bootstrap_env
bootstrap_env(project_root=Path.cwd())
from data_ingestion.requirements.connections import SqlRegistry
root=Path.cwd(); before=json.loads((Path(os.environ['SD6_DIR'])/'before.json').read_text())
def rec(role):
 d=dict(x.split('=',1) for x in (root/f'.run_sra_api_{role}.identity').read_text().splitlines())
 return {'pid':d.get('api_pid',d.get('pid')),'start':d.get('api_start_time',d.get('process_start_time'))}
after_ids={x:rec(x) for x in ('launcher','api','schedule','handoff')}
state_dir=Path(os.getenv('SRA_DEPLOYMENT_STATE_DIR','.sra_runtime')); state_dir=state_dir if state_dir.is_absolute() else root/state_dir
state=state_dir/'requirement_handoff.env'; values=dict(x.split('=',1) for x in state.read_text().splitlines())
r=SqlRegistry.load(os.getenv('REQUIREMENT_SQL_REGISTRY_FILE','config/requirements/sql_registry.json'))
c=r.open_named_connection(os.getenv('REQUIREMENT_CONTROL_DB_CONNECTION','requirement_control')); schema=os.getenv('REQUIREMENT_SCHEDULE_DB_SCHEMA','sra_schedule')
try:
 q=c.cursor(); q.execute(f"SELECT owner_id,fencing_generation,expires_at,TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00') FROM [{schema}].[requirement_handoff_coordinator_leases] WHERE control_domain=?",'requirement-report-v1'); row=q.fetchone()
finally: c.close()
def require(ok, reason):
 if not ok: raise SystemExit('SD_6_VERIFY=FAIL reason='+reason)
require(hashlib.sha256(state.read_bytes()).hexdigest()==before['state_sha256'],'state_changed')
require(values['SRA_BOOTSTRAP_HANDOFF_KEY_ID']==before['key_id'],'key_id_changed')
for role in ('launcher','api','schedule','handoff'): require(after_ids[role]!=before['identity'][role],role+'_identity_not_replaced')
old=before['identity']['launcher']; oldproc=Path('/proc')/old['pid']/'stat'
require(not oldproc.exists() or oldproc.read_text().split()[21]!=old['start'],'old_launcher_still_live')
require(bool(row) and row[2]>row[3],'lease_not_live')
require(int(row[1])>int(before['lease']['generation']),'generation_not_increased')
from datetime import datetime
before_expiry=datetime.fromisoformat(before['lease']['expires_at'])
require(row[3]<before_expiry,'replacement_not_before_previous_expiry')
explicit=os.getenv('REQUIREMENT_HANDOFF_OWNER_ID'); expected=explicit if explicit else 'handoff-'+after_ids['handoff']['pid']
require(row[0]==expected,'owner_semantics')
audit=root/'SRA-API_kill_audit.log'; require(audit.is_file() and not audit.is_symlink(),'audit_type')
with audit.open('rb') as f: f.seek(before['audit_size']); delta=f.read(1_000_001)
require(len(delta)<=1_000_000,'audit_slice_unbounded')
text=delta.decode(errors='replace'); oldpid=old['pid']; oldstart=old['start']
require(f'Sending SIGTERM to verified launcher PID={oldpid} start={oldstart}' in text,'no_supported_takeover_evidence')
require('SIGKILL' not in text and 'ABORT' not in text,'escalation_or_abort')
print('SD_6_VERIFY=PASS')
PY
  local rc=$?
  [ "$rc" -eq 0 ] || { echo 'SD_6_VERIFY=FAIL reason=executable_comparison'; return 1; }
}
```

```bash
sd6_cleanup() {
  [ -n "${SD6_DIR:-}" ] && [ -d "$SD6_DIR" ] && [ ! -L "$SD6_DIR" ] || { echo 'SD_6_CLEANUP=FAIL reason=evidence_dir'; return 1; }
  [ "$(stat -c%u "$SD6_DIR")" = "$(id -u)" ] && [ "$(stat -c%a "$SD6_DIR")" = 700 ] || { echo 'SD_6_CLEANUP=FAIL reason=evidence_owner_mode'; return 1; }
  rm -f -- "$SD6_DIR/before.json" "$SD6_DIR/restart.log" || { echo 'SD_6_CLEANUP=FAIL reason=remove_files'; return 1; }
  rmdir -- "$SD6_DIR" || { echo 'SD_6_CLEANUP=FAIL reason=remove_directory'; return 1; }
  unset SD6_DIR
  echo 'SD_6_CLEANUP=PASS'
}
```

Only `SD_6_VERIFY=PASS` is the gate comparison result. `SD_6_ACTION=PASS` merely confirms that the supported contender survived and must never be reported as the gate PASS.

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
Corrective implementation baseline: 7a54f182d9c1b6d18234d6e8085b163880b26db0
Reviewed manifest implementation commit: d170dc7c42cdfc5f454aa00f0ef37743aba34fd7
Reviewed runtime baseline: edcbc744f71374eaa839b0a31e0cd125fcb6fe52
Deployed runtime baseline: edcbc744f71374eaa839b0a31e0cd125fcb6fe52
Runbook: v1.6
Gate executed:
Identity mode:
Precheck/action/verify marker:
Observed FAIL/BLOCKED marker:
Golden Path replayed: NO
Raw credential included: NO
Approval requested for next gate: YES/NO
```

All gates remain **PENDING** until their live evidence is separately reviewed.

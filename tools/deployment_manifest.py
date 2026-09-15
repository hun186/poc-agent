"""Build and verify Git-anchored deployment manifests."""

from __future__ import annotations

import json
import hashlib
import subprocess
import argparse
import os
import stat
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any


class ManifestError(RuntimeError):
    """A bounded, non-secret deployment-manifest failure."""


def load_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("policy_invalid_json") from exc
    return _validate_policy(value)


def normalize_manifest_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ManifestError("path_invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(value).is_absolute():
        raise ManifestError("path_invalid")
    return "/".join(parts)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_unique_paths(paths: list[str]) -> None:
    normalized = [normalize_manifest_path(path) for path in paths]
    if len(normalized) != len(set(normalized)):
        raise ManifestError("path_duplicate")
    folded: dict[str, str] = {}
    for path in normalized:
        key = path.casefold()
        if key in folded and folded[key] != path:
            raise ManifestError("path_case_collision")
        folded[key] = path


def compute_files_root(entries: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["path"])):
        line = "\0".join(
            str(entry[key]) for key in ("class", "path", "git_mode", "size", "sha256")
        ) + "\n"
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class GitFile:
    path: str
    mode: str
    blob_sha: str
    data: bytes


def _git(repo_root: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), *args], stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ManifestError("git_object_error") from exc


def resolve_commit(repo_root: Path, ref: str) -> str:
    value = _git(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}").decode("ascii").strip()
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise ManifestError("git_commit_invalid")
    return value


def source_tree_sha(repo_root: Path, commit: str) -> str:
    return _git(repo_root, "rev-parse", "--verify", f"{commit}^{{tree}}").decode("ascii").strip()


def read_policy_from_commit(repo_root: Path, commit: str, policy_path: str) -> dict[str, Any]:
    try:
        raw = _git(repo_root, "show", f"{commit}:{normalize_manifest_path(policy_path)}")
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("policy_invalid_json") from exc
    return _validate_policy(value)


def _validate_policy(value: object) -> dict[str, Any]:
    keys = {
        "schema_version", "repository", "managed_roots", "managed_files",
        "release_tool_files", "allowed_runtime_extra_globs", "guarded_root_extensions",
    }
    if not isinstance(value, dict) or set(value) != keys or value.get("schema_version") != 1:
        raise ManifestError("policy_schema")
    if value.get("repository") != "hun186/poc-agent":
        raise ManifestError("policy_schema")
    for key in keys - {"schema_version", "repository"}:
        if not isinstance(value[key], list) or not all(isinstance(x, str) for x in value[key]):
            raise ManifestError("policy_schema")
    validate_unique_paths(value["managed_roots"] + value["managed_files"] + value["release_tool_files"])
    return value


def git_file_map(repo_root: Path, commit: str, policy: dict[str, object], *, file_class: str) -> dict[str, GitFile]:
    if file_class not in {"runtime", "release_tool"}:
        raise ManifestError("file_class_invalid")
    selectors = (list(policy["managed_roots"]) + list(policy["managed_files"])) if file_class == "runtime" else list(policy["release_tool_files"])
    if not selectors:
        return {}
    raw = _git(repo_root, "ls-tree", "-rz", "--full-tree", commit, "--", *selectors)
    result: dict[str, GitFile] = {}
    for record in raw.rstrip(b"\0").split(b"\0") if raw else []:
        header, encoded_path = record.split(b"\t", 1)
        mode, kind, blob = header.decode("ascii").split()
        path = normalize_manifest_path(encoded_path.decode("utf-8"))
        if kind != "blob":
            raise ManifestError("git_entry_not_blob")
        result[path] = GitFile(path, mode, blob, _git(repo_root, "cat-file", "blob", blob))
    validate_unique_paths(list(result))
    if file_class == "release_tool" and set(result) != set(selectors):
        raise ManifestError("release_tool_missing")
    return result


def require_runtime_equivalence(reviewed: dict[str, GitFile], source: dict[str, GitFile]) -> None:
    identity = lambda item: (item.mode, item.blob_sha)
    if set(reviewed) != set(source) or any(identity(reviewed[p]) != identity(source[p]) for p in reviewed):
        raise ManifestError("runtime_source_not_equivalent")


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _allowed_extra(path: str, policy: dict[str, object]) -> bool:
    # v1 policy intentionally permits extras only below a __pycache__ directory.
    return policy["allowed_runtime_extra_globs"] == ["**/__pycache__/**"] and "__pycache__" in path.split("/")[:-1]


def validate_package_root(package_root: Path, expected_files: dict[str, GitFile], policy: dict[str, object]) -> list[dict[str, object]]:
    if not package_root.is_dir() or package_root.is_symlink():
        raise ManifestError("package_root_invalid")
    entries: list[dict[str, object]] = []
    for path, source in sorted(expected_files.items()):
        target = package_root / path
        try:
            info = target.lstat()
        except OSError as exc:
            raise ManifestError("managed_file_missing") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ManifestError("managed_file_symlink")
        if not stat.S_ISREG(info.st_mode):
            raise ManifestError("managed_file_not_regular")
        data = target.read_bytes()
        if data != source.data:
            raise ManifestError("managed_file_hash_mismatch")
        entries.append({"class": "", "path": path, "git_mode": source.mode,
                        "size": len(data), "sha256": sha256_bytes(data)})
    expected = set(expected_files)
    for root_name in policy["managed_roots"]:
        root = package_root / str(root_name)
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root, followlinks=False):
            for name in list(dirs) + files:
                candidate = Path(current) / name
                rel = candidate.relative_to(package_root).as_posix()
                if candidate.is_symlink() and rel not in expected:
                    raise ManifestError("unexpected_managed_file")
                if candidate.is_file() and rel not in expected and not _allowed_extra(rel, policy):
                    raise ManifestError("unexpected_managed_file")
    guarded = tuple(policy["guarded_root_extensions"])
    for candidate in package_root.iterdir():
        if candidate.is_file() and candidate.name not in expected and candidate.name != "DEPLOYMENT_MANIFEST.json" and candidate.suffix in guarded:
            raise ManifestError("unexpected_managed_file")
    return entries


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


_MANIFEST_KEYS = {
    "schema_version", "repository", "source_commit", "source_tree",
    "reviewed_runtime_commit", "policy_sha256", "files_root_sha256", "files",
    "managed_roots", "managed_files", "release_tool_files",
    "allowed_runtime_extra_globs", "guarded_root_extensions",
}
_HEX = set("0123456789abcdef")


def _lower_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and set(value) <= _HEX


def parse_manifest_bytes(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest_schema") from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS or value.get("schema_version") != 1:
        raise ManifestError("manifest_schema")
    if value.get("repository") != "hun186/poc-agent":
        raise ManifestError("manifest_schema")
    for key in ("source_commit", "source_tree", "reviewed_runtime_commit"):
        if not _lower_hex(value[key], 40):
            raise ManifestError("manifest_schema")
    for key in ("policy_sha256", "files_root_sha256"):
        if not _lower_hex(value[key], 64):
            raise ManifestError("manifest_schema")
    policy = {key: value[key] for key in ("schema_version", "repository", "managed_roots", "managed_files",
                                           "release_tool_files", "allowed_runtime_extra_globs", "guarded_root_extensions")}
    _validate_policy(policy)
    files = value["files"]
    if not isinstance(files, list):
        raise ManifestError("manifest_schema")
    required = {"class", "path", "git_mode", "size", "sha256"}
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ManifestError("manifest_schema")
        if entry["class"] not in {"runtime", "release_tool"} or entry["git_mode"] not in {"100644", "100755"}:
            raise ManifestError("manifest_schema")
        normalize_manifest_path(entry["path"])
        if not isinstance(entry["size"], int) or isinstance(entry["size"], bool) or entry["size"] < 0:
            raise ManifestError("manifest_schema")
        if not _lower_hex(entry["sha256"], 64):
            raise ManifestError("manifest_schema")
    validate_unique_paths([entry["path"] for entry in files])
    by_path = {entry["path"]: entry for entry in files}
    release_paths = set(value["release_tool_files"])
    if not release_paths or not release_paths <= set(by_path):
        raise ManifestError("manifest_policy_inconsistent")
    for path, entry in by_path.items():
        expected_class = "release_tool" if path in release_paths else "runtime"
        if entry["class"] != expected_class:
            raise ManifestError("manifest_policy_inconsistent")
    policy_entry = by_path.get("tools/deployment_manifest_policy.json")
    if policy_entry is None or policy_entry["sha256"] != value["policy_sha256"]:
        raise ManifestError("manifest_policy_inconsistent")
    if files != sorted(files, key=lambda item: item["path"]):
        raise ManifestError("manifest_schema")
    if compute_files_root(files) != value["files_root_sha256"]:
        raise ManifestError("manifest_files_root_mismatch")
    if canonical_json_bytes(value) != raw:
        raise ManifestError("manifest_schema")
    return value


def _read_regular_no_follow(path: Path, reason: str) -> bytes:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ManifestError(reason)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise ManifestError(reason)
            chunks = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)
    except ManifestError:
        raise
    except OSError as exc:
        raise ManifestError(reason) from exc


def _verify_files(root: Path, manifest: dict[str, object]) -> int:
    entries = manifest["files"]
    expected = {entry["path"]: entry for entry in entries}
    for path, entry in expected.items():
        data = _read_regular_no_follow(root / path, "managed_file_invalid")
        if len(data) != entry["size"] or sha256_bytes(data) != entry["sha256"]:
            raise ManifestError("managed_file_hash_mismatch")
    policy = manifest
    for root_name in policy["managed_roots"]:
        managed_root = root / root_name
        if not managed_root.exists():
            continue
        for current, dirs, files in os.walk(managed_root, followlinks=False):
            for name in list(dirs) + files:
                candidate = Path(current) / name
                rel = candidate.relative_to(root).as_posix()
                if candidate.is_symlink() and rel not in expected:
                    raise ManifestError("unexpected_managed_file")
                if candidate.is_file() and rel not in expected and not _allowed_extra(rel, policy):
                    raise ManifestError("unexpected_managed_file")
    guarded = tuple(policy["guarded_root_extensions"])
    for candidate in root.iterdir():
        if (candidate.is_file() or candidate.is_symlink()) and candidate.name not in expected and candidate.name != "DEPLOYMENT_MANIFEST.json" and candidate.suffix in guarded:
            raise ManifestError("unexpected_managed_file")
    return len(entries)


def verify_deployment(*, deployment_root: Path, manifest_path: Path,
                      expected_manifest_sha256: str | None) -> int:
    if not expected_manifest_sha256:
        print("SD_1=BLOCKED reason=trusted_manifest_digest_missing")
        return 2
    try:
        deployment_root = Path(deployment_root)
        if deployment_root.is_symlink() or not deployment_root.is_dir():
            raise ManifestError("deployment_root_invalid")
        if not _lower_hex(expected_manifest_sha256, 64):
            raise ManifestError("trusted_manifest_digest_invalid")
        raw = _read_regular_no_follow(Path(manifest_path), "manifest_unreadable")
        actual_digest = sha256_bytes(raw)
        if actual_digest != expected_manifest_sha256:
            raise ManifestError("manifest_digest_mismatch")
        manifest = parse_manifest_bytes(raw)
        matched = _verify_files(deployment_root, manifest)
        print(f"SD_1_SOURCE_COMMIT={manifest['source_commit']}")
        print(f"SD_1_REVIEWED_RUNTIME_COMMIT={manifest['reviewed_runtime_commit']}")
        print(f"SD_1_MANIFEST_SHA256={actual_digest}")
        print(f"SD_1_FILES_EXPECTED={len(manifest['files'])}")
        print(f"SD_1_FILES_MATCHED={matched}")
        print("SD_1_UNEXPECTED_MANAGED=0")
        print("SD_1=PASS identity_mode=release_manifest")
        return 0
    except ManifestError as exc:
        print(f"SD_1=FAIL reason={exc}")
        return 1


def build_manifest(*, repo_root: Path, package_root: Path, source_commit: str,
                   reviewed_runtime_commit: str, receipt_out: Path) -> tuple[Path, Path, str]:
    repo_root, package_root, receipt_out = map(Path, (repo_root, package_root, receipt_out))
    if _inside(receipt_out, package_root):
        raise ManifestError("receipt_inside_package")
    source = resolve_commit(repo_root, source_commit)
    reviewed = resolve_commit(repo_root, reviewed_runtime_commit)
    policy_raw = _git(repo_root, "show", f"{source}:tools/deployment_manifest_policy.json")
    policy = read_policy_from_commit(repo_root, source, "tools/deployment_manifest_policy.json")
    runtime = git_file_map(repo_root, source, policy, file_class="runtime")
    reviewed_runtime = git_file_map(repo_root, reviewed, policy, file_class="runtime")
    require_runtime_equivalence(reviewed_runtime, runtime)
    release_tools = git_file_map(repo_root, source, policy, file_class="release_tool")
    combined = {**runtime, **release_tools}
    entries = validate_package_root(package_root, combined, policy)
    for entry in entries:
        entry["class"] = "runtime" if entry["path"] in runtime else "release_tool"
    entries.sort(key=lambda item: str(item["path"]))
    manifest = {
        "schema_version": 1, "repository": policy["repository"],
        "source_commit": source, "source_tree": source_tree_sha(repo_root, source),
        "reviewed_runtime_commit": reviewed, "policy_sha256": sha256_bytes(policy_raw),
        "files_root_sha256": compute_files_root(entries), "files": entries,
        **{key: policy[key] for key in ("managed_roots", "managed_files", "release_tool_files",
                                        "allowed_runtime_extra_globs", "guarded_root_extensions")},
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path = package_root / "DEPLOYMENT_MANIFEST.json"
    _atomic_write(manifest_path, manifest_bytes)
    manifest_digest = sha256_bytes(manifest_bytes)
    receipt = {
        "schema_version": 1, "repository": policy["repository"], "source_commit": source,
        "reviewed_runtime_commit": reviewed, "manifest_sha256": manifest_digest,
        "files_root_sha256": manifest["files_root_sha256"],
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder_version": 1,
    }
    _atomic_write(receipt_out, canonical_json_bytes(receipt))
    return manifest_path, receipt_out, manifest_digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    build = sub.add_parser("build")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--package-root", type=Path, required=True)
    build.add_argument("--source-commit", required=True)
    build.add_argument("--reviewed-runtime-commit", required=True)
    build.add_argument("--receipt-out", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--deployment-root", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-manifest-sha256")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.operation == "verify":
        return verify_deployment(
            deployment_root=args.deployment_root, manifest_path=args.manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
    try:
        manifest_path, _, digest = build_manifest(
            repo_root=args.repo_root, package_root=args.package_root,
            source_commit=args.source_commit, reviewed_runtime_commit=args.reviewed_runtime_commit,
            receipt_out=args.receipt_out,
        )
        value = json.loads(manifest_path.read_bytes())
        print(f"RELEASE_MANIFEST_SOURCE_COMMIT={value['source_commit']}")
        print(f"RELEASE_MANIFEST_RUNTIME_COMMIT={value['reviewed_runtime_commit']}")
        print(f"RELEASE_MANIFEST_SHA256={digest}")
        print(f"RELEASE_MANIFEST_FILES={len(value['files'])}")
        print("RELEASE_MANIFEST=PASS")
        return 0
    except ManifestError as exc:
        print(f"RELEASE_MANIFEST=FAIL reason={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

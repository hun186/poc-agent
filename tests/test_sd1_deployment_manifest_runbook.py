from pathlib import Path


RUNBOOK = Path(__file__).parents[1] / "docs/operations/sra-self-bootstrap-live-acceptance-v1.md"


def text():
    return RUNBOOK.read_text(encoding="utf-8")


def package_section():
    value = text()
    return value.split("### Package/overlay manifest action (read-only)", 1)[1].split("### Git-worktree action (read-only)", 1)[0]


def test_runbook_is_v161_and_binds_hosted_authority_without_awarding_sd1():
    value = text()
    assert "Package v1.6.1" in value
    assert "Supersedes v1.6" in value
    assert "Post-merge corrective source baseline" in value
    assert "8cd7be88ec3e36e344b0bbb5e73b0125a3579b39" in value
    assert "Reviewed runtime baseline" in value
    assert "edcbc744f71374eaa839b0a31e0cd125fcb6fe52" in value
    assert "Reviewed manifest implementation commit" in value
    assert "a79198aaff5828dbe54c3ffc4120d10377ea6e77" in value
    assert "d170dc7c42cdfc5f454aa00f0ef37743aba34fd7" not in value
    assert "POST-MERGE SOURCE REVIEW REQUIRED;" in value
    assert "SD-1 THROUGH SD-7 PENDING" in value


def test_package_precheck_precedes_project_verifier_and_checks_self_hash():
    section = package_section()
    assert section.index("hashlib.sha256(raw)") < section.index("json.loads(raw)")
    assert section.index("tools/deployment_manifest.py") < section.index("verifier_hash_mismatch")
    assert section.index("verifier_hash_mismatch") < section.index("SD_1_MANIFEST_PRECHECK=PASS")
    assert section.index("SD_1_MANIFEST_PRECHECK=PASS") < section.index("python tools/deployment_manifest.py verify")
    assert "reviewed_manifest_commit" in section
    assert "SD_1_REVIEWED_MANIFEST_COMMIT" in section


def test_release_build_requires_reviewed_manifest_commit_and_no_cache_allowance():
    value = text()
    assert "REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT=a79198aaff5828dbe54c3ffc4120d10377ea6e77" in value
    assert '--reviewed-manifest-commit "$REVIEWED_MANIFEST_IMPLEMENTATION_COMMIT"' in value
    assert "**/__pycache__/**" not in value


def test_package_mode_uses_external_digest_not_git_authority_and_does_not_chain_sd2():
    section = package_section()
    assert "EXPECTED_MANIFEST_SHA256" in section
    assert "SD_1=BLOCKED reason=trusted_manifest_digest_missing" in section
    for forbidden in ("git rev-parse", "git merge-base", "git status", ".git/HEAD", "sd2_"):
        assert forbidden not in section


def test_worktree_mode_excludes_release_tools_in_both_comparisons():
    section = text().split("### Git-worktree action (read-only)", 1)[1].split("## SD-2", 1)[0]
    assert section.count("':(exclude)tools/**'") == 2


def test_forbidden_destructive_commands_are_absent():
    value = text()
    for forbidden in ("git clean", "git reset", "git pull", "rm -rf"):
        assert forbidden not in value

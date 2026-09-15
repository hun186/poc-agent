from pathlib import Path


RUNBOOK = Path(__file__).parents[1] / "docs/operations/sra-self-bootstrap-live-acceptance-v1.md"


def text():
    return RUNBOOK.read_text(encoding="utf-8")


def package_section():
    value = text()
    return value.split("### Package/overlay manifest action (read-only)", 1)[1].split("### Git-worktree action (read-only)", 1)[0]


def test_runbook_is_v15_and_keeps_live_status_pending():
    value = text()
    assert "Package v1.5" in value
    assert "Supersedes v1.4" in value
    assert "SD-1 THROUGH SD-7 PENDING" in value


def test_package_precheck_precedes_project_verifier_and_checks_self_hash():
    section = package_section()
    assert section.index("hashlib.sha256(raw)") < section.index("json.loads(raw)")
    assert section.index("tools/deployment_manifest.py") < section.index("verifier_hash_mismatch")
    assert section.index("verifier_hash_mismatch") < section.index("SD_1_MANIFEST_PRECHECK=PASS")
    assert section.index("SD_1_MANIFEST_PRECHECK=PASS") < section.index("python tools/deployment_manifest.py verify")


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

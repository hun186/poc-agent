from pathlib import Path


def test_openwebui_key_setup_has_complete_chinese_operations() -> None:
    text = Path("docs/security/openwebui-service-key-setup.md").read_text(encoding="utf-8")
    for required in (
        "OpenWebUI Service Key 設定指南（中文版）",
        "SRA_SIGNED_URL_SECRET",
        "SRA_SERVICE_KEYS_FILE",
        "create-service-key",
        "model:read",
        "model:invoke",
        "revoke-service-key",
        "僅顯示一次",
    ):
        assert required in text


def test_service_key_operations_chinese_doc_covers_security_and_recovery() -> None:
    text = Path("docs/security/service-key-operations.md").read_text(encoding="utf-8")
    for required in (
        "SRA Service Key 維運技術文件（中文版）",
        "Scope 對照",
        "constant-time comparison",
        "read → validate → mutate → fsync → atomic replace",
        "JSON 損壞時應 fail closed",
        "備份",
        "輪替",
    ):
        assert required in text

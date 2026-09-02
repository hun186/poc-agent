import json
from api.security.cli import main


def test_cli_create_list_revoke_without_digest(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SRA_SERVICE_KEYS_FILE", str(tmp_path / "keys.json"))
    main(["create-service-key", "--name", "batch", "--scope", "report:job:create"])
    created = json.loads(capsys.readouterr().out)
    assert created["key"].startswith("sra_sk_") and "token_digest" not in created
    main(["list-service-keys"])
    listed = capsys.readouterr().out
    assert created["key"] not in listed and "token_digest" not in listed
    main(["revoke-service-key", created["key_id"]])
    assert json.loads(capsys.readouterr().out)["status"] == "revoked"

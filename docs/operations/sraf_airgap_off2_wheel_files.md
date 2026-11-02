# SRAF OFF-2 — 外部 Pin 的 Wheelhouse 位元組核對（部分驗證）

執行入口（需由受信任管道預先取得 Manifest 的 SHA-256）：

```bash
SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256=<trusted-64-char-lowercase-sha256> \\
  bash run_sraf_airgap_offline.sh wheel-files
```

*上述摘要必須來自獨立、已審核的發行程序，不能在待驗證部署目錄直接計算後就當作可信值。*

預期部署的專案根目錄需包含 `SRAF_WHEELHOUSE_MANIFEST.json` 及 `wheelhouse/`。Manifest 僅允許下列資料結構（具體值由外部受信任的發行工作流程產生，不在此工具內動態寫入）：

```json
{
  "schema_version": 1,
  "repository": "hun186/poc-agent",
  "wheels": [
    {
      "filename": "example_pkg-1.0-py3-none-any.whl",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "size": 42
    }
  ]
}
```

工具先使用外部 pin 核對 Manifest 的原始位元組，再以 no-follow dirfd 驗證 Wheel 路徑、指定大小及 SHA-256，拒絕未列管檔案、檔名衝突、Symlink、異常大小與不可讀檔案。Manifest 最多 128 KiB、256 顆 Wheel，單檔最多 512 MiB、列管總量最多 4 GiB；超過上限必須回報 `INCOMPLETE`，不是放寬檢查。

- 缺少或格式錯誤的外部摘要：`INCOMPLETE`，不讀取不受信任的 Manifest。
- 摘要與 Manifest 不符或 Wheel 位元組／檔案長度不符：`FAIL`。
- 沒有 Wheel、額外檔案、未知 Schema、不安全目錄或無法驗證：`INCOMPLETE`。
- 全部列管檔案核對一致：僅 `PASS_PARTIAL`。

**此工具不解壓或執行 Wheel，不調用 pip，不會下載／安裝／修改資料，也不建立自我可信摘要。** 即使 `PASS_PARTIAL`，也沒有檢查 Wheel 是否為合法格式、是否覆蓋 requirements 的完整 transitive closure、平台/ABI/OS、依賴版本衝突、原生 ODBC、模型權重、授權、來源簽章或離線可安裝性；同名既有檔案在本機並非可信來源。外部 Manifest 摘要是「需要獨立確立的信任錨」，單純 SHA-256 不等於公鑰簽章。

目前 repo 沒有可受信任的完整 Wheelhouse Manifest／套件，預期此檢查是 `INCOMPLETE`。這是 OFF-2 後續可實施的局部位元組門檻，不能代替原有 `release-files`、`release-policy`、`release-deps`，或 OFF-3／OFF-5 真實封網部署、升級與還原驗收。

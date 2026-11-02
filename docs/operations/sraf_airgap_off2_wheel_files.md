# SRAF OFF-2 — 外部 Pin 的 Wheelhouse 位元組核對（部分驗證）

執行入口（需由受信任管道預先取得 Manifest 的 SHA-256）：

```bash
SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256=<trusted-64-char-lowercase-sha256> bash run_sraf_airgap_offline.sh wheel-files
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

工具先使用外部 pin 核對 Manifest 的原始位元組，再以同一個 no-follow 檔案描述符驗證 Wheel 指定大小與 SHA-256，檢查 ZIP 中央目錄、基本 `.dist-info/WHEEL` 和 `.dist-info/METADATA`、Wheel 發行名稱／版本一致性。拒絕未列管檔案、大小／Digest 錯配、ZIP 路徑穿越、重複名稱、符號連結、加密檔案或不支援的壓縮格式。Manifest 最多 128 KiB、256 顆 Wheel，單檔最多 512 MiB、列管總量最多 4 GiB；ZIP 於建立 `ZipFile` 解析物件之前，先以限長讀取 EOCD／中央目錄並驗證真正條目數量；最多 8192 個條目與 4 MiB 中央目錄、宣告解壓總量 2 GiB，WHEEL／METADATA 各最多 64 KiB。超過上限必須回報 `INCOMPLETE`，不是放寬檢查。

- 缺少或格式錯誤的外部摘要：`INCOMPLETE`，不讀取不受信任的 Manifest。
- 摘要與 Manifest 不符或 Wheel 位元組／檔案長度不符：`FAIL`。
- 沒有 Wheel、額外檔案、未知 Schema、不安全目錄或無法驗證：`INCOMPLETE`。
- 正確 Pin 的 Wheel 是任意位元組、壞 ZIP、缺少／偽造基本 Metadata 或 ZIP 結構異常：`INCOMPLETE / wheel_archive_structure_invalid`。
- 有界串流驗證時，若 Wheel 缺少 `.dist-info/RECORD`、未列出應列檔案、出現重複或額外紀錄、非 SHA-256／大小不符、實際解壓內容雜湊不符，或超過限額：`INCOMPLETE / wheel_archive_structure_invalid`。
- 全部列管 Wheel 的外部 SHA／大小、基本 ZIP／Metadata 及 RECORD 實際內容 SHA-256 核對一致：仍僅 `PASS_PARTIAL / pinned_wheel_bytes_metadata_record_only`。

此基本驗證容許標準 `METADATA` 折行 Header（例如多行 License），但對超限中央目錄、無法預先確認條目數量、ZIP64 或多磁碟 ZIP 採保守的 `INCOMPLETE`；若 ZIP 註解內含另一個 EOCD Signature，因與 Python ZipFile 的「最後標記」解析規則可能造成歧義，也在任何 ZipInfo 配置之前拒絕，不先分配大量 `ZipInfo` 物件後才拒絕。

**此工具不解開 Wheel 至磁碟、不執行程式碼、不調用 pip、不下載／安裝／修改資料，也不建立自我可信摘要。** 現在除了兩份各上限 64 KiB 的文字 Metadata，還會用記憶體內有界串流解壓 Wheel 內的非目錄內容，逐列、遇到異常立即拒絕地核對 `.dist-info/RECORD` CSV 的涵蓋率、列出大小、SHA-256 與實際內容（ZIP 讀取亦會檢查已讀取檔案的 CRC）。單顆 Wheel 的 RECORD 最多 2 MiB；單顆 Wheel 含 RECORD 的核對解壓量上限 256 MiB，整次命令加總上限 512 MiB，超過一律 `INCOMPLETE`，**不**默默放寬。舊式 `RECORD.jws`／`RECORD.p7s` 可依格式規範不列於 RECORD，外部整顆檔案雜湊涵蓋它們，但**並不**驗證簽章真偽。

即使 `PASS_PARTIAL`，仍未全面證明 Wheel 格式／各種擴充檔案相容性、RECORD 的所有合法雜湊演算法支援、Requires-Dist 的 transitive closure、平台／ABI／OS、版本衝突、ODBC 原生函式庫、模型權重、授權、來源簽章或離線可安裝性；大型 Wheel 或不支援的格式採保守 `INCOMPLETE`。同名既有檔案在本機並非可信來源。外部 Manifest 摘要是「需要獨立確立的信任錨」，單純 SHA-256 不等於公鑰簽章。

目前 repo 沒有可受信任的完整 Wheelhouse Manifest／套件，預期此檢查是 `INCOMPLETE`。這是 OFF-2 後續可實施的局部位元組門檻，不能代替原有 `release-files`、`release-policy`、`release-deps`，或 OFF-3／OFF-5 真實封網部署、升級與還原驗收。

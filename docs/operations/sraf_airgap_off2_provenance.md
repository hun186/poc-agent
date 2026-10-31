# OFF-2 — 既有發行 Prove­nance 列管檔案 SHA-256 驗證（部分檢查）

> 此工具**不會**建置發行包、安裝套件、存取資料庫、呼叫 LLM、連接網路、產生新的 provenance 或更改任何部署檔案。只核對已列在 `REQUIREMENT_E2E_PROVENANCE.json` 的既有 runtime 檔案是否符合預期 SHA-256，且結果絕非 OFF-2 完整打包、OFF-3/4 離線發行或 OFF-5 還原／實體斷網驗收。

## 已部署環境執行

必須先由另一條可信、經審查且**獨立於待檢查目錄的管道**取得該版 `REQUIREMENT_E2E_PROVENANCE.json` 的 SHA-256（64 個小寫十六進位字元），再在目標專案根目錄操作。不可直接從可疑部署目錄重新算完雜湊、把它當作可信來源；這樣只能保證自洽，無法證明未遭替換。

```bash
cd /path/to/deployed/poc-agent
python tools/sraf_airgap_off2_manifest_check.py \
  --expected-manifest-sha256 "<TRUSTED_64_LOWERCASE_HEX>"
```

不帶外部可信摘要時，工具會直接回報 `INCOMPLETE / trusted_manifest_digest_not_supplied`、退出碼 2，**不會**把本地 JSON 視為真實發行憑據。

- `PASS_PARTIAL`／退出 0：提供的 Manifest 摘要與本地 Manifest 相符，且**該 Manifest 明列的每個 runtime 檔案** SHA-256 相符。不包含檔案清單完整性證明，也不代表該版已簽章、經獨立審查、Python wheelhouse 完備、SQL／ES schema 與依賴服務已可用。
- `FAIL`／退出 1：Manifest SHA-256 與外部指定值不符，或某個列管 runtime 檔案的確定 SHA-256 與 Manifest 不一致。不要在未確認來源的情況下直接覆蓋正式環境。
- `INCOMPLETE`／退出 2：無可信摘要、Manifest 結構錯誤、遺失、符號連結、資料過大、無法讀取、檢查期間檔案改變等，不能視為相符或已被入侵。

### 安全限制

只從當前工作目錄讀取固定的 `REQUIREMENT_E2E_PROVENANCE.json`；所有列管路徑必須先通過既有 `shared.runtime_provenance.validate_provenance` 安全規則。從 pinned root fd 出發逐層以 `O_NOFOLLOW` 打開一般檔案，不跟隨 symlink；Manifest 至多 2 MiB、單檔至多 64 MiB、總讀取量上限 2 GiB。結果只輸出固定原因碼與已檢查數量，**不輸出實際路徑、雜湊、內容、帳號、憑證或原生例外**；不會讀取未列管的 deployment-local SQL Registry。

這是**當下的檔案內容快照**，沒有阻止同 UID 惡意程序或外部寫入者在檢查後更動檔案的能力，也沒有驗證 manifest 覆蓋了全部依賴。實際 SRAF 程式可以持續更新，倉庫目前的 `reviewed_runtime_sha` 可能較舊，應以可信發行流程重新審查、產生並發布**對應版本**的 manifest。絕不可把較舊 Manifest 的 mismatch 改成 PASS 或自行改雜湊值掩蓋漂移。

## 尚未完成

OFF-2 仍需可信 Release Bundle 明細／來源及簽章、wheelhouse 和 Python/native driver 依賴封存、版本綁定、重現性與部署一致性驗收；OFF-3/4 還需實體封網完整鏈路，OFF-5 還需備份、還原與回滾演練。Hosted CI 使用最小合成檔案案例，**不代表真實部署機的 SQL、ES、LLM、Job、Word、網路物理隔離已驗收**。

#!/usr/bin/env bash
# SRAF 常用的六項本機快檢：不連網、不寫報告、不啟動服務、不使用憑證。
# 這是便於找到的入口；實際安全檢查仍由已審查的 OFF-3 deploy-check 執行。
set -euo pipefail

case "${1:-}" in
  "")
    ;;
  -h|--help)
    printf '%s\n' \
      'SRAF 一鍵快檢（不用記任何參數）' \
      '' \
      '在 SRAF 專案目錄執行：' \
      '  bash 0_一鍵快檢_SRAF.sh' \
      '  或在具備執行權限的 Linux 直接使用 ./0_一鍵快檢_SRAF.sh' \
      '' \
      '僅進行六項被動本機觀察：不連網、不寫檔、不啟動服務、不登入、不執行 SQL/ES/LLM/Report Job。' \
      '最後一行 SRAF_DEPLOY_CHECK_JSON=... 可提供給工程師診斷。' \
      '即使顯示 PASS_PARTIAL，也不是正式驗收或可上線證明。'
    exit 0
    ;;
  *)
    printf '%s\n' 'SRAF_ONE_CLICK=INCOMPLETE reason=unsupported_option' >&2
    printf '%s\n' '用 bash 0_一鍵快檢_SRAF.sh --help 查看使用方式。' >&2
    exit 2
    ;;
esac

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! -f "$PROJECT_ROOT/run_sraf_airgap_offline.sh" ]]; then
  printf '%s\n' 'SRAF_ONE_CLICK=INCOMPLETE reason=missing_canonical_dispatcher' >&2
  exit 2
fi

printf '%s\n' \
  '===== SRAF 一鍵快檢（唯讀・不連網・不寫檔）=====' \
  '正在執行六項安全的本機觀察；不執行 SQL／ES／LLM、不登入、不重啟服務。' \
  '結果最後一行 SRAF_DEPLOY_CHECK_JSON=... 可提供工程師診斷。' \
  '注意：PASS_PARTIAL 不代表正式部署或 FULL_LIVE 驗收。'

# 保留原模式的 stdout、最後 JSON 行與退出碼；不拷貝、重寫任何探測邏輯。
exec bash "$PROJECT_ROOT/run_sraf_airgap_offline.sh" deploy-check

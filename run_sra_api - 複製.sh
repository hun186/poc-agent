#!/usr/bin/env bash
set -euo pipefail

########################################
# 固定設定（10KB 測試 + Port 偵測）
########################################

BASE_DIR="/mntCZJ/TopicClassification/poc-agent"

# ✅ 主 Log（會被清空的）
LOG_FILE="SRA-API_output.txt"

# ✅ Kill 稽核 Log（永久保存）
KILL_AUDIT_LOG="SRA-API_kill_audit.log"

MAX_SIZE_KB=10*1024          # ✅ 可先用 10KB 測試
PORT=9002               # ✅ 你現在用的 port

########################################
# 程式開始
########################################

cd "$BASE_DIR"

MAX_SIZE=$((MAX_SIZE_KB * 1024))
NOW_TS="$(date '+%Y-%m-%d %H:%M:%S')"

echo "[run_sra_api] 啟動目錄：$BASE_DIR"
echo "[run_sra_api] Log 檔案：$LOG_FILE"
echo "[run_sra_api] Kill 稽核檔：$KILL_AUDIT_LOG"
echo "[run_sra_api] Log 上限：${MAX_SIZE_KB}KB"
echo "[run_sra_api] 使用 Port：$PORT"
echo "----------------------------------------"

########################################
# ✅ 1. 檢查 Port 是否被佔用 + 寫入稽核檔
########################################

echo "[run_sra_api] 檢查 Port $PORT 是否被佔用..."

PIDS=$(lsof -ti tcp:"$PORT" || true)

if [ -n "$PIDS" ]; then
  {
    echo "=================================================="
    echo "[$NOW_TS] ⚠️ Port $PORT 已被佔用"
    echo "[$NOW_TS] 佔用程式詳細資訊："
    lsof -nP -i tcp:"$PORT"
    echo "--------------------------------------------------"
    echo "[$NOW_TS] 準備進行 kill -9"
  } >> "$KILL_AUDIT_LOG"

  echo "[run_sra_api] ⚠️ Port $PORT 已被佔用！"
  echo "[run_sra_api] 佔用程式詳細資訊："
  echo "----------------------------------------"
  lsof -nP -i tcp:"$PORT"
  echo "----------------------------------------"

  echo "[run_sra_api] 正在嘗試強制關閉佔用程式..."

  for pid in $PIDS; do
    echo "[run_sra_api] → kill -9 PID=$pid"
    if kill -9 "$pid"; then
      echo "[run_sra_api] ✅ 已成功關閉 PID=$pid"
      echo "[$NOW_TS] ✅ 已成功 kill PID=$pid" >> "$KILL_AUDIT_LOG"
    else
      echo "[run_sra_api] ❌ 關閉失敗 PID=$pid"
      echo "[$NOW_TS] ❌ kill 失敗 PID=$pid" >> "$KILL_AUDIT_LOG"
    fi
  done

  sleep 1

  # ✅ 再次確認是否釋放
  if lsof -ti tcp:"$PORT" >/dev/null; then
    echo "[run_sra_api] ❌ 無法釋放 Port $PORT，請手動處理"
    echo "[$NOW_TS] ❌ Port $PORT 仍占用，kill 失敗" >> "$KILL_AUDIT_LOG"
    exit 1
  else
    echo "[run_sra_api] ✅ Port $PORT 已成功釋放"
    echo "[$NOW_TS] ✅ Port $PORT 已成功釋放" >> "$KILL_AUDIT_LOG"
  fi
else
  echo "[run_sra_api] ✅ Port $PORT 可正常使用"
  echo "[$NOW_TS] ✅ Port $PORT 可正常使用" >> "$KILL_AUDIT_LOG"
fi

########################################
# ✅ 2. 啟動時先清空主 log（不影響稽核檔）
########################################

echo "[run_sra_api] 啟動時清空舊主 log..."
: > "$LOG_FILE"

########################################
# ✅ 3. 啟動 uvicorn 並即時控管主 log 容量
########################################

echo "[run_sra_api] 啟動 uvicorn..."

#uvicorn api.main:app --host 0.0.0.0 --port "$PORT" 2>&1 | \
#python -m api.run_api --public --ssl --port "$PORT" 2>&1 | \

uvicorn api.main:app --host 0.0.0.0 --port "$PORT" 2>&1 | \
while IFS= read -r line; do

  # 取得目前主 log 檔案大小（不存在就當 0）
  if [ -f "$LOG_FILE" ]; then
    size=$(stat -c%s "$LOG_FILE")
  else
    size=0
  fi

  # ✅ 超過上限 → 立刻清空（不動稽核檔）
  if [ "$size" -gt "$MAX_SIZE" ]; then
    echo "[run_sra_api] ⚠️ 主 log 超過 ${MAX_SIZE_KB}KB，清空重寫..." >&2
    : > "$LOG_FILE"
  fi

  # ✅ 寫入主 log（UTF-8 原樣）
  printf '%s\n' "$line" >> "$LOG_FILE"

done

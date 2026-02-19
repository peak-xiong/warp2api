#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/xiongfeng/Documents/Web3Projects/warp2api"
LOG_DIR="$ROOT_DIR/logs"
STATE_FILE="$LOG_DIR/.watchdog_last_hash"
INTERVAL="${WATCH_INTERVAL_SECONDS:-45}"

mkdir -p "$LOG_DIR"

summarize_reason() {
  local text="$1"
  if echo "$text" | rg -qi "HTTP 403|403 Forbidden"; then
    if echo "$text" | rg -qi "jwt diag: exp_utc=.*remain_s=-"; then
      echo "疑似原因: JWT 已过期（remain_s<0）"
      return
    fi
    if echo "$text" | rg -qi "WARP_TRUST_ENV enabled|proxy"; then
      echo "疑似原因: 网络代理链路触发风控/拦截（建议关闭代理后重试）"
      return
    fi
    if echo "$text" | rg -qi "Warp API target dns: .*ips=\\[\\]"; then
      echo "疑似原因: DNS 解析异常，未拿到有效目标地址"
      return
    fi
    echo "疑似原因: 上游 WAF/风控拦截（JWT 未必失效）"
    return
  fi

  if echo "$text" | rg -qi "No remaining quota|No AI requests remaining|HTTP 429"; then
    echo "疑似原因: 配额用尽（429）"
    return
  fi

  if echo "$text" | rg -qi "Connection refused|ConnectError|timed out|Name or service not known|dns_lookup_failed"; then
    echo "疑似原因: 网络连通性或 DNS 问题"
    return
  fi

  if echo "$text" | rg -qi "token refresh failed|WARP_JWT is not set|JWT token.*过期"; then
    echo "疑似原因: 鉴权 token 获取/刷新失败"
    return
  fi

  echo "疑似原因: 暂未识别，请检查完整日志"
}

echo "[watchdog] started at $(date '+%F %T'), interval=${INTERVAL}s"

collect_window() {
  local files=(
    "$LOG_DIR/warp_server.log"
    "$LOG_DIR/openai_compat.log"
    "$LOG_DIR/pm2_warp_bridge_err.log"
    "$LOG_DIR/pm2_warp_openai_err.log"
    "$LOG_DIR/pm2_warp_bridge_out.log"
    "$LOG_DIR/pm2_warp_openai_out.log"
  )

  for f in "${files[@]}"; do
    if [ -f "$f" ]; then
      echo "### FILE: $(basename "$f")"
      tail -n 180 "$f" 2>/dev/null || true
      echo
    fi
  done
}

while true; do
  if [ ! -d "$LOG_DIR" ]; then
    sleep "$INTERVAL"
    continue
  fi

  WINDOW_CONTENT="$(collect_window)"
  WINDOW_HASH="$(printf '%s' "$WINDOW_CONTENT" | shasum | awk '{print $1}')"
  LAST_HASH="$(cat "$STATE_FILE" 2>/dev/null || true)"

  if [ "$WINDOW_HASH" != "$LAST_HASH" ]; then
    printf '%s' "$WINDOW_HASH" > "$STATE_FILE"

    HIT_LINES="$(printf '%s\n' "$WINDOW_CONTENT" | rg -n "HTTP 403|403 Forbidden|HTTP 429|No remaining quota|No AI requests remaining|token|JWT|dns_lookup_failed|ConnectError|timed out|Connection refused|proxy|WARP_TRUST_ENV enabled" -S || true)"
    if [ -n "$HIT_LINES" ]; then
      REASON="$(summarize_reason "$WINDOW_CONTENT")"
      echo "[watchdog][$(date '+%F %T')] files=warp_server.log,openai_compat.log,pm2_warp_*.log"
      echo "[watchdog] $REASON"
      echo "[watchdog] recent-hit-lines:"
      printf '%s\n' "$HIT_LINES" | tail -n 12
      echo "[watchdog] ----"
    fi
  fi

  sleep "$INTERVAL"
done

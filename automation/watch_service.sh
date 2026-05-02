#!/bin/bash
# 手動起動/停止/ステータス/ログ/再起動
PD="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PD"

case "${1:-start}" in
  start)
    if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
      echo "既に実行中 (PID: $(cat /tmp/yt_auto.pid))"
      exit 0
    fi
    termux-wake-lock 2>/dev/null || true
    crond -b -l 8 2>/dev/null || true
    nohup python watchdog.py >> logs/watchdog.log 2>&1 &
    echo $! > /tmp/yt_auto.pid
    echo "監視開始 (PID: $(cat /tmp/yt_auto.pid))"
    echo "ログ確認: bash $0 log"
    ;;
  stop)
    if [ -f /tmp/yt_auto.pid ]; then
      PID=$(cat /tmp/yt_auto.pid)
      kill "$PID" 2>/dev/null
      pkill -P "$PID" 2>/dev/null
      rm -f /tmp/yt_auto.pid
      echo "停止しました"
    else
      echo "実行中のプロセスなし"
    fi
    termux-wake-unlock 2>/dev/null || true
    ;;
  restart)
    bash "$0" stop
    sleep 2
    bash "$0" start
    ;;
  status)
    if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
      echo "✓ 稼働中 (PID: $(cat /tmp/yt_auto.pid))"
      echo "最新ログ:"
      tail -5 logs/automation.log 2>/dev/null
    else
      echo "✗ 停止中"
    fi
    echo ""
    echo "cron keepalive:"
    crontab -l 2>/dev/null | grep keepalive || echo "  (未設定)"
    ;;
  log)
    tail -f logs/automation.log
    ;;
  cost)
    echo "=== 最新コスト履歴 ==="
    grep -E "合計|API使用" logs/automation.log 2>/dev/null | tail -20 || echo "ログなし"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|log|cost}"
    ;;
esac

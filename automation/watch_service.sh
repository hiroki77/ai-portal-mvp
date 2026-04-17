#!/bin/bash
# 手動起動/停止/ステータス/ログ
PD="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PD"

case "${1:-start}" in
  start)
    if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
      echo "実行中 (PID: $(cat /tmp/yt_auto.pid))"
      exit 0
    fi
    termux-wake-lock 2>/dev/null || true
    nohup python watchdog.py >> logs/watchdog.log 2>&1 &
    echo $! > /tmp/yt_auto.pid
    echo "監視開始 (PID: $(cat /tmp/yt_auto.pid))"
    echo "ログ: bash $0 log"
    ;;
  stop)
    if [ -f /tmp/yt_auto.pid ]; then
      PID=$(cat /tmp/yt_auto.pid)
      kill "$PID" 2>/dev/null
      # 子プロセス(main.py)も停止
      pkill -P "$PID" 2>/dev/null
      rm -f /tmp/yt_auto.pid
      echo "停止しました"
    else
      echo "実行中のプロセスなし"
    fi
    termux-wake-unlock 2>/dev/null || true
    ;;
  status)
    if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
      echo "実行中 (PID: $(cat /tmp/yt_auto.pid))"
      echo "最新ログ:"
      tail -5 logs/automation.log 2>/dev/null
    else
      echo "停止中"
    fi
    ;;
  log)
    tail -f logs/automation.log
    ;;
  *)
    echo "Usage: $0 {start|stop|status|log}"
    ;;
esac

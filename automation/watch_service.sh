#!/bin/bash
# 手動起動用スクリプト
# 実行: bash automation/watch_service.sh

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 既存プロセス確認
if [ -f /tmp/youtube_automation.pid ]; then
    OLD_PID=$(cat /tmp/youtube_automation.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "既に実行中 (PID: $OLD_PID)"
        echo "停止する場合: kill $OLD_PID"
        exit 1
    fi
fi

echo "監視開始..."
termux-wake-lock 2>/dev/null || true
nohup python main.py >> logs/automation.log 2>&1 &
echo $! > /tmp/youtube_automation.pid
echo "PID: $(cat /tmp/youtube_automation.pid)"
echo "ログ: tail -f logs/automation.log"

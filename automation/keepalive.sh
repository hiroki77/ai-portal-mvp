#!/data/data/com.termux/files/usr/bin/bash
# cronから5分ごとに呼ばれる keepaliveスクリプト
# watchdogが死んでいたら自動再起動する

PROJECT_DIR="$HOME/youtube-shorts-automation"
cd "$PROJECT_DIR" || exit 1
mkdir -p logs

# WakeLockが外れていたら再取得
termux-wake-lock 2>/dev/null || true

# watchdogが生きているか確認
if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
    # 生きている → 何もしない
    exit 0
fi

# 死んでいる → 再起動
echo "$(date): keepalive: watchdog dead, restarting..." >> logs/keepalive.log
nohup python watchdog.py >> logs/watchdog.log 2>&1 &
echo $! > /tmp/yt_auto.pid
echo "$(date): keepalive: restarted (PID=$!)" >> logs/keepalive.log

termux-notification \
  --title "自動復帰" \
  --content "監視プロセスを再起動しました" \
  --id "yt_keepalive"

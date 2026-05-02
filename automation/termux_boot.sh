#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot 起動スクリプト
# スマホ電源ON / 再起動時に自動実行される

# ===== WakeLock: CPUスリープを防止 =====
termux-wake-lock

PROJECT_DIR="$HOME/youtube-shorts-automation"
cd "$PROJECT_DIR" || exit 1
mkdir -p logs

echo "$(date): Boot started" >> logs/boot.log

# ===== crond 起動 (keepaliveのcronジョブを動かす) =====
if ! pgrep -x crond > /dev/null; then
    crond -b -l 8
    echo "$(date): crond started" >> logs/boot.log
fi

# ===== watchdog 二重起動防止 =====
if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
    echo "$(date): Already running (PID=$(cat /tmp/yt_auto.pid))" >> logs/boot.log
    exit 0
fi

# ===== watchdog 起動 =====
nohup python watchdog.py >> logs/watchdog.log 2>&1 &
echo $! > /tmp/yt_auto.pid
echo "$(date): watchdog started (PID=$!)" >> logs/boot.log

# ===== 常駐通知 =====
termux-notification \
  --title "切り抜き自動生成 稼働中" \
  --content "スリープ中も監視継続中" \
  --ongoing --id "yt_auto"

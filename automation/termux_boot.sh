#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot 起動スクリプト
# watchdog経由で起動(クラッシュ時自動復帰)

termux-wake-lock

PROJECT_DIR="$HOME/youtube-shorts-automation"
cd "$PROJECT_DIR" || exit 1

if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
    exit 0
fi

echo "$(date): Boot started" >> logs/boot.log

nohup python watchdog.py >> logs/watchdog.log 2>&1 &
echo $! > /tmp/yt_auto.pid

termux-notification \
  --title "切り抜き自動生成" \
  --content "監視開始(クラッシュ自動復帰機能付き)" \
  --ongoing --id "yt_auto"

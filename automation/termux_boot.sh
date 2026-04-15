#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot起動スクリプト
# スマホ起動時・スリープ復帰時に自動実行

# WakeLock取得(スリープ中も動作)
termux-wake-lock

# 作業ディレクトリ
PROJECT_DIR="$HOME/youtube-shorts-automation"
cd "$PROJECT_DIR" || exit 1

# ログ
echo "$(date): Boot script started" >> logs/boot.log

# バックグラウンド実行
nohup python main.py >> logs/automation.log 2>&1 &
echo $! > /tmp/youtube_automation.pid

termux-notification --title "切り抜き自動生成" --content "監視開始しました"

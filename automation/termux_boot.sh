#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot 起動スクリプト
# スマホ起動時・スリープ復帰時に自動実行

# WakeLock取得(スリープ中もCPU動作)
termux-wake-lock

# バッテリー最適化無効化(バックグラウンド処理が止まらないように)
# ※初回のみ手動で 設定 > アプリ > Termux > バッテリー最適化 > 無制限

PROJECT_DIR="$HOME/youtube-shorts-automation"
cd "$PROJECT_DIR" || exit 1

# 既存プロセスがあればスキップ
if [ -f /tmp/yt_auto.pid ] && kill -0 "$(cat /tmp/yt_auto.pid)" 2>/dev/null; then
    echo "$(date): Already running" >> logs/boot.log
    exit 0
fi

echo "$(date): Boot script started" >> logs/boot.log

# バックグラウンドでmain.py実行
nohup python main.py >> logs/automation.log 2>&1 &
echo $! > /tmp/yt_auto.pid

termux-notification \
  --title "切り抜き自動生成" \
  --content "中町兄妹チャンネル監視開始" \
  --ongoing \
  --id "yt_auto"

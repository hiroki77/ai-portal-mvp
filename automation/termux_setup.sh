#!/bin/bash
set -e
echo "=== 中町兄妹 切り抜き自動生成 - Termuxセットアップ ==="

# 基本
pkg update -y
pkg install -y python ffmpeg git termux-api rclone

# Pythonパッケージ
pip install --upgrade pip
pip install yt-dlp feedparser schedule pyyaml
pip install google-genai
pip install openai-whisper easyocr
pip install numpy opencv-python-headless Pillow
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Termux:Boot設定
mkdir -p ~/.termux/boot
cp automation/termux_boot.sh ~/.termux/boot/
chmod +x ~/.termux/boot/termux_boot.sh

# ディレクトリ
mkdir -p output temp data fonts logs

# WakeLock
termux-wake-lock

# ストレージ権限
termux-setup-storage

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "次のステップ:"
echo "1. fonts/ にけいふぉんと.ttfを配置"
echo "2. config.yaml に Gemini APIキーを設定"
echo "   (無料取得: https://aistudio.google.com/apikey)"
echo "3. rclone config でGoogle Driveを設定"
echo "   (rclone config → New remote → google drive)"
echo "4. 設定 > アプリ > Termux > バッテリー最適化 > 無制限"
echo "5. Termux:BootアプリをF-Droidからインストール"
echo "6. python main.py --once でテスト"
echo "7. bash automation/watch_service.sh で監視開始"
echo "8. スマホ再起動で自動開始"

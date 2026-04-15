#!/bin/bash
# Termux環境セットアップスクリプト
# 実行: bash automation/termux_setup.sh
set -e

echo "=== 中町兄妹 切り抜き自動生成 - Termuxセットアップ ==="

# 基本パッケージ
pkg update -y
pkg install -y python ffmpeg git

# Termux API(通知用)
pkg install -y termux-api

# pipパッケージ
pip install --upgrade pip
pip install yt-dlp feedparser schedule pyyaml
pip install openai-whisper easyocr
pip install numpy opencv-python-headless Pillow
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Termux:Boot設定(スリープ時も自動実行)
mkdir -p ~/.termux/boot
cp automation/termux_boot.sh ~/.termux/boot/
chmod +x ~/.termux/boot/termux_boot.sh

# ディレクトリ作成
mkdir -p output temp data fonts logs

# WakeLock設定
termux-wake-lock

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "次のステップ:"
echo "1. fonts/ にけいふぉんと(.ttf)を配置"
echo "2. Termux:Bootアプリをインストール(F-Droidから)"
echo "3. python main.py でテスト実行"
echo "4. スマホ再起動で自動開始"

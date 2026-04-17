#!/bin/bash
set -e
echo "=== 中町兄妹 切り抜き自動生成 - Termuxセットアップ ==="
echo ""
echo "[1/7] パッケージインストール..."
pkg update -y && pkg install -y python ffmpeg git termux-api rclone

echo "[2/7] Pythonパッケージ..."
pip install --upgrade pip
pip install yt-dlp schedule pyyaml google-genai
pip install openai-whisper easyocr
pip install numpy opencv-python-headless Pillow
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

echo "[3/7] Termux:Boot設定..."
mkdir -p ~/.termux/boot
cp automation/termux_boot.sh ~/.termux/boot/
chmod +x ~/.termux/boot/termux_boot.sh

echo "[4/7] ディレクトリ作成..."
mkdir -p output temp data fonts logs

echo "[5/7] WakeLock設定..."
termux-wake-lock

echo "[6/7] ストレージ権限..."
termux-setup-storage

echo "[7/7] けいふぉんとダウンロード確認..."
if [ -z "$(ls -A fonts/ 2>/dev/null)" ]; then
    echo ""
    echo "⚠ fonts/ にフォントがありません"
    echo "  けいふぉんと(.ttf)をダウンロードして fonts/ に配置してください"
    echo "  検索: https://booth.pm で'けいふぉんと'"
fi

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "次のステップ:"
echo "  1. fonts/ にけいふぉんと.ttfを配置"
echo "  2. echo 'export GEMINI_API_KEY=\"AIza...\"' >> ~/.bashrc && source ~/.bashrc"
echo "  3. rclone config  (→ New remote → google drive)"
echo "  4. 設定 > アプリ > Termux > バッテリー最適化 > 無制限"
echo "  5. python tools/calibrate_colors.py  (テロップ色検出)"
echo "  6. python main.py --once  (テスト)"
echo "  7. bash automation/watch_service.sh  (自動監視開始)"

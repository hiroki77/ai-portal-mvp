#!/bin/bash
set -e
echo "=== 中町兄妹 切り抜き自動生成 - Termuxセットアップ ==="
echo ""

echo "[1/8] パッケージインストール..."
pkg update -y && pkg install -y python ffmpeg git termux-api rclone cronie

echo "[2/8] Pythonパッケージ..."
pip install --upgrade pip
pip install yt-dlp schedule pyyaml google-genai feedparser
pip install openai                          # Whisper API + ChatGPT
pip install openai-whisper                  # ローカルフォールバック用
pip install easyocr
pip install numpy opencv-python-headless Pillow
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

echo "[3/8] ディレクトリ作成..."
mkdir -p output temp data fonts logs

echo "[4/8] Termux:Boot 設定..."
mkdir -p ~/.termux/boot
cp automation/termux_boot.sh ~/.termux/boot/
chmod +x ~/.termux/boot/termux_boot.sh
echo "  → スマホ電源ON時に自動起動します"

echo "[5/8] cron keepalive 設定 (5分ごとに死活監視)..."
chmod +x automation/keepalive.sh
(crontab -l 2>/dev/null | grep -v keepalive; \
 echo "*/5 * * * * $HOME/youtube-shorts-automation/automation/keepalive.sh") | crontab -
crond -b -l 8 2>/dev/null || true
echo "  → 5分ごとにプロセス死活確認・自動復帰"

echo "[6/8] WakeLock..."
termux-wake-lock

echo "[7/8] ストレージ権限..."
termux-setup-storage

echo "[8/8] フォント確認..."
if [ -z "$(ls -A fonts/ 2>/dev/null)" ]; then
    echo "⚠ fonts/ にけいふぉんと.ttf を配置してください"
fi

echo ""
echo "================================================"
echo "  セットアップ完了"
echo "================================================"
echo ""
echo "【必須】以下3アプリのバッテリー最適化を「無制限」に"
echo "  設定 > アプリ > [アプリ] > バッテリー > 無制限"
echo "  1. Termux"
echo "  2. Termux:Boot"
echo "  3. Termux:API"
echo ""
echo "【必須】バックグラウンドデータを許可"
echo "  設定 > アプリ > Termux > データ使用量 > バックグラウンドデータ ON"
echo ""
echo "次のステップ:"
echo "  1. fonts/ にけいふぉんと.ttf を配置"
echo "  2. export GEMINI_API_KEY=\"AIza...\" >> ~/.bashrc"
echo "  3. export OPENAI_API_KEY=\"sk-...\" >> ~/.bashrc  # Whisper API"
echo "  4. source ~/.bashrc"
echo "  5. rclone config  (→ New remote → gdrive)"
echo "  6. python tools/calibrate_colors.py"
echo "  7. python main.py --once  (テスト)"
echo "  8. bash automation/watch_service.sh start"

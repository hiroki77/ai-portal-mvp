#!/bin/bash
set -e
echo "=== 中町兄妹 切り抜き自動生成 - Termuxセットアップ ==="
echo ""

echo "[1/8] パッケージインストール..."
pkg update -y && pkg install -y python ffmpeg git termux-api rclone cronie

echo "[2/8] Pythonパッケージ..."
pip install --upgrade pip
pip install yt-dlp schedule pyyaml google-genai
pip install openai-whisper easyocr
pip install numpy opencv-python-headless Pillow
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

echo "[3/8] ディレクトリ作成..."
mkdir -p output temp data fonts logs

echo "[4/8] Termux:Boot 設定..."
mkdir -p ~/.termux/boot
cp automation/termux_boot.sh ~/.termux/boot/
chmod +x ~/.termux/boot/termux_boot.sh
echo "  → スマホ電源ON時に自動起動するように設定しました"

echo "[5/8] cron keepalive 設定 (5分ごとに死活監視)..."
chmod +x automation/keepalive.sh
# 既存のcronエントリを削除してから追加
(crontab -l 2>/dev/null | grep -v keepalive; \
 echo "*/5 * * * * $HOME/youtube-shorts-automation/automation/keepalive.sh") | crontab -
crond -b -l 8 2>/dev/null || true
echo "  → 5分ごとにプロセス生存確認・自動復帰を設定しました"

echo "[6/8] WakeLock 有効化..."
termux-wake-lock
echo "  → CPUスリープを無効化しました"

echo "[7/8] ストレージ権限..."
termux-setup-storage

echo "[8/8] けいふぉんとダウンロード確認..."
if [ -z "$(ls -A fonts/ 2>/dev/null)" ]; then
    echo ""
    echo "⚠ fonts/ にフォントがありません"
    echo "  けいふぉんと(.ttf)を fonts/ に配置してください"
fi

echo ""
echo "================================================"
echo "  セットアップ完了！"
echo "================================================"
echo ""
echo "【必須: バッテリー最適化を無効化】"
echo "  以下の3アプリ全てで設定してください:"
echo "  設定 > アプリ > [アプリ名] > バッテリー > 無制限"
echo ""
echo "    1. Termux"
echo "    2. Termux:Boot"
echo "    3. Termux:API"
echo ""
echo "【必須: バックグラウンドデータを許可】"
echo "  設定 > アプリ > Termux > データ使用量 > バックグラウンドデータ ON"
echo ""
echo "【推奨: 充電しながら運用】"
echo "  充電中はAndroidのDozeモードが無効になり最も安定します"
echo ""
echo "次のステップ:"
echo "  1. fonts/ にけいふぉんと.ttfを配置"
echo "  2. echo 'export GEMINI_API_KEY=\"AIza...\"' >> ~/.bashrc && source ~/.bashrc"
echo "  3. rclone config  (→ New remote → gdrive)"
echo "  4. python tools/calibrate_colors.py  (テロップ色キャリブレーション)"
echo "  5. python main.py --once  (動作テスト)"
echo "  6. bash automation/watch_service.sh start  (自動監視開始)"

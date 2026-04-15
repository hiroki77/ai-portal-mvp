# 中町兄妹 切り抜き動画自動生成システム

新着動画を自動検知し、話題ごとに20秒～60秒の切り抜き動画を作成。スマホ(スリープ時も)でフル自動実行。

## 機能
- YouTube RSS監視(完全無料)
- Whisper + EasyOCR で焼き込みテロップを高精度認識
- 話者色検出(ピンク=綾 / シアン=純平)
- ズームで元テロップを隠し、けいふぉんとで再焼き込み
- インサイト学習でバズ精度UP
- 1動画から3本の切り抜きを自動生成

## スマホセットアップ (Android / Termux)

### 1. アプリインストール
- [Termux](https://f-droid.org/packages/com.termux/) (F-Droidから)
- [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) (自動起動用)
- [Termux:API](https://f-droid.org/packages/com.termux.api/) (通知用)

### 2. セットアップ実行
```bash
# Termuxを開いて実行
git clone https://github.com/hiroki77/ai-portal-mvp.git ~/youtube-shorts-automation
cd ~/youtube-shorts-automation
git checkout claude/youtube-shorts-automation-HvDGj
bash automation/termux_setup.sh
```

### 3. フォント配置
`fonts/` に「けいふぉんと」の.ttfファイルを配置

### 4. テスト実行
```bash
python main.py --once
```

### 5. 自動監視開始
```bash
# バックグラウンド実行
bash automation/watch_service.sh

# またはスマホ再起動で自動開始(Termux:Boot)
```

## インサイト反映
翌日に切り抜き動画のパフォーマンスデータを渡すと次回以降の選定に反映:
```bash
python main.py --insights insights_data.json
```

insights_data.jsonの例:
```json
{
  "clips": [
    {"topic": "やばい話", "views": 50000, "likes": 2000},
    {"topic": "兄妹喧嘩", "views": 80000, "likes": 3500}
  ]
}
```

## スリープ時の動作
- Termux:Boot + WakeLock で電源接続中はスリープでも動作
- 新着動画検知時にスマホ通知
- output/ に切り抜き動画が保存される

## ファイル構成
```
main.py              # メインオーケストレーター
config.yaml          # 設定ファイル
src/
  monitor.py         # YouTubeチャンネル監視
  downloader.py      # 動画ダウンロード
  transcriber.py     # 字幕認識(Whisper+OCR)
  segmenter.py       # 話題分割&クリップ選定
  processor.py       # 動画加工(ズーム+字幕)
  insights.py        # インサイト学習
automation/
  termux_setup.sh    # Termuxセットアップ
  termux_boot.sh     # 自動起動
  watch_service.sh   # 手動起動
```

## 全て無料ツール
- yt-dlp: 動画ダウンロード
- Whisper: 音声認識
- EasyOCR: 文字認識
- FFmpeg: 動画加工
- YouTube RSS: チャンネル監視

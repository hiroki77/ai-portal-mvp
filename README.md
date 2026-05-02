# 中町兄妹 切り抜き動画自動生成システム

新着動画を自動検知し、話題ごとに20-60秒の切り抜き動画を3本自動作成。
スマホスリープ時も電源があればフル稼働。クラッシュ時自動復帰。

## 機能
- **Gemini 2.0 Flash** (OCR+話題分割) - 無料枚で最高精度
- **0.1秒精度** フレーム差分検出 → 変化点のみOCR
- **話者色検出** ピンク=綾 / シアン=純平
- **フリ→展開→オチ** が収まるクリップをAIが選定
- **ズーム** で元テロップを隠し、けいふぉんとで再焼込
- **Google Drive** に自動保存
- **watchdog** クラッシュ自動復帰
- **インサイト学習** バズ精度UP

## クイックスタート

### 1. アプリインストール (F-Droidから)
- [Termux](https://f-droid.org/packages/com.termux/)
- [Termux:Boot](https://f-droid.org/packages/com.termux.boot/)
- [Termux:API](https://f-droid.org/packages/com.termux.api/)

### 2. セットアップ
```bash
git clone https://github.com/hiroki77/ai-portal-mvp.git ~/youtube-shorts-automation
cd ~/youtube-shorts-automation
git checkout claude/youtube-shorts-automation-HvDGj
bash automation/termux_setup.sh
```

### 3. 設定
```bash
# Gemini APIキー (無料: https://aistudio.google.com/apikey)
echo 'export GEMINI_API_KEY="AIza..."' >> ~/.bashrc && source ~/.bashrc

# Google Drive
rclone config
# → New remote → name: gdrive → type: google drive

# フォント: fonts/ にけいふぉんと.ttfを配置

# バッテリー最適化無効化
# 設定 > アプリ > Termux > バッテリー最適化 > 無制限
```

### 4. テロップ色キャリブレーション (初回のみ)
```bash
python tools/calibrate_colors.py
```

### 5. テスト実行
```bash
python main.py --once
```

### 6. 自動監視開始
```bash
bash automation/watch_service.sh start
```

## 操作コマンド
```bash
bash automation/watch_service.sh start   # 開始
bash automation/watch_service.sh stop    # 停止
bash automation/watch_service.sh status  # 状態確認
bash automation/watch_service.sh log     # リアルタイムログ
```

## インサイト反映
```bash
python main.py --insights insights.json
```
```json
{"clips":[{"topic":"やばい話","views":50000,"likes":2000}]}
```

## ファイル構成
```
main.py              # メイン
watchdog.py          # クラッシュ自動復帰
config.yaml          # 設定
src/
  monitor.py         # YouTube監視 (RSS/yt-dlp)
  downloader.py      # 動画DL
  transcriber.py     # 0.1s精度 Gemini OCR + Whisper
  segmenter.py       # フリ→展開→オチ AI選定
  processor.py       # ズーム + ASS字幕焼込
  insights.py        # バズ学習
  drive_uploader.py  # Google Drive保存
tools/
  calibrate_colors.py # テロップ色検出
automation/
  termux_setup.sh    # セットアップ
  termux_boot.sh     # 自動起動
  watch_service.sh   # 操作コマンド
```

## テロップスタイル
| 話者 | フォント | テキスト色 | ストローク |
|------|---------|-----------|----------|
| 中町綾 | けいふぉんと | ピンク | 白 |
| 中町純平 | けいふぉんと | シアン | 白 |

## 全て無料
- Gemini 2.0 Flash: OCR + 話題分割
- Whisper: 音声認識
- FFmpeg: 動画加工
- yt-dlp: ダウンロード
- rclone: Drive同期

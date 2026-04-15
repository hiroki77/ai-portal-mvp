"""動画ダウンロード - yt-dlp使用(完全無料)"""
import os
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoDownloader:
    """YouTube動画ダウンローダー"""

    def __init__(self, config):
        self.config = config
        self.temp_dir = config["paths"]["temp_dir"]
        self.quality = config["download"]["quality"]
        os.makedirs(self.temp_dir, exist_ok=True)

    def download(self, video_url):
        """動画をダウンロードしてファイルパスを返す"""
        logger.info(f"ダウンロード開始: {video_url}")

        output_template = os.path.join(self.temp_dir, "%(id)s.%(ext)s")

        cmd = [
            "yt-dlp",
            "-f", self.quality,
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--no-playlist",
            "--write-info-json",
            video_url,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800  # 30分タイムアウト
        )

        if result.returncode != 0:
            raise RuntimeError(f"ダウンロード失敗: {result.stderr}")

        # ダウンロードされたファイルを検索
        video_path = self._find_downloaded_file(video_url)
        if not video_path:
            raise FileNotFoundError("ダウンロードファイルが見つかりません")

        file_size = os.path.getsize(video_path) / (1024 * 1024)
        logger.info(f"ダウンロード完了: {video_path} ({file_size:.1f}MB)")
        return video_path

    def _find_downloaded_file(self, video_url):
        """ダウンロードされたファイルを検索"""
        # URLからvideo IDを抽出
        import re
        match = re.search(r"v=([a-zA-Z0-9_-]{11})", video_url)
        if match:
            video_id = match.group(1)
            expected_path = os.path.join(self.temp_dir, f"{video_id}.mp4")
            if os.path.exists(expected_path):
                return expected_path

        # フォールバック: temp_dirの最新mp4ファイル
        mp4_files = sorted(
            Path(self.temp_dir).glob("*.mp4"),
            key=os.path.getmtime, reverse=True
        )
        if mp4_files:
            return str(mp4_files[0])
        return None

    def cleanup(self, video_path):
        """一時ファイル削除"""
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                logger.debug(f"削除: {video_path}")
            # info.jsonも削除
            json_path = video_path.rsplit(".", 1)[0] + ".info.json"
            if os.path.exists(json_path):
                os.remove(json_path)
        except OSError as e:
            logger.warning(f"ファイル削除失敗: {e}")

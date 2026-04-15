"""YouTubeチャンネル監視 - RSS Feed方式(完全無料)"""
import os
import re
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    import feedparser
except ImportError:
    feedparser = None

from src.utils import load_json, save_json

logger = logging.getLogger(__name__)


class YouTubeChannelMonitor:
    """YouTubeチャンネルの新着動画を監視"""

    def __init__(self, config):
        self.config = config
        self.channel_id = config["channel"]["channel_id"]
        self.channel_name = config["channel"]["name"]
        self.history_file = os.path.join(
            config["paths"]["data_dir"], "processed_videos.json"
        )
        self.processed = load_json(self.history_file, default=[])

        # チャンネルIDが未設定の場合、自動検出
        if not self.channel_id:
            self.channel_id = self._resolve_channel_id()
            if self.channel_id:
                logger.info(f"チャンネルID検出: {self.channel_id}")

    def _resolve_channel_id(self):
        """チャンネル名からIDを自動検出(yt-dlp使用)"""
        try:
            result = subprocess.run(
                [
                    "yt-dlp", "--flat-playlist", "--print", "channel_id",
                    "--playlist-items", "1",
                    f"ytsearch1:{self.channel_name}",
                ],
                capture_output=True, text=True, timeout=30,
            )
            channel_id = result.stdout.strip()
            if channel_id and channel_id.startswith("UC"):
                return channel_id
        except Exception as e:
            logger.warning(f"チャンネルID自動検出失敗: {e}")

        # フォールバック: 中町兄妹の既知チャンネルID
        return "UCkEMjbMBUEhmz08tPMSvfvA"

    def _get_rss_url(self):
        """RSS URL取得"""
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"

    def check_new_videos(self):
        """新着動画をチェック"""
        new_videos = []

        # 方式1: RSS Feed
        if feedparser:
            new_videos = self._check_via_rss()
        
        # 方式2: yt-dlp fallback
        if not new_videos:
            new_videos = self._check_via_ytdlp()

        # 処理済みを除外
        processed_ids = set(self.processed)
        new_videos = [v for v in new_videos if v["id"] not in processed_ids]

        if new_videos:
            logger.info(f"新着動画: {len(new_videos)}件")
            for v in new_videos:
                logger.info(f"  - {v['title']}")
        else:
            logger.debug("新着動画なし")

        return new_videos

    def _check_via_rss(self):
        """RSS Feedで新着チェック"""
        try:
            feed = feedparser.parse(self._get_rss_url())
            videos = []
            for entry in feed.entries[:5]:  # 最新5件
                video_id = entry.yt_videoid if hasattr(entry, "yt_videoid") else ""
                if not video_id:
                    # URLからIDを抽出
                    match = re.search(r"v=([a-zA-Z0-9_-]{11})", entry.link)
                    video_id = match.group(1) if match else ""
                if video_id:
                    videos.append({
                        "id": video_id,
                        "title": entry.title,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "published": entry.get("published", ""),
                    })
            return videos
        except Exception as e:
            logger.warning(f"RSS取得失敗: {e}")
            return []

    def _check_via_ytdlp(self):
        """yt-dlpで新着チェック(フォールバック)"""
        try:
            result = subprocess.run(
                [
                    "yt-dlp", "--flat-playlist",
                    "--print", "%(id)s\t%(title)s",
                    "--playlist-items", "1-5",
                    f"https://www.youtube.com/channel/{self.channel_id}/videos",
                ],
                capture_output=True, text=True, timeout=60,
            )
            videos = []
            for line in result.stdout.strip().split("\n"):
                if "\t" in line:
                    vid, title = line.split("\t", 1)
                    videos.append({
                        "id": vid,
                        "title": title,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "published": "",
                    })
            return videos
        except Exception as e:
            logger.warning(f"yt-dlpチェック失敗: {e}")
            return []

    def mark_processed(self, video_id):
        """処理済みとして記録"""
        if video_id not in self.processed:
            self.processed.append(video_id)
            save_json(self.processed, self.history_file)
            logger.info(f"処理済み記録: {video_id}")

    def is_processed(self, video_id):
        """処理済みかチェック"""
        return video_id in self.processed

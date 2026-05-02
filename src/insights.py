"""インサイト学習エンジン
翌日にインサイトデータを渡すと、
次回以降の切り抜き選定に反映する
"""
import os
import json
import logging
from datetime import datetime
from src.utils import load_json, save_json

logger = logging.getLogger(__name__)


class InsightsEngine:

    def __init__(self, config):
        self.config = config
        self.enabled = config["insights"]["enabled"]
        self.data_file = config["insights"]["data_file"]
        self.history_file = config["insights"]["history_file"]
        self.data = load_json(self.data_file, default={
            "clips": [],
            "preferences": {
                "boost_keywords": [],
                "preferred_duration": 35,
                "avoid_keywords": [],
            },
        })

    def get_preferences(self):
        if not self.enabled:
            return {}
        return self.data.get("preferences", {})

    def record_clip(self, clip_info):
        """generated clipを記録"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "duration": clip_info.get("duration", 0),
            "score": clip_info.get("score", 0),
            "topic": clip_info.get("topic", ""),
            "views": 0,
            "likes": 0,
            "comments": 0,
        }
        self.data["clips"].append(entry)
        save_json(self.data, self.data_file)

    def update_insights(self, insights_data):
        """ユーザーがインサイトデータを渡したら学習

        insights_dataの例:
        {
            "clips": [
                {"topic": "...", "views": 10000, "likes": 500},
                ...
            ]
        }
        """
        if not insights_data:
            return

        clips = insights_data.get("clips", [])
        if not clips:
            return

        # パフォーマンス更新
        for clip in clips:
            for existing in self.data["clips"]:
                if existing["topic"] == clip.get("topic", ""):
                    existing["views"] = clip.get("views", 0)
                    existing["likes"] = clip.get("likes", 0)
                    existing["comments"] = clip.get("comments", 0)

        # バズったクリップの傾向を分析
        self._analyze_trends()
        save_json(self.data, self.data_file)
        logger.info("インサイト更新完了")

    def _analyze_trends(self):
        """clipsからトレンドを分析してpreferencesを更新"""
        clips = self.data.get("clips", [])
        scored = [c for c in clips if c.get("views", 0) > 0]
        if not scored:
            return

        # ビュー数上位のクリップからキーワード抽出
        scored.sort(key=lambda c: c.get("views", 0), reverse=True)
        top_clips = scored[:5]

        # キーワード頻度
        word_freq = {}
        for clip in top_clips:
            topic = clip.get("topic", "")
            for word in topic.split():
                if len(word) >= 2:
                    word_freq[word] = word_freq.get(word, 0) + 1

        boost = [w for w, c in sorted(word_freq.items(), key=lambda x: -x[1])[:10]]
        self.data["preferences"]["boost_keywords"] = boost

        # 理想の長さ
        if top_clips:
            durations = [c.get("duration", 35) for c in top_clips]
            avg_dur = sum(durations) / len(durations)
            self.data["preferences"]["preferred_duration"] = round(avg_dur)

        logger.info(f"トレンド分析: boost={boost}, dur={self.data['preferences']['preferred_duration']}s")

"""トピックセグメント分割 & クリップ選定
字幕データから話題の切れ目を検出し、
20秒～60秒の話がまとまるクリップを選定
"""
import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClipSegment:
    start: float
    end: float
    subtitles: list
    score: float = 0.0
    topic_summary: str = ""

    @property
    def duration(self):
        return self.end - self.start


class TopicSegmenter:
    # 話題切れ目を示すキーワード
    TOPIC_BREAK_WORDS = [
        "で", "でさ", "というわけで", "ということで",
        "次", "じゃあ", "ところで", "ちなみに",
        "あと", "それで", "あのさ", "えーと",
        "もう一つ", "続いて", "最後に",
    ]
    # バズりやすいキーワード
    VIRAL_WORDS = [
        "やばい", "マジ", "ウソ", "笑", "草",
        "可愛い", "かわいい", "無理", "ワロタ",
        "神", "最高", "キモい", "えぐい",
        "怖い", "可哀想う", "おもろい",
        "善い", "エモい", "泣く", "泣いた",
    ]

    def __init__(self, config):
        self.config = config
        self.min_dur = config["clips"]["min_duration"]
        self.max_dur = config["clips"]["max_duration"]
        self.clip_count = config["clips"]["count"]

    def select_clips(self, subtitles, video_path, preferences=None):
        """字幕データからベスト3クリップを選定"""
        if not subtitles:
            return []

        # 1. 話題の境界を検出
        boundaries = self._find_topic_boundaries(subtitles)

        # 2. 候補クリップを生成
        candidates = self._generate_candidates(subtitles, boundaries)

        # 3. スコアリング
        for clip in candidates:
            clip.score = self._score_clip(clip, preferences)

        # 4. 重複しないトップ3を選定
        selected = self._select_non_overlapping(candidates, self.clip_count)
        logger.info(f"{len(selected)}クリップ選定完了")
        for i, c in enumerate(selected):
            logger.info(f"  Clip{i+1}: {c.start:.1f}s-{c.end:.1f}s ({c.duration:.1f}s) score={c.score:.2f}")
        return selected

    def _find_topic_boundaries(self, subtitles):
        boundaries = [0]
        for i, sub in enumerate(subtitles):
            if i == 0:
                continue
            prev = subtitles[i - 1]
            # 無音区間(2秒以上)
            if sub.start - prev.end > 2.0:
                boundaries.append(i)
                continue
            # 話題切れ目キーワード
            for word in self.TOPIC_BREAK_WORDS:
                if sub.text.startswith(word):
                    boundaries.append(i)
                    break
            # 話者切り替わり(連続3回同じ話者から別の話者)
            if i >= 2:
                if (subtitles[i-1].speaker == subtitles[i-2].speaker and
                        sub.speaker != subtitles[i-1].speaker and
                        sub.speaker != "unknown"):
                    boundaries.append(i)
        boundaries.append(len(subtitles))
        return sorted(set(boundaries))

    def _generate_candidates(self, subtitles, boundaries):
        candidates = []
        n = len(boundaries)
        for i in range(n - 1):
            for j in range(i + 1, n):
                start_idx = boundaries[i]
                end_idx = boundaries[j]
                if end_idx > len(subtitles):
                    break
                subs = subtitles[start_idx:end_idx]
                if not subs:
                    continue
                start_t = subs[0].start
                end_t = subs[-1].end
                dur = end_t - start_t
                if self.min_dur <= dur <= self.max_dur:
                    candidates.append(ClipSegment(
                        start=start_t,
                        end=end_t,
                        subtitles=subs,
                    ))
                if dur > self.max_dur:
                    break
        # スライディングウィンドウで追加候補
        if len(candidates) < self.clip_count * 3:
            candidates += self._sliding_window_candidates(subtitles)
        return candidates

    def _sliding_window_candidates(self, subtitles):
        candidates = []
        for target_dur in [30, 45, 25, 55]:
            for i in range(len(subtitles)):
                subs = []
                for j in range(i, len(subtitles)):
                    subs.append(subtitles[j])
                    dur = subtitles[j].end - subtitles[i].start
                    if dur >= target_dur:
                        if self.min_dur <= dur <= self.max_dur:
                            candidates.append(ClipSegment(
                                start=subtitles[i].start,
                                end=subtitles[j].end,
                                subtitles=list(subs),
                            ))
                        break
        return candidates

    def _score_clip(self, clip, preferences=None):
        score = 0.0
        text = " ".join(s.text for s in clip.subtitles)

        # バズキーワード
        for word in self.VIRAL_WORDS:
            if word in text:
                score += 3.0

        # 会話の掛け合い(話者切り替わりが多いと良い)
        speaker_changes = 0
        for i in range(1, len(clip.subtitles)):
            if (clip.subtitles[i].speaker != clip.subtitles[i-1].speaker and
                    clip.subtitles[i].speaker != "unknown" and
                    clip.subtitles[i-1].speaker != "unknown"):
                speaker_changes += 1
        score += speaker_changes * 2.0

        # 30-45秒が理想
        if 30 <= clip.duration <= 45:
            score += 5.0
        elif 25 <= clip.duration <= 50:
            score += 3.0

        # 字幕密度(適度な密度が良い)
        density = len(clip.subtitles) / max(clip.duration, 1)
        if 0.3 <= density <= 0.8:
            score += 3.0

        # 強調テロップがある(盛り上がりポイント)
        emphasis_count = sum(1 for s in clip.subtitles if s.style == "emphasis")
        score += emphasis_count * 2.5

        # インサイト反映
        if preferences:
            for kw in preferences.get("boost_keywords", []):
                if kw in text:
                    score += 4.0
            preferred_dur = preferences.get("preferred_duration", 0)
            if preferred_dur > 0:
                dur_diff = abs(clip.duration - preferred_dur)
                score += max(0, 5.0 - dur_diff * 0.2)

        clip.topic_summary = text[:50]
        return score

    def _select_non_overlapping(self, candidates, count):
        candidates.sort(key=lambda c: c.score, reverse=True)
        selected = []
        for clip in candidates:
            overlap = False
            for sel in selected:
                if not (clip.end <= sel.start or clip.start >= sel.end):
                    overlap = True
                    break
            if not overlap:
                selected.append(clip)
            if len(selected) >= count:
                break
        return selected

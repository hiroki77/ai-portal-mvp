"""話題分割 & クリップ選定
Gemini 2.0 Flashで全トランスクリプトを分析し、
話の導入→展開→オチが綺麗に収まる20-60秒のクリップを3本選定
"""
import os
import re
import json
import time
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    genai = None
    gtypes = None


@dataclass
class ClipSegment:
    start: float
    end: float
    subtitles: list
    score: float = 0.0
    topic_summary: str = ""
    reason: str = ""

    @property
    def duration(self):
        return self.end - self.start


class TopicSegmenter:

    def __init__(self, config):
        self.config = config
        self.min_dur = config["clips"]["min_duration"]
        self.max_dur = config["clips"]["max_duration"]
        self.clip_count = config["clips"]["count"]

        tc = config["transcription"]
        self._gemini = None
        self._model = tc.get("gemini_model", "gemini-2.0-flash")
        gkey = tc.get("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
        if gkey and genai:
            self._gemini = genai.Client(api_key=gkey)

    def select_clips(self, subtitles, video_path, preferences=None):
        if not subtitles:
            return []

        # Geminiで知的に選定
        if self._gemini:
            clips = self._select_with_gemini(subtitles, preferences)
            if clips:
                return clips
            logger.warning("Gemini分割失敗、ルールベースにフォールバック")

        # フォールバック: ルールベース
        return self._select_rule_based(subtitles, preferences)

    # =============================================================
    # Gemini AI 話題分割
    # =============================================================

    def _select_with_gemini(self, subtitles, preferences=None):
        # 全字幕をタイムスタンプ付きテキストに変換
        transcript_lines = []
        for s in subtitles:
            speaker = {"aya": "綾", "junpei": "純平"}.get(s.speaker, "不明")
            transcript_lines.append(
                f"[{s.start:.1f}-{s.end:.1f}] {speaker}: {s.text}"
            )
        transcript = "\n".join(transcript_lines)

        # インサイト情報
        boost_info = ""
        if preferences:
            kws = preferences.get("boost_keywords", [])
            if kws:
                boost_info = f"\n過去にバズったキーワード: {", ".join(kws)}"
            pref_dur = preferences.get("preferred_duration", 0)
            if pref_dur:
                boost_info += f"\n過去にバズった平均時間: {pref_dur}秒"

        prompt = (
            "以下は中町兄妹(YouTubeチャンネル)の動画の全字幕データです。"
            "形式: [開始秒-終了秒] 話者: テキスト\n\n"
            f"{transcript}\n\n"
            "この動画から切り抜き動画を作ります。以下の条件で最適な3箇所を選んでください。\n\n"
            "【必須条件】\n"
            f"- 各1クリップは{self.min_dur}秒以上{self.max_dur}秒以内\n"
            "- 話の導入→展開→オチ(結論)まで綺麗に収まること\n"
            "- 話の途中で切れないこと\n"
            "- 3クリップは時間が重複しないこと\n\n"
            "【優先条件】\n"
            "- 兄妹の掛け合いが面白い部分\n"
            "- リアクションが大きい部分(笑い、驚き、ツッコミ)\n"
            "- バズりやすいキャッチーな話題\n"
            "- 感情の起伏がある部分\n"
            f"{boost_info}\n\n"
            "【出力形式】JSON配列のみ。説明不要。\n"
            '[{"start": 開始秒, "end": 終了秒, "topic": "話題の要約", '
            '"reason": "選定理由", "score": 1-10のバズり予測}, ...]'
        )

        for attempt in range(3):
            try:
                resp = self._gemini.models.generate_content(
                    model=self._model,
                    contents=gtypes.Content(
                        parts=[gtypes.Part.from_text(prompt)],
                        role="user",
                    ),
                    config=gtypes.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=1500,
                    ),
                )
                raw = resp.text.strip()
                m = re.search(r'\[.*\]', raw, re.DOTALL)
                if not m:
                    continue

                items = json.loads(m.group())
                clips = []
                for item in items[:self.clip_count]:
                    start = float(item["start"])
                    end = float(item["end"])
                    dur = end - start
                    if dur < self.min_dur or dur > self.max_dur:
                        # 範囲外なら調整
                        if dur < self.min_dur:
                            end = start + self.min_dur
                        elif dur > self.max_dur:
                            end = start + self.max_dur

                    clip_subs = [
                        s for s in subtitles
                        if s.start >= start and s.end <= end
                    ]
                    clips.append(ClipSegment(
                        start=start,
                        end=end,
                        subtitles=clip_subs,
                        score=float(item.get("score", 5)),
                        topic_summary=item.get("topic", ""),
                        reason=item.get("reason", ""),
                    ))

                if clips:
                    for i, c in enumerate(clips):
                        logger.info(
                            f"  Clip{i+1}: {c.start:.1f}s-{c.end:.1f}s "
                            f"({c.duration:.0f}s) score={c.score} "
                            f"「{c.topic_summary}」 {c.reason}"
                        )
                    return clips

            except Exception as e:
                logger.warning(f"Geminiセグメントエラー (attempt {attempt+1}): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)

        return []

    # =============================================================
    # ルールベース フォールバック
    # =============================================================

    TOPIC_BREAK_WORDS = [
        "で", "でさ", "というわけで", "次", "じゃあ",
        "ところで", "ちなみに", "あと", "それで",
        "えーと", "最後に",
    ]
    VIRAL_WORDS = [
        "やばい", "マジ", "笑", "可愛い", "無理",
        "神", "最高", "おもろい", "怖い", "泣く", "エモい",
    ]

    def _select_rule_based(self, subtitles, preferences=None):
        bounds = self._find_boundaries(subtitles)
        cands = self._gen_candidates(subtitles, bounds)
        for c in cands:
            c.score = self._score(c, preferences)
        return self._select_top(cands, self.clip_count)

    def _find_boundaries(self, subs):
        b = [0]
        for i in range(1, len(subs)):
            if subs[i].start - subs[i - 1].end > 2.0:
                b.append(i)
                continue
            for w in self.TOPIC_BREAK_WORDS:
                if subs[i].text.startswith(w):
                    b.append(i)
                    break
        b.append(len(subs))
        return sorted(set(b))

    def _gen_candidates(self, subs, bounds):
        cands = []
        for i in range(len(bounds) - 1):
            for j in range(i + 1, len(bounds)):
                sl = subs[bounds[i]:bounds[j]]
                if not sl:
                    continue
                dur = sl[-1].end - sl[0].start
                if self.min_dur <= dur <= self.max_dur:
                    cands.append(ClipSegment(
                        start=sl[0].start, end=sl[-1].end, subtitles=sl))
                if dur > self.max_dur:
                    break
        return cands

    def _score(self, clip, prefs=None):
        score = 0.0
        text = " ".join(s.text for s in clip.subtitles)
        for w in self.VIRAL_WORDS:
            if w in text:
                score += 3.0
        changes = sum(
            1 for i in range(1, len(clip.subtitles))
            if clip.subtitles[i].speaker != clip.subtitles[i - 1].speaker
            and clip.subtitles[i].speaker != "unknown"
        )
        score += changes * 2.0
        if 30 <= clip.duration <= 45:
            score += 5.0
        emphasis = sum(1 for s in clip.subtitles if s.style == "emphasis")
        score += emphasis * 2.5
        if prefs:
            for kw in prefs.get("boost_keywords", []):
                if kw in text:
                    score += 4.0
        clip.topic_summary = text[:50]
        return score

    def _select_top(self, cands, count):
        cands.sort(key=lambda c: c.score, reverse=True)
        sel = []
        for c in cands:
            if not any(
                not (c.end <= s.start or c.start >= s.end) for s in sel
            ):
                sel.append(c)
            if len(sel) >= count:
                break
        return sel

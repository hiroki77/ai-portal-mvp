"""話題分割 & クリップ選定 v2
Geminiで導入→展開→オチが収まるクリップを選定
プロンプト強化: オチの定義を明確化、切り抜き動画としての完成度を重視
"""
import os
import re
import json
import time
import logging
from dataclasses import dataclass
from typing import List

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
        if self._gemini:
            clips = self._select_gemini(subtitles, preferences)
            if clips:
                return clips
            logger.warning("Gemini失敗、ルールベースにフォールバック")
        return self._select_rules(subtitles, preferences)

    def _select_gemini(self, subtitles, preferences=None):
        lines = []
        for s in subtitles:
            sp = {"aya": "綾", "junpei": "純平"}.get(s.speaker, "?")
            lines.append(f"[{s.start:.1f}-{s.end:.1f}] {sp}: {s.text}")
        transcript = "\n".join(lines)

        boost = ""
        if preferences:
            kws = preferences.get("boost_keywords", [])
            if kws:
                boost += f"\n過去にバズったキーワード: {", ".join(kws)}"
            pd = preferences.get("preferred_duration", 0)
            if pd:
                boost += f"\n過去にバズった平均時間: {pd}秒"

        prompt = (
            "あなたはプロの切り抜き動画クリエイターです。"
            "以下は中町兄妹(YouTubeチャンネル)の動画の全字幕データです。"
            "形式: [開始秒-終了秒] 話者: テキスト\n\n"
            f"{transcript}\n\n"
            "この動画から「それだけ見ても面白い」切り抜き動画を3本作ります。\n\n"
            "【絶対条件】\n"
            f"- {self.min_dur}秒以上{self.max_dur}秒以内\n"
            "- 話の途中で絶対に切らない\n"
            "- 3クリップは時間が重複しない\n\n"
            "【オチの定義 - 最重要】\n"
            "切り抜き動画は「オチ」が全てです。以下のいずれかで終わるクリップを選んでください:\n"
            "- 笑いのオチ: ツッコミ、ボケ、予想外の展開で笑える\n"
            "- 感動のオチ: 良い話、兄妹愛が感じられる\n"
            "- 驚きのオチ: 衡撃の告白、予想外の事実\n"
            "- 共感のオチ: 「わかる～」と思わせる日常的な話題\n"
            "オチのないクリップは絶対にNGです。\n\n"
            "【構成】\n"
            "各クリップはこの構成であること:\n"
            "1. フリ(導入): 視聴者が「何の話？」と興味を持つ部分\n"
            "2. 展開: 話が盛り上がる部分\n"
            "3. オチ: 上記のどれかで綺麗に終わる\n\n"
            "【優先】\n"
            "- 兄妹の掛け合い・テンポのいい会話\n"
            "- リアクションが大きい瞬間\n"
            "- SNSでシェアされそうなキャッチーな瞬間\n"
            f"{boost}\n\n"
            "【出力】JSON配列のみ。説明不要。\n"
            '[{"start":秒,"end":秒,"topic":"話題要約",'
            '"punchline":"オチの内容",'
            '"reason":"選定理由","score":1-10},...]'
        )

        for attempt in range(3):
            try:
                resp = self._gemini.models.generate_content(
                    model=self._model,
                    contents=gtypes.Content(
                        parts=[gtypes.Part.from_text(prompt)], role="user"),
                    config=gtypes.GenerateContentConfig(
                        temperature=0.3, max_output_tokens=2000))
                m = re.search(r'\[.*\]', resp.text.strip(), re.DOTALL)
                if not m:
                    continue
                items = json.loads(m.group())
                clips = []
                for it in items[:self.clip_count]:
                    s, e = float(it["start"]), float(it["end"])
                    if e - s < self.min_dur:
                        e = s + self.min_dur
                    if e - s > self.max_dur:
                        e = s + self.max_dur
                    cs = [sub for sub in subtitles if sub.start >= s and sub.end <= e]
                    clips.append(ClipSegment(
                        start=s, end=e, subtitles=cs,
                        score=float(it.get("score", 5)),
                        topic_summary=it.get("topic", ""),
                        reason=it.get("reason", "")))
                if clips:
                    for i, c in enumerate(clips):
                        logger.info(
                            f"  Clip{i+1}: {c.start:.1f}-{c.end:.1f}s "
                            f"({c.duration:.0f}s) score={c.score}\n"
                            f"    話題: {c.topic_summary}\n"
                            f"    理由: {c.reason}")
                    return clips
            except Exception as e:
                logger.warning(f"Gemini seg error (attempt {attempt+1}): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return []

    # === ルールベース fallback ===

    TOPIC_BREAK = ["で", "でさ", "というわけで", "次", "じゃあ",
                   "ところで", "ちなみに", "あと", "それで", "最後に"]
    VIRAL = ["やばい", "マジ", "笑", "可愛い", "無理", "神",
             "最高", "おもろい", "怖い", "泣く", "エモい"]

    def _select_rules(self, subtitles, preferences=None):
        bounds = [0]
        for i in range(1, len(subtitles)):
            if subtitles[i].start - subtitles[i-1].end > 2.0:
                bounds.append(i)
                continue
            for w in self.TOPIC_BREAK:
                if subtitles[i].text.startswith(w):
                    bounds.append(i)
                    break
        bounds.append(len(subtitles))
        bounds = sorted(set(bounds))
        cands = []
        for i in range(len(bounds)-1):
            for j in range(i+1, len(bounds)):
                sl = subtitles[bounds[i]:bounds[j]]
                if not sl:
                    continue
                dur = sl[-1].end - sl[0].start
                if self.min_dur <= dur <= self.max_dur:
                    cands.append(ClipSegment(
                        start=sl[0].start, end=sl[-1].end, subtitles=sl))
                if dur > self.max_dur:
                    break
        for c in cands:
            text = " ".join(s.text for s in c.subtitles)
            sc = sum(3.0 for w in self.VIRAL if w in text)
            sc += sum(2.0 for i in range(1, len(c.subtitles))
                      if c.subtitles[i].speaker != c.subtitles[i-1].speaker
                      and c.subtitles[i].speaker != "unknown")
            if 30 <= c.duration <= 45:
                sc += 5.0
            c.score = sc
            c.topic_summary = text[:50]
        cands.sort(key=lambda c: c.score, reverse=True)
        sel = []
        for c in cands:
            if not any(not (c.end <= s.start or c.start >= s.end) for s in sel):
                sel.append(c)
            if len(sel) >= self.clip_count:
                break
        return sel

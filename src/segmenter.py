import os, re, json, time, logging
from dataclasses import dataclass
logger = logging.getLogger(__name__)
try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    genai = None; gtypes = None

from src.cost_tracker import get_tracker

# 接続助詞（文の途中を示すパターン）
_CONTINUATION_START = ('て、', 'で、', 'けど、', 'けど', 'から、', 'し、', 'が、', 'って、', 'って')
_CONTINUATION_END   = ('て', 'で', 'けど', 'から', 'し', 'が', 'って', 'ながら', 'たら')
_SENTENCE_FINAL     = ('。', '！', '？', '笑', 'ね', 'よ', 'わ', 'か', 'な', 'ん', '〜', '!', '?')
_SNAP_GAP_SEC       = 0.5   # 前後の字幕との間隔がこれ以上なら文境界とみなす


@dataclass
class ClipSegment:
    start: float
    end: float
    subtitles: list
    score: float = 0.0
    topic_summary: str = ""
    reason: str = ""
    punchline: str = ""

    @property
    def duration(self):
        return self.end - self.start


class TopicSegmenter:
    TB = ['で', 'でさ', 'というわけで', '次', 'じゃあ', 'ところで', 'ちなみに', 'あと', 'それで', '最後に']
    VW = ['やばい', 'マジ', '笑', '可愛い', '無理', '神', '最高', 'おもろい', '怖い', '泣く', 'エモい']
    SILENCE_GAP = 2.0

    def __init__(self, config):
        self.mn = config['clips']['min_duration']
        self.mx = config['clips']['max_duration']
        self.cc = config['clips']['count']
        tc = config['transcription']
        self._g = None
        self._gm = tc.get('gemini_model', 'gemini-2.0-flash')
        gk = tc.get('gemini_api_key', '') or os.environ.get('GEMINI_API_KEY', '')
        if gk and genai:
            self._g = genai.Client(api_key=gk)

    def select_clips(self, subs, video_path, pref=None, audio_features=None):
        if not subs:
            return []
        af = audio_features or self._extract_audio_features(video_path)
        if self._g:
            clips = self._two_phase(subs, pref, af)
            if clips:
                return clips
            logger.warning('2フェーズ失敗, fallback')
        return self._rules(subs, pref)

    # ========================================================
    # Phase 1: 話題境界を検出
    # ========================================================

    def _detect_silence_gaps(self, subs):
        gaps = []
        for i in range(1, len(subs)):
            gap = subs[i].start - subs[i - 1].end
            if gap >= self.SILENCE_GAP:
                gaps.append({'after_time': round(subs[i - 1].end, 1),
                              'before_time': round(subs[i].start, 1),
                              'gap_sec': round(gap, 1)})
        return gaps

    def _phase1_topics(self, subs):
        lines = [
            f"[{x.start:.1f}s] {'綾' if x.speaker == 'aya' else '純平' if x.speaker == 'junpei' else '?'}: {x.text}"
            for x in subs
        ]
        transcript = '\n'.join(lines)
        gaps = self._detect_silence_gaps(subs)
        gap_info = ''
        if gaps:
            gap_lines = [f"  {g['after_time']}s〜{g['before_time']}s ({g['gap_sec']}秒の無音)"
                         for g in gaps[:20]]
            gap_info = '\n\n【無音区間（話題の切れ目の強いヒント）】\n' + '\n'.join(gap_lines)

        prompt = (
            'あなたは中町兄妹（YouTube）動画の構成を分析する専門家です。\n'
            '以下の字幕から「完結した話題の塊」を全て検出してください。\n\n'
            '【必須ルール】\n'
            '- 各話題はフリ（導入）から始まり、オチ・結論・笑いで完全に終わる単位にする\n'
            '- 話の途中（フリの最中・展開の途中）を境界にしてはいけない\n'
            '- 文の途中（〜て/〜で/〜けど/〜から で終わる字幕の直後）を境界にしてはいけない\n'
            '- 無音区間・「じゃあ」「次」「ちなみに」などの転換ワードを境界のヒントにする\n'
            '- 1話題の最低時間: 15秒\n'
            '- 動画全体を隙間なくカバーする\n\n'
            f'【字幕】\n{transcript}'
            f'{gap_info}\n\n'
            'JSON配列のみ出力（説明不要）:\n'
            '[{"start": 秒, "end": 秒, "summary": "話題の概要（20文字以内）", "punchline": "オチの内容"}]'
        )

        for attempt in range(3):
            try:
                r = self._g.models.generate_content(
                    model=self._gm,
                    contents=gtypes.Content(parts=[gtypes.Part.from_text(prompt)], role='user'),
                    config=gtypes.GenerateContentConfig(temperature=0.2, max_output_tokens=3000)
                )
                get_tracker().record_gemini('Phase1: 話題境界検出', self._gm, r)
                m = re.search(r'\[.*\]', r.text.strip(), re.DOTALL)
                if not m:
                    continue
                topics = json.loads(m.group())
                valid = []
                prev_end = subs[0].start
                for t in topics:
                    st, en = float(t['start']), float(t['end'])
                    if en <= st or en - st < 10:
                        continue
                    st = max(st, prev_end - 1.0)
                    valid.append({'start': round(st, 1), 'end': round(en, 1),
                                  'summary': t.get('summary', ''),
                                  'punchline': t.get('punchline', '')})
                    prev_end = en
                if valid:
                    logger.info(f'Phase1: {len(valid)}話題を検出')
                    for i, t in enumerate(valid):
                        logger.info(f"  [{i}] {t['start']:.0f}-{t['end']:.0f}s 「{t['summary']}」")
                    return valid
            except Exception as e:
                logger.warning(f'Phase1 err({attempt + 1}): {e}')
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return []

    # ========================================================
    # Phase 2: 話題リストからクリップ選定
    # ========================================================

    def _merge_short_topics(self, topics):
        if not topics:
            return topics
        merged = list(topics)
        changed = True
        while changed:
            changed = False
            new = []
            i = 0
            while i < len(merged):
                t = merged[i]
                dur = t['end'] - t['start']
                if dur < self.mn and i + 1 < len(merged):
                    nxt = merged[i + 1]
                    if nxt['end'] - t['start'] <= self.mx * 1.5:
                        new.append({'start': t['start'], 'end': nxt['end'],
                                    'summary': t['summary'] + '+' + nxt['summary'],
                                    'punchline': nxt['punchline'] or t['punchline']})
                        i += 2
                        changed = True
                        continue
                new.append(t)
                i += 1
            merged = new
        return merged

    def _phase2_select(self, topics, subs, pref=None, af=None):
        merged = self._merge_short_topics(topics)
        candidates = [(i, t) for i, t in enumerate(merged)
                      if t['end'] - t['start'] >= self.mn] or list(enumerate(merged))

        topics_json = json.dumps(
            [{'index': i, 'start': t['start'], 'end': t['end'],
              'duration_sec': round(t['end'] - t['start'], 0),
              'summary': t['summary'], 'punchline': t['punchline']}
             for i, t in candidates],
            ensure_ascii=False, indent=2
        )
        boost = ''
        if pref:
            kw = pref.get('boost_keywords', [])
            if kw:
                boost += f"\n過去バズキーワード（優先）: {', '.join(kw)}"
            pd = pref.get('preferred_duration', 0)
            if pd:
                boost += f'\n過去バズ平均尺: {pd}秒'
        audio_info = ''
        if af and af.get('loud_sections'):
            ls = ', '.join(f"{x['start']}-{x['end']}s" for x in af['loud_sections'])
            audio_info = f'\n盛り上がり区間: {ls}\nこの区間を含む話題を優先してください。'

        prompt = (
            'あなたはプロの切り抜き動画クリエイターです。\n'
            '以下は中町兄妹動画の「完結した話題リスト」です。\n\n'
            f'{topics_json}\n\n'
            f'この中から切り抜き動画として最高の{self.cc}本を選んでください。\n\n'
            '【選定基準】\n'
            f'- {self.mn}〜{self.mx}秒に収まること（duration_secを確認）\n'
            '- オチ（punchline）が明確にある\n'
            '- 兄妹の掛け合い、笑い、驚き、共感のどれかがある\n'
            '- 重複なし\n'
            f'{boost}{audio_info}\n\n'
            '【厳守】start/endは話題リストの値をそのまま使う。絶対に変えない。\n'
            'JSON配列のみ出力:\n'
            '[{"index": 話題のindex番号, "score": 1-10, "reason": "理由（30文字以内）"}]'
        )

        for attempt in range(3):
            try:
                r = self._g.models.generate_content(
                    model=self._gm,
                    contents=gtypes.Content(parts=[gtypes.Part.from_text(prompt)], role='user'),
                    config=gtypes.GenerateContentConfig(temperature=0.3, max_output_tokens=1000)
                )
                get_tracker().record_gemini('Phase2: クリップ選定', self._gm, r)
                m = re.search(r'\[.*\]', r.text.strip(), re.DOTALL)
                if not m:
                    continue
                selected = json.loads(m.group())
                candidate_map = {i: t for i, t in candidates}
                clips = []
                used = set()
                for sel in selected[:self.cc]:
                    idx = int(sel.get('index', -1))
                    if idx in used or idx not in candidate_map:
                        continue
                    used.add(idx)
                    t = candidate_map[idx]
                    st, en = t['start'], t['end']
                    if en - st > self.mx:
                        st = en - self.mx
                    clip_subs = [s for s in subs if s.start >= st and s.end <= en + 1.0]
                    clips.append(ClipSegment(
                        start=round(st, 1), end=round(en, 1), subtitles=clip_subs,
                        score=float(sel.get('score', 5)),
                        topic_summary=t['summary'], punchline=t['punchline'],
                        reason=sel.get('reason', '')
                    ))
                if clips:
                    return clips
            except Exception as e:
                logger.warning(f'Phase2 err({attempt + 1}): {e}')
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return []

    # ========================================================
    # 発話境界スナップ（ゼロコスト・ハードルール）
    # ========================================================

    def _is_sentence_final(self, text: str) -> bool:
        return any(text.rstrip().endswith(e) for e in _SENTENCE_FINAL)

    def _is_continuation_start(self, text: str) -> bool:
        return any(text.lstrip().startswith(c) for c in _CONTINUATION_START)

    def _is_continuation_end(self, text: str) -> bool:
        stripped = text.rstrip('　 ')
        return any(stripped.endswith(c) for c in _CONTINUATION_END) and not self._is_sentence_final(stripped)

    def _snap_start(self, clip_start: float, all_subs: list) -> float:
        """
        クリップ開始を「文の頭」にスナップ。
        接続助詞で始まる字幕や、前字幕と連続している字幕は前に戻す。
        """
        idx = next((i for i, s in enumerate(all_subs) if s.start >= clip_start - 0.1), 0)
        moved = False
        for _ in range(8):  # 最大8字幕分さかのぼる
            if idx <= 0:
                break
            sub = all_subs[idx]
            prev = all_subs[idx - 1]
            gap = sub.start - prev.end
            # 前字幕との間隔が十分あり、前字幕が文末 → クリーンな開始
            if gap >= _SNAP_GAP_SEC and self._is_sentence_final(prev.text):
                break
            # この字幕が接続助詞始まり → 前に戻る必要あり
            if self._is_continuation_start(sub.text):
                idx -= 1
                moved = True
                continue
            # 前字幕が文の途中で終わっている → 前に戻る
            if self._is_continuation_end(prev.text):
                idx -= 1
                moved = True
                continue
            break
        new_start = round(all_subs[idx].start, 1)
        if moved:
            logger.info(f'  START スナップ: {clip_start:.1f}s → {new_start:.1f}s')
        return new_start

    def _snap_end(self, clip_end: float, all_subs: list) -> float:
        """
        クリップ終了を「文の末尾」にスナップ。
        接続助詞で終わる字幕は次に進む。
        """
        idx = next((i for i in range(len(all_subs) - 1, -1, -1)
                    if all_subs[i].end <= clip_end + 0.1), len(all_subs) - 1)
        moved = False
        for _ in range(8):
            if idx >= len(all_subs) - 1:
                break
            sub = all_subs[idx]
            nxt = all_subs[idx + 1]
            # 文末で終わっている → クリーンな終わり
            if self._is_sentence_final(sub.text):
                break
            # 接続助詞で終わっている → 次に進む
            if self._is_continuation_end(sub.text):
                idx += 1
                moved = True
                continue
            # 次字幕との間隔が十分ある → クリーンな終わり
            if nxt.start - sub.end >= _SNAP_GAP_SEC:
                break
            # 次字幕が接続助詞始まり → まだ文が続いている
            if self._is_continuation_start(nxt.text):
                idx += 1
                moved = True
                continue
            break
        new_end = round(all_subs[idx].end + 0.2, 1)  # 0.2秒余白
        if moved:
            logger.info(f'  END   スナップ: {clip_end:.1f}s → {new_end:.1f}s')
        return new_end

    def _enforce_sentence_boundaries(self, clips: list, all_subs: list) -> list:
        """全クリップに発話境界スナップを適用（ハードルール・ゼロコスト）"""
        result = []
        for c in clips:
            new_start = self._snap_start(c.start, all_subs)
            new_end   = self._snap_end(c.end, all_subs)
            # 修正後にdurationがmxを大幅超過したら元に戻す
            if new_end - new_start > self.mx * 1.15:
                logger.warning(f'  スナップ後duration超過, 元に戻す ({new_end - new_start:.0f}s)')
                result.append(c)
                continue
            c.start = new_start
            c.end   = new_end
            c.subtitles = [s for s in all_subs if s.start >= c.start and s.end <= c.end + 0.5]
            result.append(c)
        return result

    # ========================================================
    # Phase 3: 完結性バリデーション（AI最終確認）
    # ========================================================

    def _phase3_validate(self, clips: list, all_subs: list) -> list:
        """Phase3: 各クリップの前後文脈を含めてAIに完結性を確認・修正させる"""
        result = []
        for c in clips:
            fixed = self._validate_one(c, all_subs)
            result.append(fixed)
        return result

    def _validate_one(self, clip: ClipSegment, all_subs: list) -> ClipSegment:
        context_sec = 30.0
        pre  = [s for s in all_subs if clip.start - context_sec <= s.start < clip.start]
        body = [s for s in all_subs if clip.start <= s.start <= clip.end]
        post = [s for s in all_subs if clip.end < s.end <= clip.end + context_sec]

        def fmt(segs, label):
            if not segs:
                return ''
            lines = [f"[{s.start:.1f}s] {'綾' if s.speaker == 'aya' else '純平' if s.speaker == 'junpei' else '?'}: {s.text}"
                     for s in segs]
            return f'【{label}】\n' + '\n'.join(lines)

        prompt = (
            f"{fmt(pre, 'クリップ前の文脈（参考）')}\n\n"
            f"【★クリップ本体 (start={clip.start:.1f}s / end={clip.end:.1f}s)】\n"
            + '\n'.join(f"[{s.start:.1f}s] {'綾' if s.speaker == 'aya' else '純平' if s.speaker == 'junpei' else '?'}: {s.text}" for s in body)
            + f"\n\n{fmt(post, 'クリップ後の文脈（参考）')}\n\n"
            'このクリップについて以下を判定してください。\n\n'
            '1. is_complete: このクリップ単体で完結した話題か（true/false）\n'
            '2. start_issue: 開始が話・文の途中なら問題を説明、なければnull\n'
            '3. end_issue:   終了が話・文の途中なら問題を説明、なければnull\n'
            '4. suggested_start: 正しい開始時刻（秒）。問題なければ元の値\n'
            '5. suggested_end:   正しい終了時刻（秒）。問題なければ元の値\n\n'
            'JSONのみ出力:\n'
            '{"is_complete": bool, "start_issue": str|null, "end_issue": str|null, '
            '"suggested_start": 秒, "suggested_end": 秒}'
        )

        for attempt in range(2):
            try:
                r = self._g.models.generate_content(
                    model=self._gm,
                    contents=gtypes.Content(parts=[gtypes.Part.from_text(prompt)], role='user'),
                    config=gtypes.GenerateContentConfig(temperature=0.1, max_output_tokens=400)
                )
                get_tracker().record_gemini(f'Phase3: バリデーション「{clip.topic_summary[:12]}」', self._gm, r)
                m = re.search(r'\{.*\}', r.text.strip(), re.DOTALL)
                if not m:
                    break
                v = json.loads(m.group())
                if v.get('start_issue'):
                    logger.info(f'  Phase3 START修正: {v["start_issue"]}')
                if v.get('end_issue'):
                    logger.info(f'  Phase3 END修正: {v["end_issue"]}')
                new_st = float(v.get('suggested_start', clip.start))
                new_en = float(v.get('suggested_end', clip.end))
                if abs(new_st - clip.start) > 0.5 or abs(new_en - clip.end) > 0.5:
                    if self.mn <= new_en - new_st <= self.mx * 1.1:
                        logger.info(f'  Phase3 修正適用: {clip.start:.1f}→{new_st:.1f}s, {clip.end:.1f}→{new_en:.1f}s')
                        clip.start = round(new_st, 1)
                        clip.end   = round(new_en, 1)
                        clip.subtitles = [s for s in all_subs
                                          if s.start >= clip.start and s.end <= clip.end + 0.5]
                break
            except Exception as e:
                logger.warning(f'Phase3 err({attempt + 1}): {e}')
                if attempt < 1:
                    time.sleep(2)
        return clip

    # ========================================================
    # 統合パイプライン
    # ========================================================

    def _two_phase(self, subs, pref=None, af=None):
        logger.info('Phase1: 話題境界を検出中...')
        topics = self._phase1_topics(subs)
        if not topics:
            return []
        logger.info('Phase2: 最高クリップを選定中...')
        clips = self._phase2_select(topics, subs, pref, af)
        if not clips:
            return []
        logger.info('発話境界スナップ（ハードルール）...')
        clips = self._enforce_sentence_boundaries(clips, subs)
        logger.info('Phase3: 完結性バリデーション...')
        clips = self._phase3_validate(clips, subs)
        for i, c in enumerate(clips):
            logger.info(f'  最終Clip{i+1}: {c.start:.1f}-{c.end:.1f}s({c.duration:.0f}s) '
                        f'「{c.topic_summary}」 オチ:{c.punchline[:20] if c.punchline else "-"}')
        return clips

    # ========================================================
    # 音声特徴抽出
    # ========================================================

    def _extract_audio_features(self, video_path):
        try:
            import subprocess, numpy as np
            result = subprocess.run(
                ['ffmpeg', '-i', str(video_path), '-af',
                 'astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level',
                 '-f', 'null', '-'],
                capture_output=True, text=True, timeout=300)
            levels = []; times = []
            for line in result.stderr.split('\n'):
                if 'RMS_level' in line:
                    m = re.search(r'RMS_level=(-?[\d.]+)', line)
                    if m: levels.append(float(m.group(1)))
                elif 'pts_time:' in line:
                    m = re.search(r'pts_time:([\d.]+)', line)
                    if m: times.append(float(m.group(1)))
            if not levels:
                return {'peaks': [], 'loud_sections': []}
            arr = np.array(levels)
            mean_lv = np.mean(arr); std_lv = np.std(arr)
            peaks = [{'time': round(times[i] if i < len(times) else i * 1.0, 1), 'level': round(lv, 1)}
                     for i, lv in enumerate(levels) if lv > mean_lv + 1.5 * std_lv]
            loud = []
            if peaks:
                seg_start = peaks[0]['time']; prev_t = peaks[0]['time']
                for p in peaks[1:]:
                    if p['time'] - prev_t > 3.0:
                        loud.append({'start': round(seg_start, 1), 'end': round(prev_t + 1, 1)})
                        seg_start = p['time']
                    prev_t = p['time']
                loud.append({'start': round(seg_start, 1), 'end': round(prev_t + 1, 1)})
            return {'peaks': peaks[:20], 'loud_sections': loud[:10]}
        except Exception as e:
            logger.debug(f'audio features skip: {e}')
            return {'peaks': [], 'loud_sections': []}

    # ========================================================
    # ルールベース fallback
    # ========================================================

    def _rules(self, subs, pref=None):
        b = [0]
        for i in range(1, len(subs)):
            if subs[i].start - subs[i - 1].end > 2.0:
                b.append(i); continue
            for w in self.TB:
                if subs[i].text.startswith(w):
                    b.append(i); break
        b.append(len(subs)); b = sorted(set(b))
        ca = []
        for i in range(len(b) - 1):
            for j in range(i + 1, len(b)):
                sl = subs[b[i]:b[j]]
                if not sl: continue
                d = sl[-1].end - sl[0].start
                if self.mn <= d <= self.mx:
                    ca.append(ClipSegment(start=sl[0].start, end=sl[-1].end, subtitles=sl))
                if d > self.mx: break
        for c in ca:
            tx = ' '.join(x.text for x in c.subtitles)
            sc = sum(3.0 for w in self.VW if w in tx)
            sc += sum(2.0 for i in range(1, len(c.subtitles))
                      if c.subtitles[i].speaker != c.subtitles[i - 1].speaker
                      and c.subtitles[i].speaker != 'unknown')
            if 30 <= c.duration <= 45: sc += 5.0
            c.score = sc; c.topic_summary = tx[:50]
        ca.sort(key=lambda c: c.score, reverse=True)
        se = []
        for c in ca:
            if not any(not (c.end <= x.start or c.start >= x.end) for x in se):
                se.append(c)
            if len(se) >= self.cc: break
        return se

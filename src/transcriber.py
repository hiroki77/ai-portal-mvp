import os, re, json, time, base64, logging, shutil
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Optional
import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None
try:
    import whisper as _whisper_local_lib
except ImportError:
    _whisper_local_lib = None
try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    genai = None; gtypes = None
try:
    import easyocr
except ImportError:
    easyocr = None
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None
from src.utils import run_ffmpeg, get_video_resolution, get_video_duration
from src.cost_tracker import get_tracker
logger = logging.getLogger(__name__)
FI = 0.1
WHISPER_API_MAX_MB = 24.0   # Whisper API のファイル制限（25MB）より小さく設定
WHISPER_CHUNK_SEC  = 1200   # 20分別に分割


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str
    speaker: str
    style: str
    confidence: float = 1.0
    words: list = field(default_factory=list)  # [{word, start, end}] Whisper APIの単語タイムスタンプ

    def to_dict(self):
        d = asdict(self)
        d.pop('words', None)
        return d


class SubtitleRecognizer:
    DIFF_TH    = 12.0
    BRIGHT_TH  = 140
    NO_SPEECH_TH = 0.8  # Whisper API: 非音声区間の間値

    def __init__(self, config):
        tc = config['transcription']
        self.lang          = tc['language']
        self.ocr_engine    = tc.get('ocr_engine', 'gemini')
        self.srr           = tc['subtitle_region_ratio']
        self.bs            = tc.get('batch_size', 4)
        self.mr            = tc.get('max_retries', 3)
        self.td            = config['paths']['temp_dir']
        self.whisper_engine = tc.get('whisper_engine', 'local')  # 'api' or 'local'
        self.wm            = tc.get('whisper_model', 'small')

        # Gemini
        self._g  = None
        self._gm = tc.get('gemini_model', 'gemini-2.0-flash')
        gk = tc.get('gemini_api_key', '') or os.environ.get('GEMINI_API_KEY', '')
        if gk and genai:
            self._g = genai.Client(api_key=gk)

        # OpenAI Whisper API
        self._oai = None
        ok = tc.get('openai_api_key', '') or os.environ.get('OPENAI_API_KEY', '')
        if ok and OpenAI:
            self._oai = OpenAI(api_key=ok)
        elif self.whisper_engine == 'api':
            logger.warning('OPENAI_API_KEY 未設定。ローカルWhisperにフォールバック')
            self.whisper_engine = 'local'

        self._wm_obj = None
        self._or     = None

    # =========================================================
    # メインエントリーポイント
    # =========================================================

    def recognize(self, vp):
        logger.info(f'[Transcribe] {Path(vp).name}')
        logger.info(f'  Whisperエンジン: {self.whisper_engine}')
        ws = self._whisper(vp)
        logger.info(f'  Whisperセグメント: {len(ws)}')

        if self.ocr_engine == 'gemini' and self._g:
            os_ = self._smart_ocr(vp)
        else:
            os_ = self._easyocr(vp)
        logger.info(f'  OCRセグメント: {len(os_)}')

        merged = self._cross_validate(ws, os_)
        logger.info(f'  検証後: {len(merged)}')
        return merged

    # =========================================================
    # Whisper API (高速・高精度)
    # =========================================================

    def _whisper(self, vp):
        if self.whisper_engine == 'api' and self._oai:
            return self._whisper_api(vp)
        return self._whisper_local(vp)

    def _whisper_api(self, vp):
        """
        OpenAI Whisper APIで音声認識。
        - 平均 2〜3分/本（ローカルの1/10）
        - セグメント境界が已に文第境界に近い
        - 各セグメントに no_speech_prob で非音声フィルタリングあり
        """
        au = os.path.join(self.td, 'audio_api.mp3')
        # 32kbps mono 16kHz: 長氷動画でも小サイズ・十分な品質
        run_ffmpeg(['-i', str(vp), '-vn', '-acodec', 'libmp3lame',
                    '-ar', '16000', '-ac', '1', '-b:a', '32k', au])
        duration = get_video_duration(vp)
        file_mb = os.path.getsize(au) / 1024 / 1024
        logger.info(f'  音声ファイル: {file_mb:.1f}MB')

        try:
            if file_mb > WHISPER_API_MAX_MB:
                logger.info(f'  {file_mb:.1f}MB > {WHISPER_API_MAX_MB}MB → {WHISPER_CHUNK_SEC//60}分割りで処理')
                return self._whisper_api_chunked(au, duration)
            return self._whisper_api_single(au, duration)
        finally:
            if os.path.exists(au):
                os.remove(au)

    def _whisper_api_single(self, au_path: str, duration: float) -> List[SubtitleEntry]:
        with open(au_path, 'rb') as f:
            tr = self._oai.audio.transcriptions.create(
                model='whisper-1',
                file=f,
                language=self.lang,
                response_format='verbose_json',
                timestamp_granularities=['segment', 'word']
            )
        get_tracker().record_whisper_api('Whisper API', duration)
        return self._parse_whisper_segments(tr.segments, tr.words if hasattr(tr, 'words') else [])

    def _whisper_api_chunked(self, au_path: str, duration: float) -> List[SubtitleEntry]:
        """音声ファイルが大きい場合は WHISPER_CHUNK_SEC 秒ごとに分割して処理"""
        chunks = []
        offset = 0.0
        chunk_idx = 0
        all_subs = []

        while offset < duration:
            chunk_path = os.path.join(self.td, f'chunk_{chunk_idx:03d}.mp3')
            run_ffmpeg(['-i', au_path, '-ss', str(offset),
                        '-t', str(WHISPER_CHUNK_SEC), '-c', 'copy', chunk_path])
            chunks.append((chunk_path, offset))
            offset += WHISPER_CHUNK_SEC
            chunk_idx += 1

        logger.info(f'  分割数: {len(chunks)}チャンク')
        for path, time_offset in chunks:
            try:
                with open(path, 'rb') as f:
                    tr = self._oai.audio.transcriptions.create(
                        model='whisper-1',
                        file=f,
                        language=self.lang,
                        response_format='verbose_json',
                        timestamp_granularities=['segment']
                    )
                chunk_duration = min(WHISPER_CHUNK_SEC, duration - time_offset)
                get_tracker().record_whisper_api(f'Whisper API chunk@{time_offset:.0f}s', chunk_duration)
                subs = self._parse_whisper_segments(tr.segments, [], offset=time_offset)
                all_subs.extend(subs)
            finally:
                if os.path.exists(path):
                    os.remove(path)

        return all_subs

    def _parse_whisper_segments(self, segments, words, offset: float = 0.0) -> List[SubtitleEntry]:
        result = []
        word_list = list(words) if words else []
        for seg in segments:
            # 非音声区間はスキップ
            if getattr(seg, 'no_speech_prob', 0.0) > self.NO_SPEECH_TH:
                continue
            text = seg.text.strip()
            if not text:
                continue
            st = round(float(seg.start) + offset, 2)
            en = round(float(seg.end) + offset, 2)
            # このセグメント内の単語タイムスタンプを取得
            seg_words = [
                {'word': w.word, 'start': round(float(w.start) + offset, 2),
                 'end': round(float(w.end) + offset, 2)}
                for w in word_list
                if float(w.start) >= float(seg.start) and float(w.end) <= float(seg.end)
            ]
            result.append(SubtitleEntry(
                start=st, end=en, text=text,
                speaker='unknown', style='normal',
                confidence=0.98,
                words=seg_words
            ))
        return result

    # =========================================================
    # ローカルWhisper (フォールバック)
    # =========================================================

    def _whisper_local(self, vp):
        au = os.path.join(self.td, 'a.wav')
        run_ffmpeg(['-i', str(vp), '-vn', '-acodec', 'pcm_s16le',
                    '-ar', '16000', '-ac', '1', au])
        try:
            if self._wm_obj is None:
                logger.info(f'  Whisperモデルロード: {self.wm}')
                self._wm_obj = _whisper_local_lib.load_model(self.wm)
            r = self._wm_obj.transcribe(au, language=self.lang,
                                        word_timestamps=True, verbose=False)
            return [
                SubtitleEntry(start=x['start'], end=x['end'],
                              text=x['text'].strip(), speaker='unknown',
                              style='normal')
                for x in r.get('segments', []) if x['text'].strip()
            ]
        finally:
            if os.path.exists(au):
                os.remove(au)

    # =========================================================
    # Gemini OCR (話者識別・テロップ読取り)
    # =========================================================

    def _smart_ocr(self, vp):
        w, h = get_video_resolution(vp)
        sy = int(h * (1 - self.srr)); sh = h - sy
        fd = os.path.join(self.td, 'f01')
        os.makedirs(fd, exist_ok=True)
        try:
            run_ffmpeg(['-i', str(vp), '-vf', f'fps=10,crop=iw:{sh}:0:{sy}',
                        '-q:v', '2', os.path.join(fd, 'f_%07d.jpg')], timeout=1800)
            ff = sorted(Path(fd).glob('f_*.jpg'))
            if not ff:
                return []
            logger.info(f'  フレーム数: {len(ff)}')
            cp = self._detect(ff)
            logger.info(f'  変化フレーム: {len(cp)}')
            if not cp:
                return []
            oc = self._ocr_cp(cp)
            return self._build(oc)
        finally:
            shutil.rmtree(fd, ignore_errors=True)

    def _detect(self, ff):
        ch = []; pg = None; pt = False
        for i, fp in enumerate(ff):
            f = cv2.imread(str(fp))
            if f is None:
                continue
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            br = np.sum(g > self.BRIGHT_TH) / g.size
            ht = 0.003 < br < 0.45
            if pg is not None:
                d = np.mean(cv2.absdiff(g, pg))
                if d > self.DIFF_TH:
                    ch.append((i, str(fp)))
                elif ht != pt:
                    ch.append((i, str(fp)))
            elif ht:
                ch.append((i, str(fp)))
            pg = g; pt = ht
        return ch

    def _ocr_cp(self, cp):
        res = []
        for bi in range(0, len(cp), self.bs):
            b = cp[bi:bi + self.bs]
            ps = [c[1] for c in b]; ix = [c[0] for c in b]
            ts = [i * FI for i in ix]
            oc = self._gbr(ps, ts)
            res.extend([(ix[j], ts[j], oc[j][1], oc[j][2], oc[j][3])
                         for j in range(len(oc))])
            if bi + self.bs < len(cp):
                time.sleep(4.5)
        return res

    def _build(self, oc):
        if not oc:
            return []
        ent = []
        for i, (idx, ts, tx, sp, sy) in enumerate(oc):
            if not tx:
                continue
            st = ts
            en = oc[i + 1][1] if i + 1 < len(oc) else ts + 2.0
            if ent and ent[-1].text == tx:
                ent[-1].end = round(en, 1); continue
            ent.append(SubtitleEntry(start=round(st, 1), end=round(en, 1),
                                     text=tx, speaker=sp, style=sy, confidence=0.95))
        return ent

    def _gbr(self, ps, ts):
        for a in range(self.mr):
            try:
                return self._gb(ps, ts)
            except Exception as e:
                logger.warning(f'OCR err({a + 1}): {e}')
                if a < self.mr - 1:
                    time.sleep(2 ** (a + 1))
                else:
                    return [(t, '', 'unknown', 'normal') for t in ts]

    def _gb(self, ps, ts):
        prompt = (
            'あなたは最高精度のOCRエンジンです。'
            '以下の画像はYouTube動画の字幕(テロップ)部分です。\n\n'
            '【ルール】\n'
            '- 全ての文字を1文字たりとも間違えず正確に読む\n'
            '- 句読点、感嘆符、括弧も正確に\n'
            '- テキストなし→空文字\n'
            '- 色: pink(ピンク)、cyan(シアン)、other\n'
            '- サイズ大→emphasis、小→normal\n'
            '- 画像枚数=要素数\n\n'
            'JSON配列のみ: [{"text":"","color":"other","style":"normal"},...]'
        )
        pa = [gtypes.Part.from_text(prompt)]
        for fp in ps:
            with open(fp, 'rb') as f:
                pa.append(gtypes.Part.from_bytes(data=f.read(), mime_type='image/jpeg'))
        r = self._g.models.generate_content(
            model=self._gm,
            contents=gtypes.Content(parts=pa, role='user'),
            config=gtypes.GenerateContentConfig(temperature=0, max_output_tokens=1500)
        )
        get_tracker().record_gemini(f'OCR ({len(ps)}枚)', self._gm, r)
        m = re.search(r'\[.*\]', r.text.strip(), re.DOTALL)
        if not m:
            return [(t, '', 'unknown', 'normal') for t in ts]
        it = json.loads(m.group()); res = []
        for i, t in enumerate(ts):
            if i < len(it):
                x = it[i]; tx = x.get('text', '').strip()
                co = x.get('color', 'other').lower()
                sy = x.get('style', 'normal').lower()
                sp = 'aya' if 'pink' in co else ('junpei' if 'cyan' in co else 'unknown')
                res.append((t, tx, sp, sy))
            else:
                res.append((t, '', 'unknown', 'normal'))
        return res

    # =========================================================
    # クロス検証: Whisperテキスト x OCR話者識別
    # =========================================================

    def _cross_validate(self, whisper_segs, ocr_segs):
        """
        Whisper APIセグメントはテキスト精度が高いので優先。
        OCRセグメントは話者識別(色)を付加するだけに使用。
        """
        if not ocr_segs:
            return whisper_segs
        if not whisper_segs:
            return ocr_segs

        validated = []
        for ws in whisper_segs:
            best_ocr = None; best_ov = 0
            for oc in ocr_segs:
                ov_s = max(ws.start, oc.start); ov_e = min(ws.end, oc.end)
                if ov_e > ov_s:
                    ov = ov_e - ov_s
                    if ov > best_ov:
                        best_ov = ov; best_ocr = oc
            # Whisperテキストをベースに、OCRから話者情報だけ取得
            if best_ocr and best_ocr.speaker != 'unknown':
                ws.speaker = best_ocr.speaker
                ws.style   = best_ocr.style
            validated.append(ws)

        # WhisperにながOCRにあるセグメントはスキップ（Whisper APIの方がテキスト精度高）
        validated.sort(key=lambda e: e.start)
        cleaned = []
        for e in validated:
            if not e.text.strip() or e.end - e.start < 0.2:
                continue
            e.text = re.sub(r'\s+', ' ', e.text).strip()
            if cleaned and cleaned[-1].text == e.text and abs(cleaned[-1].start - e.start) < 0.3:
                if (e.end - e.start) > (cleaned[-1].end - cleaned[-1].start):
                    cleaned[-1] = e
                continue
            cleaned.append(e)
        return cleaned

    def _similarity(self, a, b):
        if not a or not b:
            return 0.0
        sa, sb = set(a), set(b)
        inter = len(sa & sb); union = len(sa | sb)
        return inter / union if union else 0.0

    # =========================================================
    # EasyOCR fallback
    # =========================================================

    def _easyocr(self, vp):
        if not cv2 or not easyocr:
            return []
        w, h = get_video_resolution(vp); sy = int(h * (1 - self.srr))
        fd = os.path.join(self.td, 'foc'); os.makedirs(fd, exist_ok=True)
        try:
            run_ffmpeg(['-i', str(vp), '-vf', f'fps=10,crop=iw:{h-sy}:0:{sy}',
                        '-q:v', '2', os.path.join(fd, 'f_%07d.jpg')], timeout=1800)
            if self._or is None:
                self._or = easyocr.Reader(['ja', 'en'], gpu=False)
            pg = None; raw = []
            for i, fp in enumerate(sorted(Path(fd).glob('f_*.jpg'))):
                ts = i * FI; f = cv2.imread(str(fp))
                if f is None: continue
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                if pg is not None and np.mean(cv2.absdiff(g, pg)) < 12:
                    pg = g; continue
                pg = g
                if not (0.003 < np.sum(g > 140) / g.size < 0.45):
                    raw.append((ts, '', 'unknown', 'normal')); continue
                r = self._or.readtext(str(fp), detail=1, paragraph=True)
                tx = ''.join(d[1] for d in r if len(d) >= 2).strip() if r else ''
                hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
                pk = np.sum(cv2.inRange(hsv, np.array([140,50,150]), np.array([175,255,255])) > 0)
                cy = np.sum(cv2.inRange(hsv, np.array([80,50,150]),  np.array([100,255,255])) > 0)
                sp = 'aya' if pk > cy and pk > 100 else ('junpei' if cy > 100 else 'unknown')
                raw.append((ts, tx, sp, 'normal'))
            return self._grp(raw)
        finally:
            shutil.rmtree(fd, ignore_errors=True)

    def _grp(self, raw):
        ent = []; ct, cs, cy, st, en = '', 'unknown', 'normal', 0.0, 0.0
        for ts, tx, sp, sy in raw:
            if tx == ct and tx:
                en = ts + FI
            else:
                if ct:
                    ent.append(SubtitleEntry(start=round(st,1), end=round(en,1),
                                             text=ct, speaker=cs, style=cy, confidence=0.95))
                ct, cs, cy, st, en = tx, sp, sy, ts, ts + FI
        if ct:
            ent.append(SubtitleEntry(start=round(st,1), end=round(en,1),
                                     text=ct, speaker=cs, style=cy, confidence=0.95))
        return ent

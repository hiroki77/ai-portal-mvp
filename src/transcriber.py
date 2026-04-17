"""字幕認識モジュール v2
- 0.1秒間隔フレーム抽出
- フレーム差分検出でテロップ変化点だけ検知
- 変化フレームのみGemini OCRに送信(最小API消費)
- Whisperでタイミング補完
"""
import os
import re
import json
import time
import base64
import logging
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None
try:
    import whisper
except ImportError:
    whisper = None
try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    genai = None
    gtypes = None
try:
    import easyocr
except ImportError:
    easyocr = None

from src.utils import run_ffmpeg, get_video_resolution, get_video_duration

logger = logging.getLogger(__name__)

FRAME_INTERVAL = 0.1  # 0.1秒精度


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str
    speaker: str
    style: str
    confidence: float = 1.0
    def to_dict(self):
        return asdict(self)


class SubtitleRecognizer:

    # フレーム差分検出の閾値
    DIFF_THRESHOLD = 15.0  # ピクセル平均差分がこれ以上で「変化あり」
    # テキストがあるかの明度閾値
    BRIGHT_THRESHOLD = 150

    def __init__(self, config):
        tc = config["transcription"]
        self.whisper_model_name = tc["whisper_model"]
        self.language = tc["language"]
        self.ocr_engine = tc.get("ocr_engine", "gemini")
        self.subtitle_region_ratio = tc["subtitle_region_ratio"]
        self.batch_size = tc.get("batch_size", 4)
        self.max_retries = tc.get("max_retries", 3)
        self.api_timeout = tc.get("api_timeout", 30)
        self.temp_dir = config["paths"]["temp_dir"]

        self._gemini = None
        self._gemini_model = tc.get("gemini_model", "gemini-2.0-flash")
        gkey = tc.get("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
        if gkey and genai:
            self._gemini = genai.Client(api_key=gkey)

        self._whisper_model = None
        self._ocr_reader = None

    def recognize(self, video_path: str) -> List[SubtitleEntry]:
        logger.info(f"字幕認識開始 (0.1秒精度): {video_path}")

        whisper_segs = self._run_whisper(video_path)
        logger.info(f"Whisper: {len(whisper_segs)} segs")

        if self.ocr_engine == "gemini" and self._gemini:
            ocr_segs = self._run_smart_ocr(video_path)
        else:
            ocr_segs = self._run_easyocr(video_path)
        logger.info(f"OCR: {len(ocr_segs)} segs")

        return self._merge(whisper_segs, ocr_segs)

    # =================================================================
    # 0.1秒精度 スマートOCR
    # =================================================================

    def _run_smart_ocr(self, video_path: str) -> List[SubtitleEntry]:
        """0.1秒間隔でフレーム抽出 → 差分検出 → 変化点のみOCR"""
        w, h = get_video_resolution(video_path)
        sub_y = int(h * (1 - self.subtitle_region_ratio))
        sub_h = h - sub_y

        frames_dir = os.path.join(self.temp_dir, "frames_01s")
        os.makedirs(frames_dir, exist_ok=True)

        try:
            # 0.1秒間隔(10fps)で字幕領域を抽出
            run_ffmpeg([
                "-i", str(video_path),
                "-vf", f"fps=10,crop=iw:{sub_h}:0:{sub_y}",
                "-q:v", "3",
                os.path.join(frames_dir, "f_%07d.jpg"),
            ], timeout=1800)

            frame_files = sorted(Path(frames_dir).glob("f_*.jpg"))
            if not frame_files:
                return []

            logger.info(f"フレーム抽出: {len(frame_files)}枚 (0.1s間隔)")

            # フレーム差分検出 → 変化点を特定
            change_points = self._detect_changes(frame_files)
            logger.info(f"テロップ変化点: {len(change_points)}箇所")

            if not change_points:
                return []

            # 変化点のフレームだけGeminiに送信
            ocr_results = self._ocr_change_points(change_points, frame_files)

            # 連続同一テキストをグルーピング
            return self._build_entries(ocr_results)

        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

    def _detect_changes(self, frame_files: list) -> List[Tuple[int, str]]:
        """フレーム間の差分を検出し、テロップが変わったフレーム番号とパスを返す"""
        changes = []
        prev_gray = None
        prev_has_text = False

        for i, fp in enumerate(frame_files):
            frame = cv2.imread(str(fp))
            if frame is None:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # テキストがあるか判定
            bright_ratio = np.sum(gray > self.BRIGHT_THRESHOLD) / gray.size
            has_text = 0.005 < bright_ratio < 0.40

            if prev_gray is not None:
                # フレーム間の差分
                diff = cv2.absdiff(gray, prev_gray)
                mean_diff = np.mean(diff)

                # 変化あり: 差分が閾値以上
                if mean_diff > self.DIFF_THRESHOLD:
                    changes.append((i, str(fp)))
                # テキストの出現/消失
                elif has_text != prev_has_text:
                    changes.append((i, str(fp)))
            else:
                # 最初のフレーム
                if has_text:
                    changes.append((i, str(fp)))

            prev_gray = gray
            prev_has_text = has_text

        return changes

    def _ocr_change_points(self, change_points, all_frames):
        """変化点のフレームをGeminiにOCR送信"""
        results = []  # [(frame_idx, timestamp, text, speaker, style)]

        # バッチ分割
        for bi in range(0, len(change_points), self.batch_size):
            batch = change_points[bi:bi + self.batch_size]
            paths = [cp[1] for cp in batch]
            indices = [cp[0] for cp in batch]
            timestamps = [idx * FRAME_INTERVAL for idx in indices]

            ocr = self._gemini_batch_retry(paths, timestamps)

            for j, (ts, text, spk, sty) in enumerate(ocr):
                results.append((indices[j], ts, text, spk, sty))

            # Gemini無料枚15RPM制限対策
            if bi + self.batch_size < len(change_points):
                time.sleep(4.5)

        return results

    def _build_entries(self, ocr_results):
        """変化点のOCR結果から字幕エントリを構築
        各変化点のテキストは次の変化点まで続く"""
        if not ocr_results:
            return []

        entries = []
        for i, (idx, ts, text, spk, sty) in enumerate(ocr_results):
            if not text:
                continue

            start = ts
            # 次の変化点までがこのテロップの表示時間
            if i + 1 < len(ocr_results):
                end = ocr_results[i + 1][1]  # 次の変化点のtimestamp
            else:
                end = ts + 2.0  # 最後は2秒

            # 同じテキストが続く場合はマージ
            if entries and entries[-1].text == text:
                entries[-1].end = end
                continue

            entries.append(SubtitleEntry(
                start=round(start, 1),
                end=round(end, 1),
                text=text,
                speaker=spk,
                style=sty,
                confidence=0.95,
            ))

        return entries

    # =================================================================
    # Gemini OCR
    # =================================================================

    def _gemini_batch_retry(self, paths, timestamps):
        for attempt in range(self.max_retries):
            try:
                return self._gemini_batch(paths, timestamps)
            except Exception as e:
                logger.warning(f"Gemini OCR error (attempt {attempt+1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                else:
                    return [(ts, "", "unknown", "normal") for ts in timestamps]

    def _gemini_batch(self, paths, timestamps):
        parts = [gtypes.Part.from_text(
            "以下の画像はYouTube動画の字幕(テロップ)部分です。"
            "各画像についてJSON配列で答えてください。"
            "テキストがない画像も含めて全画像分返してください。"
            "文字は1文字も間違えずに正確に読み取ってください。\n"
            '[{"text":"表示テキスト(空文字可)","color":"pink/cyan/other",'
            '"style":"normal/emphasis"},...]\n'
            "JSONのみ出力。"
        )]
        for fp in paths:
            with open(fp, "rb") as f:
                img = f.read()
            parts.append(gtypes.Part.from_bytes(data=img, mime_type="image/jpeg"))

        resp = self._gemini.models.generate_content(
            model=self._gemini_model,
            contents=gtypes.Content(parts=parts, role="user"),
            config=gtypes.GenerateContentConfig(temperature=0, max_output_tokens=1000),
        )
        raw = resp.text.strip()
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if not m:
            return [(ts, "", "unknown", "normal") for ts in timestamps]
        items = json.loads(m.group())
        results = []
        for i, ts in enumerate(timestamps):
            if i < len(items):
                it = items[i]
                text = it.get("text", "").strip()
                color = it.get("color", "other").lower()
                style = it.get("style", "normal").lower()
                spk = "aya" if "pink" in color else ("junpei" if "cyan" in color else "unknown")
                results.append((ts, text, spk, style))
            else:
                results.append((ts, "", "unknown", "normal"))
        return results

    # =================================================================
    # EasyOCR fallback
    # =================================================================

    def _run_easyocr(self, video_path):
        if cv2 is None or easyocr is None:
            return []
        w, h = get_video_resolution(video_path)
        sub_y = int(h * (1 - self.subtitle_region_ratio))
        frames_dir = os.path.join(self.temp_dir, "frames_ocr")
        os.makedirs(frames_dir, exist_ok=True)
        try:
            run_ffmpeg(["-i", str(video_path), "-vf",
                        f"fps=10,crop=iw:{h-sub_y}:0:{sub_y}",
                        "-q:v", "3", os.path.join(frames_dir, "f_%07d.jpg")],
                       timeout=1800)
            if self._ocr_reader is None:
                self._ocr_reader = easyocr.Reader(["ja", "en"], gpu=False)
            prev_gray = None
            raw = []
            for i, fp in enumerate(sorted(Path(frames_dir).glob("f_*.jpg"))):
                ts = i * FRAME_INTERVAL
                frame = cv2.imread(str(fp))
                if frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    diff = np.mean(cv2.absdiff(gray, prev_gray))
                    if diff < self.DIFF_THRESHOLD:
                        prev_gray = gray
                        continue
                prev_gray = gray
                if not (0.005 < np.sum(gray > 150) / gray.size < 0.40):
                    raw.append((ts, "", "unknown", "normal"))
                    continue
                res = self._ocr_reader.readtext(str(fp), detail=1, paragraph=True)
                text = "".join(d[1] for d in res if len(d) >= 2).strip() if res else ""
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                pink = np.sum(cv2.inRange(hsv, np.array([140,50,150]), np.array([175,255,255])) > 0)
                cyan = np.sum(cv2.inRange(hsv, np.array([80,50,150]), np.array([100,255,255])) > 0)
                spk = "aya" if pink > cyan and pink > 100 else ("junpei" if cyan > 100 else "unknown")
                raw.append((ts, text, spk, "normal"))
            return self._group_ocr(raw)
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

    # =================================================================
    # Whisper
    # =================================================================

    def _run_whisper(self, video_path):
        audio = os.path.join(self.temp_dir, "audio.wav")
        run_ffmpeg(["-i", str(video_path), "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1", audio])
        try:
            if self._whisper_model is None:
                self._whisper_model = whisper.load_model(self.whisper_model_name)
            result = self._whisper_model.transcribe(
                audio, language=self.language, word_timestamps=True, verbose=False)
            return [SubtitleEntry(start=s["start"], end=s["end"],
                                  text=s["text"].strip(), speaker="unknown", style="normal")
                    for s in result.get("segments", []) if s["text"].strip()]
        finally:
            if os.path.exists(audio):
                os.remove(audio)

    # =================================================================
    # 共通
    # =================================================================

    def _group_ocr(self, raw):
        entries = []
        cur_text, cur_spk, cur_sty, start, end = "", "unknown", "normal", 0.0, 0.0
        for ts, text, spk, sty in raw:
            if text == cur_text and text:
                end = ts + FRAME_INTERVAL
            else:
                if cur_text:
                    entries.append(SubtitleEntry(start=round(start,1), end=round(end,1),
                        text=cur_text, speaker=cur_spk, style=cur_sty, confidence=0.95))
                cur_text, cur_spk, cur_sty = text, spk, sty
                start, end = ts, ts + FRAME_INTERVAL
        if cur_text:
            entries.append(SubtitleEntry(start=round(start,1), end=round(end,1),
                text=cur_text, speaker=cur_spk, style=cur_sty, confidence=0.95))
        return entries

    def _merge(self, whisper_segs, ocr_segs):
        if not ocr_segs:
            return whisper_segs
        if not whisper_segs:
            return ocr_segs
        merged = list(ocr_segs)
        for ws in whisper_segs:
            if not any(min(ws.end, o.end) - max(ws.start, o.start) > 0.3 for o in ocr_segs):
                merged.append(ws)
        merged.sort(key=lambda e: e.start)
        cleaned = []
        for e in merged:
            if not e.text.strip() or e.end - e.start < 0.2:
                continue
            e.text = re.sub(r'\s+', ' ', e.text).strip()
            if cleaned and cleaned[-1].text == e.text and abs(cleaned[-1].start - e.start) < 0.3:
                if (e.end - e.start) > (cleaned[-1].end - cleaned[-1].start):
                    cleaned[-1] = e
                continue
            cleaned.append(e)
        return cleaned

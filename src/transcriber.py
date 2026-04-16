import os
import re
import json
import time
import base64
import logging
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List
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
except ImportError:
    genai = None
try:
    import easyocr
except ImportError:
    easyocr = None

from src.utils import run_ffmpeg, get_video_resolution, get_video_duration

logger = logging.getLogger(__name__)

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
    AYA_HSV_LOWER = np.array([140, 50, 150])
    AYA_HSV_UPPER = np.array([175, 255, 255])
    JUNPEI_HSV_LOWER = np.array([80, 50, 150])
    JUNPEI_HSV_UPPER = np.array([100, 255, 255])

    def __init__(self, config):
        tc = config["transcription"]
        self.whisper_model_name = tc["whisper_model"]
        self.language = tc["language"]
        self.ocr_engine = tc.get("ocr_engine", "gemini")
        self.frame_interval = tc["frame_interval"]
        self.subtitle_region_ratio = tc["subtitle_region_ratio"]
        self.batch_size = tc.get("batch_size", 4)
        self.max_retries = tc.get("max_retries", 3)
        self.api_timeout = tc.get("api_timeout", 30)
        self.temp_dir = config["paths"]["temp_dir"]
        # Gemini
        self._gemini_client = None
        self._gemini_model = tc.get("gemini_model", "gemini-2.0-flash")
        gkey = tc.get("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
        if gkey and genai:
            self._gemini_client = genai.Client(api_key=gkey)
        self._whisper_model = None
        self._ocr_reader = None

    def recognize(self, video_path):
        whisper_segs = self._run_whisper(video_path)
        logger.info(f"Whisper: {len(whisper_segs)} segs")
        if self.ocr_engine == "gemini" and self._gemini_client:
            ocr_segs = self._run_gemini_ocr(video_path)
        else:
            ocr_segs = self._run_easyocr(video_path)
        logger.info(f"OCR: {len(ocr_segs)} segs")
        return self._merge(whisper_segs, ocr_segs)

    # === Gemini 2.0 Flash Vision OCR (無料枚) ===

    def _run_gemini_ocr(self, video_path):
        w, h = get_video_resolution(video_path)
        sub_y = int(h * (1 - self.subtitle_region_ratio))
        frames_dir = os.path.join(self.temp_dir, "frames_ocr")
        os.makedirs(frames_dir, exist_ok=True)
        try:
            fps = 1.0 / self.frame_interval
            run_ffmpeg(["-i", str(video_path), "-vf",
                        f"fps={fps},crop=iw:{h-sub_y}:0:{sub_y}",
                        "-q:v", "2", os.path.join(frames_dir, "f_%06d.jpg")],
                       timeout=1200)
            frames = sorted(Path(frames_dir).glob("f_*.jpg"))
            if not frames:
                return []
            all_results = []
            for bi in range(0, len(frames), self.batch_size):
                batch = frames[bi:bi + self.batch_size]
                batch_ts = [(bi + i) * self.frame_interval for i in range(len(batch))]
                results = self._gemini_batch_retry(batch, batch_ts)
                all_results.extend(results)
                # Gemini無料枚: 15RPM制限対策
                time.sleep(4.5)
            return self._group_ocr(all_results)
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

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
        from google.genai import types as gtypes
        parts = []
        parts.append(gtypes.Part.from_text(
            "以下の画像はYouTube動画の字幕(テロップ)部分です。"
            "各画像についてJSON配列で答えてください。"
            "テキストがない画像も含め全画像分返してください。\n"
            '[{"text":"表示テキスト(空文字可)","color":"pink/cyan/other",'
            '"style":"normal/emphasis"},...]\n'
            "JSONのみ出力。説明不要。"
        ))
        for fp in paths:
            with open(fp, "rb") as f:
                img_bytes = f.read()
            parts.append(gtypes.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

        resp = self._gemini_client.models.generate_content(
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

    # === EasyOCR fallback ===

    def _run_easyocr(self, video_path):
        if cv2 is None or easyocr is None:
            return []
        w, h = get_video_resolution(video_path)
        sub_y = int(h * (1 - self.subtitle_region_ratio))
        frames_dir = os.path.join(self.temp_dir, "frames_ocr")
        os.makedirs(frames_dir, exist_ok=True)
        try:
            fps = 1.0 / self.frame_interval
            run_ffmpeg(["-i", str(video_path), "-vf",
                        f"fps={fps},crop=iw:{h-sub_y}:0:{sub_y}",
                        "-q:v", "2", os.path.join(frames_dir, "f_%06d.jpg")],
                       timeout=1200)
            if self._ocr_reader is None:
                self._ocr_reader = easyocr.Reader(["ja", "en"], gpu=False)
            raw = []
            for i, fp in enumerate(sorted(Path(frames_dir).glob("f_*.jpg"))):
                ts = i * self.frame_interval
                frame = cv2.imread(str(fp))
                if frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if not (0.01 < np.sum(gray > 180) / gray.size < 0.40):
                    raw.append((ts, "", "unknown", "normal"))
                    continue
                res = self._ocr_reader.readtext(str(fp), detail=1, paragraph=True)
                if not res:
                    raw.append((ts, "", "unknown", "normal"))
                    continue
                text = "".join(d[1] for d in res if len(d) >= 2).strip()
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                pink = np.sum(cv2.inRange(hsv, self.AYA_HSV_LOWER, self.AYA_HSV_UPPER) > 0)
                cyan = np.sum(cv2.inRange(hsv, self.JUNPEI_HSV_LOWER, self.JUNPEI_HSV_UPPER) > 0)
                spk = "aya" if pink > cyan and pink > 100 else ("junpei" if cyan > 100 else "unknown")
                raw.append((ts, text, spk, "normal"))
            return self._group_ocr(raw)
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

    # === Whisper ===

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

    # === 共通 ===

    def _group_ocr(self, raw):
        entries = []
        cur_text, cur_spk, cur_sty, start, end = "", "unknown", "normal", 0.0, 0.0
        for ts, text, spk, sty in raw:
            if text == cur_text and text:
                end = ts + self.frame_interval
            else:
                if cur_text:
                    entries.append(SubtitleEntry(start=start, end=end, text=cur_text,
                                                speaker=cur_spk, style=cur_sty, confidence=0.95))
                cur_text, cur_spk, cur_sty, start, end = text, spk, sty, ts, ts + self.frame_interval
        if cur_text:
            entries.append(SubtitleEntry(start=start, end=end, text=cur_text,
                                        speaker=cur_spk, style=cur_sty, confidence=0.95))
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
            if not e.text.strip() or e.end - e.start < 0.3:
                continue
            e.text = re.sub(r'\s+', ' ', e.text).strip()
            if cleaned and cleaned[-1].text == e.text and abs(cleaned[-1].start - e.start) < 0.5:
                if (e.end - e.start) > (cleaned[-1].end - cleaned[-1].start):
                    cleaned[-1] = e
                continue
            cleaned.append(e)
        return cleaned

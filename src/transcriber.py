"""字幕認識モジュール
GPT-4o Visionで焼き込みテロップを高精度OCR
+ Whisper音声認識でタイミング補完
+ 話者色検出(ピンク=綾 / シアン=純平)
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
    from openai import OpenAI
except ImportError:
    OpenAI = None

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
    speaker: str  # "aya" / "junpei" / "unknown"
    style: str    # "normal" / "emphasis"
    confidence: float = 1.0
    def to_dict(self):
        return asdict(self)


class SubtitleRecognizer:
    """GPT-4o Vision + Whisper でテロップを高精度認識"""

    # HSV色範囲 (フォールバック用)
    AYA_HSV_LOWER = np.array([140, 50, 150])
    AYA_HSV_UPPER = np.array([175, 255, 255])
    JUNPEI_HSV_LOWER = np.array([80, 50, 150])
    JUNPEI_HSV_UPPER = np.array([100, 255, 255])

    def __init__(self, config):
        self.config = config
        tc = config["transcription"]
        self.whisper_model_name = tc["whisper_model"]
        self.language = tc["language"]
        self.ocr_engine = tc.get("ocr_engine", "openai")
        self.frame_interval = tc["frame_interval"]
        self.subtitle_region_ratio = tc["subtitle_region_ratio"]
        self.batch_size = tc.get("batch_size", 5)
        self.max_retries = tc.get("max_retries", 3)
        self.api_timeout = tc.get("api_timeout", 30)
        self.temp_dir = config["paths"]["temp_dir"]

        # OpenAIクライアント
        self._openai = None
        self._openai_model = tc.get("openai_model", "gpt-4o")
        api_key = tc.get("openai_api_key", "") or os.environ.get("OPENAI_API_KEY", "")
        if api_key and OpenAI:
            self._openai = OpenAI(api_key=api_key, timeout=self.api_timeout)

        self._whisper_model = None
        self._ocr_reader = None

    # =================================================================
    # メイン
    # =================================================================

    def recognize(self, video_path: str) -> List[SubtitleEntry]:
        logger.info(f"字幕認識開始: {video_path}")

        # 1. Whisper音声認識
        whisper_segs = self._run_whisper(video_path)
        logger.info(f"Whisper: {len(whisper_segs)}セグメント")

        # 2. フレームOCR (GPT-4o or EasyOCR)
        if self.ocr_engine == "openai" and self._openai:
            ocr_segs = self._run_openai_ocr(video_path)
        else:
            ocr_segs = self._run_easyocr_pipeline(video_path)
        logger.info(f"OCR: {len(ocr_segs)}セグメント")

        # 3. マージ (OCRテキスト優先 + Whisperタイミング補完)
        merged = self._merge(whisper_segs, ocr_segs)
        logger.info(f"最終: {len(merged)}エントリ")
        return merged

    # =================================================================
    # GPT-4o Vision OCR
    # =================================================================

    def _run_openai_ocr(self, video_path: str) -> List[SubtitleEntry]:
        """GPT-4o Visionでフレームからテロップを読み取る"""
        w, h = get_video_resolution(video_path)
        sub_y = int(h * (1 - self.subtitle_region_ratio))

        frames_dir = os.path.join(self.temp_dir, "frames_ocr")
        os.makedirs(frames_dir, exist_ok=True)

        try:
            # 字幕領域のフレーム抽出
            fps = 1.0 / self.frame_interval
            run_ffmpeg([
                "-i", str(video_path),
                "-vf", f"fps={fps},crop=iw:{h - sub_y}:0:{sub_y}",
                "-q:v", "2",
                os.path.join(frames_dir, "f_%06d.jpg"),
            ], timeout=1200)

            frame_files = sorted(Path(frames_dir).glob("f_*.jpg"))
            if not frame_files:
                return []

            # バッチでAPIに送信
            all_results = []
            for batch_start in range(0, len(frame_files), self.batch_size):
                batch = frame_files[batch_start:batch_start + self.batch_size]
                batch_ts = [
                    (batch_start + i) * self.frame_interval
                    for i in range(len(batch))
                ]
                results = self._ocr_batch_with_retry(batch, batch_ts)
                all_results.extend(results)

            return self._group_ocr(all_results)

        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

    def _ocr_batch_with_retry(self, frame_paths, timestamps):
        """1バッチをリトライ付きでAPIに送信"""
        for attempt in range(self.max_retries):
            try:
                return self._ocr_batch(frame_paths, timestamps)
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"OCR APIエラー (attempt {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    logger.info(f"{wait}秒待機後リトライ...")
                    time.sleep(wait)
                else:
                    logger.error(f"OCR API {self.max_retries}回失敗。このバッチをスキップ。")
                    # フォールバック: 空結果を返す
                    return [(ts, "", "unknown", "normal") for ts in timestamps]

    def _ocr_batch(self, frame_paths, timestamps):
        """GPT-4o Visionにバッチ送信"""
        content = []
        content.append({
            "type": "text",
            "text": (
                "以下の画像はYouTube動画の字幕(テロップ)部分です。"
                "各画像について以下をJSON配列で答えてください。"
                "テキストがない画像も含めて全ての画像分返してください。\n"
                '[{"text": "表示されているテキスト(なければ空文字)", '
                '"color": "テキストの色(pink/cyan/other)", '
                '"style": "通常サイズはnormal, 大きい文字はemphasis"}, ...]\n'
                "JSONのみを出力してください。説明不要。"
            ),
        })

        for fp in frame_paths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "high",
                },
            })

        response = self._openai.chat.completions.create(
            model=self._openai_model,
            messages=[{"role": "user", "content": content}],
            max_tokens=1000,
            temperature=0,
        )

        raw_text = response.choices[0].message.content.strip()
        # JSON抽出
        json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if not json_match:
            return [(ts, "", "unknown", "normal") for ts in timestamps]

        items = json.loads(json_match.group())

        results = []
        for i, ts in enumerate(timestamps):
            if i < len(items):
                item = items[i]
                text = item.get("text", "").strip()
                color = item.get("color", "other").lower()
                style = item.get("style", "normal").lower()
                speaker = "aya" if "pink" in color else ("junpei" if "cyan" in color else "unknown")
                results.append((ts, text, speaker, style))
            else:
                results.append((ts, "", "unknown", "normal"))

        return results

    # =================================================================
    # EasyOCR フォールバック
    # =================================================================

    def _run_easyocr_pipeline(self, video_path: str) -> List[SubtitleEntry]:
        if cv2 is None or easyocr is None:
            return []
        w, h = get_video_resolution(video_path)
        sub_y = int(h * (1 - self.subtitle_region_ratio))
        frames_dir = os.path.join(self.temp_dir, "frames_ocr")
        os.makedirs(frames_dir, exist_ok=True)
        try:
            fps = 1.0 / self.frame_interval
            run_ffmpeg(["-i", str(video_path), "-vf", f"fps={fps},crop=iw:{h-sub_y}:0:{sub_y}", "-q:v", "2", os.path.join(frames_dir, "f_%06d.jpg")], timeout=1200)
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
                ocr_res = self._ocr_reader.readtext(str(fp), detail=1, paragraph=True)
                if not ocr_res:
                    raw.append((ts, "", "unknown", "normal"))
                    continue
                text = "".join(d[1] for d in ocr_res if len(d) >= 2).strip()
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                pink = np.sum(cv2.inRange(hsv, self.AYA_HSV_LOWER, self.AYA_HSV_UPPER) > 0)
                cyan = np.sum(cv2.inRange(hsv, self.JUNPEI_HSV_LOWER, self.JUNPEI_HSV_UPPER) > 0)
                speaker = "aya" if pink > cyan and pink > 100 else ("junpei" if cyan > 100 else "unknown")
                raw.append((ts, text, speaker, "normal"))
            return self._group_ocr(raw)
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

    # =================================================================
    # Whisper
    # =================================================================

    def _run_whisper(self, video_path: str) -> List[SubtitleEntry]:
        audio = os.path.join(self.temp_dir, "audio.wav")
        run_ffmpeg(["-i", str(video_path), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio])
        try:
            if self._whisper_model is None:
                if whisper is None:
                    raise ImportError("pip install openai-whisper")
                self._whisper_model = whisper.load_model(self.whisper_model_name)
            result = self._whisper_model.transcribe(audio, language=self.language, word_timestamps=True, verbose=False)
            segs = []
            for s in result.get("segments", []):
                t = s["text"].strip()
                if t:
                    segs.append(SubtitleEntry(start=s["start"], end=s["end"], text=t, speaker="unknown", style="normal"))
            return segs
        finally:
            if os.path.exists(audio):
                os.remove(audio)

    # =================================================================
    # 共通処理
    # =================================================================

    def _group_ocr(self, raw):
        """(timestamp, text, speaker, style) のリストをグルーピング"""
        entries = []
        cur_text, cur_spk, cur_sty = "", "unknown", "normal"
        start, end = 0.0, 0.0
        for ts, text, spk, sty in raw:
            if text == cur_text and text:
                end = ts + self.frame_interval
            else:
                if cur_text:
                    entries.append(SubtitleEntry(
                        start=start, end=end, text=cur_text,
                        speaker=cur_spk, style=cur_sty, confidence=0.95))
                cur_text, cur_spk, cur_sty = text, spk, sty
                start = ts
                end = ts + self.frame_interval
        if cur_text:
            entries.append(SubtitleEntry(
                start=start, end=end, text=cur_text,
                speaker=cur_spk, style=cur_sty, confidence=0.95))
        return entries

    def _merge(self, whisper_segs, ocr_segs):
        """OCRテキストを優先、Whisperで補完"""
        if not ocr_segs:
            return whisper_segs
        if not whisper_segs:
            return ocr_segs

        merged = list(ocr_segs)

        # OCRでカバーされていない時間帯のWhisperセグメントを追加
        for ws in whisper_segs:
            covered = False
            for oc in ocr_segs:
                overlap_start = max(ws.start, oc.start)
                overlap_end = min(ws.end, oc.end)
                if overlap_end - overlap_start > 0.3:
                    covered = True
                    break
            if not covered:
                merged.append(ws)

        # 整形
        merged.sort(key=lambda e: e.start)
        cleaned = []
        for e in merged:
            if not e.text.strip():
                continue
            e.text = re.sub(r'\s+', ' ', e.text).strip()
            if e.end - e.start < 0.3:
                continue
            if cleaned and cleaned[-1].text == e.text and abs(cleaned[-1].start - e.start) < 0.5:
                if (e.end - e.start) > (cleaned[-1].end - cleaned[-1].start):
                    cleaned[-1] = e
                continue
            cleaned.append(e)
        return cleaned

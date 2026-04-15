"""字幕認識モジュール
Whisper音声認識 + EasyOCR文字認識 + 話者色検出
を組み合わせて焼き込みテロップを高精度で再現する
"""
import os
import re
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Optional

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import whisper
except ImportError:
    whisper = None

try:
    import easyocr
except ImportError:
    easyocr = None

from src.utils import run_ffmpeg, get_video_resolution, get_video_duration

logger = logging.getLogger(__name__)


@dataclass
class SubtitleEntry:
    """字幕エントリ"""
    start: float           # 開始時間(秒)
    end: float             # 終了時間(秒)
    text: str              # テキスト
    speaker: str           # "aya" or "junpei" or "unknown"
    style: str             # "normal" or "emphasis"
    confidence: float = 1.0

    def to_dict(self):
        return asdict(self)


class SubtitleRecognizer:
    """焼き込みテロップの高精度認識"""

    # 中町綾(ピンク)のHSV範囲
    AYA_HSV_LOWER = np.array([140, 50, 150])
    AYA_HSV_UPPER = np.array([175, 255, 255])

    # 中町純平(シアン)のHSV範囲
    JUNPEI_HSV_LOWER = np.array([80, 50, 150])
    JUNPEI_HSV_UPPER = np.array([100, 255, 255])

    # テキスト検出用の明度閾値
    TEXT_BRIGHTNESS_THRESHOLD = 180

    def __init__(self, config):
        self.config = config
        self.whisper_model_name = config["transcription"]["whisper_model"]
        self.language = config["transcription"]["language"]
        self.frame_interval = config["transcription"]["frame_interval"]
        self.subtitle_region_ratio = config["transcription"]["subtitle_region_ratio"]
        self.temp_dir = config["paths"]["temp_dir"]

        self._whisper_model = None
        self._ocr_reader = None

    def _get_whisper_model(self):
        """Whisperモデルの遅延ロード"""
        if self._whisper_model is None:
            if whisper is None:
                raise ImportError("openai-whisper をインストールしてください: pip install openai-whisper")
            logger.info(f"Whisperモデル読み込み中: {self.whisper_model_name}")
            self._whisper_model = whisper.load_model(self.whisper_model_name)
            logger.info("Whisperモデル読み込み完了")
        return self._whisper_model

    def _get_ocr_reader(self):
        """EasyOCRリーダーの遅延ロード"""
        if self._ocr_reader is None:
            if easyocr is None:
                raise ImportError("easyocr をインストールしてください: pip install easyocr")
            logger.info("EasyOCR初期化中...")
            self._ocr_reader = easyocr.Reader(["ja", "en"], gpu=False)
            logger.info("EasyOCR初期化完了")
        return self._ocr_reader

    def recognize(self, video_path: str) -> List[SubtitleEntry]:
        """動画から字幕を認識して返す(メイン処理)"""
        logger.info(f"字幕認識開始: {video_path}")

        # 1. Whisper音声認識
        whisper_segments = self._run_whisper(video_path)
        logger.info(f"Whisper: {len(whisper_segments)}セグメント検出")

        # 2. OCR + 色検出
        ocr_segments = self._run_ocr_pipeline(video_path)
        logger.info(f"OCR: {len(ocr_segments)}セグメント検出")

        # 3. 結果のマージ(OCR優先、Whisperで補完)
        merged = self._merge_results(whisper_segments, ocr_segments)
        logger.info(f"マージ後: {len(merged)}エントリ")

        # 4. 重複除去と整形
        cleaned = self._clean_subtitles(merged)
        logger.info(f"整形後: {len(cleaned)}エントリ")

        return cleaned

    # =========================================================================
    # Whisper音声認識
    # =========================================================================

    def _run_whisper(self, video_path: str) -> List[SubtitleEntry]:
        """Whisperで音声認識"""
        # 音声抽出
        audio_path = os.path.join(self.temp_dir, "audio_whisper.wav")
        run_ffmpeg([
            "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(audio_path)
        ])

        try:
            model = self._get_whisper_model()
            result = model.transcribe(
                audio_path,
                language=self.language,
                word_timestamps=True,
                verbose=False,
            )

            segments = []
            for seg in result.get("segments", []):
                text = seg["text"].strip()
                if text:
                    segments.append(SubtitleEntry(
                        start=seg["start"],
                        end=seg["end"],
                        text=text,
                        speaker="unknown",
                        style="normal",
                        confidence=seg.get("avg_logprob", -1.0),
                    ))
            return segments
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)

    # =========================================================================
    # OCR + 色検出パイプライン
    # =========================================================================

    def _run_ocr_pipeline(self, video_path: str) -> List[SubtitleEntry]:
        """フレーム抽出 → OCR → 色検出 パイプライン"""
        if cv2 is None:
            logger.warning("OpenCVが未インストール。OCRスキップ。")
            return []

        duration = get_video_duration(video_path)
        width, height = get_video_resolution(video_path)

        # 字幕領域の範囲(画面下部)
        sub_y_start = int(height * (1 - self.subtitle_region_ratio))
        sub_y_end = height

        # フレーム抽出してOCR
        raw_ocr_results = []
        frames_dir = os.path.join(self.temp_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        try:
            # FFmpegでフレーム抽出
            fps = 1.0 / self.frame_interval
            run_ffmpeg([
                "-i", str(video_path),
                "-vf", f"fps={fps},crop=iw:{sub_y_end - sub_y_start}:0:{sub_y_start}",
                "-q:v", "2",
                os.path.join(frames_dir, "frame_%06d.jpg"),
            ], timeout=1200)

            # 各フレームをOCR
            frame_files = sorted(Path(frames_dir).glob("frame_*.jpg"))
            reader = self._get_ocr_reader()

            for i, frame_path in enumerate(frame_files):
                timestamp = i * self.frame_interval
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    continue

                # テキストが存在するかチェック
                if not self._has_text_in_region(frame):
                    raw_ocr_results.append((timestamp, "", "unknown", "normal"))
                    continue

                # OCR実行
                ocr_result = reader.readtext(
                    str(frame_path),
                    detail=1,
                    paragraph=True,
                )

                if not ocr_result:
                    raw_ocr_results.append((timestamp, "", "unknown", "normal"))
                    continue

                # テキスト結合
                texts = []
                for detection in ocr_result:
                    if len(detection) >= 2:
                        texts.append(detection[1])
                full_text = "".join(texts).strip()

                # テキスト色検出 → 話者判定
                speaker = self._detect_speaker_from_frame(frame)

                # テキストサイズ判定 → スタイル
                style = self._detect_text_style(frame, ocr_result)

                raw_ocr_results.append((timestamp, full_text, speaker, style))

        finally:
            # フレーム画像を削除
            import shutil
            if os.path.exists(frames_dir):
                shutil.rmtree(frames_dir, ignore_errors=True)

        # 連続同一テキストをグルーピング
        return self._group_ocr_results(raw_ocr_results)

    def _has_text_in_region(self, frame: np.ndarray) -> bool:
        """フレームにテキストが存在するか判定"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # 高輝度ピクセル(テキストやストローク)の割合
        bright_pixels = np.sum(gray > self.TEXT_BRIGHTNESS_THRESHOLD)
        total_pixels = gray.size
        ratio = bright_pixels / total_pixels
        # 1%以上5%以下の明るいピクセルがあればテキストの可能性
        return 0.01 < ratio < 0.40

    def _detect_speaker_from_frame(self, frame: np.ndarray) -> str:
        """フレームの字幕テキスト色から話者を判定"""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # ピンク(綾)のマスク
        pink_mask = cv2.inRange(hsv, self.AYA_HSV_LOWER, self.AYA_HSV_UPPER)
        pink_count = np.sum(pink_mask > 0)

        # シアン(純平)のマスク
        cyan_mask = cv2.inRange(hsv, self.JUNPEI_HSV_LOWER, self.JUNPEI_HSV_UPPER)
        cyan_count = np.sum(cyan_mask > 0)

        min_pixels = 100  # 最低ピクセル数

        if pink_count > min_pixels and pink_count > cyan_count * 1.5:
            return "aya"
        elif cyan_count > min_pixels and cyan_count > pink_count * 1.5:
            return "junpei"
        elif pink_count > min_pixels:
            return "aya"
        elif cyan_count > min_pixels:
            return "junpei"
        else:
            return "unknown"

    def _detect_text_style(self, frame: np.ndarray, ocr_result) -> str:
        """テキストサイズからスタイル(通常/強調)を判定"""
        if not ocr_result:
            return "normal"

        frame_height = frame.shape[0]
        for detection in ocr_result:
            if len(detection) >= 1:
                bbox = detection[0]
                if isinstance(bbox, list) and len(bbox) >= 4:
                    # バウンディングボックスの高さ
                    text_height = abs(bbox[2][1] - bbox[0][1])
                    # フレーム高さの15%以上なら強調テロップ
                    if text_height > frame_height * 0.15:
                        return "emphasis"
        return "normal"

    def _group_ocr_results(
        self, raw_results: list
    ) -> List[SubtitleEntry]:
        """連続する同一テキストをグルーピングして字幕エントリにする"""
        if not raw_results:
            return []

        entries = []
        current_text = ""
        current_speaker = "unknown"
        current_style = "normal"
        start_time = 0.0
        end_time = 0.0

        for timestamp, text, speaker, style in raw_results:
            if text == current_text and text != "":
                # 同じテキストが続く → 終了時間を延長
                end_time = timestamp + self.frame_interval
            else:
                # テキストが変わった → 前のエントリを保存
                if current_text:
                    entries.append(SubtitleEntry(
                        start=start_time,
                        end=end_time,
                        text=current_text,
                        speaker=current_speaker,
                        style=current_style,
                        confidence=0.9,
                    ))
                # 新しいテキスト開始
                current_text = text
                current_speaker = speaker
                current_style = style
                start_time = timestamp
                end_time = timestamp + self.frame_interval

        # 最後のエントリ
        if current_text:
            entries.append(SubtitleEntry(
                start=start_time,
                end=end_time,
                text=current_text,
                speaker=current_speaker,
                style=current_style,
                confidence=0.9,
            ))

        return entries

    # =========================================================================
    # 結果マージ
    # =========================================================================

    def _merge_results(
        self,
        whisper_segments: List[SubtitleEntry],
        ocr_segments: List[SubtitleEntry],
    ) -> List[SubtitleEntry]:
        """WhisperとOCRの結果をマージ
        - OCRのテキスト(焼き込みテロップの実テキスト)を優先
        - Whisperのタイミングと話者情報で補完
        """
        if not ocr_segments:
            return whisper_segments
        if not whisper_segments:
            return ocr_segments

        merged = []

        for ocr_entry in ocr_segments:
            # OCRエントリに対応するWhisperセグメントを検索
            best_whisper = None
            best_overlap = 0

            for w_seg in whisper_segments:
                overlap = self._calc_overlap(ocr_entry, w_seg)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_whisper = w_seg

            if best_whisper and best_overlap > 0.3:
                # OCRテキスト + Whisperタイミング
                merged.append(SubtitleEntry(
                    start=ocr_entry.start,
                    end=ocr_entry.end,
                    text=ocr_entry.text,  # OCRのテキストを優先
                    speaker=ocr_entry.speaker if ocr_entry.speaker != "unknown" else best_whisper.speaker,
                    style=ocr_entry.style,
                    confidence=max(ocr_entry.confidence, best_whisper.confidence),
                ))
            else:
                merged.append(ocr_entry)

        return merged

    def _calc_overlap(self, a: SubtitleEntry, b: SubtitleEntry) -> float:
        """2つのセグメントの時間的重なりを計算(0-1)"""
        overlap_start = max(a.start, b.start)
        overlap_end = min(a.end, b.end)
        if overlap_start >= overlap_end:
            return 0.0
        overlap_duration = overlap_end - overlap_start
        min_duration = min(a.end - a.start, b.end - b.start)
        if min_duration <= 0:
            return 0.0
        return overlap_duration / min_duration

    # =========================================================================
    # 整形
    # =========================================================================

    def _clean_subtitles(self, entries: List[SubtitleEntry]) -> List[SubtitleEntry]:
        """字幕エントリを整形"""
        cleaned = []
        for entry in entries:
            if not entry.text or not entry.text.strip():
                continue
            # テキスト正規化
            entry.text = self._normalize_text(entry.text)
            # 極端に短い字幕を除外(0.3秒未満)
            if entry.end - entry.start < 0.3:
                continue
            cleaned.append(entry)

        # 時間順ソート
        cleaned.sort(key=lambda e: e.start)

        # 重複テキストの除去(0.5秒以内の同一テキスト)
        deduplicated = []
        for entry in cleaned:
            if deduplicated:
                prev = deduplicated[-1]
                if (prev.text == entry.text and
                        abs(prev.start - entry.start) < 0.5):
                    # 重複 → 長い方を残す
                    if (entry.end - entry.start) > (prev.end - prev.start):
                        deduplicated[-1] = entry
                    continue
            deduplicated.append(entry)

        return deduplicated

    def _normalize_text(self, text: str) -> str:
        """テキスト正規化"""
        # 不要な空白除去
        text = re.sub(r'\s+', ' ', text).strip()
        # OCRのよくある誤認識を修正
        text = text.replace('|', 'I')
        text = text.replace('\\', '')
        return text

    # =========================================================================
    # エクスポート
    # =========================================================================

    def export_to_json(self, entries: List[SubtitleEntry], output_path: str):
        """字幕エントリをJSONにエクスポート"""
        data = [e.to_dict() for e in entries]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"字幕JSON保存: {output_path}")

    @staticmethod
    def load_from_json(json_path: str) -> List[SubtitleEntry]:
        """JSONから字幕エントリを読み込み"""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [SubtitleEntry(**d) for d in data]

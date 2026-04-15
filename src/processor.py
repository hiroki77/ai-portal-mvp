"""動画処理モジュール
- ズームで元の焼き込みテロップを隠す
- ASS形式で新しいテロップを焼き込み
- けいふぉんと / ピンク(綾) / シアン(純平) / 白ストローク
"""
import os
import logging
from pathlib import Path
from datetime import datetime

from src.utils import (
    run_ffmpeg, get_video_resolution, seconds_to_ass_time,
    send_termux_notification,
)

logger = logging.getLogger(__name__)


class VideoProcessor:

    def __init__(self, config):
        self.config = config
        self.zoom = config["video"]["zoom_factor"]
        self.crf = config["video"]["crf"]
        self.codec = config["video"]["codec"]
        self.output_dir = config["paths"]["output_dir"]
        self.temp_dir = config["paths"]["temp_dir"]
        self.sub_cfg = config["subtitles"]
        os.makedirs(self.output_dir, exist_ok=True)

    def create_clip(self, video_path, clip, subtitles, index):
        """1クリップを生成"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_name = f"clip_{ts}_{index}.mp4"
        output_path = os.path.join(self.output_dir, out_name)

        # 一時ファイル
        seg_path = os.path.join(self.temp_dir, f"seg_{index}.mp4")
        zoom_path = os.path.join(self.temp_dir, f"zoom_{index}.mp4")
        ass_path = os.path.join(self.temp_dir, f"sub_{index}.ass")

        try:
            w, h = get_video_resolution(video_path)

            # 1. クリップ切り出し
            self._extract_segment(video_path, clip.start, clip.end, seg_path)

            # 2. ズーム(元テロップ隠し)
            self._apply_zoom(seg_path, zoom_path, w, h)

            # 3. ASS字幕生成
            clip_subs = [s for s in subtitles
                         if s.start >= clip.start and s.end <= clip.end]
            self._generate_ass(clip_subs, clip.start, ass_path, w, h)

            # 4. 字幕焼き込み
            self._burn_subtitles(zoom_path, ass_path, output_path)

            logger.info(f"Clip {index} 完成: {output_path}")
            send_termux_notification(
                "切り抜き完成",
                f"Clip {index}: {clip.duration:.0f}秒"
            )
            return output_path

        finally:
            for p in [seg_path, zoom_path, ass_path]:
                if os.path.exists(p):
                    os.remove(p)

    def _extract_segment(self, video_path, start, end, output):
        run_ffmpeg([
            "-ss", str(start),
            "-i", str(video_path),
            "-t", str(end - start),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(output),
        ])

    def _apply_zoom(self, input_path, output_path, orig_w, orig_h):
        """zoom_factor倍に拡大して中央から元サイズでクロップ
        下部の焼き込みテロップが見えなくなる"""
        zw = int(orig_w * self.zoom)
        zh = int(orig_h * self.zoom)
        # 下寄せクロップ(下部のテロップを確実に隠す)
        crop_x = (zw - orig_w) // 2
        crop_y = zh - orig_h  # 下端基準
        vf = f"scale={zw}:{zh},crop={orig_w}:{orig_h}:{crop_x}:{crop_y}"
        run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", self.codec, "-crf", str(self.crf),
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ], timeout=300)

    def _generate_ass(self, subtitles, clip_start, ass_path, w, h):
        """ASS字幕ファイル生成"""
        font = self.sub_cfg["font_name"]
        n_size = self.sub_cfg["normal_font_size"]
        e_size = self.sub_cfg["emphasis_font_size"]
        stroke_w = self.sub_cfg["stroke_width"]
        margin_v = self.sub_cfg["margin_v"]

        # BGR形式に変換 (ASSは&H00BBGGRR)
        aya_bgr = self._rgb_to_ass_color(self.sub_cfg["aya_color"])
        jun_bgr = self._rgb_to_ass_color(self.sub_cfg["junpei_color"])
        stroke_bgr = self._rgb_to_ass_color(self.sub_cfg["stroke_color"])

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {w}\n"
            f"PlayResY: {h}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: AyaNormal,{font},{n_size},{aya_bgr},&H000000FF,{stroke_bgr},&H80000000,"
            f"-1,0,0,0,100,100,0,0,1,{stroke_w},0,2,10,10,{margin_v},1\n"
            f"Style: AyaEmphasis,{font},{e_size},{aya_bgr},&H000000FF,{stroke_bgr},&H80000000,"
            f"-1,0,0,0,100,100,0,0,1,{stroke_w+1},0,2,10,10,{margin_v},1\n"
            f"Style: JunpeiNormal,{font},{n_size},{jun_bgr},&H000000FF,{stroke_bgr},&H80000000,"
            f"-1,0,0,0,100,100,0,0,1,{stroke_w},0,2,10,10,{margin_v},1\n"
            f"Style: JunpeiEmphasis,{font},{e_size},{jun_bgr},&H000000FF,{stroke_bgr},&H80000000,"
            f"-1,0,0,0,100,100,0,0,1,{stroke_w+1},0,2,10,10,{margin_v},1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        dialogues = []
        for sub in subtitles:
            # クリップ先頭からの相対時間
            s = max(0, sub.start - clip_start)
            e = sub.end - clip_start
            start_ts = seconds_to_ass_time(s)
            end_ts = seconds_to_ass_time(e)

            # スタイル選択
            if sub.speaker == "aya":
                style = "AyaEmphasis" if sub.style == "emphasis" else "AyaNormal"
            elif sub.speaker == "junpei":
                style = "JunpeiEmphasis" if sub.style == "emphasis" else "JunpeiNormal"
            else:
                style = "AyaNormal"  # 不明の場合は綾スタイル

            text = sub.text.replace("\n", "\\N")
            dialogues.append(
                f"Dialogue: 0,{start_ts},{end_ts},{style},,0,0,0,,{text}"
            )

        with open(ass_path, "w", encoding="utf-8-sig") as f:
            f.write(header)
            f.write("\n".join(dialogues))
            f.write("\n")

    def _burn_subtitles(self, video_path, ass_path, output_path):
        fonts_dir = self.config["paths"]["fonts_dir"]
        vf = f"ass={ass_path}"
        if os.path.isdir(fonts_dir) and os.listdir(fonts_dir):
            vf = f"ass={ass_path}:fontsdir={fonts_dir}"
        run_ffmpeg([
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", self.codec, "-crf", str(self.crf),
            "-c:a", "copy",
            str(output_path),
        ], timeout=300)

    @staticmethod
    def _rgb_to_ass_color(hex_rgb):
        """RGB hex -> ASS color (&H00BBGGRR)"""
        hex_rgb = hex_rgb.lstrip("#")
        r = int(hex_rgb[0:2], 16)
        g = int(hex_rgb[2:4], 16)
        b = int(hex_rgb[4:6], 16)
        return f"&H00{b:02X}{g:02X}{r:02X}"

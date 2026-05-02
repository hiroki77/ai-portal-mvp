import os, logging, json, subprocess, shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None
from src.utils import run_ffmpeg, get_video_resolution, seconds_to_ass_time, send_termux_notification
logger = logging.getLogger(__name__)


class VideoProcessor:
    def __init__(s, config):
        s.config = config
        s.zoom_default = config["video"]["zoom_factor"]
        s.crf = config["video"]["crf"]
        s.codec = config["video"]["codec"]
        s.output_dir = config["paths"]["output_dir"]
        s.temp_dir = config["paths"]["temp_dir"]
        s.sub_cfg = config["subtitles"]
        os.makedirs(s.output_dir, exist_ok=True)

    def create_clips_parallel(s, video_path, clips, subtitles):
        results = []
        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = {}
            for i, clip in enumerate(clips[:3]):
                f = ex.submit(s.create_clip, video_path, clip, subtitles, i + 1)
                futures[f] = i + 1
            for f in as_completed(futures):
                idx = futures[f]
                try:
                    out = f.result()
                    results.append((idx, out))
                except Exception as e:
                    logger.error(f"Clip{idx} error:{e}")
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results]

    def create_clip(s, video_path, clip, subtitles, index):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out    = os.path.join(s.output_dir, f"clip_{ts}_{index}.mp4")
        seg    = os.path.join(s.temp_dir,   f"seg_{index}_{ts}.mp4")
        zoomed = os.path.join(s.temp_dir,   f"zoom_{index}_{ts}.mp4")
        ass    = os.path.join(s.temp_dir,   f"sub_{index}_{ts}.ass")
        try:
            w, h = get_video_resolution(video_path)
            run_ffmpeg(["-ss", str(clip.start), "-i", str(video_path),
                        "-t", str(clip.duration), "-c", "copy",
                        "-avoid_negative_ts", "make_zero", seg])
            zoom = s._detect_optimal_zoom(seg, w, h)
            s._apply_zoom(seg, zoomed, w, h, zoom)
            clip_subs = [sub for sub in subtitles if sub.start >= clip.start and sub.end <= clip.end]
            font_info = s._detect_font_params(seg, w, h)
            s._write_ass(clip_subs, clip.start, ass, w, h, font_info)
            fonts_dir = s.config["paths"]["fonts_dir"]
            vf = f"ass={ass}:fontsdir={fonts_dir}" if os.path.isdir(fonts_dir) and os.listdir(fonts_dir) else f"ass={ass}"
            run_ffmpeg(["-i", zoomed, "-vf", vf, "-c:v", s.codec,
                        "-crf", str(s.crf), "-c:a", "copy", out], timeout=300)
            send_termux_notification("切り抜き完成", f"Clip{index}:{clip.duration:.0f}s")
            return out
        finally:
            for p in [seg, zoomed, ass]:
                if os.path.exists(p): os.remove(p)

    # === 動的ズーム ===

    def _detect_optimal_zoom(s, seg_path, w, h):
        if cv2 is None:
            return s.zoom_default
        try:
            fd = os.path.join(s.temp_dir, "zoom_detect")
            os.makedirs(fd, exist_ok=True)
            run_ffmpeg(["-i", seg_path, "-vf", "fps=0.5", "-frames:v", "6",
                        "-q:v", "2", os.path.join(fd, "zd_%03d.jpg")], timeout=30)
            frames = sorted(os.listdir(fd))
            if not frames:
                return s.zoom_default
            top_text_y = h
            for fname in frames:
                fp = os.path.join(fd, fname)
                img = cv2.imread(fp)
                if img is None: continue
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                lower = gray[h // 2:, :]
                for row_idx in range(lower.shape[0]):
                    bright = np.sum(lower[row_idx] > 160) / lower.shape[1]
                    if bright > 0.02:
                        actual_y = h // 2 + row_idx
                        top_text_y = min(top_text_y, actual_y)
                        break
            shutil.rmtree(fd, ignore_errors=True)
            if top_text_y >= h:
                return s.zoom_default
            margin = 10
            text_from_bottom = h - top_text_y + margin
            zoom = h / (h - text_from_bottom)
            zoom = max(1.05, min(zoom, 1.30))
            logger.info(f"Dynamic zoom:{zoom:.3f} (text_y={top_text_y})")
            return zoom
        except Exception as e:
            logger.debug(f"zoom detect fail:{e}")
            return s.zoom_default

    def _apply_zoom(s, inp, out, w, h, zoom):
        zw = int(w * zoom); zh = int(h * zoom)
        cx = (zw - w) // 2; cy = zh - h
        run_ffmpeg(["-i", inp, "-vf", f"scale={zw}:{zh},crop={w}:{h}:{cx}:{cy}",
                    "-c:v", s.codec, "-crf", str(s.crf), "-c:a", "aac", out], timeout=300)

    # === フォントパラメータ自動検出 ===

    def _detect_font_params(s, seg_path, w, h):
        defaults = {
            "normal_size": s.sub_cfg["normal_font_size"],
            "emphasis_size": s.sub_cfg["emphasis_font_size"],
            "margin_v": s.sub_cfg["margin_v"],
            "shadow": 0,
        }
        if cv2 is None:
            return defaults
        try:
            fd = os.path.join(s.temp_dir, "font_detect")
            os.makedirs(fd, exist_ok=True)
            sub_h = int(h * 0.25)
            run_ffmpeg(["-i", seg_path, "-vf",
                        f"fps=1,crop=iw:{sub_h}:0:{h-sub_h}",
                        "-frames:v", "5", "-q:v", "2",
                        os.path.join(fd, "fd_%03d.jpg")], timeout=20)
            text_heights = []
            text_y_positions = []
            for fname in sorted(os.listdir(fd)):
                img = cv2.imread(os.path.join(fd, fname))
                if img is None: continue
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                _, thresh = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for cnt in contours:
                    x_, y_, cw, ch_ = cv2.boundingRect(cnt)
                    if ch_ > 10 and cw > 20:
                        text_heights.append(ch_)
                        text_y_positions.append(sub_h - y_ - ch_)
            shutil.rmtree(fd, ignore_errors=True)
            if text_heights:
                import statistics
                med_h = statistics.median(text_heights)
                est_size = int(med_h / 0.75)
                scale = h / 1080.0
                normal = max(24, min(int(est_size / scale * 0.9), 80))
                emphasis = max(32, min(int(est_size / scale * 1.3), 100))
                if text_y_positions:
                    margin = max(10, min(int(statistics.median(text_y_positions) / scale), 80))
                else:
                    margin = defaults["margin_v"]
                logger.info(f"Font detect: normal={normal} emphasis={emphasis} margin={margin}")
                return {"normal_size": normal, "emphasis_size": emphasis, "margin_v": margin, "shadow": 1}
        except Exception as e:
            logger.debug(f"font detect fail:{e}")
        return defaults

    # === ASS字幕生成 ===

    def _write_ass(s, subs, clip_start, path, w, h, font_info):
        font = s.sub_cfg["font_name"]
        ns = font_info["normal_size"]
        es = font_info["emphasis_size"]
        sw = s.sub_cfg["stroke_width"]
        mv = font_info["margin_v"]
        sh = font_info.get("shadow", 0)
        ac = s._rgb2ass(s.sub_cfg["aya_color"])      # 綾: ピンク
        jc = s._rgb2ass(s.sub_cfg["junpei_color"])   # 純平: シアン
        sc = s._rgb2ass(s.sub_cfg["stroke_color"])   # 縁取り: 白
        header = (
            f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: AyaN,{font},{ns},{ac},&H000000FF,{sc},&H80000000,-1,0,0,0,100,100,0,0,1,{sw},{sh},2,10,10,{mv},1\n"
            f"Style: AyaE,{font},{es},{ac},&H000000FF,{sc},&H80000000,-1,0,0,0,100,100,0,0,1,{sw+1},{sh},2,10,10,{mv},1\n"
            f"Style: JunN,{font},{ns},{jc},&H000000FF,{sc},&H80000000,-1,0,0,0,100,100,0,0,1,{sw},{sh},2,10,10,{mv},1\n"
            f"Style: JunE,{font},{es},{jc},&H000000FF,{sc},&H80000000,-1,0,0,0,100,100,0,0,1,{sw+1},{sh},2,10,10,{mv},1\n"
            f"Style: UnkN,{font},{ns},&H00FFFFFF,&H000000FF,{sc},&H80000000,0,0,0,0,100,100,0,0,1,{sw},{sh},2,10,10,{mv},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        lines = []
        for sub in subs:
            t0 = seconds_to_ass_time(max(0, sub.start - clip_start))
            t1 = seconds_to_ass_time(sub.end - clip_start)
            if sub.speaker == "aya":
                sty = "AyaE" if sub.style == "emphasis" else "AyaN"
            elif sub.speaker == "junpei":
                sty = "JunE" if sub.style == "emphasis" else "JunN"
            else:
                sty = "UnkN"   # 話者不明は白テキスト
            lines.append(f"Dialogue: 0,{t0},{t1},{sty},,0,0,0,,{sub.text}")
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(header + "\n".join(lines) + "\n")

    @staticmethod
    def _rgb2ass(hex_rgb):
        hex_rgb = hex_rgb.lstrip("#")
        r, g, b = int(hex_rgb[0:2], 16), int(hex_rgb[2:4], 16), int(hex_rgb[4:6], 16)
        return f"&H00{b:02X}{g:02X}{r:02X}"

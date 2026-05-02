#!/usr/bin/env python3
"""テロップ色キャリブレーションツール
中町兄妹の実動画からテロップ色(RGB/HSV)を自動検出し、
config.yamlの色設定を正確に更新する

使い方:
  python tools/calibrate_colors.py
  python tools/calibrate_colors.py --url "https://www.youtube.com/watch?v=XXXXX"
"""
import os
import sys
import json
import logging
import subprocess
import argparse
from pathlib import Path
from collections import Counter

import numpy as np

try:
    import cv2
except ImportError:
    print("ERROR: pip install opencv-python-headless")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERROR: pip install pyyaml")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def download_sample_frames(video_url, temp_dir, count=20):
    """動画から字幕領域のサンプルフレームを取得"""
    os.makedirs(temp_dir, exist_ok=True)

    # 動画の長さを取得
    result = subprocess.run(
        ["yt-dlp", "--print", "duration", "--no-download", video_url],
        capture_output=True, text=True, timeout=30)
    duration = float(result.stdout.strip() or 600)

    # 動画を一時DL
    dl_path = os.path.join(temp_dir, "sample.mp4")
    subprocess.run([
        "yt-dlp", "-f", "bestvideo[height<=720]",
        "--merge-output-format", "mp4",
        "-o", dl_path, "--no-playlist", video_url
    ], capture_output=True, timeout=300)

    if not os.path.exists(dl_path):
        raise FileNotFoundError("動画のダウンロードに失敗")

    # 解像度取得
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", dl_path],
        capture_output=True, text=True, timeout=10)
    info = json.loads(result.stdout)
    h = 720
    for s in info["streams"]:
        if s["codec_type"] == "video":
            h = s["height"]
            break

    # 字幕領域(下20%)のフレームを抽出
    sub_h = int(h * 0.20)
    sub_y = h - sub_h
    # 動画の中盤から等間隔でフレーム取得
    start = duration * 0.15
    interval = (duration * 0.7) / count

    frames_dir = os.path.join(temp_dir, "cal_frames")
    os.makedirs(frames_dir, exist_ok=True)

    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(start), "-i", dl_path,
        "-vf", f"fps=1/{interval},crop=iw:{sub_h}:0:{sub_y}",
        "-frames:v", str(count),
        "-q:v", "2",
        os.path.join(frames_dir, "cal_%03d.jpg"),
    ], capture_output=True, timeout=120)

    frame_paths = sorted(Path(frames_dir).glob("cal_*.jpg"))
    logger.info(f"{len(frame_paths)} フレーム取得完了")
    return frame_paths, dl_path


def extract_text_colors(frame_paths):
    """フレームからテキスト色を抽出"""
    all_pink_pixels = []
    all_cyan_pixels = []
    all_other_pixels = []

    for fp in frame_paths:
        frame = cv2.imread(str(fp))
        if frame is None:
            continue

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 明るいピクセルのみ(テキスト部分)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        text_mask = gray > 150

        # 白でないピクセル(ストロークではなくテキスト色)
        saturation = hsv[:, :, 1]
        colored_mask = text_mask & (saturation > 40)

        if not np.any(colored_mask):
            continue

        colored_hsv = hsv[colored_mask]
        colored_rgb = rgb[colored_mask]

        for i in range(len(colored_hsv)):
            h_val = colored_hsv[i][0]
            # ピンク系 (H: 140-180 in OpenCV, つまり280-360度)
            if 140 <= h_val <= 179 or 0 <= h_val <= 10:
                all_pink_pixels.append(colored_rgb[i])
            # シアン系 (H: 75-105 in OpenCV, つまり150-210度)
            elif 75 <= h_val <= 105:
                all_cyan_pixels.append(colored_rgb[i])
            else:
                all_other_pixels.append(colored_rgb[i])

    return (
        np.array(all_pink_pixels) if all_pink_pixels else np.array([]),
        np.array(all_cyan_pixels) if all_cyan_pixels else np.array([]),
        np.array(all_other_pixels) if all_other_pixels else np.array([]),
    )


def analyze_colors(pink_pixels, cyan_pixels):
    """検出されたピクセルから代表色を算出"""
    results = {}

    if len(pink_pixels) > 0:
        median_rgb = np.median(pink_pixels, axis=0).astype(int)
        mean_rgb = np.mean(pink_pixels, axis=0).astype(int)
        results["aya"] = {
            "median_rgb": median_rgb.tolist(),
            "mean_rgb": mean_rgb.tolist(),
            "hex": f"{median_rgb[0]:02X}{median_rgb[1]:02X}{median_rgb[2]:02X}",
            "pixel_count": len(pink_pixels),
        }
        logger.info(f"")
        logger.info(f"=== 中町綾 (ピンク) ===")
        logger.info(f"  検出ピクセル数: {len(pink_pixels)}")
        logger.info(f"  中央値 RGB: ({median_rgb[0]}, {median_rgb[1]}, {median_rgb[2]})")
        logger.info(f"  平均値 RGB: ({mean_rgb[0]}, {mean_rgb[1]}, {mean_rgb[2]})")
        logger.info(f"  HEX: #{results['aya']['hex']}")
    else:
        logger.warning("ピンク色のテキストが検出されませんでした")

    if len(cyan_pixels) > 0:
        median_rgb = np.median(cyan_pixels, axis=0).astype(int)
        mean_rgb = np.mean(cyan_pixels, axis=0).astype(int)
        results["junpei"] = {
            "median_rgb": median_rgb.tolist(),
            "mean_rgb": mean_rgb.tolist(),
            "hex": f"{median_rgb[0]:02X}{median_rgb[1]:02X}{median_rgb[2]:02X}",
            "pixel_count": len(cyan_pixels),
        }
        logger.info(f"")
        logger.info(f"=== 中町純平 (シアン) ===")
        logger.info(f"  検出ピクセル数: {len(cyan_pixels)}")
        logger.info(f"  中央値 RGB: ({median_rgb[0]}, {median_rgb[1]}, {median_rgb[2]})")
        logger.info(f"  平均値 RGB: ({mean_rgb[0]}, {mean_rgb[1]}, {mean_rgb[2]})")
        logger.info(f"  HEX: #{results['junpei']['hex']}")
    else:
        logger.warning("シアン色のテキストが検出されませんでした")

    return results


def compute_hsv_ranges(pink_pixels, cyan_pixels):
    """検出精度向上のためのHSV範囲を算出"""
    ranges = {}

    for name, pixels in [("aya", pink_pixels), ("junpei", cyan_pixels)]:
        if len(pixels) == 0:
            continue
        # RGB -> HSV
        pixels_bgr = pixels[:, ::-1]  # RGB to BGR
        pixels_3d = pixels_bgr.reshape(-1, 1, 3).astype(np.uint8)
        hsv_pixels = cv2.cvtColor(pixels_3d, cv2.COLOR_BGR2HSV).reshape(-1, 3)

        h_vals = hsv_pixels[:, 0]
        s_vals = hsv_pixels[:, 1]
        v_vals = hsv_pixels[:, 2]

        # 下位5%・上位95%で範囲設定
        ranges[name] = {
            "h_lower": int(np.percentile(h_vals, 5)),
            "h_upper": int(np.percentile(h_vals, 95)),
            "s_lower": int(np.percentile(s_vals, 5)),
            "s_upper": int(np.percentile(s_vals, 95)),
            "v_lower": int(np.percentile(v_vals, 5)),
            "v_upper": int(np.percentile(v_vals, 95)),
        }
        r = ranges[name]
        logger.info(f"")
        logger.info(f"=== {name} HSV範囲 ===")
        logger.info(f"  H: {r['h_lower']} - {r['h_upper']}")
        logger.info(f"  S: {r['s_lower']} - {r['s_upper']}")
        logger.info(f"  V: {r['v_lower']} - {r['v_upper']}")

    return ranges


def update_config(results, config_path="config.yaml"):
    """検出した色でconfig.yamlを更新"""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    updated = False
    if "aya" in results:
        old = config["subtitles"]["aya_color"]
        new = results["aya"]["hex"]
        config["subtitles"]["aya_color"] = new
        logger.info(f"")
        logger.info(f"config.yaml 更新: aya_color {old} → {new}")
        updated = True

    if "junpei" in results:
        old = config["subtitles"]["junpei_color"]
        new = results["junpei"]["hex"]
        config["subtitles"]["junpei_color"] = new
        logger.info(f"config.yaml 更新: junpei_color {old} → {new}")
        updated = True

    if updated:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info(f"config.yaml 保存完了")
    else:
        logger.warning("更新する色が検出されませんでした")


def find_recent_video():
    """中町兄妹の最新動画URLを取得"""
    result = subprocess.run([
        "yt-dlp", "--flat-playlist",
        "--print", "%(id)s",
        "--playlist-items", "1",
        "https://www.youtube.com/@nakamachi_kyodai/videos",
    ], capture_output=True, text=True, timeout=30)
    vid = result.stdout.strip()
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    # フォールバック: 検索
    result = subprocess.run([
        "yt-dlp", "--flat-playlist",
        "--print", "%(id)s",
        "--playlist-items", "1",
        "ytsearch1:中町兄妹",
    ], capture_output=True, text=True, timeout=30)
    vid = result.stdout.strip()
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def main():
    parser = argparse.ArgumentParser(description="テロップ色キャリブレーション")
    parser.add_argument("--url", type=str, help="分析する動画URL")
    parser.add_argument("--config", default="config.yaml", help="config.yamlのパス")
    parser.add_argument("--no-update", action="store_true", help="config.yamlを更新しない")
    parser.add_argument("--frames", type=int, default=20, help="分析フレーム数")
    args = parser.parse_args()

    temp_dir = "./temp/calibration"

    # 動画URL取得
    url = args.url
    if not url:
        logger.info("中町兄妹の最新動画を検索中...")
        url = find_recent_video()
        if not url:
            logger.error("動画URLが見つかりません。--url で指定してください")
            sys.exit(1)
    logger.info(f"分析動画: {url}")

    try:
        # 1. サンプルフレーム取得
        logger.info(f"\nフレーム抽出中 ({args.frames}フレーム)...")
        frame_paths, dl_path = download_sample_frames(url, temp_dir, args.frames)

        if not frame_paths:
            logger.error("フレームが取得できませんでした")
            sys.exit(1)

        # 2. テキスト色抽出
        logger.info("\nテキスト色を分析中...")
        pink_px, cyan_px, other_px = extract_text_colors(frame_paths)

        # 3. 代表色算出
        results = analyze_colors(pink_px, cyan_px)

        # 4. HSV範囲算出
        hsv_ranges = compute_hsv_ranges(pink_px, cyan_px)

        # 5. config.yaml更新
        if not args.no_update and results:
            logger.info("")
            update_config(results, args.config)

        # 6. 結果をJSONでも保存
        output = {"colors": results, "hsv_ranges": hsv_ranges, "video_url": url}
        out_path = os.path.join("data", "calibration_result.json")
        os.makedirs("data", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info(f"\n結果保存: {out_path}")

        logger.info("\n=== キャリブレーション完了 ===")

    finally:
        # 一時ファイル削除
        import shutil
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

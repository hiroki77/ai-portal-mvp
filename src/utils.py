"""共通ユーティリティ"""
import os
import json
import yaml
import logging
import subprocess
from pathlib import Path
from datetime import datetime


def load_config(config_path="config.yaml"):
    """設定ファイル読み込み"""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # ディレクトリ作成
    for key in ["output_dir", "temp_dir", "data_dir", "fonts_dir", "logs_dir"]:
        path = config["paths"][key]
        os.makedirs(path, exist_ok=True)

    # RSS URL自動生成
    if config["channel"]["channel_id"] and not config["monitor"]["rss_url"]:
        cid = config["channel"]["channel_id"]
        config["monitor"]["rss_url"] = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"

    return config


def setup_logging(config):
    """ログ設定"""
    log_file = config["logging"]["file"]
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, config["logging"]["level"]),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def run_ffmpeg(args, timeout=600):
    """FFmpegコマンド実行"""
    cmd = ["ffmpeg", "-y"] + args
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr}")
    return result


def run_ffprobe(args):
    """FFprobeコマンド実行"""
    cmd = ["ffprobe"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe error: {result.stderr}")
    return result.stdout


def get_video_info(video_path):
    """動画の情報を取得"""
    output = run_ffprobe([
        "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path)
    ])
    return json.loads(output)


def get_video_duration(video_path):
    """動画の長さを取得(秒)"""
    info = get_video_info(video_path)
    return float(info["format"]["duration"])


def get_video_resolution(video_path):
    """動画の解像度を取得"""
    info = get_video_info(video_path)
    for stream in info["streams"]:
        if stream["codec_type"] == "video":
            return stream["width"], stream["height"]
    return 1920, 1080


def timestamp_to_seconds(ts):
    """HH:MM:SS.ms → 秒に変換"""
    parts = ts.split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def seconds_to_ass_time(seconds):
    """秒 → ASS時刻形式(H:MM:SS.cc)に変換"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def send_termux_notification(title, message):
    """Termux通知送信"""
    try:
        subprocess.run(
            ["termux-notification", "--title", title, "--content", message],
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def ensure_font_installed(config):
    """けいふぉんとの存在確認"""
    font_dir = config["paths"]["fonts_dir"]
    font_files = list(Path(font_dir).glob("*.ttf")) + list(Path(font_dir).glob("*.otf"))
    if not font_files:
        logging.getLogger(__name__).warning(
            f"フォントが見つかりません。{font_dir}/ にけいふぉんと(.ttf/.otf)を配置してください。"
            f" ダウンロード: https://booth.pm 等で'けいふぉんと'を検索"
        )
        return False
    return True


def save_json(data, filepath):
    """JSON保存"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(filepath, default=None):
    """JSON読み込み"""
    if not os.path.exists(filepath):
        return default if default is not None else {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

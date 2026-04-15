#!/usr/bin/env python3
"""中町兄妹 切り抜き動画自動生成システム
新着動画を監視し、自動で切り抜き動画を作成する
"""
import os
import sys
import time
import argparse
import logging
import schedule

from src.utils import load_config, setup_logging, send_termux_notification, ensure_font_installed
from src.monitor import YouTubeChannelMonitor
from src.downloader import VideoDownloader
from src.transcriber import SubtitleRecognizer
from src.segmenter import TopicSegmenter
from src.processor import VideoProcessor
from src.insights import InsightsEngine


def process_new_videos(monitor, downloader, transcriber, segmenter, processor, insights):
    logger = logging.getLogger(__name__)
    try:
        new_videos = monitor.check_new_videos()
        if not new_videos:
            return

        for video in new_videos:
            logger.info(f"=== 処理開始: {video['title']} ===")
            send_termux_notification("新着動画検出", video["title"])

            video_path = None
            try:
                # ダウンロード
                video_path = downloader.download(video["url"])

                # 字幕認識
                subtitles = transcriber.recognize(video_path)

                # クリップ選定
                prefs = insights.get_preferences()
                clips = segmenter.select_clips(subtitles, video_path, prefs)

                # 動画生成(3本)
                for i, clip in enumerate(clips[:3]):
                    output = processor.create_clip(video_path, clip, subtitles, i + 1)
                    insights.record_clip({
                        "duration": clip.duration,
                        "score": clip.score,
                        "topic": clip.topic_summary,
                    })
                    logger.info(f"Clip {i+1} 保存: {output}")

                monitor.mark_processed(video["id"])
                send_termux_notification(
                    "切り抜き完成",
                    f"{video['title']} - 3本作成済み"
                )
                logger.info(f"=== 完了: {video['title']} ===")

            except Exception as e:
                logger.error(f"動画処理エラー: {e}", exc_info=True)
                send_termux_notification("エラー", str(e)[:100])
            finally:
                if video_path:
                    downloader.cleanup(video_path)

    except Exception as e:
        logger.error(f"監視エラー: {e}", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="中町兄妹 切り抜き自動生成")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="1回実行して終了")
    parser.add_argument("--insights", type=str, help="インサイトJSONファイルを取り込み")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)
    logger = logging.getLogger(__name__)

    logger.info("システム起動")

    # フォント確認
    ensure_font_installed(config)

    # コンポーネント初期化
    monitor = YouTubeChannelMonitor(config)
    downloader = VideoDownloader(config)
    transcriber = SubtitleRecognizer(config)
    segmenter = TopicSegmenter(config)
    processor = VideoProcessor(config)
    insights = InsightsEngine(config)

    # インサイト取り込み
    if args.insights:
        import json
        with open(args.insights, "r", encoding="utf-8") as f:
            insights.update_insights(json.load(f))
        logger.info(f"インサイト取り込み完了: {args.insights}")

    if args.once:
        process_new_videos(monitor, downloader, transcriber, segmenter, processor, insights)
    else:
        interval = config["monitor"]["check_interval"]
        logger.info(f"監視開始 ({interval}秒間隔)")
        send_termux_notification("監視開始", f"中町兄妹チャンネルを{interval}秒間隔で監視中")

        run = lambda: process_new_videos(monitor, downloader, transcriber, segmenter, processor, insights)
        schedule.every(interval).seconds.do(run)
        run()  # 初回即実行

        while True:
            schedule.run_pending()
            time.sleep(1)


if __name__ == "__main__":
    main()

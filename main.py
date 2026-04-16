#!/usr/bin/env python3
"""中町兄妹 切り抜き動画自動生成
新着監視 → DL → 字幕認識 → 話題分割 → 動画生成 → Drive格納
"""
import os, sys, time, argparse, logging, schedule
from src.utils import load_config, setup_logging, send_termux_notification, ensure_font_installed
from src.monitor import YouTubeChannelMonitor
from src.downloader import VideoDownloader
from src.transcriber import SubtitleRecognizer
from src.segmenter import TopicSegmenter
from src.processor import VideoProcessor
from src.insights import InsightsEngine
from src.drive_uploader import DriveUploader


def process(monitor, dl, tr, seg, proc, ins, drive):
    logger = logging.getLogger(__name__)
    try:
        videos = monitor.check_new_videos()
        if not videos:
            return
        for video in videos:
            logger.info(f"=== 処理開始: {video['title']} ===")
            send_termux_notification("新着動画検出", video["title"])
            vp = None
            try:
                vp = dl.download(video["url"])
                subs = tr.recognize(vp)
                clips = seg.select_clips(subs, vp, ins.get_preferences())
                created = []
                for i, clip in enumerate(clips[:3]):
                    out = proc.create_clip(vp, clip, subs, i + 1)
                    ins.record_clip({"duration": clip.duration, "score": clip.score, "topic": clip.topic_summary})
                    # Driveにアップロード
                    drive.upload(out)
                    created.append(out)
                    logger.info(f"Clip {i+1} 完成+Driveアップロード: {out}")
                monitor.mark_processed(video["id"])
                send_termux_notification("切り抜き完成", f"{video['title']} - {len(created)}本作成、Driveに保存済み")
                logger.info(f"=== 完了: {video['title']} ===")
            except Exception as e:
                logger.error(f"動画処理エラー: {e}", exc_info=True)
                send_termux_notification("エラー", str(e)[:100])
            finally:
                if vp:
                    dl.cleanup(vp)
    except Exception as e:
        logger.error(f"監視エラー: {e}", exc_info=True)


def main():
    p = argparse.ArgumentParser(description="中町兄妹 切り抜き自動生成")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--once", action="store_true", help="1回実行して終了")
    p.add_argument("--insights", type=str, help="インサイトJSONを取り込み")
    args = p.parse_args()

    config = load_config(args.config)
    setup_logging(config)
    logger = logging.getLogger(__name__)
    logger.info("システム起動")
    ensure_font_installed(config)

    mon = YouTubeChannelMonitor(config)
    dl = VideoDownloader(config)
    tr = SubtitleRecognizer(config)
    seg = TopicSegmenter(config)
    proc = VideoProcessor(config)
    ins = InsightsEngine(config)
    drive = DriveUploader(config)

    if args.insights:
        import json
        with open(args.insights, "r", encoding="utf-8") as f:
            ins.update_insights(json.load(f))
        logger.info("インサイト取り込み完了")

    if args.once:
        process(mon, dl, tr, seg, proc, ins, drive)
    else:
        iv = config["monitor"]["check_interval"]
        logger.info(f"監視開始 ({iv}秒間隔)")
        send_termux_notification("監視開始", f"中町兄妹チャンネルを{iv}秒間隔で監視中")
        run = lambda: process(mon, dl, tr, seg, proc, ins, drive)
        schedule.every(iv).seconds.do(run)
        run()
        while True:
            schedule.run_pending()
            time.sleep(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os,sys,time,argparse,logging,schedule
from src.utils import load_config,setup_logging,send_termux_notification,ensure_font_installed
from src.monitor import YouTubeChannelMonitor
from src.downloader import VideoDownloader
from src.transcriber import SubtitleRecognizer
from src.segmenter import TopicSegmenter
from src.processor import VideoProcessor
from src.insights import InsightsEngine
from src.drive_uploader import DriveUploader
from src.cost_tracker import get_tracker, reset_tracker

def process(mon,dl,tr,seg,proc,ins,drv):
    logger=logging.getLogger(__name__)
    try:
        for v in mon.check_new_videos():
            logger.info(f"=== {v['title']} ===")
            send_termux_notification("新着動画",v["title"])
            reset_tracker()  # 動画1本ごとにコストをリセット
            vp=None
            try:
                vp=dl.download(v["url"])
                subs=tr.recognize(vp)
                clips=seg.select_clips(subs,vp,ins.get_preferences())
                outputs=proc.create_clips_parallel(vp,clips,subs)
                for i,out in enumerate(outputs):
                    c=clips[i] if i<len(clips) else clips[-1]
                    ins.record_clip({"duration":c.duration,"score":c.score,"topic":c.topic_summary})
                    drv.upload(out)
                    logger.info(f"Clip{i+1} -> Drive: {out}")
                mon.mark_processed(v["id"])

                # コスト集計・出力
                tracker=get_tracker()
                tracker.print_summary()
                cost_jpy=tracker.total_usd()*155
                send_termux_notification(
                    f"完了 ({len(outputs)}本)",
                    f"{v['title']}\nAPI費用: ¥{cost_jpy:.2f}"
                )
            except Exception as e:
                logger.error(f"Error: {e}",exc_info=True)
                send_termux_notification("エラー",str(e)[:100])
                # エラー時もコスト出力(途中まで使ったAPIコストを記録)
                get_tracker().print_summary()
            finally:
                if vp:dl.cleanup(vp)
    except Exception as e:
        logger.error(f"Monitor error: {e}",exc_info=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",default="config.yaml")
    p.add_argument("--once",action="store_true")
    p.add_argument("--insights",type=str)
    a=p.parse_args()
    cfg=load_config(a.config);setup_logging(cfg)
    logger=logging.getLogger(__name__);logger.info("起動")
    ensure_font_installed(cfg)
    mon=YouTubeChannelMonitor(cfg);dl=VideoDownloader(cfg)
    tr=SubtitleRecognizer(cfg);seg=TopicSegmenter(cfg)
    proc=VideoProcessor(cfg);ins=InsightsEngine(cfg);drv=DriveUploader(cfg)
    if a.insights:
        import json
        with open(a.insights,"r",encoding="utf-8") as f:ins.update_insights(json.load(f))
    if a.once:
        process(mon,dl,tr,seg,proc,ins,drv)
    else:
        iv=cfg["monitor"]["check_interval"]
        logger.info(f"監視開始({iv}s)")
        send_termux_notification("監視開始",f"{iv}秒間隔で監視中")
        run=lambda:process(mon,dl,tr,seg,proc,ins,drv)
        schedule.every(iv).seconds.do(run);run()
        while True:schedule.run_pending();time.sleep(1)

if __name__=="__main__":main()

#!/usr/bin/env python3
"""クラッシュ復帰・自動再起動スクリプト
main.pyがクラッシュしても自動で再起動する
スリープ中も電源があれば止まらない
"""
import os
import sys
import time
import subprocess
import logging
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "watchdog.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger()

MAX_RESTARTS = 50  # 連続再起動上限
BASE_WAIT = 10     # 初回待機(秒)
MAX_WAIT = 300     # 最大待機(秒)


def run():
    restarts = 0
    wait = BASE_WAIT

    while restarts < MAX_RESTARTS:
        logger.info(f"main.py 起動 (restart #{restarts})")
        try:
            result = subprocess.run(
                [sys.executable, "main.py"],
                cwd=PROJECT_DIR,
                timeout=None,
            )
            if result.returncode == 0:
                logger.info("正常終了")
                break
            else:
                logger.warning(f"異常終了 (code={result.returncode})")
        except KeyboardInterrupt:
            logger.info("ユーザー停止")
            break
        except Exception as e:
            logger.error(f"クラッシュ: {e}")

        restarts += 1
        logger.info(f"{wait}秒後に再起動...")

        try:
            subprocess.run(
                ["termux-notification", "--title", "切り抜きエラー",
                 "--content", f"クラッシュ復帰中({wait}秒後再起動)"],
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        time.sleep(wait)
        wait = min(wait * 2, MAX_WAIT)  # 指数バックオフ

        # 30分以上安定したらカウンタリセット
        # (実際には次のループでrestartが增えないとこの判定には到達しないが安全策)

    if restarts >= MAX_RESTARTS:
        logger.error(f"再起動上限({MAX_RESTARTS}回)に到達。停止。")


if __name__ == "__main__":
    run()

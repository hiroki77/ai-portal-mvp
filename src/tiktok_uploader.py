import os, time, logging, subprocess
from pathlib import Path
logger = logging.getLogger(__name__)


class TikTokUploader:
    """
    TikTok自動投稿 (tiktok-uploader ライブラリ使用)
    インストール: pip install tiktok-uploader
    初回認証: python -c "from tiktok_uploader.auth import AuthBackend; AuthBackend(cookies='tiktok_cookies.txt')"
    """

    def __init__(self, config):
        tt = config.get("tiktok", {})
        self.enabled = tt.get("enabled", False)
        self.cookies_file = tt.get("cookies_file", "./tiktok_cookies.txt")
        self.hashtags = tt.get("hashtags", ["#中町兄妹", "#切り抜き", "#shorts"])
        self.schedule_delay = tt.get("schedule_delay_min", 0)
        self._available = self._check_lib()

    def _check_lib(self):
        try:
            import tiktok_uploader
            return True
        except ImportError:
            logger.warning("tiktok-uploader 未インストール: pip install tiktok-uploader")
            return False

    def upload(self, video_path, title, topic_summary="", punchline=""):
        if not self.enabled:
            logger.info("TikTok投稿: 無効 (config.yaml tiktok.enabled: false)")
            return False
        if not self._available:
            logger.error("tiktok-uploader が未インストールです")
            return False
        if not os.path.exists(self.cookies_file):
            logger.error(f"TikTok cookieファイルが見つかりません: {self.cookies_file}")
            logger.error("初回認証: tiktokuploader -c tiktok_cookies.txt auth")
            return False

        caption = self._build_caption(title, topic_summary, punchline)
        logger.info(f"TikTok投稿開始: {Path(video_path).name}")
        logger.info(f"  キャプション: {caption[:50]}...")

        if self.schedule_delay > 0:
            logger.info(f"  {self.schedule_delay}分後に投稿")
            time.sleep(self.schedule_delay * 60)

        try:
            from tiktok_uploader.upload import upload_video
            result = upload_video(
                filename=str(video_path),
                description=caption,
                cookies=self.cookies_file
            )
            logger.info(f"TikTok投稿完了: {result}")
            return True
        except Exception as e:
            logger.error(f"TikTok投稿失敗: {e}")
            return False

    def upload_batch(self, clips):
        """
        clips: [(video_path, title, topic_summary, punchline), ...]
        連続投稿時は間隔を空ける
        """
        results = []
        for i, (path, title, summary, punchline) in enumerate(clips):
            if i > 0:
                wait = 120  # 2分間隔 (スパム対策)
                logger.info(f"次の投稿まで{wait}秒待機...")
                time.sleep(wait)
            ok = self.upload(path, title, summary, punchline)
            results.append((path, ok))
        success = sum(1 for _, ok in results if ok)
        logger.info(f"TikTok投稿完了: {success}/{len(results)}本")
        return results

    def _build_caption(self, title, topic_summary, punchline):
        parts = []
        if topic_summary:
            parts.append(topic_summary)
        if punchline:
            parts.append(punchline)
        if title:
            parts.append(title)
        tag_str = " ".join(self.hashtags)
        caption = " ".join(parts) if parts else title
        return f"{caption}\n\n{tag_str}"

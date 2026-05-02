"""切り抜き動画をGoogle Driveにアップロード
方式1: rclone (Google Driveリモート設定済みの場合)
方式2: Android共有ストレージにコピー(Driveアプリが自動同期)
"""
import os
import shutil
import logging
import subprocess

logger = logging.getLogger(__name__)


class DriveUploader:

    def __init__(self, config):
        dc = config.get("drive", {})
        self.enabled = dc.get("enabled", False)
        self.method = dc.get("method", "rclone")
        self.rclone_remote = dc.get("rclone_remote", "gdrive")
        self.remote_folder = dc.get("remote_folder", "中町兄妹_切り抜き")
        self.shared_path = dc.get("shared_path", "/storage/emulated/0/Movies/切り抜き")

    def upload(self, file_path):
        """Driveにアップロード。成功でTrueを返す"""
        if not self.enabled:
            return False
        if not os.path.exists(file_path):
            logger.warning(f"ファイルが存在しません: {file_path}")
            return False

        if self.method == "rclone":
            return self._upload_rclone(file_path)
        elif self.method == "shared_storage":
            return self._copy_to_shared(file_path)
        else:
            logger.warning(f"未対応のアップロード方式: {self.method}")
            return False

    def _upload_rclone(self, file_path):
        """rcloneでGoogle Driveにアップロード"""
        dest = f"{self.rclone_remote}:{self.remote_folder}/"
        for attempt in range(3):
            try:
                result = subprocess.run(
                    ["rclone", "copy", file_path, dest,
                     "--retries", "3", "--low-level-retries", "5"],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    fname = os.path.basename(file_path)
                    logger.info(f"Driveアップロード完了: {fname}")
                    return True
                else:
                    logger.warning(f"rcloneエラー: {result.stderr}")
            except FileNotFoundError:
                logger.error("rcloneがインストールされていません。pkg install rclone")
                return False
            except subprocess.TimeoutExpired:
                logger.warning(f"rcloneタイムアウト (attempt {attempt+1})")
            if attempt < 2:
                import time
                time.sleep(5)
        return False

    def _copy_to_shared(self, file_path):
        """Android共有ストレージにコピー
        Google Driveアプリの自動同期でアップロードされる"""
        try:
            os.makedirs(self.shared_path, exist_ok=True)
            fname = os.path.basename(file_path)
            dest = os.path.join(self.shared_path, fname)
            shutil.copy2(file_path, dest)
            logger.info(f"共有ストレージにコピー: {dest}")
            # termux-media-scanでメディアスキャン
            try:
                subprocess.run(["termux-media-scan", dest], timeout=10)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            return True
        except Exception as e:
            logger.error(f"共有ストレージコピー失敗: {e}")
            return False

    def upload_all(self, directory):
        """ディレクトリ内の全mp4をアップロード"""
        count = 0
        for f in sorted(os.listdir(directory)):
            if f.endswith(".mp4"):
                if self.upload(os.path.join(directory, f)):
                    count += 1
        return count

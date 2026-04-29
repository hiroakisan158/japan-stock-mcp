"""SQLite DB のバックアップ・リストア"""
import glob
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")
BACKUP_DIR = Path(DB_PATH).parent / "backups"
MAX_LOCAL_BACKUPS = 5


def backup_local(tag: str = "") -> str:
    """DB をローカルにコピーして保存。バックアップパスを返す。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    dest = BACKUP_DIR / f"stocks_{ts}{suffix}.db"

    conn = sqlite3.connect(DB_PATH)
    backup_conn = sqlite3.connect(str(dest))
    with backup_conn:
        conn.backup(backup_conn)
    backup_conn.close()
    conn.close()

    _cleanup_old_backups()
    logger.info(f"バックアップ完了: {dest}")
    return str(dest)


def _cleanup_old_backups() -> None:
    files = sorted(glob.glob(str(BACKUP_DIR / "stocks_*.db")))
    for old in files[:-MAX_LOCAL_BACKUPS]:
        os.remove(old)
        logger.info(f"古いバックアップを削除: {old}")


def backup_to_s3(local_path: str) -> str | None:
    bucket = os.environ.get("S3_BUCKET", "")
    if not bucket:
        return None
    try:
        import boto3
        s3 = boto3.client("s3")
        key = f"backups/{Path(local_path).name}"
        s3.upload_file(local_path, bucket, key)
        s3_url = f"s3://{bucket}/{key}"
        logger.info(f"S3 アップロード完了: {s3_url}")
        return s3_url
    except Exception as e:
        logger.warning(f"S3 アップロード失敗: {e}")
        return None


def list_local_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    files = sorted(glob.glob(str(BACKUP_DIR / "stocks_*.db")), reverse=True)
    result = []
    for f in files:
        stat = os.stat(f)
        result.append({
            "filename": Path(f).name,
            "path": f,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return result


def restore_local(backup_filename: str) -> None:
    src = BACKUP_DIR / backup_filename
    if not src.exists():
        raise FileNotFoundError(f"バックアップが見つかりません: {backup_filename}")
    shutil.copy2(str(src), DB_PATH)
    logger.info(f"リストア完了: {backup_filename} → {DB_PATH}")

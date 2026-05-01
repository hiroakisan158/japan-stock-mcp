from __future__ import annotations
import glob
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from mcp.server.fastmcp import FastMCP
import db

COMPOSE_DIR = os.environ.get("DOCKER_COMPOSE_DIR", "..")
PROGRESS_FILE = os.path.join(COMPOSE_DIR, "data", "batch_progress.json")


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def update_data(
        mode: str = "update",
        sector: str | None = None,
    ) -> dict:
        """EDINET からデータを取得・更新する。
        mode: 'initial'（初回・過去5年）または 'update'（差分更新）。
        sector を指定すると同期実行（数分〜数時間）。
        sector=None かつ mode='initial' は非同期実行。
        """
        today = date.today()
        fetch_from = (today - timedelta(days=365 * 5)) if mode == "initial" else today - timedelta(days=30)

        cmd = ["docker", "compose", "run", "--rm", "batch", "python", "run.py", "--mode", mode]
        if sector:
            cmd += ["--sector", sector]

        is_async = sector is None and mode == "initial"
        if is_async:
            cmd.insert(3, "-d")

        try:
            result = subprocess.run(cmd, cwd=COMPOSE_DIR, capture_output=True, text=True, timeout=None if is_async else 600)
            if is_async:
                return {
                    "status": "started",
                    "mode": mode,
                    "fetch_range": {"from": str(fetch_from), "to": str(today)},
                    "message": "バックグラウンドで実行中。check_batch_status で進捗を確認できます。",
                }
            if result.returncode != 0:
                return {"status": "failed", "message": result.stderr[:500]}
            return {
                "status": "completed",
                "mode": mode,
                "fetch_range": {"from": str(fetch_from), "to": str(today)},
            }
        except FileNotFoundError:
            return {"status": "error", "message": "Docker が見つかりません。Docker Desktop が起動しているか確認してください。"}

    @mcp.tool()
    def update_prices(sector: str | None = None) -> dict:
        """yfinance で株価・PER/PBR/配当利回り等を更新する。
        sector を指定すると対象セクターのみ更新（同期）。
        省略すると全銘柄を非同期で更新（30〜60分程度）。
        """
        cmd = ["docker", "compose", "run", "--rm", "batch", "python", "run.py", "--mode", "fetch-prices"]
        if sector:
            cmd += ["--sector", sector]

        is_async = sector is None
        if is_async:
            cmd.insert(3, "-d")

        try:
            result = subprocess.run(cmd, cwd=COMPOSE_DIR, capture_output=True, text=True, timeout=None if is_async else 600)
            if is_async:
                return {"status": "started", "message": "バックグラウンドで株価取得中。check_batch_status で確認できます。"}
            if result.returncode != 0:
                return {"status": "failed", "message": result.stderr[:500]}
            return {"status": "completed", "sector": sector}
        except FileNotFoundError:
            return {"status": "error", "message": "Docker が見つかりません。"}

    @mcp.tool()
    def update_quarterly(sector: str | None = None) -> dict:
        """J-Quants API で四半期財務データ（PL・BS・CF）を取得・更新する。
        sector を指定すると対象セクターのみ更新（同期）。
        省略すると全銘柄を非同期で更新（約40分）。
        事前に JQUANTS_REFRESH_TOKEN の設定が必要。
        """
        cmd = ["docker", "compose", "run", "--rm", "batch", "python", "run.py", "--mode", "fetch-quarterly"]
        if sector:
            cmd += ["--sector", sector]

        is_async = sector is None
        if is_async:
            cmd.insert(3, "-d")

        try:
            result = subprocess.run(cmd, cwd=COMPOSE_DIR, capture_output=True, text=True, timeout=None if is_async else 600)
            if is_async:
                return {"status": "started", "message": "バックグラウンドで四半期データ取得中。check_batch_status で確認できます。"}
            if result.returncode != 0:
                stderr = result.stderr[:500]
                if "JQUANTS_REFRESH_TOKEN" in stderr or "認証エラー" in stderr or "401" in stderr or "403" in stderr:
                    return {"status": "failed", "message": f"J-Quants API 認証エラー。.env の JQUANTS_REFRESH_TOKEN を確認してください。\n{stderr}"}
                return {"status": "failed", "message": stderr}
            return {"status": "completed", "sector": sector}
        except FileNotFoundError:
            return {"status": "error", "message": "Docker が見つかりません。"}

    @mcp.tool()
    def check_batch_status() -> dict:
        """実行中・最新バッチの進捗を返す"""
        try:
            if os.path.exists(PROGRESS_FILE):
                with open(PROGRESS_FILE) as f:
                    progress = json.load(f)
                return progress
        except Exception:
            pass

        if not db.db_exists():
            return {"status": "no_batch", "message": "バッチ未実行またはDB未初期化です。"}

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM batch_log ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

        if not row:
            return {"status": "no_batch"}

        return dict(row)

    @mcp.tool()
    def backup_db(tag: str = "") -> dict:
        """SQLite DB をローカルにバックアップする。tag は任意の識別文字列。"""
        db_path = db.DB_PATH
        backup_dir = Path(db_path).parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{tag}" if tag else ""
        dest = backup_dir / f"stocks_{ts}{suffix}.db"

        try:
            conn = sqlite3.connect(db_path)
            backup_conn = sqlite3.connect(str(dest))
            with backup_conn:
                conn.backup(backup_conn)
            backup_conn.close()
            conn.close()
        except Exception as e:
            return {"status": "error", "message": str(e)}

        # 古いバックアップを削除（直近5件保持）
        files = sorted(glob.glob(str(backup_dir / "stocks_*.db")))
        for old in files[:-5]:
            os.remove(old)

        size_mb = round(os.path.getsize(str(dest)) / 1024 / 1024, 2)
        return {"status": "completed", "filename": dest.name, "size_mb": size_mb}

    @mcp.tool()
    def list_backups() -> dict:
        """ローカルに保存されたバックアップの一覧を返す。"""
        db_path = db.DB_PATH
        backup_dir = Path(db_path).parent / "backups"
        if not backup_dir.exists():
            return {"backups": []}

        files = sorted(glob.glob(str(backup_dir / "stocks_*.db")), reverse=True)
        backups = []
        for f in files:
            stat = os.stat(f)
            backups.append({
                "filename": Path(f).name,
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return {"backups": backups}

    @mcp.tool()
    def restore_db(filename: str) -> dict:
        """指定したバックアップファイルから DB をリストアする。
        filename は list_backups で確認したファイル名（例: stocks_20260429_120000.db）。
        現在の DB は上書きされるため注意。
        """
        db_path = db.DB_PATH
        backup_dir = Path(db_path).parent / "backups"
        src = backup_dir / filename
        if not src.exists():
            return {"status": "error", "message": f"バックアップが見つかりません: {filename}"}

        try:
            shutil.copy2(str(src), db_path)
        except Exception as e:
            return {"status": "error", "message": str(e)}

        return {"status": "completed", "restored_from": filename}

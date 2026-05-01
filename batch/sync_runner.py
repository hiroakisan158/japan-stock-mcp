"""sync オーケストレーター: 財務差分→株価→四半期 を順次実行し進捗を記録する"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")
PROGRESS_FILE = Path(DB_PATH).parent / "sync_progress.json"
STATUS_OUTPUT = os.environ.get("STATUS_OUTPUT", "/workspace/tmp/db_status.md")

STEPS = ["update", "fetch-prices", "fetch-quarterly"]


def _write(progress: dict) -> None:
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _run_step(mode: str, sector: str | None) -> bool:
    cmd = [sys.executable, "run.py", "--mode", mode]
    if sector:
        cmd += ["--sector", sector]
    return subprocess.run(cmd).returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sector", default=None)
    args = parser.parse_args()

    progress = {
        "started_at": datetime.now().isoformat(),
        "sector": args.sector or "全社",
        "steps": {s: {"status": "pending"} for s in STEPS},
    }
    _write(progress)
    print(f"[sync] 開始  セクター: {progress['sector']}")

    for step in STEPS:
        progress["steps"][step] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
        _write(progress)
        print(f"[sync] ▶ {step} ...")

        success = _run_step(step, args.sector)

        finished_at = datetime.now().isoformat()
        if success:
            progress["steps"][step] = {"status": "done", "finished_at": finished_at}
            print(f"[sync] ✅ {step} 完了")
        else:
            progress["steps"][step] = {"status": "error", "finished_at": finished_at}
            _write(progress)
            print(f"[sync] ❌ {step} 失敗。中断します。", file=sys.stderr)
            sys.exit(1)

        _write(progress)

    progress["finished_at"] = datetime.now().isoformat()
    _write(progress)
    print("[sync] 全ステップ完了。ステータスレポートを生成中...")

    subprocess.run(
        [sys.executable, "gen_db_status.py"],
        env={**os.environ, "STATUS_OUTPUT": STATUS_OUTPUT},
    )


if __name__ == "__main__":
    main()

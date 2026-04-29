import os
import sys
from datetime import datetime, timezone

# app/ ディレクトリを sys.path に追加して tools, db を import できるようにする
sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
import db
from tools import annual_report, batch_trigger, financials, metadata, screener

mcp = FastMCP("japan-stocks")


@mcp.resource("status://data-freshness")
def data_freshness() -> dict:
    last_updated = db.get_last_updated()
    days_ago = (datetime.now(timezone.utc).date() - last_updated).days if last_updated else None
    s3_configured = bool(os.environ.get("S3_BUCKET"))
    stale = days_ago is None or days_ago > 90

    parts = []
    if days_ago is None:
        parts.append("財務データが未取得です。update_data でデータを取得してください。")
    elif stale:
        parts.append(f"財務データは{days_ago}日前に更新されました。更新を推奨します。")
    if not s3_configured:
        parts.append("S3 バックアップが未設定です。")

    return {
        "last_updated": str(last_updated) if last_updated else None,
        "days_since_update": days_ago,
        "stale": stale,
        "s3_configured": s3_configured,
        "message": " ".join(parts),
    }


metadata.register(mcp)
screener.register(mcp)
financials.register(mcp)
batch_trigger.register(mcp)
annual_report.register(mcp)


if __name__ == "__main__":
    mcp.run()

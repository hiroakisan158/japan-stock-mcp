from __future__ import annotations
from mcp.server.fastmcp import FastMCP
import db


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_sectors() -> dict:
        """利用可能なセクター一覧と所属企業数を返す"""
        if not db.db_exists():
            return {"sectors": [], "message": "データが未取得です。update_data で初期化してください。"}
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT sector, COUNT(*) as count FROM companies"
                " WHERE sector IS NOT NULL GROUP BY sector ORDER BY count DESC"
            ).fetchall()
        return {"sectors": [{"name": r["sector"], "count": r["count"]} for r in rows]}

    @mcp.tool()
    def get_company_info(code: str) -> dict:
        """企業の基本情報と最新財務サマリーを返す。code は証券コード（例: '7974'）"""
        if not db.db_exists():
            return {"error": "データが未取得です。update_data で初期化してください。"}
        with db.get_connection() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE sec_code = ?", [code]
            ).fetchone()
            if not company:
                return {"error": f"証券コード {code} が見つかりません"}
            financials = conn.execute(
                "SELECT * FROM financials WHERE edinet_code = ? AND quarter IS NULL"
                " ORDER BY period_end DESC LIMIT 1",
                [company["edinet_code"]],
            ).fetchone()
            price = conn.execute(
                "SELECT * FROM prices WHERE edinet_code = ? ORDER BY fetched_at DESC LIMIT 1",
                [company["edinet_code"]],
            ).fetchone()
        return {
            "company": dict(company),
            "latest_financials": dict(financials) if financials else None,
            "latest_price": dict(price) if price else None,
        }

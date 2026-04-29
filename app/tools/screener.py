from __future__ import annotations
from datetime import date
from mcp.server.fastmcp import FastMCP
import db


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def screen_stocks(
        sector: str | None = None,
        market: str | None = None,
        roe_min: float | None = None,
        per_max: float | None = None,
        pbr_max: float | None = None,
        revenue_min: float | None = None,
        op_margin_min: float | None = None,
        sort_by: str = "market_cap",
        limit: int = 30,
    ) -> dict:
        """財務指標で銘柄をフィルタリングする。
        revenue_min の単位は百万円。roe_min / op_margin_min の単位は %。
        sort_by には market_cap / roe / per / pbr / revenue / op_margin が指定可能。
        """
        if not db.db_exists():
            return {
                "data": [],
                "meta": {"total_matches": 0, "returned": 0, "message": "データが未取得です。update_data で初期化してください。"},
            }

        conditions = ["1=1"]
        params: list = []

        if sector:
            conditions.append("c.sector = ?")
            params.append(sector)
        if market:
            conditions.append("c.market = ?")
            params.append(market)
        if roe_min is not None:
            conditions.append("f.roe >= ?")
            params.append(roe_min)
        if per_max is not None:
            conditions.append("p.per <= ?")
            params.append(per_max)
        if pbr_max is not None:
            conditions.append("p.pbr <= ?")
            params.append(pbr_max)
        if revenue_min is not None:
            conditions.append("f.revenue >= ?")
            params.append(revenue_min * 1_000_000)
        if op_margin_min is not None:
            conditions.append("f.operating_profit_margin >= ?")
            params.append(op_margin_min)

        sort_map = {
            "market_cap": "p.market_cap DESC",
            "roe": "f.roe DESC",
            "per": "p.per ASC",
            "pbr": "p.pbr ASC",
            "revenue": "f.revenue DESC",
            "op_margin": "f.operating_profit_margin DESC",
        }
        order = sort_map.get(sort_by, "p.market_cap DESC")

        where = " AND ".join(conditions)
        sql = f"""
            SELECT
                c.sec_code, c.company_name, c.sector, c.market,
                f.revenue, f.operating_income, f.operating_profit_margin,
                f.roe, f.roa, f.equity_ratio, f.fiscal_year,
                p.price, p.market_cap, p.per, p.pbr, p.dividend_yield
            FROM companies c
            JOIN (
                SELECT edinet_code, MAX(period_end) AS max_period
                FROM financials WHERE quarter IS NULL GROUP BY edinet_code
            ) latest ON c.edinet_code = latest.edinet_code
            JOIN financials f
                ON f.edinet_code = latest.edinet_code AND f.period_end = latest.max_period AND f.quarter IS NULL
            LEFT JOIN (
                SELECT edinet_code, MAX(fetched_at) AS max_fetched FROM prices GROUP BY edinet_code
            ) lp ON c.edinet_code = lp.edinet_code
            LEFT JOIN prices p ON p.edinet_code = lp.edinet_code AND p.fetched_at = lp.max_fetched
            WHERE {where}
            ORDER BY {order}
        """

        with db.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        last_updated = db.get_last_updated()
        days_ago = (date.today() - last_updated).days if last_updated else None

        return {
            "data": [dict(r) for r in rows[:limit]],
            "meta": {
                "total_matches": len(rows),
                "returned": min(len(rows), limit),
                "last_updated": str(last_updated) if last_updated else None,
                "days_since_update": days_ago,
                "stale": days_ago is None or days_ago > 90,
            },
        }

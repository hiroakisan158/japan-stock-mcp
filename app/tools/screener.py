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
        quarterly_revenue_growth_min: float | None = None,
        quarterly_op_income_growth_min: float | None = None,
        sort_by: str = "market_cap",
        limit: int = 30,
    ) -> dict:
        """財務指標で銘柄をフィルタリングする。
        revenue_min の単位は百万円。roe_min / op_margin_min の単位は %。
        quarterly_revenue_growth_min / quarterly_op_income_growth_min は
        直近四半期の前年同期比成長率（%）による絞り込み（update_quarterly 実行後に有効）。
        sort_by には market_cap / roe / per / pbr / revenue / op_margin が指定可能。
        """
        if not db.db_exists():
            return {
                "data": [],
                "meta": {"total_matches": 0, "returned": 0, "message": "データが未取得です。update_data で初期化してください。"},
            }

        use_quarterly = (
            quarterly_revenue_growth_min is not None
            or quarterly_op_income_growth_min is not None
        )

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

        # 四半期 YoY 成長率フィルタ（前年同期比）
        # CASE 式を WHERE に直書き（SQLite は SELECT alias を WHERE で参照不可）
        if quarterly_revenue_growth_min is not None:
            conditions.append(
                "CASE WHEN pq.prev_revenue > 0"
                " THEN (cq.q_revenue - pq.prev_revenue) / ABS(pq.prev_revenue) * 100"
                " ELSE NULL END >= ?"
            )
            params.append(quarterly_revenue_growth_min)
        if quarterly_op_income_growth_min is not None:
            conditions.append(
                "CASE WHEN pq.prev_op_income != 0"
                " THEN (cq.q_op_income - pq.prev_op_income) / ABS(pq.prev_op_income) * 100"
                " ELSE NULL END >= ?"
            )
            params.append(quarterly_op_income_growth_min)

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

        # 四半期フィルタあり: CTE で直近四半期と前年同期を結合
        if use_quarterly:
            cte = """
                WITH curr_q AS (
                    SELECT f.edinet_code,
                           f.quarter,
                           f.period_end,
                           f.revenue          AS q_revenue,
                           f.operating_income AS q_op_income
                    FROM financials f
                    INNER JOIN (
                        SELECT edinet_code, MAX(period_end) AS max_pe
                        FROM financials WHERE quarter IS NOT NULL GROUP BY edinet_code
                    ) lq ON f.edinet_code = lq.edinet_code AND f.period_end = lq.max_pe
                    WHERE f.quarter IS NOT NULL
                ),
                prev_q AS (
                    SELECT f.edinet_code,
                           f.revenue          AS prev_revenue,
                           f.operating_income AS prev_op_income
                    FROM financials f
                    INNER JOIN (
                        SELECT f2.edinet_code, MAX(f2.period_end) AS best_pe
                        FROM financials f2
                        INNER JOIN curr_q ON f2.edinet_code = curr_q.edinet_code
                            AND f2.quarter = curr_q.quarter
                            AND f2.period_end < curr_q.period_end
                            AND f2.period_end >= date(curr_q.period_end, '-15 months')
                        WHERE f2.quarter IS NOT NULL
                        GROUP BY f2.edinet_code
                    ) best ON f.edinet_code = best.edinet_code AND f.period_end = best.best_pe
                    WHERE f.quarter IS NOT NULL
                )
            """
            quarterly_join = """
                LEFT JOIN curr_q cq ON c.edinet_code = cq.edinet_code
                LEFT JOIN prev_q pq ON c.edinet_code = pq.edinet_code
            """
            growth_select = """,
                CASE WHEN pq.prev_revenue > 0
                     THEN ROUND((cq.q_revenue - pq.prev_revenue) / ABS(pq.prev_revenue) * 100, 1)
                     ELSE NULL END AS quarterly_revenue_growth,
                CASE WHEN pq.prev_op_income != 0
                     THEN ROUND((cq.q_op_income - pq.prev_op_income) / ABS(pq.prev_op_income) * 100, 1)
                     ELSE NULL END AS quarterly_op_income_growth"""
        else:
            cte = ""
            quarterly_join = ""
            growth_select = ""

        sql = f"""
            {cte}
            SELECT
                c.sec_code, c.company_name, c.sector, c.market,
                f.revenue, f.operating_income, f.operating_profit_margin,
                f.roe, f.roa, f.equity_ratio, f.fiscal_year,
                p.price, p.market_cap, p.per, p.pbr, p.dividend_yield
                {growth_select}
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
            {quarterly_join}
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

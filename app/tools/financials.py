from __future__ import annotations
from mcp.server.fastmcp import FastMCP
import db


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_financials(
        code: str,
        metrics: list[str] | None = None,
        years: int = 5,
    ) -> dict:
        """特定企業の財務データを年次で取得する。
        code は証券コード（例: '7974'）。
        metrics を省略すると主要指標を全件返す。
        years は遡る年数（デフォルト 5）。
        """
        if not db.db_exists():
            return {"error": "データが未取得です。update_data で初期化してください。"}

        with db.get_connection() as conn:
            company = conn.execute(
                "SELECT * FROM companies WHERE sec_code = ?", [code]
            ).fetchone()
            if not company:
                return {"error": f"証券コード {code} が見つかりません"}

            rows = conn.execute(
                "SELECT * FROM financials WHERE edinet_code = ? AND quarter IS NULL"
                " ORDER BY period_end DESC LIMIT ?",
                [company["edinet_code"], years],
            ).fetchall()

        all_metrics = [
            "fiscal_year", "period_end",
            "revenue", "gross_profit", "operating_income", "ordinary_income", "net_income",
            "total_assets", "net_assets", "shareholders_equity",
            "operating_cf", "investing_cf", "financing_cf", "free_cf", "net_cash",
            "gross_profit_margin", "operating_profit_margin", "ordinary_profit_margin", "net_profit_margin",
            "roe", "roa", "equity_ratio", "debt_to_equity_ratio", "current_ratio",
        ]
        keys = metrics if metrics else all_metrics

        financials_data = []
        for r in rows:
            row_dict = dict(r)
            # クエリ時に成長率を計算（前期比較）
            entry = {k: row_dict.get(k) for k in keys if k in row_dict}
            financials_data.append(entry)

        return {
            "company": {
                "sec_code": company["sec_code"],
                "company_name": company["company_name"],
                "sector": company["sector"],
            },
            "financials": financials_data,
            "meta": {"years_returned": len(financials_data)},
        }

    @mcp.tool()
    def compare_companies(
        codes: list[str],
        metrics: list[str] | None = None,
        year: int | None = None,
    ) -> dict:
        """複数企業の財務データを比較する。
        codes は証券コードのリスト（例: ['7974', '9684']）。
        year を省略すると各社の最新年度を使用。
        """
        if not db.db_exists():
            return {"error": "データが未取得です。update_data で初期化してください。"}

        default_metrics = [
            "revenue", "operating_income", "operating_profit_margin",
            "roe", "roa", "equity_ratio", "per", "pbr",
        ]
        keys = metrics if metrics else default_metrics

        results = []
        with db.get_connection() as conn:
            for code in codes:
                company = conn.execute(
                    "SELECT * FROM companies WHERE sec_code = ?", [code]
                ).fetchone()
                if not company:
                    results.append({"sec_code": code, "error": "見つかりません"})
                    continue

                if year:
                    f_row = conn.execute(
                        "SELECT * FROM financials WHERE edinet_code = ? AND fiscal_year = ? AND quarter IS NULL",
                        [company["edinet_code"], year],
                    ).fetchone()
                else:
                    f_row = conn.execute(
                        "SELECT * FROM financials WHERE edinet_code = ? AND quarter IS NULL"
                        " ORDER BY period_end DESC LIMIT 1",
                        [company["edinet_code"]],
                    ).fetchone()

                p_row = conn.execute(
                    "SELECT * FROM prices WHERE edinet_code = ? ORDER BY fetched_at DESC LIMIT 1",
                    [company["edinet_code"]],
                ).fetchone()

                merged = {}
                if f_row:
                    merged.update(dict(f_row))
                if p_row:
                    merged.update(dict(p_row))

                entry = {
                    "sec_code": company["sec_code"],
                    "company_name": company["company_name"],
                    "sector": company["sector"],
                }
                entry.update({k: merged.get(k) for k in keys})
                results.append(entry)

        return {"companies": results, "metrics": keys}

"""yfinance から四半期財務データを取得して financials テーブルに保存"""
import logging
import os
import sqlite3
import time
from datetime import date

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _get_fiscal_year_end_month(conn: sqlite3.Connection, edinet_code: str) -> int | None:
    row = conn.execute(
        "SELECT CAST(strftime('%m', MAX(period_end)) AS INTEGER) AS fy_month "
        "FROM financials WHERE edinet_code = ? AND quarter IS NULL",
        [edinet_code],
    ).fetchone()
    return row[0] if row and row[0] else None


def _infer_quarter(period_end: date, fy_end_month: int) -> int | None:
    """period_end から四半期番号（1-3）を推定する。Q4（年次）は None を返す。"""
    fy_start_month = (fy_end_month % 12) + 1
    months_in = ((period_end.month - fy_start_month) % 12) + 1
    return {3: 1, 6: 2, 9: 3}.get(months_in)


def _quarter_start(period_end: date) -> date:
    """四半期末日から期首日（3か月前の1日）を求める。"""
    m = period_end.month - 2
    y = period_end.year
    if m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _infer_fiscal_year(period_end: date, fy_end_month: int) -> int:
    """四半期の period_end が属する会計年度（期末年）を返す。"""
    if period_end.month <= fy_end_month:
        return period_end.year
    return period_end.year + 1


def _safe_val(df: pd.DataFrame, row_key: str, col: object) -> float | None:
    try:
        v = df.at[row_key, col]
        return None if pd.isna(v) else float(v)
    except (KeyError, TypeError):
        return None


def _fetch_quarterly(sec_code: str) -> list[dict]:
    """yfinance から四半期財務データを取得してレコードのリストを返す。"""
    ticker = yf.Ticker(f"{sec_code}.T")

    try:
        qf = ticker.quarterly_financials      # PL
    except Exception:
        qf = pd.DataFrame()
    try:
        qbs = ticker.quarterly_balance_sheet  # BS
    except Exception:
        qbs = pd.DataFrame()
    try:
        qcf = ticker.quarterly_cashflow       # CF
    except Exception:
        qcf = pd.DataFrame()

    if qf.empty and qbs.empty and qcf.empty:
        return []

    # 全 DataFrame の列（period_end）を統合
    cols = set()
    for df in (qf, qbs, qcf):
        if not df.empty:
            cols.update(df.columns)

    records = []
    for col in cols:
        try:
            period_end = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
        except Exception:
            continue

        revenue          = _safe_val(qf, "Total Revenue", col)
        gross_profit     = _safe_val(qf, "Gross Profit", col)
        operating_income = _safe_val(qf, "Operating Income", col)
        net_income       = _safe_val(qf, "Net Income", col)

        total_assets       = _safe_val(qbs, "Total Assets", col)
        shareholders_equity = (
            _safe_val(qbs, "Stockholders Equity", col)
            or _safe_val(qbs, "Common Stock Equity", col)
        )

        operating_cf  = _safe_val(qcf, "Operating Cash Flow", col)
        investing_cf  = _safe_val(qcf, "Investing Cash Flow", col)
        financing_cf  = _safe_val(qcf, "Financing Cash Flow", col)

        free_cf = None
        if operating_cf is not None and investing_cf is not None:
            free_cf = operating_cf + investing_cf

        gpm  = round(gross_profit / revenue * 100, 4)     if gross_profit is not None and revenue else None
        opm  = round(operating_income / revenue * 100, 4) if operating_income is not None and revenue else None
        npm  = round(net_income / revenue * 100, 4)       if net_income is not None and revenue else None

        # 主要財務値がすべて None なら格納しても意味がないのでスキップ
        if all(v is None for v in (revenue, operating_income, net_income, total_assets)):
            continue

        records.append({
            "period_end":          period_end,
            "period_start":        _quarter_start(period_end),
            "revenue":             revenue,
            "gross_profit":        gross_profit,
            "operating_income":    operating_income,
            "net_income":          net_income,
            "total_assets":        total_assets,
            "shareholders_equity": shareholders_equity,
            "operating_cf":        operating_cf,
            "investing_cf":        investing_cf,
            "financing_cf":        financing_cf,
            "free_cf":             free_cf,
            "gross_profit_margin":    gpm,
            "operating_profit_margin": opm,
            "net_profit_margin":      npm,
        })

    return records


def _upsert_quarterly(
    conn: sqlite3.Connection,
    edinet_code: str,
    rec: dict,
    quarter: int,
    fiscal_year: int,
) -> None:
    conn.execute("""
        INSERT INTO financials (
            edinet_code, period_start, period_end, fiscal_year, quarter, doc_id, source,
            revenue, gross_profit, operating_income, net_income,
            total_assets, shareholders_equity,
            operating_cf, investing_cf, financing_cf, free_cf,
            gross_profit_margin, operating_profit_margin, net_profit_margin
        ) VALUES (
            :edinet_code, :period_start, :period_end, :fiscal_year, :quarter, NULL, 'yfinance',
            :revenue, :gross_profit, :operating_income, :net_income,
            :total_assets, :shareholders_equity,
            :operating_cf, :investing_cf, :financing_cf, :free_cf,
            :gross_profit_margin, :operating_profit_margin, :net_profit_margin
        )
        ON CONFLICT(edinet_code, period_end, quarter) DO UPDATE SET
            revenue               = CASE WHEN source = 'edinet' THEN revenue               ELSE excluded.revenue               END,
            gross_profit          = CASE WHEN source = 'edinet' THEN gross_profit          ELSE excluded.gross_profit          END,
            operating_income      = CASE WHEN source = 'edinet' THEN operating_income      ELSE excluded.operating_income      END,
            net_income            = CASE WHEN source = 'edinet' THEN net_income            ELSE excluded.net_income            END,
            total_assets          = CASE WHEN source = 'edinet' THEN total_assets          ELSE excluded.total_assets          END,
            shareholders_equity   = CASE WHEN source = 'edinet' THEN shareholders_equity   ELSE excluded.shareholders_equity   END,
            operating_cf          = CASE WHEN source = 'edinet' THEN operating_cf          ELSE excluded.operating_cf          END,
            investing_cf          = CASE WHEN source = 'edinet' THEN investing_cf          ELSE excluded.investing_cf          END,
            financing_cf          = CASE WHEN source = 'edinet' THEN financing_cf          ELSE excluded.financing_cf          END,
            free_cf               = CASE WHEN source = 'edinet' THEN free_cf               ELSE excluded.free_cf               END,
            gross_profit_margin   = CASE WHEN source = 'edinet' THEN gross_profit_margin   ELSE excluded.gross_profit_margin   END,
            operating_profit_margin = CASE WHEN source = 'edinet' THEN operating_profit_margin ELSE excluded.operating_profit_margin END,
            net_profit_margin     = CASE WHEN source = 'edinet' THEN net_profit_margin     ELSE excluded.net_profit_margin     END,
            source                = CASE WHEN source = 'edinet' THEN source                ELSE 'yfinance'                     END
    """, {
        "edinet_code":    edinet_code,
        "period_start":   rec["period_start"].isoformat(),
        "period_end":     rec["period_end"].isoformat(),
        "fiscal_year":    fiscal_year,
        "quarter":        quarter,
        **{k: rec[k] for k in (
            "revenue", "gross_profit", "operating_income", "net_income",
            "total_assets", "shareholders_equity",
            "operating_cf", "investing_cf", "financing_cf", "free_cf",
            "gross_profit_margin", "operating_profit_margin", "net_profit_margin",
        )},
    })


def run_fetch_quarterly(sector: str | None = None, sec_code: str | None = None) -> None:
    conn = _get_db()

    if sec_code:
        rows = conn.execute(
            "SELECT edinet_code, sec_code, company_name FROM companies WHERE sec_code = ?",
            [sec_code],
        ).fetchall()
    elif sector:
        rows = conn.execute(
            "SELECT edinet_code, sec_code, company_name FROM companies WHERE sector = ?",
            [sector],
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT edinet_code, sec_code, company_name FROM companies WHERE sec_code IS NOT NULL"
        ).fetchall()

    total = len(rows)
    logger.info(f"四半期データ取得対象: {total} 社")

    ok = skip = 0
    for i, row in enumerate(rows):
        edinet_code = row["edinet_code"]
        code        = row["sec_code"]
        name        = row["company_name"]

        fy_end_month = _get_fiscal_year_end_month(conn, edinet_code)
        if fy_end_month is None:
            logger.debug(f"  スキップ（年次データなし）: {name} ({code})")
            skip += 1
            continue

        logger.info(f"[{i+1}/{total}] {name} ({code}) ...")
        try:
            records = _fetch_quarterly(code)
        except Exception as e:
            logger.warning(f"  スキップ（取得エラー）: {name} ({code}) - {e}")
            skip += 1
            time.sleep(0.5)
            continue

        inserted = 0
        for rec in records:
            quarter = _infer_quarter(rec["period_end"], fy_end_month)
            if quarter is None:
                continue  # Q4（年次）はスキップ
            fiscal_year = _infer_fiscal_year(rec["period_end"], fy_end_month)

            # revenue が YTD 累積値の疑いがある場合に警告
            if rec["revenue"] is not None:
                annual = conn.execute(
                    "SELECT revenue FROM financials WHERE edinet_code=? AND quarter IS NULL "
                    "ORDER BY period_end DESC LIMIT 1",
                    [edinet_code],
                ).fetchone()
                if annual and annual["revenue"] and rec["revenue"] > annual["revenue"] * 0.95:
                    logger.warning(
                        f"  YTD 累積値の疑い: {name} Q{quarter} revenue={rec['revenue']:,.0f} "
                        f">= annual={annual['revenue']:,.0f} * 0.95"
                    )

            _upsert_quarterly(conn, edinet_code, rec, quarter, fiscal_year)
            inserted += 1

        conn.commit()
        if inserted:
            ok += 1
            logger.info(f"  {inserted} 件 upsert")
        else:
            skip += 1

        time.sleep(0.5)

    conn.close()
    logger.info(f"完了: 取得 {ok} 社、スキップ {skip} 社")

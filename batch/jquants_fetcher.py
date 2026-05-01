"""J-Quants API v2 から四半期財務データを取得して financials テーブルに保存"""
import logging
import os
import sqlite3
import time

import jquantsapi
import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")

PERIOD_TYPE_TO_QUARTER = {"1Q": 1, "2Q": 2, "3Q": 3}


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _get_client() -> jquantsapi.ClientV2:
    token = os.environ.get("JQUANTS_REFRESH_TOKEN")
    if not token:
        raise ValueError("JQUANTS_REFRESH_TOKEN が設定されていません")
    return jquantsapi.ClientV2(api_key=token)


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _upsert_quarterly(conn: sqlite3.Connection, edinet_code: str, rec: dict) -> None:
    revenue = rec.get("revenue")
    op_income = rec.get("operating_income")
    ord_income = rec.get("ordinary_income")
    net_income = rec.get("net_income")
    op_cf = rec.get("operating_cf")
    inv_cf = rec.get("investing_cf")

    opm = round(op_income / revenue * 100, 4) if op_income is not None and revenue else None
    npm = round(net_income / revenue * 100, 4) if net_income is not None and revenue else None
    opm_ord = round(ord_income / revenue * 100, 4) if ord_income is not None and revenue else None
    free_cf = op_cf + inv_cf if op_cf is not None and inv_cf is not None else None

    conn.execute("""
        INSERT INTO financials (
            edinet_code, period_start, period_end, fiscal_year, quarter, doc_id, source,
            revenue, operating_income, ordinary_income, net_income,
            total_assets, net_assets,
            operating_cf, investing_cf, financing_cf, free_cf,
            cash_and_deposits,
            operating_profit_margin, ordinary_profit_margin, net_profit_margin
        ) VALUES (
            :edinet_code, :period_start, :period_end, :fiscal_year, :quarter, NULL, 'jquants',
            :revenue, :operating_income, :ordinary_income, :net_income,
            :total_assets, :net_assets,
            :operating_cf, :investing_cf, :financing_cf, :free_cf,
            :cash_and_deposits,
            :operating_profit_margin, :ordinary_profit_margin, :net_profit_margin
        )
        ON CONFLICT(edinet_code, period_end, quarter) DO UPDATE SET
            revenue                 = CASE WHEN source = 'edinet' THEN revenue                 ELSE excluded.revenue                 END,
            operating_income        = CASE WHEN source = 'edinet' THEN operating_income        ELSE excluded.operating_income        END,
            ordinary_income         = CASE WHEN source = 'edinet' THEN ordinary_income         ELSE excluded.ordinary_income         END,
            net_income              = CASE WHEN source = 'edinet' THEN net_income              ELSE excluded.net_income              END,
            total_assets            = CASE WHEN source = 'edinet' THEN total_assets            ELSE excluded.total_assets            END,
            net_assets              = CASE WHEN source = 'edinet' THEN net_assets              ELSE excluded.net_assets              END,
            operating_cf            = CASE WHEN source = 'edinet' THEN operating_cf            ELSE excluded.operating_cf            END,
            investing_cf            = CASE WHEN source = 'edinet' THEN investing_cf            ELSE excluded.investing_cf            END,
            financing_cf            = CASE WHEN source = 'edinet' THEN financing_cf            ELSE excluded.financing_cf            END,
            free_cf                 = CASE WHEN source = 'edinet' THEN free_cf                 ELSE excluded.free_cf                 END,
            cash_and_deposits       = CASE WHEN source = 'edinet' THEN cash_and_deposits       ELSE excluded.cash_and_deposits       END,
            operating_profit_margin = CASE WHEN source = 'edinet' THEN operating_profit_margin ELSE excluded.operating_profit_margin END,
            ordinary_profit_margin  = CASE WHEN source = 'edinet' THEN ordinary_profit_margin  ELSE excluded.ordinary_profit_margin  END,
            net_profit_margin       = CASE WHEN source = 'edinet' THEN net_profit_margin       ELSE excluded.net_profit_margin       END,
            source                  = CASE WHEN source = 'edinet' THEN source                  ELSE 'jquants'                        END
    """, {
        "edinet_code":           edinet_code,
        "period_start":          rec["period_start"],
        "period_end":            rec["period_end"],
        "fiscal_year":           rec["fiscal_year"],
        "quarter":               rec["quarter"],
        "revenue":               revenue,
        "operating_income":      op_income,
        "ordinary_income":       ord_income,
        "net_income":            net_income,
        "total_assets":          rec.get("total_assets"),
        "net_assets":            rec.get("net_assets"),
        "operating_cf":          op_cf,
        "investing_cf":          inv_cf,
        "financing_cf":          rec.get("financing_cf"),
        "free_cf":               free_cf,
        "cash_and_deposits":     rec.get("cash_and_deposits"),
        "operating_profit_margin":  opm,
        "ordinary_profit_margin":   opm_ord,
        "net_profit_margin":        npm,
    })


def run_fetch_quarterly_jquants(sector: str | None = None, sec_code: str | None = None) -> None:
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
    logger.info(f"四半期データ取得対象: {total} 社 (J-Quants v2)")

    cli = _get_client()
    ok = skip = 0

    for i, row in enumerate(rows):
        edinet_code = row["edinet_code"]
        code = row["sec_code"]
        name = row["company_name"]

        logger.info(f"[{i+1}/{total}] {name} ({code}) ...")
        df = None
        for attempt in range(3):
            try:
                df = cli.get_fin_summary(code=code)
                break
            except Exception as e:
                err = str(e)
                if "401" in err or "403" in err:
                    raise RuntimeError(
                        f"J-Quants API 認証エラー。JQUANTS_REFRESH_TOKEN が正しいか確認してください: {e}"
                    )
                if "429" in err and attempt < 2:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"  レート制限 (429)、{wait}秒待機して再試行 [{attempt+1}/3]: {name}")
                    time.sleep(wait)
                else:
                    logger.warning(f"  スキップ（API エラー）: {name} ({code}) - {e}")
                    skip += 1
                    time.sleep(2.0)
                    df = None
                    break

        if df is None or df.empty:
            if df is not None:
                logger.debug(f"  スキップ（データなし）: {name}")
                skip += 1
            time.sleep(0.6)
            continue

        # 訂正開示があった場合は最新（DiscDate が最新）を残す
        df = df.sort_values("DiscDate").drop_duplicates(
            subset=["CurPerType", "CurPerEn"], keep="last"
        )

        inserted = 0
        for _, r in df.iterrows():
            period_type = r.get("CurPerType", "")
            quarter = PERIOD_TYPE_TO_QUARTER.get(period_type)
            if quarter is None:
                continue  # FY / 4Q はスキップ

            period_end_raw = r.get("CurPerEn", "")
            period_start_raw = r.get("CurPerSt", "")
            fy_end_raw = r.get("CurFYEn", "")

            if not period_end_raw or str(period_end_raw) in ("", "NaT"):
                continue

            period_end = str(period_end_raw)[:10]
            period_start = str(period_start_raw)[:10] if period_start_raw else period_end
            fiscal_year = int(str(fy_end_raw)[:4]) if fy_end_raw else int(period_end[:4])

            revenue = _safe_float(r.get("Sales"))
            op_income = _safe_float(r.get("OP"))
            net_income = _safe_float(r.get("NP"))
            if revenue is None and op_income is None and net_income is None:
                continue

            rec = {
                "period_start":    period_start,
                "period_end":      period_end,
                "fiscal_year":     fiscal_year,
                "quarter":         quarter,
                "revenue":         revenue,
                "operating_income": op_income,
                "ordinary_income": _safe_float(r.get("OdP")),
                "net_income":      net_income,
                "total_assets":    _safe_float(r.get("TA")),
                "net_assets":      _safe_float(r.get("Eq")),
                "operating_cf":    _safe_float(r.get("CFO")),
                "investing_cf":    _safe_float(r.get("CFI")),
                "financing_cf":    _safe_float(r.get("CFF")),
                "cash_and_deposits": _safe_float(r.get("CashEq")),
            }

            _upsert_quarterly(conn, edinet_code, rec)
            inserted += 1

        conn.commit()
        if inserted:
            ok += 1
            logger.info(f"  {inserted} 件 upsert")
        else:
            skip += 1
            logger.debug(f"  四半期データなし: {name}")

        time.sleep(0.6)

    conn.close()
    logger.info(f"完了: 取得 {ok} 社、スキップ {skip} 社")

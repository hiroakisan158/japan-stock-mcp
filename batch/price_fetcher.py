"""yfinance で株価・バリュエーション指標を取得して prices テーブルに保存"""
import logging
import os
import sqlite3
import time
from datetime import date

import yfinance as yf

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _fetch_price(sec_code: str) -> dict | None:
    ticker_symbol = f"{sec_code}.T"
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
    except Exception as e:
        logger.warning(f"  yfinance error {ticker_symbol}: {e}")
        return None

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if price is None:
        return None

    market_cap = info.get("marketCap")
    per = info.get("trailingPE")
    pbr = info.get("priceToBook")
    psr = info.get("priceToSalesTrailing12Months")
    div_yield = info.get("dividendYield")
    div_per_share = info.get("dividendRate")
    payout_ratio = info.get("payoutRatio")
    eps = info.get("trailingEps")
    bps = info.get("bookValue")

    return {
        "price": price,
        "market_cap": market_cap,
        "per": per,
        "pbr": pbr,
        "psr": psr,
        "dividend_yield": round(div_yield, 4) if div_yield is not None else None,
        "dividend_per_share": div_per_share,
        "dividend_payout_ratio": round(payout_ratio * 100, 4) if payout_ratio is not None else None,
        "eps": eps,
        "bps": bps,
    }


def run_fetch_prices(sector: str | None = None, sec_code: str | None = None) -> None:
    conn = _get_db()
    today = date.today().isoformat()

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
    logger.info(f"株価取得対象: {total} 社")

    ok = skip = 0
    for i, row in enumerate(rows):
        edinet_code = row["edinet_code"]
        code = row["sec_code"]
        name = row["company_name"]

        logger.info(f"[{i+1}/{total}] {name} ({code}) ...")
        data = _fetch_price(code)
        if data is None:
            logger.warning(f"  スキップ: {name} ({code})")
            skip += 1
            time.sleep(0.5)
            continue

        conn.execute("""
            INSERT INTO prices (
                edinet_code, fetched_at,
                price, market_cap, per, pbr, psr,
                dividend_yield, dividend_per_share, dividend_payout_ratio,
                eps, bps
            ) VALUES (
                :edinet_code, :fetched_at,
                :price, :market_cap, :per, :pbr, :psr,
                :dividend_yield, :dividend_per_share, :dividend_payout_ratio,
                :eps, :bps
            )
            ON CONFLICT(edinet_code, fetched_at) DO UPDATE SET
                price = excluded.price,
                market_cap = excluded.market_cap,
                per = excluded.per,
                pbr = excluded.pbr,
                psr = excluded.psr,
                dividend_yield = excluded.dividend_yield,
                dividend_per_share = excluded.dividend_per_share,
                dividend_payout_ratio = excluded.dividend_payout_ratio,
                eps = excluded.eps,
                bps = excluded.bps
        """, {"edinet_code": edinet_code, "fetched_at": today, **data})
        conn.commit()
        ok += 1
        time.sleep(0.5)

    conn.close()
    logger.info(f"完了: 取得 {ok} 件、スキップ {skip} 件")

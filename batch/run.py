"""バッチ実行エントリーポイント"""
import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")
PROGRESS_FILE = Path(DB_PATH).parent / "batch_progress.json"


def write_progress(data: dict) -> None:
    with open(PROGRESS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ------------------------------------------------------------------ #
# init-companies                                                       #
# ------------------------------------------------------------------ #

def run_init_companies() -> None:
    from edinet import fetch_company_list

    logger.info("EDINETコードリストを取得中...")
    companies = fetch_company_list()
    logger.info(f"取得件数: {len(companies)}")

    conn = get_db()
    for c in companies:
        conn.execute("""
            INSERT INTO companies (edinet_code, sec_code, company_name, sector, market, updated_at)
            VALUES (:edinet_code, :sec_code, :company_name, :sector, :market, CURRENT_TIMESTAMP)
            ON CONFLICT(edinet_code) DO UPDATE SET
                sec_code     = excluded.sec_code,
                company_name = excluded.company_name,
                sector       = excluded.sector,
                market       = excluded.market,
                updated_at   = CURRENT_TIMESTAMP
        """, c)
    conn.commit()
    conn.close()
    logger.info(f"companies テーブルに {len(companies)} 件を upsert しました。")


# ------------------------------------------------------------------ #
# XBRL 取得 → DB 保存                                                  #
# ------------------------------------------------------------------ #

def upsert_financials(conn: sqlite3.Connection, edinet_code: str, doc: dict, financials: dict) -> None:
    from xbrl_parser import compute_derived

    period_end = doc.get("periodEnd", "")
    period_start = doc.get("periodStart", "")
    if not period_end:
        return

    fiscal_year = int(period_end[:4]) if period_end else None
    derived = compute_derived(financials)

    conn.execute("""
        INSERT INTO financials (
            edinet_code, period_start, period_end, fiscal_year, quarter, doc_id,
            revenue, gross_profit, operating_income, ordinary_income, net_income,
            total_assets, current_assets, non_current_assets, net_assets, total_liabilities,
            current_liabilities, non_current_liabilities, shareholders_equity, goodwill,
            accounts_receivable, inventory,
            operating_cf, investing_cf, financing_cf,
            free_cf, net_cash, net_cash_approximate,
            gross_profit_margin, operating_profit_margin, ordinary_profit_margin, net_profit_margin,
            roe, roa, asset_turnover, receivable_turnover,
            equity_ratio, debt_to_equity_ratio, current_ratio, quick_ratio, fixed_assets_ratio,
            cash_and_deposits, securities, investment_securities,
            short_term_borrowings, long_term_borrowings, bonds_payable, commercial_papers
        ) VALUES (
            :edinet_code, :period_start, :period_end, :fiscal_year, :quarter, :doc_id,
            :revenue, :gross_profit, :operating_income, :ordinary_income, :net_income,
            :total_assets, :current_assets, :non_current_assets, :net_assets, :total_liabilities,
            :current_liabilities, :non_current_liabilities, :shareholders_equity, :goodwill,
            :accounts_receivable, :inventory,
            :operating_cf, :investing_cf, :financing_cf,
            :free_cf, :net_cash, :net_cash_approximate,
            :gross_profit_margin, :operating_profit_margin, :ordinary_profit_margin, :net_profit_margin,
            :roe, :roa, :asset_turnover, :receivable_turnover,
            :equity_ratio, :debt_to_equity_ratio, :current_ratio, :quick_ratio, :fixed_assets_ratio,
            :cash_and_deposits, :securities, :investment_securities,
            :short_term_borrowings, :long_term_borrowings, :bonds_payable, :commercial_papers
        )
        ON CONFLICT(edinet_code, period_end, quarter) DO UPDATE SET
            doc_id = excluded.doc_id,
            revenue = excluded.revenue,
            gross_profit = excluded.gross_profit,
            operating_income = excluded.operating_income,
            ordinary_income = excluded.ordinary_income,
            net_income = excluded.net_income,
            total_assets = excluded.total_assets,
            current_assets = excluded.current_assets,
            non_current_assets = excluded.non_current_assets,
            net_assets = excluded.net_assets,
            total_liabilities = excluded.total_liabilities,
            current_liabilities = excluded.current_liabilities,
            non_current_liabilities = excluded.non_current_liabilities,
            shareholders_equity = excluded.shareholders_equity,
            goodwill = excluded.goodwill,
            accounts_receivable = excluded.accounts_receivable,
            inventory = excluded.inventory,
            operating_cf = excluded.operating_cf,
            investing_cf = excluded.investing_cf,
            financing_cf = excluded.financing_cf,
            free_cf = excluded.free_cf,
            net_cash = excluded.net_cash,
            net_cash_approximate = excluded.net_cash_approximate,
            gross_profit_margin = excluded.gross_profit_margin,
            operating_profit_margin = excluded.operating_profit_margin,
            ordinary_profit_margin = excluded.ordinary_profit_margin,
            net_profit_margin = excluded.net_profit_margin,
            roe = excluded.roe, roa = excluded.roa,
            asset_turnover = excluded.asset_turnover,
            receivable_turnover = excluded.receivable_turnover,
            equity_ratio = excluded.equity_ratio,
            debt_to_equity_ratio = excluded.debt_to_equity_ratio,
            current_ratio = excluded.current_ratio,
            quick_ratio = excluded.quick_ratio,
            fixed_assets_ratio = excluded.fixed_assets_ratio,
            cash_and_deposits = excluded.cash_and_deposits,
            securities = excluded.securities,
            investment_securities = excluded.investment_securities,
            short_term_borrowings = excluded.short_term_borrowings,
            long_term_borrowings = excluded.long_term_borrowings,
            bonds_payable = excluded.bonds_payable,
            commercial_papers = excluded.commercial_papers
    """, {
        **derived,
        "edinet_code": edinet_code,
        "period_start": period_start,
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "quarter": None,
        "doc_id": doc.get("docID"),
    })


# ------------------------------------------------------------------ #
# ギャップ検出                                                          #
# ------------------------------------------------------------------ #

def detect_fetch_range(conn: sqlite3.Connection) -> tuple[date, date]:
    row = conn.execute(
        "SELECT finished_at FROM batch_log WHERE status='completed' ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()

    today = date.today()
    if row is None:
        return today - timedelta(days=365 * 5), today

    last_date = date.fromisoformat(row["finished_at"][:10])
    return last_date + timedelta(days=1), today


# ------------------------------------------------------------------ #
# update / initial バッチ                                              #
# ------------------------------------------------------------------ #

def run_update(
    mode: str,
    sector: str | None,
    sec_code: str | None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> None:
    import time
    from edinet import download_xbrl_zip, fetch_document_list_range
    from xbrl_parser import parse_xbrl_zip

    conn = get_db()

    # 対象企業を絞り込む
    if sec_code:
        companies = conn.execute(
            "SELECT edinet_code, sec_code, company_name FROM companies WHERE sec_code = ?", [sec_code]
        ).fetchall()
    elif sector:
        companies = conn.execute(
            "SELECT edinet_code, sec_code, company_name FROM companies WHERE sector = ?", [sector]
        ).fetchall()
    else:
        companies = conn.execute(
            "SELECT edinet_code, sec_code, company_name FROM companies"
        ).fetchall()

    edinet_codes = {c["edinet_code"] for c in companies}
    logger.info(f"対象企業: {len(edinet_codes)} 社")

    # 取得期間の決定
    if from_date and to_date:
        fetch_from, fetch_to = from_date, to_date
    elif mode == "initial":
        fetch_from = date.today() - timedelta(days=365 * 5)
        fetch_to = date.today()
    else:
        fetch_from, fetch_to = detect_fetch_range(conn)

    logger.info(f"取得期間: {fetch_from} 〜 {fetch_to}")

    # バッチ前にバックアップ
    try:
        from backup import backup_local, backup_to_s3
        backup_path = backup_local(tag="pre_batch")
        backup_to_s3(backup_path)
    except Exception as e:
        logger.warning(f"バックアップ失敗（続行）: {e}")

    # バッチログ開始
    cur = conn.execute(
        "INSERT INTO batch_log (started_at, status, sector, total) VALUES (?, 'running', ?, ?)",
        [datetime.now().isoformat(), sector, len(edinet_codes)],
    )
    batch_id = cur.lastrowid
    conn.commit()

    # 書類一覧を取得
    logger.info("書類一覧を取得中...")
    all_docs = fetch_document_list_range(fetch_from, fetch_to)
    # 対象企業のみに絞り込む
    target_docs = [d for d in all_docs if d.get("edinetCode") in edinet_codes]
    logger.info(f"対象書類: {len(target_docs)} 件")

    processed = errors = 0
    total = len(target_docs)

    for i, doc in enumerate(target_docs):
        edinet_code = doc["edinetCode"]
        doc_id = doc["docID"]
        company_name = next(
            (c["company_name"] for c in companies if c["edinet_code"] == edinet_code), edinet_code
        )

        write_progress({
            "status": "running",
            "progress": f"{i}/{total}",
            "current": company_name,
            "sector": sector,
            "started_at": datetime.now().isoformat(),
        })

        try:
            logger.info(f"[{i+1}/{total}] {company_name} ({doc_id}) ...")
            zip_bytes = download_xbrl_zip(doc_id)
            financials = parse_xbrl_zip(zip_bytes)
            if financials is None:
                raise ValueError("XBRL 解析失敗")
            upsert_financials(conn, edinet_code, doc, financials)
            conn.commit()
            processed += 1
        except Exception as e:
            logger.warning(f"  スキップ: {company_name} ({doc_id}) - {e}")
            errors += 1

        # バッチログ更新
        conn.execute(
            "UPDATE batch_log SET processed=?, errors=? WHERE id=?",
            [processed, errors, batch_id],
        )
        conn.commit()
        time.sleep(1)

    # バッチ完了
    conn.execute(
        "UPDATE batch_log SET finished_at=?, status='completed', processed=?, errors=?, message=? WHERE id=?",
        [datetime.now().isoformat(), processed, errors, f"処理: {processed}, エラー: {errors}", batch_id],
    )
    conn.commit()
    conn.close()

    PROGRESS_FILE.unlink(missing_ok=True)
    logger.info(f"完了: 処理 {processed} 件、エラー {errors} 件")


# ------------------------------------------------------------------ #
# メイン                                                               #
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["init-companies", "initial", "update", "fetch-prices", "fetch-quarterly"], default="update")
    parser.add_argument("--sector", default=None)
    parser.add_argument("--sec-code", default=None)
    parser.add_argument("--from-date", default=None, help="取得開始日 YYYY-MM-DD (テスト用)")
    parser.add_argument("--to-date", default=None, help="取得終了日 YYYY-MM-DD (テスト用)")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date   = date.fromisoformat(args.to_date)   if args.to_date   else None

    if args.mode == "init-companies":
        run_init_companies()
    elif args.mode == "fetch-prices":
        from price_fetcher import run_fetch_prices
        run_fetch_prices(args.sector, args.sec_code)
    elif args.mode == "fetch-quarterly":
        from quarterly_fetcher import run_fetch_quarterly
        run_fetch_quarterly(args.sector, args.sec_code)
    else:
        run_update(args.mode, args.sector, args.sec_code, from_date, to_date)


if __name__ == "__main__":
    main()

"""セクター別DBデータ取得状況レポートを tmp/db_status.md に出力する"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")
OUTPUT_PATH = os.environ.get("STATUS_OUTPUT", "/workspace/tmp/db_status.md")


def generate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM companies")
    total_companies = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM financials")
    total_financials = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM prices")
    total_prices = cur.fetchone()[0]

    cur.execute("SELECT MAX(created_at) FROM financials")
    last_financial = cur.fetchone()[0] or "—"

    cur.execute("SELECT MAX(updated_at) FROM prices")
    last_price = cur.fetchone()[0] or "—"

    cur.execute("""
        SELECT
            c.sector,
            COUNT(DISTINCT c.edinet_code)                       AS total,
            COUNT(DISTINCT f.edinet_code)                       AS fin_cos,
            COUNT(DISTINCT p.edinet_code)                       AS price_cos,
            ROUND(COUNT(DISTINCT f.edinet_code) * 100.0 / COUNT(DISTINCT c.edinet_code), 0) AS fin_pct,
            ROUND(COUNT(DISTINCT p.edinet_code) * 100.0 / COUNT(DISTINCT c.edinet_code), 0) AS price_pct
        FROM companies c
        LEFT JOIN financials f ON c.edinet_code = f.edinet_code
        LEFT JOIN prices     p ON c.edinet_code = p.edinet_code
        GROUP BY c.sector
        ORDER BY total DESC
    """)
    rows = cur.fetchall()
    conn.close()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# DB データ取得状況",
        f"",
        f"更新日時: {now}",
        f"",
        f"## サマリー",
        f"",
        f"| 項目 | 件数 |",
        f"|------|------|",
        f"| 企業数 | {total_companies:,} 社 |",
        f"| 財務データ | {total_financials:,} 件 |",
        f"| 株価データ | {total_prices:,} 件 |",
        f"| 財務データ 最終取得 | {last_financial} |",
        f"| 株価データ 最終取得 | {last_price} |",
        f"",
        f"## セクター別カバレッジ",
        f"",
        f"| セクター | 企業数 | 財務取得 | 財務% | 株価取得 | 株価% |",
        f"|----------|--------|----------|-------|----------|-------|",
    ]

    for sector, total, fin_cos, price_cos, fin_pct, price_pct in rows:
        fin_bar = "✅" if fin_pct == 100 else ("🔶" if fin_pct > 0 else "❌")
        price_bar = "✅" if price_pct == 100 else ("🔶" if price_pct > 0 else "❌")
        lines.append(
            f"| {sector} | {total} | {fin_bar} {fin_cos} | {int(fin_pct)}% | {price_bar} {price_cos} | {int(price_pct)}% |"
        )

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_PATH).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[db-status] {OUTPUT_PATH} を更新しました ({now})")


if __name__ == "__main__":
    generate()

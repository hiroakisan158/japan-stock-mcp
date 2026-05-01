"""セクター別DBデータ取得状況レポートを tmp/db_status.md に出力する"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/stocks.db")
OUTPUT_PATH = os.environ.get("STATUS_OUTPUT", "/workspace/tmp/db_status.md")


def _icon(cos, total):
    if total == 0:
        return "—"
    if cos == total:
        return "✅"
    if cos > 0:
        return "🔶"
    return "❌"


def generate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM companies")
    total_companies = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM financials WHERE source='edinet'")
    total_edinet = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM financials WHERE source='jquants'")
    total_jquants = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM prices")
    total_prices = cur.fetchone()[0]

    cur.execute("SELECT MAX(created_at) FROM financials WHERE source='edinet'")
    last_edinet = cur.fetchone()[0] or "—"

    cur.execute("SELECT MAX(fetched_at) FROM prices")
    last_price = cur.fetchone()[0] or "—"

    cur.execute("""
        SELECT
            c.sector,
            COUNT(DISTINCT c.edinet_code)                                        AS total,
            COUNT(DISTINCT CASE WHEN f.source='edinet'  THEN f.edinet_code END)  AS edinet_cos,
            COUNT(CASE WHEN f.source='edinet'  THEN 1 END)                       AS edinet_cnt,
            COUNT(DISTINCT CASE WHEN f.source='jquants' THEN f.edinet_code END)  AS jq_cos,
            COUNT(CASE WHEN f.source='jquants' THEN 1 END)                       AS jq_cnt,
            COUNT(DISTINCT p.edinet_code)                                        AS price_cos
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
        "# DB データ取得状況",
        "",
        f"更新日時: {now}",
        "",
        "## サマリー",
        "",
        "| 項目 | 件数 |",
        "|------|------|",
        f"| 企業数 | {total_companies:,} 社 |",
        f"| EDINET 年次(FY) | {total_edinet:,} 件 |",
        f"| J-Quants 四半期(Q) | {total_jquants:,} 件 |",
        f"| 株価データ | {total_prices:,} 件 |",
        f"| EDINET 最終取得 | {last_edinet} |",
        f"| 株価 最終取得 | {last_price} |",
        "",
        "## セクター別カバレッジ",
        "",
        "| セクター | 企業数 | EDINET(FY)<br>社数/件数 | J-Quants(Q)<br>社数/件数 | 株価<br>社数 |",
        "|----------|--------|------------------------|--------------------------|-------------|",
    ]

    for sector, total, edinet_cos, edinet_cnt, jq_cos, jq_cnt, price_cos in rows:
        e_icon = _icon(edinet_cos, total)
        j_icon = _icon(jq_cos, total)
        p_icon = _icon(price_cos, total)
        lines.append(
            f"| {sector} | {total} "
            f"| {e_icon} {edinet_cos}社 {edinet_cnt}件 "
            f"| {j_icon} {jq_cos}社 {jq_cnt}件 "
            f"| {p_icon} {price_cos}社 |"
        )

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_PATH).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[db-status] {OUTPUT_PATH} を更新しました ({now})")


if __name__ == "__main__":
    generate()

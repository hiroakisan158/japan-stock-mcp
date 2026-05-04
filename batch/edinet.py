"""EDINET API クライアント"""
import csv
import io
import os
import time
import zipfile
from datetime import date, timedelta

import requests

API_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"
CODELIST_URL = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
API_KEY = os.environ.get("EDINET_API_KEY", "")


def _session() -> requests.Session:
    s = requests.Session()
    s.params = {"Subscription-Key": API_KEY}  # type: ignore
    return s


def fetch_company_list() -> list[dict]:
    """EDINETコードリスト CSV を取得して企業情報のリストを返す"""
    resp = requests.get(CODELIST_URL, timeout=30)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        raw = zf.read(csv_name).decode("cp932")

    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)

    # 1行目: ダウンロード日・件数メタ、2行目: ヘッダー
    header = rows[1]
    col = {name.strip(): i for i, name in enumerate(header)}

    companies = []
    for row in rows[2:]:
        if not row or not row[col["ＥＤＩＮＥＴコード"]].strip():
            continue
        sec_code_raw = row[col["証券コード"]].strip()
        if not sec_code_raw:
            continue
        # EDINET は4桁コードを末尾に0を付けた5桁で格納している (例: 7974 → 79740)
        sec_code = sec_code_raw[:-1] if len(sec_code_raw) == 5 and sec_code_raw.endswith("0") else sec_code_raw
        companies.append({
            "edinet_code":  row[col["ＥＤＩＮＥＴコード"]].strip(),
            "sec_code":     sec_code,
            "company_name": row[col["提出者名"]].strip(),
            "sector":       row[col["提出者業種"]].strip() or None,
            "market":       row[col["上場区分"]].strip() or None,
        })

    return companies


def fetch_document_list(target_date: date) -> list[dict]:
    """指定日の書類一覧を取得する（docTypeCode=120: 有価証券報告書）"""
    session = _session()
    resp = session.get(
        f"{API_BASE}/documents.json",
        params={"date": target_date.isoformat(), "type": 2},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if data["metadata"]["status"] != "200":
        return []

    results = data.get("results", [])
    if not results:
        return []

    return [
        doc for doc in results
        if doc.get("docTypeCode") == "120"  # 有価証券報告書のみ
    ]


def fetch_document_list_range(start: date, end: date) -> list[dict]:
    """期間内の有価証券報告書の書類一覧を取得する"""
    import logging
    logger = logging.getLogger(__name__)

    all_docs: list[dict] = []
    current = start
    total_days = (end - start).days + 1
    day_num = 0

    while current <= end:
        day_num += 1
        try:
            docs = fetch_document_list(current)
            all_docs.extend(docs)
            if docs:
                logger.info(f"  {current} ({day_num}/{total_days}日) +{len(docs)}件 累計{len(all_docs)}件")
            elif day_num % 30 == 0:
                logger.info(f"  {current} ({day_num}/{total_days}日) 累計{len(all_docs)}件")
        except Exception as e:
            logger.warning(f"  警告: {current} の書類一覧取得失敗: {e}")
        time.sleep(1)
        current += timedelta(days=1)
    return all_docs


def download_xbrl_zip(doc_id: str) -> bytes:
    """書類の XBRL ZIP をダウンロードして bytes を返す"""
    session = _session()
    resp = session.get(
        f"{API_BASE}/documents/{doc_id}",
        params={"type": 1},
        timeout=60,
        stream=True,
    )
    resp.raise_for_status()
    return resp.content


def download_pdf(doc_id: str) -> bytes:
    """書類の PDF をダウンロードして bytes を返す（有報 PDF ツール用）"""
    session = _session()
    resp = session.get(
        f"{API_BASE}/documents/{doc_id}",
        params={"type": 2},
        timeout=120,
        stream=True,
    )
    resp.raise_for_status()
    return resp.content

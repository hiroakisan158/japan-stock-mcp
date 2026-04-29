"""有価証券報告書 PDF ツール（EDINET オンデマンド取得）"""
from __future__ import annotations
import base64
import io
import os
import time
import zipfile
from datetime import date, timedelta
from typing import Optional

import fitz  # pymupdf
import requests
from mcp.server.fastmcp import FastMCP
import db

EDINET_API_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"
EDINET_API_KEY = os.environ.get("EDINET_API_KEY", "")

SECTION_KEYWORDS: dict[str, list[str]] = {
    "事業内容":     ["事業の内容", "事業内容"],
    "リスク":       ["事業等のリスク", "リスク要因"],
    "経営方針":     ["経営方針", "経営戦略", "中期経営計画"],
    "財務状況":     ["財政状態及び経営成績", "財務状況", "経営成績等の状況"],
    "設備":         ["設備の状況", "主要な設備"],
    "株式":         ["株式等の状況", "株主の状況", "大株主"],
    "役員":         ["役員の状況", "取締役"],
    "コーポレートガバナンス": ["コーポレート・ガバナンスの状況"],
    "関連当事者":   ["関連当事者の取引"],
    "注記":         ["重要な会計方針", "注記事項"],
}


def _edinet_session() -> requests.Session:
    s = requests.Session()
    s.params = {"Subscription-Key": EDINET_API_KEY}  # type: ignore
    return s


def _get_edinet_code(sec_code: str) -> Optional[str]:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT edinet_code FROM companies WHERE sec_code = ?", [sec_code]
        ).fetchone()
    return row["edinet_code"] if row else None


def _find_latest_annual_report(edinet_code: str) -> Optional[dict]:
    """最新の有報 doc_id を取得。
    DB に doc_id が保存されていればそれを返す。なければ EDINET API を直近1年分さかのぼる。
    """
    # まず DB から doc_id を取得（高速パス）
    try:
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT doc_id, period_end FROM financials WHERE edinet_code = ? AND quarter IS NULL ORDER BY period_end DESC LIMIT 1",
                [edinet_code],
            ).fetchone()
        if row and row["doc_id"]:
            return {"docID": row["doc_id"], "periodEnd": row["period_end"], "edinetCode": edinet_code, "filerName": ""}
    except Exception:
        pass

    # DB にない場合は API を直近1年分さかのぼる（低速パス）
    session = _edinet_session()
    today = date.today()
    for delta_days in range(0, 365):
        target = today - timedelta(days=delta_days)
        try:
            resp = session.get(
                f"{EDINET_API_BASE}/documents.json",
                params={"date": target.isoformat(), "type": 2},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data["metadata"]["status"] != "200":
                continue
            for doc in data.get("results", []):
                if doc.get("edinetCode") == edinet_code and doc.get("docTypeCode") == "120":
                    return doc
        except Exception:
            pass
        time.sleep(0.3)
    return None


def _download_pdf(doc_id: str) -> bytes:
    session = _edinet_session()
    resp = session.get(
        f"{EDINET_API_BASE}/documents/{doc_id}",
        params={"type": 2},
        timeout=120,
        stream=True,
    )
    resp.raise_for_status()
    return resp.content


def _normalize_section(section: str) -> list[str]:
    for canonical, aliases in SECTION_KEYWORDS.items():
        if section in aliases or section == canonical:
            return SECTION_KEYWORDS[canonical]
    return [section]


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_annual_report_section(
        sec_code: str,
        section: str,
        fiscal_year: int | None = None,
    ) -> dict:
        """有価証券報告書の指定セクションをテキストで取得する。
        sec_code: 証券コード（例: "7974"）
        section: セクション名（例: "事業内容", "リスク", "経営方針", "財務状況", "役員" など）
        fiscal_year: 決算年度（省略時は最新）
        has_table が true のページは get_annual_report_pages で PDF を直接参照できる。
        """
        edinet_code = _get_edinet_code(sec_code)
        if not edinet_code:
            return {"error": f"証券コード {sec_code} が見つかりません"}

        doc_info = _find_latest_annual_report(edinet_code)
        if not doc_info:
            return {"error": f"{sec_code} の有価証券報告書が見つかりません"}

        try:
            pdf_bytes = _download_pdf(doc_info["docID"])
        except Exception as e:
            return {"error": f"PDF ダウンロード失敗: {e}"}

        keywords = _normalize_section(section)

        try:
            pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            return {"error": f"PDF 解析失敗: {e}"}

        matched_pages: list[int] = []
        for page_num in range(len(pdf)):
            page = pdf[page_num]
            text = page.get_text()
            if any(kw in text for kw in keywords):
                matched_pages.append(page_num + 1)  # 1-indexed

        if not matched_pages:
            pdf.close()
            return {
                "doc_id": doc_info["docID"],
                "company_name": doc_info.get("filerName", ""),
                "period_end": doc_info.get("periodEnd", ""),
                "section": section,
                "text": "",
                "pages": [],
                "has_table": False,
                "message": f"セクション「{section}」が見つかりませんでした",
            }

        # 最初のマッチページから最大5ページ分テキストを抽出
        text_parts: list[str] = []
        has_table = False
        extract_pages = matched_pages[:5]
        for pn in extract_pages:
            page = pdf[pn - 1]
            text_parts.append(page.get_text())
            if page.find_tables().tables:
                has_table = True

        pdf.close()

        return {
            "doc_id": doc_info["docID"],
            "company_name": doc_info.get("filerName", ""),
            "period_end": doc_info.get("periodEnd", ""),
            "section": section,
            "text": "\n\n---\n\n".join(text_parts),
            "pages": extract_pages,
            "has_table": has_table,
            "total_matched_pages": len(matched_pages),
        }

    @mcp.tool()
    def get_annual_report_pages(
        sec_code: str,
        pages: list[int],
    ) -> dict:
        """有価証券報告書の指定ページを PDF（base64）で返す。
        sec_code: 証券コード（例: "7974"）
        pages: ページ番号のリスト（1-indexed）、最大10ページまで
        表が含まれるページや図を参照したい場合に使用する。
        """
        if len(pages) > 10:
            return {"error": "一度に取得できるページ数は最大10です"}

        edinet_code = _get_edinet_code(sec_code)
        if not edinet_code:
            return {"error": f"証券コード {sec_code} が見つかりません"}

        doc_info = _find_latest_annual_report(edinet_code)
        if not doc_info:
            return {"error": f"{sec_code} の有価証券報告書が見つかりません"}

        try:
            pdf_bytes = _download_pdf(doc_info["docID"])
        except Exception as e:
            return {"error": f"PDF ダウンロード失敗: {e}"}

        try:
            src = fitz.open(stream=pdf_bytes, filetype="pdf")
            dst = fitz.open()
            total = len(src)
            valid_pages = [p for p in pages if 1 <= p <= total]
            for pn in valid_pages:
                dst.insert_pdf(src, from_page=pn - 1, to_page=pn - 1)
            out_bytes = dst.write()
            dst.close()
            src.close()
        except Exception as e:
            return {"error": f"PDF 加工失敗: {e}"}

        return {
            "doc_id": doc_info["docID"],
            "company_name": doc_info.get("filerName", ""),
            "period_end": doc_info.get("periodEnd", ""),
            "pages": valid_pages,
            "pdf_base64": base64.b64encode(out_bytes).decode(),
            "total_pages": total,
        }

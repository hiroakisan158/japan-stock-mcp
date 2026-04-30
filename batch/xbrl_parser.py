"""XBRL 解析 → 財務数値抽出"""
import io
import zipfile
from typing import Optional

from lxml import etree

# コンテキスト優先順（連結優先、なければ個別）
DURATION_CONTEXTS = [
    "CurrentYearDuration",
    "CurrentYearDuration_NonConsolidatedMember",
]
INSTANT_CONTEXTS = [
    "CurrentYearInstant",
    "CurrentYearInstant_NonConsolidatedMember",
]

# タグ候補（先勝ち）
TAG_CANDIDATES: dict[str, list[str]] = {
    # IFRSタグを先に列挙（IFRS企業: CurrentYearDuration_NonConsolidatedMember の個別値より優先）
    "revenue": [
        "SalesAndFinancialServicesRevenueIFRS",
        "SalesRevenuesIFRS",
        "TotalNetRevenuesIFRS",
        "NetSalesIFRS",
        "RevenueIFRS",
        "NetSales",
        "Revenue",
        "NetSalesSummaryOfBusinessResults",
    ],
    "gross_profit": [
        "GrossProfitIFRS",
        "GrossProfit",
        "GrossProfitOnSales",
    ],
    "cost_of_sales": [
        "CostOfSalesIFRS",
        "CostOfSales",
        "CostOfGoodsSold",
    ],
    "operating_income": [
        "OperatingProfitLossIFRS",
        "OperatingProfitLossIFRSSummaryOfBusinessResults",
        "OperatingIncome",
        "OperatingIncomeSummaryOfBusinessResults",
    ],
    "ordinary_income": [
        "OrdinaryIncome",
        "OrdinaryIncomeSummaryOfBusinessResults",
    ],
    "net_income": [
        "ProfitLossAttributableToOwnersOfParentIFRS",
        "ProfitAttributableToOwnersOfParentIFRS",
        "ProfitLoss",
        "ProfitLossAttributableToOwnersOfParent",
        "ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults",
        "NetIncomeSummaryOfBusinessResults",
    ],
    "total_assets": [
        "AssetsIFRS",
        "TotalAssets",
        "TotalAssetsSummaryOfBusinessResults",
    ],
    "current_assets": [
        "CurrentAssetsIFRS",
        "CurrentAssets",
    ],
    "non_current_assets": [
        "NonCurrentAssetsIFRS",
        "NoncurrentAssetsIFRS",
        "NoncurrentAssets",
        "FixedAssets",
    ],
    "net_assets": [
        "EquityIFRS",
        "TotalEquityIFRS",
        "NetAssets",
        "NetAssetsSummaryOfBusinessResults",
    ],
    "total_liabilities": [
        "LiabilitiesIFRS",
        "TotalLiabilitiesIFRS",
        "TotalLiabilities",
    ],
    "current_liabilities": [
        "TotalCurrentLiabilitiesIFRS",
        "CurrentLiabilitiesIFRS",
        "CurrentLiabilities",
    ],
    "non_current_liabilities": [
        "TotalNonCurrentLiabilitiesIFRS",
        "NoncurrentLiabilitiesIFRS",
        "NoncurrentLiabilities",
        "LongTermLiabilities",
    ],
    "shareholders_equity": [
        "EquityAttributableToOwnersOfParentIFRS",
        "TotalEquityAttributableToOwnersOfParentIFRS",
        "ShareholdersEquity",
        "EquityAttributableToOwnersOfParent",
    ],
    "goodwill": [
        "GoodwillIFRS",
        "Goodwill",
    ],
    "accounts_receivable": [
        "TradeAndOtherReceivablesIFRS",
        "AccountsReceivableTrade",
        "AccountsReceivableTradeAndContractAssets",
        "TradeAndOtherReceivables",
        "NotesAndAccountsReceivableTrade",
        "NotesAndAccountsReceivableTradeAndContractAssets",
    ],
    "inventory": [
        "InventoriesCAIFRS",
        "InventoriesIFRS",
        "Inventories",
        "MerchandiseAndFinishedGoods",
        "merchandise",
    ],
    "operating_cf": [
        "NetCashProvidedByUsedInOperatingActivitiesIFRS",
        "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults",
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults",
    ],
    "investing_cf": [
        "NetCashProvidedByUsedInInvestingActivitiesIFRS",
        "CashFlowsFromUsedInInvestingActivitiesIFRSSummaryOfBusinessResults",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesSummaryOfBusinessResults",
    ],
    "financing_cf": [
        "NetCashProvidedByUsedInFinancingActivitiesIFRS",
        "CashFlowsFromUsedInFinancingActivitiesIFRSSummaryOfBusinessResults",
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesSummaryOfBusinessResults",
    ],
    # ネットキャッシュ内訳
    "cash_and_deposits": [
        "CashAndCashEquivalentsIFRS",
        "CashAndCashEquivalents",
        "CashAndDeposits",
    ],
    "securities": ["Securities"],
    "investment_securities": [
        "OtherFinancialAssetsNoncurrentIFRS",
        "InvestmentSecurities",
    ],
    "short_term_borrowings": [
        "ShortTermBorrowingsIFRS",
        "ShortTermBorrowings",
        "ShortTermLoansPayable",
    ],
    "long_term_borrowings": [
        "LongTermBorrowingsIFRS",
        "LongTermBorrowings",
        "LongTermLoansPayable",
    ],
    "bonds_payable": [
        "BondsPayableIFRS",
        "Bonds",
        "BondsPayable",
    ],
    "commercial_papers": ["CommercialPapers"],
}

# BS 項目（Duration ではなく Instant コンテキストを使う）
INSTANT_METRICS = {
    "total_assets", "current_assets", "non_current_assets", "net_assets",
    "total_liabilities", "current_liabilities", "non_current_liabilities",
    "shareholders_equity", "goodwill", "accounts_receivable", "inventory",
    "cash_and_deposits", "securities", "investment_securities",
    "short_term_borrowings", "long_term_borrowings", "bonds_payable", "commercial_papers",
}


def _build_index(root: etree._Element) -> dict[tuple[str, str], int]:
    """(local_tag, contextRef) → 数値 のインデックスを構築"""
    index: dict[tuple[str, str], int] = {}
    for elem in root.iter():
        text = elem.text
        if not text:
            continue
        val_str = text.strip().lstrip("-")
        if not val_str.isdigit():
            continue
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        ctx = elem.get("contextRef", "")
        # 符号付きで保存（マイナスを保持）
        signed = -int(val_str) if text.strip().startswith("-") else int(val_str)
        key = (local, ctx)
        if key not in index:
            index[key] = signed
    return index


def _get_value(
    index: dict[tuple[str, str], int],
    metric: str,
) -> Optional[int]:
    """メトリクス名からタグ候補×コンテキスト優先順で値を取得"""
    candidates = TAG_CANDIDATES.get(metric, [])
    contexts = INSTANT_CONTEXTS if metric in INSTANT_METRICS else DURATION_CONTEXTS
    for tag in candidates:
        for ctx in contexts:
            val = index.get((tag, ctx))
            if val is not None:
                return val
    return None


def parse_xbrl_zip(zip_bytes: bytes) -> Optional[dict]:
    """XBRL ZIP バイト列を受け取り、財務数値の dict を返す。
    失敗時は None を返す。"""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xbrl_names = [
                n for n in zf.namelist()
                if n.endswith(".xbrl") and "PublicDoc" in n and "jpcrp030000-asr" in n
            ]
            if not xbrl_names:
                # フォールバック: PublicDoc 内の最初の XBRL
                xbrl_names = [
                    n for n in zf.namelist()
                    if n.endswith(".xbrl") and "PublicDoc" in n
                ]
            if not xbrl_names:
                return None
            xbrl_bytes = zf.read(xbrl_names[0])
    except Exception:
        return None

    try:
        root = etree.fromstring(xbrl_bytes)
    except Exception:
        return None

    index = _build_index(root)
    result: dict[str, Optional[int]] = {}

    for metric in TAG_CANDIDATES:
        result[metric] = _get_value(index, metric)

    # gross_profit がなければ売上高 − 売上原価 で計算
    if result.get("gross_profit") is None:
        rev = result.get("revenue")
        cos = result.get("cost_of_sales")
        if rev is not None and cos is not None:
            result["gross_profit"] = rev - cos

    return result


def compute_derived(r: dict) -> dict:
    """財務数値から派生指標を計算して追記した dict を返す"""

    def safe_div(a, b) -> Optional[float]:
        if a is None or b is None or b == 0:
            return None
        return a / b

    def pct(a, b) -> Optional[float]:
        v = safe_div(a, b)
        return round(v * 100, 4) if v is not None else None

    d = dict(r)

    rev   = r.get("revenue")
    op    = r.get("operating_income")
    ord_  = r.get("ordinary_income")
    net   = r.get("net_income")
    eq    = r.get("shareholders_equity")
    ta    = r.get("total_assets")
    ar    = r.get("accounts_receivable")
    ca    = r.get("current_assets")
    cl    = r.get("current_liabilities")
    fa    = r.get("non_current_assets")
    tl    = r.get("total_liabilities")
    inv   = r.get("inventory")
    op_cf = r.get("operating_cf")
    inv_cf = r.get("investing_cf")
    gp    = r.get("gross_profit")

    d["gross_profit_margin"]     = pct(gp, rev)
    d["operating_profit_margin"] = pct(op, rev)
    d["ordinary_profit_margin"]  = pct(ord_, rev)
    d["net_profit_margin"]       = pct(net, rev)
    d["roe"]                     = pct(net, eq)
    d["roa"]                     = pct(net, ta)
    d["asset_turnover"]          = round(rev / ta, 4) if rev and ta else None
    d["receivable_turnover"]     = round(rev / ar, 4) if rev and ar else None
    d["equity_ratio"]            = pct(eq, ta)
    d["debt_to_equity_ratio"]    = pct(tl, eq)
    d["current_ratio"]           = pct(ca, cl)
    d["quick_ratio"]             = pct((ca - inv) if ca and inv else ca, cl)
    d["fixed_assets_ratio"]      = pct(fa, eq)
    d["free_cf"]                 = (op_cf + inv_cf) if op_cf is not None and inv_cf is not None else None

    # ネットキャッシュ（取得できた項目のみで計算、欠損あれば approximate=True）
    cash = r.get("cash_and_deposits") or 0
    sec  = r.get("securities") or 0
    inv_sec = r.get("investment_securities") or 0
    st_borrow = r.get("short_term_borrowings")
    lt_borrow = r.get("long_term_borrowings")
    bonds = r.get("bonds_payable")
    cp    = r.get("commercial_papers")

    debt_items = [st_borrow, lt_borrow, bonds, cp]
    debt = sum(x for x in debt_items if x is not None)
    approximate = any(x is None for x in debt_items)

    d["net_cash"] = (cash + sec + inv_sec - debt) if (cash + sec + inv_sec) > 0 else None
    d["net_cash_approximate"] = approximate

    return d

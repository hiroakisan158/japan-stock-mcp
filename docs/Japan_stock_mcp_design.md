# 日本株分析MCPサーバー 設計ドキュメント

## 概要

全上場企業（約4,000社）の財務データを EDINET API から取得・蓄積し、
Claude Desktop から MCP 経由で銘柄スクリーニング・財務分析を行うツール。

Web アプリは作らず、Claude の会話 UI + skills による可視化で分析を完結させる。

---

## アーキテクチャ

```
Claude Desktop
    │ stdio（自動起動）
    ▼
MCPサーバー（uv + Python / ホスト直実行）
    │ SQLite 読み取り
    │ subprocess で Docker コマンド発行（バッチトリガー）
    ▼
data/stocks.db ← SQLite ファイル（volume 共有）
    ▲
    │ SQLite 書き込み
バッチ処理コンテナ（Docker）
    │
    ├── EDINET API（書類一覧 → ZIP DL → XBRL 解析）
    └── yfinance（株価・PER・PBR 等）
```

### 設計判断の根拠

| 判断 | 理由 |
|------|------|
| MCPサーバーはホスト直実行 | Claude Desktop の stdio 接続が安定する |
| バッチ処理は Docker | arelle 等の重い依存を隔離、MCPと独立したライフサイクル |
| DB は SQLite | 個人利用には十分、ファイル共有でシンプル |
| Web アプリは作らない | Claude UI + skills で可視化・分析をカバー |

---

## ディレクトリ構成

```
japan-stock-mcp/
├── README.md
├── Makefile
├── docker-compose.yml
│
├── app/                        # MCPサーバー（ホスト直実行）
│   ├── pyproject.toml          # uv 用プロジェクト定義
│   ├── server.py               # MCPサーバー エントリーポイント
│   ├── db.py                   # SQLite 操作ユーティリティ
│   └── tools/
│       ├── screener.py         # スクリーニングツール
│       ├── financials.py       # 財務データ取得ツール
│       ├── metadata.py         # 企業情報・セクター取得ツール
│       └── batch_trigger.py    # バッチ起動・進捗確認ツール
│
├── batch/                      # バッチ処理（Docker）
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── run.py                  # バッチ実行エントリーポイント
│   ├── edinet.py               # EDINET API 取得（書類一覧・ZIP DL）
│   ├── xbrl_parser.py          # XBRL 解析 → 財務数値抽出
│   ├── price_fetcher.py        # yfinance 株価・指標取得
│   ├── init_db.py              # DB スキーマ初期化 + マイグレーション適用
│   ├── backup.py               # DB バックアップ（ローカル + S3）
│   └── migrations/             # スキーマ変更履歴（git 管理）
│       ├── 001_initial.sql
│       ├── 002_add_dividend_yield.sql
│       └── ...
│
├── skills/
│   └── stock-analysis/
│       └── SKILL.md            # Claude 用分析・可視化指示書
│
├── .gitignore
│
└── data/                       # 永続化データ（volume 共有）
    ├── stocks.db               # SQLite データベース（gitignore）
    ├── batch_progress.json     # バッチ進捗ファイル（gitignore）
    └── backups/                # ローカルバックアップ（gitignore、直近5世代）
        └── stocks_20260429_100000_post.db
```

---

## DB スキーマ

### companies テーブル

企業マスタ。EDINET コードリストから取得。

```sql
CREATE TABLE companies (
    edinet_code  TEXT PRIMARY KEY,   -- EDINET 企業コード（例: E02529）
    sec_code     TEXT,               -- 証券コード（例: 8058）
    company_name TEXT NOT NULL,      -- 企業名
    sector       TEXT,               -- 業種
    market       TEXT,               -- 市場区分（プライム・スタンダード等）
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_companies_sec_code ON companies(sec_code);
CREATE INDEX idx_companies_sector ON companies(sector);
```

### financials テーブル

財務諸表データ。EDINET の XBRL から抽出。

```sql
CREATE TABLE financials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    edinet_code     TEXT NOT NULL,
    period_start    DATE NOT NULL,       -- 会計期間開始
    period_end      DATE NOT NULL,       -- 会計期間終了
    fiscal_year     INTEGER,             -- 会計年度
    quarter         INTEGER,             -- 四半期（1-4、通期は NULL）
    doc_id          TEXT,                -- EDINET docID

    -- 損益計算書 (PL)
    revenue              REAL,           -- 売上高
    gross_profit         REAL,           -- 売上総利益（売上高 − 売上原価）
    operating_income     REAL,           -- 営業利益
    ordinary_income      REAL,           -- 経常利益
    net_income           REAL,           -- 当期純利益

    -- 貸借対照表 (BS)
    total_assets             REAL,       -- 総資産
    current_assets           REAL,       -- 流動資産
    non_current_assets       REAL,       -- 固定資産
    net_assets               REAL,       -- 純資産
    total_liabilities        REAL,       -- 負債合計
    current_liabilities      REAL,       -- 流動負債
    non_current_liabilities  REAL,       -- 固定負債
    shareholders_equity      REAL,       -- 株主資本
    goodwill                 REAL,       -- のれん
    accounts_receivable      REAL,       -- 売掛金（受取手形・契約資産含む場合あり）
    inventory                REAL,       -- 棚卸資産（当座比率計算用）

    -- キャッシュフロー計算書 (CF)
    operating_cf         REAL,           -- 営業CF
    investing_cf         REAL,           -- 投資CF
    financing_cf         REAL,           -- 財務CF

    -- 派生指標（自前計算）
    free_cf                  REAL,       -- フリーCF = 営業CF + 投資CF
    net_cash                 REAL,       -- ネットキャッシュ = 現金等 − 有利子負債
    net_cash_approximate     BOOLEAN DEFAULT FALSE, -- 有利子負債の内訳項目に欠損がある場合 true
    -- 収益性指標
    gross_profit_margin      REAL,       -- 売上総利益率 = 売上総利益 ÷ 売上高 × 100
    operating_profit_margin  REAL,       -- 営業利益率 = 営業利益 ÷ 売上高 × 100
    ordinary_profit_margin   REAL,       -- 経常利益率 = 経常利益 ÷ 売上高 × 100
    net_profit_margin        REAL,       -- 純利益率 = 当期純利益 ÷ 売上高 × 100
    roe                      REAL,       -- ROE = 当期純利益 ÷ 株主資本 × 100
    roa                      REAL,       -- ROA = 当期純利益 ÷ 総資産 × 100
    -- 効率性指標
    asset_turnover           REAL,       -- 総資産回転率 = 売上高 ÷ 総資産
    receivable_turnover      REAL,       -- 売上債権回転率 = 売上高 ÷ 売掛金
    -- 安全性指標
    equity_ratio             REAL,       -- 自己資本比率 = 株主資本 ÷ 総資産 × 100
    debt_to_equity_ratio     REAL,       -- 負債比率 = 負債合計 ÷ 株主資本 × 100
    current_ratio            REAL,       -- 流動比率 = 流動資産 ÷ 流動負債 × 100
    quick_ratio              REAL,       -- 当座比率 = (流動資産 − 棚卸資産) ÷ 流動負債 × 100
    fixed_assets_ratio       REAL,       -- 固定比率 = 固定資産 ÷ 株主資本 × 100

    -- ネットキャッシュ計算用の内訳（XBRL から直接取得）
    cash_and_deposits        REAL,       -- 現金及び預金
    securities               REAL,       -- 有価証券
    investment_securities    REAL,       -- 投資有価証券
    short_term_borrowings    REAL,       -- 短期借入金
    long_term_borrowings     REAL,       -- 長期借入金
    bonds_payable            REAL,       -- 社債
    commercial_papers        REAL,       -- コマーシャルペーパー

    -- メタデータ
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (edinet_code) REFERENCES companies(edinet_code),
    UNIQUE(edinet_code, period_end, quarter)
);
CREATE INDEX idx_financials_sec ON financials(edinet_code, period_end);
```

### prices テーブル

株価・バリュエーション指標。yfinance から取得。

```sql
CREATE TABLE prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    edinet_code TEXT NOT NULL,
    fetched_at  DATE NOT NULL,           -- 取得日

    -- 株価データ
    price           REAL,                -- 現在株価
    market_cap      REAL,                -- 時価総額

    -- バリュエーション指標
    per                    REAL,        -- PER（株価収益率）
    pbr                    REAL,        -- PBR（株価純資産倍率）
    psr                    REAL,        -- PSR（株価売上高倍率 = 時価総額 ÷ 売上高）
    dividend_yield         REAL,        -- 配当利回り
    dividend_per_share     REAL,        -- 1株当たり配当金（yfinance: dividendRate）
    dividend_payout_ratio  REAL,        -- 配当性向（= 1株当たり配当金 ÷ EPS × 100）
    eps                    REAL,        -- EPS（1株当たり利益）
    bps                    REAL,        -- BPS（1株当たり純資産）

    FOREIGN KEY (edinet_code) REFERENCES companies(edinet_code),
    UNIQUE(edinet_code, fetched_at)
);
```

### batch_log テーブル

バッチ実行履歴。

```sql
CREATE TABLE batch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status      TEXT NOT NULL DEFAULT 'running',  -- running / completed / failed
    sector      TEXT,                              -- NULL = 全セクター
    total       INTEGER,
    processed   INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0,
    message     TEXT
);
```

---

## MCP ツール一覧

### スクリーニング

#### screen_stocks

財務指標で銘柄をフィルタリングする。

```
引数:
  sector:        str | None    # セクター（例: "半導体"）
  market:        str | None    # 市場区分（例: "プライム"）
  roe_min:       float | None  # ROE 下限（%）
  per_max:       float | None  # PER 上限
  pbr_max:       float | None  # PBR 上限
  revenue_min:   float | None  # 売上高下限（百万円）
  op_margin_min: float | None  # 営業利益率下限（%）
  sort_by:       str           # ソートキー（デフォルト: "market_cap"）
  limit:         int           # 件数上限（デフォルト: 30）

返却:
  {
    "data": [
      {
        "sec_code": "8035",
        "company_name": "東京エレクトロン",
        "sector": "電気機器",
        "revenue": 2208972,
        "operating_income": 660822,
        "roe": 32.1,
        "per": 28.5,
        "pbr": 6.8,
        "market_cap": 15200000
      }, ...
    ],
    "meta": {
      "total_matches": 45,
      "returned": 30,
      "last_updated": "2026-01-25",
      "days_since_update": 95,
      "stale": true
    }
  }
```

### 財務データ取得

#### get_financials

特定企業の財務データを期間指定で取得。

```
引数:
  code:    str        # 証券コード（例: "7974"）
  metrics: list[str]  # 取得指標（例: ["revenue", "operating_income", "roe"]）
  years:   int        # 遡る年数（デフォルト: 5）

返却:
  {
    "company": {
      "sec_code": "7974",
      "company_name": "任天堂",
      "sector": "その他製品"
    },
    "financials": [
      {
        "fiscal_year": 2025,
        "period_end": "2025-03-31",
        "revenue": 1718620,
        "operating_income": 528900,
        "roe": 19.8
      }, ...
    ],
    "meta": { ... }
  }
```

#### compare_companies

複数企業の財務データを比較。

```
引数:
  codes:   list[str]  # 証券コード一覧（例: ["7974", "9684", "9766"]）
  metrics: list[str]  # 比較指標
  year:    int | None  # 特定年度（NULL で最新）

返却:
  比較表形式のデータ
```

### 企業情報

#### get_company_info

企業の基本情報とサマリーを返す。

```
引数:
  code: str  # 証券コード

返却:
  企業情報 + 最新財務サマリー + 株価情報
```

#### list_sectors

利用可能なセクター一覧を返す。

```
引数: なし
返却: セクター名と所属企業数の一覧
```

### データ更新

#### update_data

EDINET からデータを取得・更新する。モードと対象セクターを指定できる。
セクター指定かつ通常モード時は同期実行（数分〜数時間）、それ以外は非同期実行。

```
引数:
  mode:   str        # "initial"（初回・過去5年）/ "update"（通常・差分）
                     # デフォルト: "update"
  sector: str | None # セクター指定（None = 全社）

返却（同期完了時）:
  {
    "status": "completed",
    "mode": "update",
    "fetch_range": { "from": "2025-01-01", "to": "2026-04-29" },
    "gap_detected": false,
    "processed": 120,
    "errors": 2
  }

返却（非同期開始時）:
  {
    "status": "started",
    "mode": "initial",
    "fetch_range": { "from": "2021-04-29", "to": "2026-04-29" },
    "message": "バックグラウンドで実行中。check_batch_status で進捗を確認できます。"
  }
```

#### check_batch_status

実行中・最新のバッチ処理の進捗を返す。

```
引数: なし
返却:
  {
    "status": "running",        # running / completed / failed / no_batch
    "progress": "1200/4000",
    "sector": null,
    "started_at": "2026-04-29T10:00:00",
    "elapsed_minutes": 45
  }
```

### DB 運用

#### backup_db

DB のバックアップを作成する。ローカル保存に加え、S3 へのアップロードも可能。

```
引数:
  to_s3: bool  # S3 にもアップロードするか（デフォルト: false）

返却:
  {
    "status": "completed",
    "local": "data/backups/stocks_20260429_100000.db",
    "s3": "s3://your-bucket/japan-stock-mcp/backups/stocks_20260429_100000.db",
    "kept_local": 5
  }
```

#### restore_db

指定したバックアップから DB を復元する。

```
引数:
  backup_name: str         # バックアップファイル名
  from_s3:     bool        # S3 から取得するか（デフォルト: false）

返却:
  { "status": "restored", "source": "stocks_20260429_100000.db" }
```

#### list_backups

利用可能なバックアップの一覧を返す。

```
引数:
  include_s3: bool  # S3 のバックアップも含めるか（デフォルト: false）

返却:
  {
    "local": [
      { "name": "stocks_20260429_100000.db", "size_mb": 320, "created": "2026-04-29" },
      ...
    ],
    "s3": [
      { "name": "stocks_20260401_100000.db", "size_mb": 310, "created": "2026-04-01" },
      ...
    ]
  }
```

### データ鮮度

#### MCP Resource: status://data-freshness

MCPサーバー接続時に Claude が自動読み取り。データ鮮度と S3 設定状況を返す。

```
返却:
  {
    "last_updated": "2026-01-25",
    "days_since_update": 95,
    "stale": true,
    "s3_configured": false,
    "message": "財務データは95日前に更新されました。更新を推奨します。"
  }
```

```python
# app/server.py での実装イメージ
@server.resource("status://data-freshness")
async def data_freshness():
    last_updated = db.get_last_updated()
    days_ago = (datetime.now() - last_updated).days if last_updated else None
    s3_configured = bool(os.environ.get("S3_BUCKET"))

    return {
        "last_updated": str(last_updated) if last_updated else None,
        "days_since_update": days_ago,
        "stale": days_ago is None or days_ago > 90,
        "s3_configured": s3_configured,
        "message": _build_status_message(days_ago, s3_configured)
    }

def _build_status_message(days_ago, s3_configured):
    parts = []
    if days_ago is None:
        parts.append("財務データが未取得です。update_data でデータを取得してください。")
    elif days_ago > 90:
        parts.append(f"財務データは{days_ago}日前に更新されました。更新を推奨します。")
    if not s3_configured:
        parts.append("S3 バックアップが未設定です。")
    return " ".join(parts)
```

### 有価証券報告書 PDF

財務数値（XBRL）では取得できない情報（設備の状況・有価証券明細・事業リスク等）を
有報 PDF から取得するためのツール。2ツールに分割し、テキスト取得と表の読み取りを使い分ける。

#### get_annual_report_section

有報の指定セクションのテキストを取得する。表が含まれる場合はページ番号も返す。

```
引数:
  code:    str        # 証券コード（例: "7974"）
  section: str        # セクション名（例: "設備の状況"）
  year:    int | None # 対象年度（None で最新）

返却:
  {
    "section": "設備の状況",
    "text": "当社グループの設備の状況は以下のとおりです...",
    "doc_id": "S100XXXXX",
    "pages": {
      "start": 45,
      "end": 48
    },
    "has_table": true   # true の場合は get_annual_report_pages で表を取得する
  }
```

対応セクションキーワード:

```python
SECTION_KEYWORDS = {
    "設備の状況":         "設備の状況",
    "investment_securities": "有価証券明細表",
    "risk_factors":       "事業等のリスク",
    "business":           "事業の内容",
    "segment":            "セグメント情報",
    "related_party":      "関連当事者との取引",
    "rd_expense":         "研究開発活動",
}
```

#### get_annual_report_pages

有報の指定ページを PDF としてそのまま返す。`get_annual_report_section` で
`has_table=true` の場合に Claude が自動的に呼び出す。

```
引数:
  doc_id: str        # get_annual_report_section の返却値から取得
  pages:  list[int]  # 取得するページ番号のリスト（例: [45, 46, 47, 48]）

返却:
  {
    "type": "document",
    "source": {
      "type": "base64",
      "media_type": "application/pdf",
      "data": "<base64エンコードされたPDF>"
    },
    "pages": [45, 46, 47, 48]
  }
```

実装上の注意:

- PDF は EDINET から**オンデマンド取得**（事前バッチ保存はしない）
- 1社あたり数MB〜数十MBになるため、指定ページのみ抜き出して返す
- スキャンPDF（古い年度）の場合は表抽出精度が落ちる旨を Claude が伝える
- `pymupdf`（fitz）でキーワード検索・ページ特定・テキスト抽出・ページ分割を行う

---



### 実行モード

バッチには3つのモードがあり、`run.py` の引数で切り替える。

```bash
# 初回バッチ（過去5年分を一括取得）
python run.py --mode initial

# 通常バッチ（最新期 + ギャップ補完）
python run.py --mode update

# セクター指定（通常バッチ + セクター絞り込み）
python run.py --mode update --sector 半導体
```

### 初回バッチ（--mode initial）

```
1. EDINET コードリスト取得
   - 企業マスタ（companies テーブル）を構築

2. 取得期間の決定
   - 今日から過去5年分（約1,825日）を対象
   - 日付ループで書類一覧 API を叩き docID を収集
   - docTypeCode=120（有価証券報告書）のみ

3. 書類取得 → XBRL 解析 → DB upsert
   - 約4,000社 × 5年分
   - 所要時間の目安: 8〜15時間
   - 進捗は data/batch_progress.json にリアルタイム書き込み

4. yfinance で株価・指標取得

5. 派生指標を計算して DB に保存

6. DB バックアップ（ローカル + S3）
```

### 通常バッチ（--mode update）

```
1. ギャップ検出
   - DB の最終取得日（batch_log の最新 finished_at）を確認
   - 現在日との差が 1年以上ある場合 → ギャップ補完モードに切り替え
   - 1年未満の場合 → 最新期のみ取得

2a. 最新期のみ取得（ギャップ < 1年）
   - 前回取得日の翌日〜今日までの書類を取得

2b. ギャップ補完（ギャップ ≥ 1年）
   - 前回取得日の翌日〜今日まで全期間を取得
   - ログに「ギャップ補完モードで実行」と記録
   - 所要時間が長くなるため非同期実行を推奨

3. 書類取得 → XBRL 解析 → DB upsert（差分のみ）

4. yfinance で株価・指標を更新

5. 派生指標を再計算

6. DB バックアップ（ローカル + S3）
```

### ギャップ検出ロジック

```python
# batch/run.py
def detect_fetch_range(db) -> tuple[date, date]:
    """取得すべき期間を決定する"""
    last_batch = db.get_last_successful_batch()

    if last_batch is None:
        # 初回バッチ：過去5年分
        return date.today() - timedelta(days=365 * 5), date.today()

    days_gap = (date.today() - last_batch.finished_at.date()).days

    if days_gap >= 365:
        # ギャップ補完：前回取得日の翌日〜今日
        logger.warning(f"ギャップ {days_gap} 日を検出。補完モードで実行します。")
        return last_batch.finished_at.date() + timedelta(days=1), date.today()
    else:
        # 通常更新：前回取得日の翌日〜今日
        return last_batch.finished_at.date() + timedelta(days=1), date.today()
```

### EDINET API レート制限対策

5. DB upsert
   - financials テーブルに企業・期間ごとに保存
   - 既存データは上書き
   - 派生指標を計算して保存:
     - フリーCF = 営業CF + 投資CF
     - ネットキャッシュ = (現金及び預金 + 有価証券 + 投資有価証券) − (短期借入金 + 長期借入金 + 社債 + CP)
     - 売上総利益率 = 売上総利益 ÷ 売上高 × 100
       ※ 売上総利益が取得できない場合は 売上高 − 売上原価 で代替計算
     - 営業利益率 = 営業利益 ÷ 売上高 × 100
     - 経常利益率 = 経常利益 ÷ 売上高 × 100
     - 純利益率 = 当期純利益 ÷ 売上高 × 100
     - ROE = 当期純利益 ÷ 株主資本 × 100
     - ROA = 当期純利益 ÷ 総資産 × 100
     - 総資産回転率 = 売上高 ÷ 総資産
     - 売上債権回転率 = 売上高 ÷ 売掛金
     - 自己資本比率 = 株主資本 ÷ 総資産 × 100
     - 負債比率 = 負債合計 ÷ 株主資本 × 100
     - 流動比率 = 流動資産 ÷ 流動負債 × 100
     - 当座比率 = (流動資産 − 棚卸資産) ÷ 流動負債 × 100
     - 固定比率 = 固定資産 ÷ 株主資本 × 100
     ※ 分母が NULL またはゼロの場合は該当指標を NULL にする
     ※ ネットキャッシュは有利子負債の内訳項目が欠損している場合、
       取得できた項目のみで計算し approximate フラグを true にして保存する

### 成長率指標（クエリ時計算・DB保存なし）

前期比較が必要な以下3指標は DB に保存せず、MCPツールのクエリ実行時に計算する。

```python
# db.py での計算イメージ
def get_growth_rates(edinet_code: str, fiscal_year: int) -> dict:
    sql = """
    SELECT
        curr.fiscal_year,
        -- 売上成長率
        CASE WHEN prev.revenue > 0
            THEN (curr.revenue - prev.revenue) / prev.revenue * 100
        END AS revenue_growth,
        -- 営業利益成長率
        CASE WHEN prev.operating_income > 0
            THEN (curr.operating_income - prev.operating_income) / prev.operating_income * 100
        END AS operating_income_growth,
        -- 純利益成長率
        CASE WHEN prev.net_income > 0
            THEN (curr.net_income - prev.net_income) / prev.net_income * 100
        END AS net_income_growth
    FROM financials curr
    LEFT JOIN financials prev
        ON curr.edinet_code = prev.edinet_code
        AND curr.fiscal_year = prev.fiscal_year + 1
        AND prev.quarter IS NULL
    WHERE curr.edinet_code = ? AND curr.fiscal_year = ? AND curr.quarter IS NULL
    """
    return db.execute(sql, [edinet_code, fiscal_year]).fetchone()
```

前期が赤字（営業利益・純利益がマイナス）の場合は成長率が意味を持たないため NULL にする。

6. yfinance で株価・指標取得
   - 全対象企業の現在値を取得
   - prices テーブルに保存
   - yfinance 取得後に派生指標を計算して保存:
     - PSR = 時価総額 ÷ 売上高（prices.market_cap ÷ financials.revenue）
     - 配当性向 = 1株当たり配当金 ÷ EPS × 100（dividendRate ÷ eps × 100）
     ※ EPS が NULL またはゼロの場合は配当性向も NULL にする
     ※ 直近の年次売上高を使用。売上高が NULL の場合は PSR も NULL にする

7. 進捗管理
   - batch_log テーブルに実行記録
   - data/batch_progress.json にリアルタイム進捗書き込み

8. DB バックアップ
   - バッチ開始前にローカルバックアップ（pre）
   - バッチ正常完了後にローカルバックアップ（post）+ S3 アップロード
   - ローカルは直近 5 世代のみ保持、S3 は無期限保持
```

### バッチ前後の自動バックアップ

```python
# batch/run.py のイメージ
from backup import backup_local, backup_to_s3, cleanup_old_backups

# バッチ開始前
backup_local(tag="pre")

# ... バッチ処理本体 ...

# 正常完了後
backup_local(tag="post")
backup_to_s3()              # S3_BUCKET 環境変数が未設定なら skip
cleanup_old_backups(keep=5) # ローカルは直近5世代のみ
```

### セクター単位実行

```bash
# 半導体セクターのみ（数分で完了）
docker compose run --rm batch python run.py --sector 半導体

# 全社（数時間、デタッチモード）
docker compose run -d --rm batch python run.py
```

### EDINET API レート制限対策

- リクエスト間に `time.sleep(1)` を挿入
- ZIP ダウンロード失敗時は 3 回リトライ
- yfinance は `time.sleep(0.5)` で間隔調整

### XBRL 解析の注意点（実装上の重要事項）

EDINET の XBRL から BS・PL・CF の主要項目は取得可能だが、以下の3点に対応が必要。

#### 1. 会計基準によるタグの差異

企業の会計基準（日本基準 / IFRS / 米国基準）によって勘定科目のタグ名が異なる。
1項目につき複数の候補タグをフォールバックで探索する設計にすること。

```python
# xbrl_parser.py での候補タグ定義
TAG_CANDIDATES = {
    "revenue": [
        "jppfs_cor:NetSales",                                  # 日本基準
        "jppfs_cor:Revenue",                                   # IFRS
        "jppfs_cor:RevenueIFRS",                               # IFRS 別名
        "jpcrp_cor:NetSalesSummaryOfBusinessResults",          # 経営指標等
    ],
    "gross_profit": [
        "jppfs_cor:GrossProfit",                               # 売上総利益（直接取得）
        "jppfs_cor:GrossProfitOnSales",                        # 別名
    ],
    # 売上総利益が取得できない場合は売上原価から計算: 売上総利益 = 売上高 − 売上原価
    "cost_of_sales": [
        "jppfs_cor:CostOfSales",                               # 売上原価（フォールバック用）
        "jppfs_cor:CostOfGoodsSold",                           # 別名
    ],
    "operating_income": [
        "jppfs_cor:OperatingIncome",                           # 日本基準
        "jppfs_cor:OperatingProfitLossIFRS",                   # IFRS
        "jpcrp_cor:OperatingIncomeSummaryOfBusinessResults",   # 経営指標等
    ],
    "ordinary_income": [
        "jppfs_cor:OrdinaryIncome",
        "jpcrp_cor:OrdinaryIncomeSummaryOfBusinessResults",
    ],
    "net_income": [
        "jppfs_cor:ProfitLoss",
        "jppfs_cor:ProfitLossAttributableToOwnersOfParent",    # IFRS 連結
        "jpcrp_cor:NetIncomeSummaryOfBusinessResults",
    ],
    "total_assets": [
        "jppfs_cor:TotalAssets",
        "jpcrp_cor:TotalAssetsSummaryOfBusinessResults",
    ],
    "current_assets": [
        "jppfs_cor:CurrentAssets",
    ],
    "non_current_assets": [
        "jppfs_cor:NoncurrentAssets",
        "jppfs_cor:FixedAssets",                                # 旧タグ名
    ],
    "net_assets": [
        "jppfs_cor:NetAssets",
        "jpcrp_cor:NetAssetsSummaryOfBusinessResults",
    ],
    "total_liabilities": [
        "jppfs_cor:TotalLiabilities",
    ],
    "current_liabilities": [
        "jppfs_cor:CurrentLiabilities",
    ],
    "non_current_liabilities": [
        "jppfs_cor:NoncurrentLiabilities",
        "jppfs_cor:LongTermLiabilities",                        # 旧タグ名
    ],
    "shareholders_equity": [
        "jppfs_cor:ShareholdersEquity",
        "jppfs_cor:EquityAttributableToOwnersOfParent",        # IFRS
    ],
    "goodwill": [
        "jppfs_cor:Goodwill",
    ],
    "accounts_receivable": [
        "jppfs_cor:AccountsReceivableTrade",                                # 日本基準（従来）
        "jppfs_cor:AccountsReceivableTradeAndContractAssets",               # 日本基準（2021年改正後）
        "jppfs_cor:TradeAndOtherReceivables",                               # IFRS
        "jppfs_cor:NotesAndAccountsReceivableTrade",                        # 受取手形及び売掛金
        "jppfs_cor:NotesAndAccountsReceivableTradeAndContractAssets",       # 受取手形、売掛金及び契約資産
    ],
    "inventory": [
        "jppfs_cor:Inventories",                                            # 棚卸資産（一般）
        "jppfs_cor:MerchandiseAndFinishedGoods",                            # 商品及び製品
        "jppfs_cor:merchandise",                                            # 商品
    ],
    "operating_cf": [
        "jppfs_cor:NetCashProvidedByUsedInOperatingActivities",
    ],
    "investing_cf": [
        "jppfs_cor:NetCashProvidedByUsedInInvestingActivities",
    ],
    "financing_cf": [
        "jppfs_cor:NetCashProvidedByUsedInFinancingActivities",
    ],

    # ネットキャッシュ計算用の内訳（BS 項目、Instant コンテキスト）
    "cash_and_deposits": [
        "jppfs_cor:CashAndDeposits",
    ],
    "securities": [
        "jppfs_cor:Securities",
    ],
    "investment_securities": [
        "jppfs_cor:InvestmentSecurities",
    ],
    "short_term_borrowings": [
        "jppfs_cor:ShortTermBorrowings",
        "jppfs_cor:ShortTermLoansPayable",
    ],
    "long_term_borrowings": [
        "jppfs_cor:LongTermBorrowings",
        "jppfs_cor:LongTermLoansPayable",
    ],
    "bonds_payable": [
        "jppfs_cor:Bonds",
        "jppfs_cor:BondsPayable",
    ],
    "commercial_papers": [
        "jppfs_cor:CommercialPapers",
    ],
}
```

#### 2. 連結 / 個別の判定

コンテキスト ID で連結・個別が区別される。連結を優先し、なければ個別にフォールバック。

```python
# 連結 → 個別のフォールバック順
CONTEXT_PRIORITY = [
    "CurrentYearDuration",                              # 連結（当期）
    "CurrentYearDuration_NonConsolidatedMember",        # 個別（当期）
]

CONTEXT_INSTANT_PRIORITY = [
    "CurrentYearInstant",                               # 連結（期末時点、BS用）
    "CurrentYearInstant_NonConsolidatedMember",         # 個別（期末時点）
]
```

BS 項目（総資産・純資産等）は期間（Duration）ではなく時点（Instant）のコンテキストを使う点に注意。

#### 3. 企業・年度による構造差異

- 2014年以前の古いデータは XBRL 構造が不安定な場合がある
- 一部の企業で独自拡張タグ（`jpcrp_cor` 以外）を使用している場合がある
- パース失敗時はエラーログに記録し、スキップして続行する設計にすること

```python
# エラーハンドリングの方針
try:
    financials = parse_xbrl(xbrl_path)
    db.upsert_financials(financials)
except XBRLParseError as e:
    logger.warning(f"XBRL解析失敗: {doc_id} - {e}")
    db.log_parse_error(doc_id, str(e))
    # スキップして次の企業へ続行
```

#### 4. CSV ダウンロード（補助手段）

EDINET API の `type=5` で CSV 形式の財務データも取得可能。
XBRL より構造がフラットで扱いやすいが、全企業・全項目が含まれるとは限らない。
XBRL を主軸にしつつ、XBRL 解析失敗時に CSV をフォールバックとして使う方針。

---

## DB 運用

### スキーマ管理（マイグレーション）

DB ファイルは git 管理しないが、スキーマ定義はマイグレーションファイルとして git 管理する。
空の DB からでも `make init` で最新スキーマを再構築できる状態を保つ。

```
batch/migrations/
├── 001_initial.sql          # 初期テーブル作成
├── 002_add_dividend_yield.sql
└── ...                      # 順番に適用
```

```python
# batch/init_db.py のイメージ
migrations_dir = Path("migrations")
applied = db.get_applied_migrations()

for sql_file in sorted(migrations_dir.glob("*.sql")):
    if sql_file.name not in applied:
        db.execute(sql_file.read_text())
        db.mark_applied(sql_file.name)
```

### バックアップ戦略

| タイミング | 保存先 | 保持世代 |
|-----------|--------|----------|
| バッチ開始前 | ローカル（data/backups/） | 直近 5 世代 |
| バッチ正常完了後 | ローカル + S3 | ローカル 5 世代 / S3 無期限 |
| MCP ツールで手動実行 | ローカル + S3（オプション） | 同上 |

### S3 バックアップ設定

S3 バックアップはオプション。`S3_BUCKET` 環境変数が未設定の場合は自動的にスキップされる。

```
S3 バケット構成:
s3://your-bucket/
└── japan-stock-mcp/
    └── backups/
        ├── stocks_20260101_100000.db
        ├── stocks_20260401_100000.db
        └── ...
```

コスト目安（月額）:
- S3 保存（500MB × 数世代）: 約 $0.06
- PUT リクエスト（月数回）: 約 $0.00002
- 実質月数円

### 障害復旧シナリオ

| 障害 | 復旧手順 |
|------|----------|
| DB ファイル誤削除 | `make restore` または MCP ツール `restore_db` でバックアップから復元 |
| バッチ途中でクラッシュ | 自動作成された pre バックアップから復元、バッチ再実行 |
| PC 故障 | S3 からバックアップ取得、`make init` でスキーマ構築後にリストア |
| スキーマ変更失敗 | pre バックアップから復元、マイグレーションファイルを修正して再適用 |

### .gitignore

```gitignore
# DB・データファイル
data/stocks.db
data/backups/
data/batch_progress.json

# 環境変数
.env

# Python
__pycache__/
*.pyc
.venv/

# Docker
.docker/
```

---

## docker-compose.yml

```yaml
services:
  batch:
    build: ./batch
    volumes:
      - ./data:/data
      - ~/.aws:/root/.aws:ro        # AWS 認証情報（S3 バックアップ用）
    environment:
      - EDINET_API_KEY=${EDINET_API_KEY}
      - S3_BUCKET=${S3_BUCKET:-}     # 未設定なら S3 バックアップをスキップ
    profiles: ["batch"]
```

- `profiles: ["batch"]` により `docker compose up` では起動しない
- MCP ツールからは `docker compose run -d --rm batch ...` で起動
- `data/` ディレクトリを volume 共有し SQLite ファイルを共有
- `~/.aws` を読み取り専用マウントし、S3 バックアップに使用
- `S3_BUCKET` 未設定時は S3 バックアップを自動スキップ（ローカルのみ）

---

## Makefile

```makefile
# --- バッチ操作 ---

# 初回バッチ（過去5年分・バックグラウンド実行）
batch-init:
	docker compose run -d --rm batch python run.py --mode initial

# 通常バッチ・全社（差分更新 + ギャップ検出・バックグラウンド実行）
batch:
	docker compose run -d --rm batch python run.py --mode update

# セクター指定更新（同期実行）
batch-sector:
	@read -p "セクター名: " sector; \
	docker compose run --rm batch python run.py --mode update --sector "$$sector"

# DB 初期化（初回のみ）
init:
	docker compose run --rm batch python init_db.py

# --- MCP サーバー ---

# MCP サーバー起動（手動テスト用）
mcp:
	cd app && uv run server.py

# --- ユーティリティ ---

# Docker ビルド
build:
	docker compose build

# バッチ進捗確認
status:
	@cat data/batch_progress.json 2>/dev/null || echo "バッチ未実行"

# DB の統計情報
db-stats:
	@sqlite3 data/stocks.db " \
		SELECT '企業数: ' || COUNT(*) FROM companies; \
		SELECT '財務データ件数: ' || COUNT(*) FROM financials; \
		SELECT '株価データ件数: ' || COUNT(*) FROM prices; \
		SELECT '最終更新: ' || MAX(created_at) FROM financials;"

# --- DB バックアップ ---

# ローカルバックアップ
backup:
	docker compose run --rm batch python backup.py --local

# S3 バックアップ
backup-s3:
	docker compose run --rm batch python backup.py --s3

# バックアップ一覧
backups:
	@ls -lh data/backups/*.db 2>/dev/null || echo "バックアップなし"

# S3 からリストア
restore:
	@read -p "バックアップファイル名: " name; \
	docker compose run --rm batch python backup.py --restore "$$name"

# 全クリーン
clean:
	docker compose down --rmi local
	rm -f data/stocks.db data/batch_progress.json
```

---

## Claude Desktop 設定

```json
{
  "mcpServers": {
    "japan-stocks": {
      "command": "uv",
      "args": ["--directory", "/path/to/japan-stock-mcp/app", "run", "server.py"],
      "env": {
        "DB_PATH": "/path/to/japan-stock-mcp/data/stocks.db",
        "DOCKER_COMPOSE_DIR": "/path/to/japan-stock-mcp"
      }
    }
  }
}
```

---

## SKILL.md（skills/stock-analysis/SKILL.md）

```markdown
# 日本株分析スキル

## 概要
MCP サーバー japan-stocks から取得した財務データを分析・可視化するためのスキル。

## データ鮮度の管理ルール
- ツール応答の meta.stale が true の場合、分析結果の前に
  「⚠️ データが{days_since_update}日前のものです。
  update_data で更新できます」と伝えること
- 四半期決算シーズン（2月/5月/8月/11月）は特に更新を推奨すること
- update_data の返却値に gap_detected: true が含まれる場合、
  「1年以上のギャップを検出したため、過去分を遡って補完しました」と伝えること
- DB が空（初回バッチ未完了）の場合は「初回バッチを実行中です。
  make status で進捗を確認できます」と伝えること

## S3 バックアップの推奨ルール
- resource status://data-freshness の s3_configured が false の場合、
  会話の最初の応答で以下を伝えること:
  「💡 S3 バックアップが未設定です。DB は数時間かけて構築したデータなので、
  PC 故障時のリスクを減らすために S3 バックアップの設定をおすすめします。
  .env に S3_BUCKET を設定し、AWS 認証を構成するだけで有効になります。
  コストは月数円程度です。」
- この推奨は会話ごとに1回だけ表示する（繰り返さない）
- s3_configured が true の場合はこのメッセージを表示しない
- ユーザーが「後で」「不要」と言った場合は以降触れない

## スクリーニング結果の表示
- 結果は表形式で表示し、主要指標をハイライト
- 30件以上の場合はトップ10を表示し「残りN件あります」と伝える
- ソート理由を簡潔に説明する

## 財務分析の方針
- 単年の数値だけでなく、トレンド（3〜5年推移）を重視する
- 業界平均との比較を含める
- 以下の派生指標を計算して提示する:
  - 収益性: 売上総利益率・営業利益率・経常利益率・純利益率・ROE・ROA
  - 効率性: 総資産回転率・売上債権回転率
  - 成長性: 売上成長率・営業利益成長率・純利益成長率（前期比、クエリ時計算）
  - 安全性: 自己資本比率・負債比率・流動比率・当座比率・固定比率
  - CF: フリーCF・ネットキャッシュ
  - バリュエーション: PSR・配当性向
- 成長率は前期が赤字の場合 NULL になる。その場合は「前期が赤字のため成長率は算出不可」と伝えること
- ネットキャッシュに net_cash_approximate フラグが true の場合、
  「有利子負債の一部項目が取得できなかったため概算値です」と注記すること

## 可視化ルール
- 時系列データ → 折れ線チャート（Artifact）
- 企業比較 → 棒グラフまたはレーダーチャート
- セクター分布 → 散布図（例: PER vs ROE）
- 財務構成 → 積み上げ棒グラフ

## 有価証券報告書の読み取りルール
- XBRL で取得できない情報（設備の状況・有価証券明細等）は
  get_annual_report_section でテキストとページ番号を取得する
- has_table が true の場合、自動的に get_annual_report_pages を呼んで
  該当ページの PDF を取得し、表を直接読み取ること
- ユーザーに「PDF を取得します」と断りを入れてから実行する
- スキャン PDF（古い年度）で表が読み取れない場合は、
  「この年度の PDF はスキャン形式のため表の読み取り精度が低い可能性があります」と伝える
- XBRL で取得できる項目（売上・営業利益等）は PDF ではなく DB の値を優先して使う

## 注意事項
- これは投資助言ではないことを明記する
- EDINET データは有価証券報告書ベースであり、速報値ではない
- yfinance の株価はリアルタイムではなく遅延がある
```

---

## 初回セットアップ手順

```bash
# 1. リポジトリセットアップ
cd japan-stock-mcp

# 2. 環境変数設定（.env ファイルを作成）
cat <<EOF > .env
EDINET_API_KEY=your_api_key_here
S3_BUCKET=your-bucket-name          # S3 バックアップ不要なら空欄 or 行削除
EOF

# 3. AWS 認証設定（S3 バックアップを使う場合のみ）
aws configure
# → AWS Access Key ID / Secret Access Key / Region を入力

# 4. Docker ビルド
make build

# 5. DB 初期化 + 企業マスタ取得
make init

# 6. 初回バッチ実行（過去5年分・8〜15時間かかる・バックグラウンド実行）
make batch-init

# 進捗確認（別ターミナルで随時確認）
make status

# 7. Claude Desktop 設定ファイルに MCP サーバーを追加
# （上記の Claude Desktop 設定セクションを参照）

# 8. Claude Desktop を再起動 → 使い始める
# ※ 初回バッチ完了前でも MCP サーバーは起動できる
#   データが空の状態でも「バッチ実行中です」と Claude が案内する
```

---

## 今後の拡張候補（スコープ外）

- FastAPI エンドポイント追加（Web アプリ化）
- SSE トランスポート対応（Claude.ai から利用）
- Railway / Render へのデプロイ
- J-Quants API 連携（より詳細な財務データ）
- 決算短信（TDnet）対応で速報性向上
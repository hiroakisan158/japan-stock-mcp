-- 企業マスタ
CREATE TABLE IF NOT EXISTS companies (
    edinet_code  TEXT PRIMARY KEY,
    sec_code     TEXT,
    company_name TEXT NOT NULL,
    sector       TEXT,
    market       TEXT,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_companies_sec_code ON companies(sec_code);
CREATE INDEX IF NOT EXISTS idx_companies_sector   ON companies(sector);

-- 財務諸表データ
CREATE TABLE IF NOT EXISTS financials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    edinet_code     TEXT NOT NULL,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    fiscal_year     INTEGER,
    quarter         INTEGER,
    doc_id          TEXT,

    -- PL
    revenue              REAL,
    gross_profit         REAL,
    operating_income     REAL,
    ordinary_income      REAL,
    net_income           REAL,

    -- BS
    total_assets             REAL,
    current_assets           REAL,
    non_current_assets       REAL,
    net_assets               REAL,
    total_liabilities        REAL,
    current_liabilities      REAL,
    non_current_liabilities  REAL,
    shareholders_equity      REAL,
    goodwill                 REAL,
    accounts_receivable      REAL,
    inventory                REAL,

    -- CF
    operating_cf   REAL,
    investing_cf   REAL,
    financing_cf   REAL,

    -- 派生指標
    free_cf                  REAL,
    net_cash                 REAL,
    net_cash_approximate     BOOLEAN DEFAULT FALSE,
    gross_profit_margin      REAL,
    operating_profit_margin  REAL,
    ordinary_profit_margin   REAL,
    net_profit_margin        REAL,
    roe                      REAL,
    roa                      REAL,
    asset_turnover           REAL,
    receivable_turnover      REAL,
    equity_ratio             REAL,
    debt_to_equity_ratio     REAL,
    current_ratio            REAL,
    quick_ratio              REAL,
    fixed_assets_ratio       REAL,

    -- ネットキャッシュ内訳
    cash_and_deposits        REAL,
    securities               REAL,
    investment_securities    REAL,
    short_term_borrowings    REAL,
    long_term_borrowings     REAL,
    bonds_payable            REAL,
    commercial_papers        REAL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (edinet_code) REFERENCES companies(edinet_code),
    UNIQUE(edinet_code, period_end, quarter)
);
CREATE INDEX IF NOT EXISTS idx_financials_sec ON financials(edinet_code, period_end);

-- 株価・バリュエーション
CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    edinet_code TEXT NOT NULL,
    fetched_at  DATE NOT NULL,

    price                  REAL,
    market_cap             REAL,
    per                    REAL,
    pbr                    REAL,
    psr                    REAL,
    dividend_yield         REAL,
    dividend_per_share     REAL,
    dividend_payout_ratio  REAL,
    eps                    REAL,
    bps                    REAL,

    FOREIGN KEY (edinet_code) REFERENCES companies(edinet_code),
    UNIQUE(edinet_code, fetched_at)
);

-- バッチ実行履歴
CREATE TABLE IF NOT EXISTS batch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status      TEXT NOT NULL DEFAULT 'running',
    sector      TEXT,
    total       INTEGER,
    processed   INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0,
    message     TEXT
);

-- マイグレーション管理
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

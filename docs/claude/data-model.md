# Data Model

## Tables

### `companies` — company master
| Column | Type | Notes |
|--------|------|-------|
| `edinet_code` | TEXT PK | EDINET identifier (e.g. `E00001`) |
| `sec_code` | TEXT | TSE stock code (4–5 digits); used as Yahoo Finance ticker `{sec_code}.T` |
| `company_name` | TEXT | |
| `sector` | TEXT | TSE sector (e.g. `電気機器`) |
| `market` | TEXT | |

~3,800 companies listed on TSE that file annual reports.

### `financials` — financial statements
| Column Group | Key Columns |
|-------------|-------------|
| Identity | `edinet_code`, `period_start`, `period_end`, `fiscal_year`, `quarter`, `doc_id` |
| PL | `revenue`, `gross_profit`, `operating_income`, `ordinary_income`, `net_income` |
| BS | `total_assets`, `current_assets`, `net_assets`, `total_liabilities`, `shareholders_equity`, `goodwill`, `accounts_receivable`, `inventory` |
| CF | `operating_cf`, `investing_cf`, `financing_cf` |
| Derived | `free_cf`, `net_cash`, `gross_profit_margin`, `operating_profit_margin`, `roe`, `roa`, `equity_ratio`, `current_ratio`, … |
| Net cash detail | `cash_and_deposits`, `securities`, `investment_securities`, `short_term_borrowings`, `long_term_borrowings`, `bonds_payable` |

**`quarter IS NULL` = annual record.** Quarterly records have `quarter` = 1–4.

Uniqueness: `UNIQUE(edinet_code, period_end, quarter)` (SQLite enforces via partial index for annual records).

### `prices` — stock prices and valuation
| Column | Notes |
|--------|-------|
| `edinet_code`, `fetched_at` | Composite unique key |
| `price`, `market_cap` | |
| `per`, `pbr`, `psr` | Valuation multiples |
| `dividend_yield`, `dividend_per_share`, `dividend_payout_ratio` | |
| `eps`, `bps` | |

Updated daily (intended). Source: yfinance (Yahoo Finance).

### `batch_log` — batch execution history
Tracks `started_at`, `finished_at`, `status`, `sector`, progress counters. The latest `finished_at` from a completed run is the starting point for `--mode update`.

## Units

| Metric | Unit |
|--------|------|
| All monetary values (`revenue`, `operating_income`, etc.) | JPY (yen). Example: ¥1 trillion = 1,000,000,000,000 |
| Ratio metrics (`roe`, `roa`, `operating_profit_margin`, etc.) | Percent. Example: 15.5 = 15.5% |
| Valuation multiples (`per`, `pbr`) | Times (×) |
| `dividend_yield` | Percent |
| **`screen_stocks.revenue_min` parameter** | **Millions of JPY** (converted ×1,000,000 inside the function) |

## Accounting Standards

- J-GAAP: most companies
- IFRS: Sony, Toyota, Honda, Hitachi, and others — XBRL tag set differs; `xbrl_parser.py` prioritizes IFRS tags

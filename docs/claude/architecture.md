# Architecture

## Component Overview

```
Claude Desktop (Windows)
    │  wsl.exe bash -lc
    ▼
MCP Server  app/server.py  (uv, stdio, host process)
    │  SQLite read
    ▼
data/stocks.db
    ▲  SQLite write
Batch  batch/  (Docker container)
    ├── EDINET API → XBRL ZIP → xbrl_parser.py → financials table (annual)
    ├── J-Quants API → jquants_fetcher.py → financials table (quarterly Q1/Q2/Q3)
    └── yfinance → price_fetcher.py → prices table
```

## MCP Server (app/)

- Framework: FastMCP (mcp package)
- Entry point: `server.py` — registers tools from `tools/` modules and a `status://data-freshness` resource
- DB access: `db.py` — read-only SQLite connections
- Runs on the WSL host via `uv`, **not** in Docker (Docker stdio is unstable)
- Claude Desktop invokes it via `wsl.exe bash -lc "... uv --directory .../app run server.py"`

**Tool modules:**

| File | Tools registered |
|------|-----------------|
| `tools/screener.py` | `screen_stocks` (incl. quarterly YoY growth filters) |
| `tools/financials.py` | `get_financials`, `get_quarterly_financials`, `compare_companies` |
| `tools/metadata.py` | `get_company_info`, `list_sectors` |
| `tools/batch_trigger.py` | `update_data`, `update_prices`, `update_quarterly`, `check_batch_status`, `backup_db`, `restore_db` |
| `tools/annual_report.py` | `get_annual_report_section`, `get_annual_report_pages` |

## Batch (batch/)

- Runs inside Docker (`docker compose --profile batch`)
- Entry point: `run.py` — dispatches by `--mode`
  - `init-companies`: populate `companies` from EDINET company list
  - `initial`: full historical load (5 years), respects `--sector`, `--from-date`, `--to-date`
  - `update`: incremental from `batch_log.finished_at`
  - `fetch-prices`: yfinance price/valuation update
- `edinet.py`: EDINET API client — fetches document lists and downloads XBRL ZIPs
- `xbrl_parser.py`: parses XBRL ZIP, extracts financials, computes derived metrics
- `price_fetcher.py`: fetches price/valuation via yfinance
- `jquants_fetcher.py`: fetches quarterly PL/BS/CF via J-Quants API v2 (`ClientV2.get_fin_summary`), upserts into `financials` with `source='jquants'`
- `backup.py`: SQLite backup (local + optional S3)
- `init_db.py`: runs SQL migrations in `migrations/`

## Data Flow

1. `edinet.py` fetches document index for a date range
2. For each annual report (`docTypeCode=120`), downloads XBRL ZIP
3. `xbrl_parser.py` extracts financial values using tag priority lists (first-match wins)
4. Derived metrics (ROE, ROA, margins, etc.) computed in Python and stored alongside raw values
5. `price_fetcher.py` maps `sec_code` → Yahoo Finance ticker (`{sec_code}.T`) and fetches via yfinance
6. `jquants_fetcher.py` calls `ClientV2.get_fin_summary(code=sec_code)`, deduplicates revised disclosures by keeping latest `DiscDate`, maps V2 short column names (`Sales`/`OP`/`OdP`/`NP`/`TA`/`Eq`/`CFO`/`CFI`/`CFF`/`CashEq`) to DB schema

# Constraints and Critical Decisions

## batch/ Changes Require Docker Rebuild

`make build` must be run after **any** change to `batch/`. The batch runs inside a Docker image; file changes on the host are not reflected until the image is rebuilt. This has caused silent failures (e.g., missing `yfinance` module after adding it to `pyproject.toml`).

## XBRL Revenue Tag Priority

`xbrl_parser.py` uses first-match-wins across tag candidates. Revenue priority (must not change without verifying against actual financial statements for Sony, Toyota, Honda, Hitachi, Nissan):

1. `SalesAndFinancialServicesRevenueIFRS` — total including financial services (Sony)
2. `SalesRevenuesIFRS` — IFRS total revenue (Toyota)
3. `TotalNetRevenuesIFRS`
4. `NetSalesIFRS` — may exclude financial services, so ranked lower
5. `RevenueIFRS` — Honda, Hitachi
6. `NetSales` — Nissan (uses consolidated context if present)
7. `Revenue`, `NetSalesSummaryOfBusinessResults`

Consolidated context (`CurrentYearDuration`) takes priority over non-consolidated (`CurrentYearDuration_NonConsolidatedMember`).

## Incremental Update Mode Limitation

`--mode update` starts from `batch_log.finished_at` of the last completed run. It **cannot** reprocess historical data. For reprocessing, always use `--mode initial` with explicit `--from-date` / `--to-date`.

## Abnormal Batch Termination

If `data/batch_progress.json` exists after a batch run, the run ended abnormally. Delete it manually before the next run to avoid stale progress state. `data/sync_progress.json` steps marked `error` indicate where `make sync` stopped.

## DB File Ownership

`data/stocks.db` is created by Docker running as root. On the WSL host, the file may be read-only. Write operations (migrations, batch) must go through Docker. The MCP server only reads, so this is fine under normal operation.

## MCP Server Not Dockerized

The MCP server runs directly on the WSL host via `uv` (not in Docker). This is intentional: Docker adds latency and complexity to stdio transport that causes instability with Claude Desktop.

## Annual Report Tools

`get_annual_report_section` extracts text; `get_annual_report_pages` returns PDF pages as base64. For pages containing tables, use `get_annual_report_pages` — PDF rendering is more accurate than text extraction for structured data.

## J-Quants Quarterly Data Constraints

- **API version**: Uses `jquants-api-client >= 1.0.0` with `ClientV2` (V1 `Client` is deprecated). Authentication via `api_key` (stored as `JQUANTS_REFRESH_TOKEN` env var for historical reasons).
- **Plan**: Light plan — covers all listed companies, past 5 years.
- **Coverage**: `TypeOfCurrentPeriod` values `1Q`/`2Q`/`3Q` stored; `FY` and `4Q` skipped (covered by EDINET annual data).
- **IFRS companies**: `OrdinaryProfit` (`OdP`) is empty for IFRS filers; stored as NULL.
- **Derived metrics**: Only PL-based margins and `free_cf` computed. Balance sheet ratios (ROE, ROA, equity_ratio, etc.) are NULL for jquants rows.
- **Revised disclosures**: When a company re-files a quarter, the fetcher keeps only the latest `DiscDate`.
- **Rate limiting**: Sleeps 0.6 s between requests; retries up to 3× (10 s / 20 s backoff) on 429 errors.
- **`net_assets` vs `shareholders_equity`**: J-Quants `Equity` maps to `net_assets`. `shareholders_equity` is left NULL.

## S3 Backup

S3 backup is called automatically for all batch modes. Requires `S3_BUCKET` in `.env` and `~/.aws` credentials mounted into Docker. If `S3_BUCKET` is unset, S3 upload is silently skipped — only local backups (max 5) are kept.

## Environment Variables

| Variable | Required | Notes |
|----------|----------|-------|
| `EDINET_API_KEY` | Yes | EDINET API key |
| `JQUANTS_REFRESH_TOKEN` | Yes (for quarterly) | J-Quants API v2 key (passed as `api_key` to `ClientV2`) |
| `S3_BUCKET` | No | S3 backup destination bucket name |
| `DB_PATH` | No | Defaults to `/data/stocks.db` inside Docker |
| `STATUS_OUTPUT` | No | Output path for `gen_db_status.py`; defaults to `/workspace/tmp/db_status.md` |

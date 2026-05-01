# CLAUDE.md

MCP server for Japan stock financial screening and analysis via Claude Desktop. Collects annual financial data from EDINET (XBRL), quarterly data from J-Quants API, and stock prices from yfinance into a local SQLite database.

## Commands

```bash
# MCP server
make mcp              # Start MCP server (dev)

# Setup
make build            # Build Docker image (required after any batch/ changes)
make init             # Initialize/migrate DB

# Financial data (EDINET/XBRL)
make batch-init       # Initial load: all companies, past 5 years (background, 8–15h)
make batch            # Incremental update since last run (background)
make batch-sector     # Interactive: specify sector (foreground)

# Price data (yfinance)
make prices           # All companies (background, 30–60 min)
make prices-sector    # Interactive: specify sector (foreground)

# Quarterly financial data (J-Quants API)
make quarters         # All companies (background, ~40 min)
make quarters-sector  # Interactive: specify sector (foreground)

# Status
make status           # Batch progress
make db-stats         # DB row counts and last update timestamp
make db-status-report # Regenerate tmp/db_status.md (sector coverage report)
make backups          # List DB backups
```

**Reprocess a specific sector/date range** (use `--mode initial`, not `update`):
```bash
docker compose --profile batch run --rm batch python run.py \
  --mode initial --sector "電気機器" --from-date 2025-06-01 --to-date 2025-09-30
```

## Rules

- バッチ（batch, prices, quarters いずれか）を実行したら、必ず最後に `make db-status-report` を実行して `tmp/db_status.md` を更新すること。
- `tmp/db_status.md` はセクター別カバレッジの最新状態を示すファイル。手動でも確認・共有できる。

## Details

- [docs/claude/architecture.md](docs/claude/architecture.md) — component structure, data flow
- [docs/claude/data-model.md](docs/claude/data-model.md) — DB schema, metric units
- [docs/claude/constraints.md](docs/claude/constraints.md) — non-obvious constraints and critical decisions

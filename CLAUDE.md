# CLAUDE.md

MCP server for Japan stock financial screening and analysis via Claude Desktop. Collects annual financial data from EDINET (XBRL), quarterly data from J-Quants API, and stock prices from yfinance into a local SQLite database.

## Commands

```bash
# MCP server
make mcp              # Start MCP server (dev)

# Setup
make build            # Build Docker image — required after ANY change to batch/
make init             # Initialize/migrate DB

# One-shot sync (financial diff → prices → quarterly → status report)
make sync             # All companies
make sync-sector      # Interactive: specify sector
make sync-status      # Show progress from data/sync_progress.json

# Financial data (EDINET/XBRL)
make batch-init       # Initial load: all companies, past 5 years (8–15h)
make batch            # Incremental update since last run (background)
make batch-sector     # Interactive: specify sector (foreground)

# Price data (yfinance)
make prices           # All companies (30–60 min)
make prices-sector    # Interactive: specify sector

# Quarterly financial data (J-Quants API)
make quarters         # All companies (~40 min)
make quarters-sector  # Interactive: specify sector

# Status / reporting
make status           # Current batch progress (batch_progress.json)
make db-stats         # DB row counts and last update timestamp
make db-status-report # Regenerate tmp/db_status.md (sector coverage report)
make sync-status      # Show sync pipeline step progress
make backups          # List local DB backups

# Claude Desktop skill
make skill            # Generate skills/stock-analysis.zip for upload
```

**Reprocess a specific sector/date range** (use `--mode initial`, not `update`):
```bash
docker compose --profile batch run --rm batch python run.py \
  --mode initial --sector "電気機器" --from-date 2025-06-01 --to-date 2025-09-30
```

## Rules

- Run `make build` after any change to `batch/` before running batch commands.
- After any batch run, `tmp/db_status.md` should reflect current coverage — regenerate with `make db-status-report` if not using `make sync`.

## Details

- [docs/claude/architecture.md](docs/claude/architecture.md) — component structure, data flow
- [docs/claude/data-model.md](docs/claude/data-model.md) — DB schema, metric units, status files
- [docs/claude/constraints.md](docs/claude/constraints.md) — non-obvious constraints and critical decisions

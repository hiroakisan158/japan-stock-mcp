.PHONY: mcp build init batch batch-init batch-sector prices prices-sector quarters quarters-sector status db-stats db-status-report backups clean skill

# --- MCP サーバー ---

mcp:
	cd app && uv run server.py

# --- ビルド・初期化 ---

build:
	docker compose --profile batch build

init:
	docker compose --profile batch run --rm batch python init_db.py

# --- 財務データバッチ ---

batch-init:
	docker compose --profile batch run -d --rm batch python run.py --mode initial

batch:
	docker compose --profile batch run -d --rm batch python run.py --mode update

batch-sector:
	@read -p "セクター名: " sector; \
	docker compose --profile batch run --rm batch python run.py --mode update --sector "$$sector"

# --- 株価データバッチ ---

prices:
	docker compose --profile batch run -d --rm batch python run.py --mode fetch-prices

prices-sector:
	@read -p "セクター名: " sector; \
	docker compose --profile batch run --rm batch python run.py --mode fetch-prices --sector "$$sector"

# --- 四半期財務データバッチ ---

quarters:
	docker compose --profile batch run -d --rm batch python run.py --mode fetch-quarterly

quarters-sector:
	@read -p "セクター名: " sector; \
	docker compose --profile batch run --rm batch python run.py --mode fetch-quarterly --sector "$$sector"

# --- 確認・統計 ---

status:
	@cat data/batch_progress.json 2>/dev/null || echo "バッチ未実行"

db-stats:
	@sqlite3 data/stocks.db \
		"SELECT '企業数: ' || COUNT(*) FROM companies; \
		 SELECT '財務データ件数: ' || COUNT(*) FROM financials; \
		 SELECT '株価データ件数: ' || COUNT(*) FROM prices; \
		 SELECT '最終更新: ' || MAX(created_at) FROM financials;"

# --- DB バックアップ ---

db-status-report:
	docker compose --profile batch run --rm \
		-e STATUS_OUTPUT=/workspace/tmp/db_status.md \
		batch python gen_db_status.py

backups:
	@ls -lh data/backups/*.db 2>/dev/null || echo "バックアップなし"

# --- スキル ---

skill:
	@python3 -c "\
import zipfile, os; \
zf = zipfile.ZipFile('skills/stock-analysis.zip', 'w', zipfile.ZIP_DEFLATED); \
[zf.write(os.path.join(r,f), os.path.relpath(os.path.join(r,f), 'skills')) \
 for r,_,files in os.walk('skills/stock-analysis') for f in files]; \
zf.close()"
	@echo "作成: skills/stock-analysis.zip — Claude Desktop の カスタマイズ > Skills からアップロードしてください"

# --- クリーン ---

clean:
	docker compose down --rmi local
	rm -f data/stocks.db data/batch_progress.json

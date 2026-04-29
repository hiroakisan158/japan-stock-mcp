# Japan Stock MCP Server

Claude Desktop から日本株の財務分析・銘柄スクリーニングを行う MCP サーバーです。

**データソース**
- 財務データ: [EDINET](https://disclosure.edinet-fsa.go.jp/)（金融庁・有価証券報告書 XBRL）
- 株価・バリュエーション: [yfinance](https://github.com/ranaroussi/yfinance)（Yahoo Finance）

**対象銘柄**: 東証上場の有報提出企業 約3,800社

---

## アーキテクチャ

```
Claude Desktop (Windows)
    │  wsl.exe bash -lc
    ▼
MCP Server (WSL / Python / uv)       ← app/
    │  SQLite
    ▼
stocks.db (data/)
    ▲
Batch (Docker)                        ← batch/
  ├── EDINET API → XBRL 解析 → financials テーブル
  └── yfinance → prices テーブル
```

---

## セットアップ

### 前提条件

- WSL2 (Ubuntu)
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker Desktop for Windows（WSL2 統合を有効化）
- Claude Desktop
- EDINET API キー（[申請ページ](https://disclosure2.edinet-fsa.go.jp/)）

### 1. リポジトリのクローン

```bash
git clone git@github.com:hiroakisan158/japan-stock-mcp.git
cd japan-stock-mcp
```

### 2. 環境変数の設定

```bash
cat > .env << EOF
EDINET_API_KEY=your_api_key_here
S3_BUCKET=          # S3バックアップを使う場合のみ
EOF
```

### 3. DB 初期化

```bash
make build   # Docker イメージのビルド
make init    # SQLite スキーマ作成
```

### 4. 企業マスタの取得

```bash
docker compose --profile batch run --rm batch python run.py --mode init-companies
# → companies テーブルに ~3,800社が登録される
```

### 5. Claude Desktop の設定

`%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`（Microsoft Store 版）または `%APPDATA%\Claude\claude_desktop_config.json` を編集：

```json
{
  "mcpServers": {
    "japan-stocks": {
      "command": "wsl.exe",
      "args": [
        "bash",
        "-lc",
        "DB_PATH=/path/to/japan-stock-mcp/data/stocks.db DOCKER_COMPOSE_DIR=/path/to/japan-stock-mcp EDINET_API_KEY=your_api_key /home/youruser/.local/bin/uv --directory /path/to/japan-stock-mcp/app run server.py"
      ]
    }
  }
}
```

Claude Desktop を再起動すると `japan-stocks` ツールが有効になります。

---

## データ取得

### 財務データ（XBRL）

```bash
# 特定セクターのみ（動作確認用）
make batch-sector   # → セクター名を入力

# 全銘柄・初回（バックグラウンド、8〜15時間）
make batch-init

# 差分更新
make batch
```

### 株価データ（yfinance）

```bash
# 特定セクターのみ
make prices-sector  # → セクター名を入力

# 全銘柄（バックグラウンド、30〜60分）
make prices
```

### DB の状態確認

```bash
make db-stats
```

---

## MCP ツール一覧

| ツール | 説明 |
|--------|------|
| `screen_stocks` | ROE・PER・PBR・営業利益率などで銘柄をフィルタリング |
| `get_financials` | 企業の財務データを年次で取得（デフォルト5年） |
| `compare_companies` | 複数企業の財務指標を横並び比較 |
| `get_company_info` | 企業の基本情報・最新財務サマリー |
| `list_sectors` | セクター一覧と銘柄数 |
| `get_annual_report_section` | 有価証券報告書のセクションをテキスト取得 |
| `get_annual_report_pages` | 有報の指定ページを PDF（base64）で取得 |
| `update_data` | EDINET から財務データを更新 |
| `update_prices` | yfinance で株価・バリュエーションを更新 |
| `check_batch_status` | バッチの進捗状況を確認 |
| `backup_db` | DB をローカルにバックアップ |
| `list_backups` | バックアップ一覧 |
| `restore_db` | バックアップから DB をリストア |

---

## 使用例

### 銘柄スクリーニング

```
ROE 15%以上、PER 20倍以下の電気機器銘柄を教えて
→ screen_stocks(sector="電気機器", roe_min=15, per_max=20)
```

### 財務トレンド分析

```
任天堂の過去5年の業績推移を見せて
→ get_financials(code="7974", years=5)
```

### 同業他社比較

```
ソニー・パナソニック・日立を比較して
→ compare_companies(codes=["6758", "6752", "6501"])
```

### 有報の事業内容確認

```
任天堂の有報で事業内容を教えて
→ get_annual_report_section(sec_code="7974", section="事業内容")
```

### データ更新

```
電気機器セクターのデータを更新して
→ update_data(sector="電気機器")
→ update_prices(sector="電気機器")
```

---

## プロジェクト構成

```
japan-stock-mcp/
├── app/                        # MCP サーバー（uv で実行）
│   ├── server.py               # FastMCP エントリーポイント
│   ├── db.py                   # SQLite 接続ユーティリティ
│   ├── pyproject.toml
│   └── tools/
│       ├── screener.py         # screen_stocks
│       ├── financials.py       # get_financials, compare_companies
│       ├── metadata.py         # get_company_info, list_sectors
│       ├── batch_trigger.py    # update_data, update_prices, backup系
│       └── annual_report.py    # 有報 PDF ツール
├── batch/                      # バッチ処理（Docker で実行）
│   ├── Dockerfile
│   ├── run.py                  # バッチエントリーポイント
│   ├── edinet.py               # EDINET API クライアント
│   ├── xbrl_parser.py          # XBRL 解析・派生指標計算
│   ├── price_fetcher.py        # yfinance 株価取得
│   ├── backup.py               # DB バックアップ
│   ├── init_db.py              # マイグレーション実行
│   ├── pyproject.toml
│   └── migrations/
│       ├── 001_initial.sql     # テーブル定義
│       └── 002_fix_quarter_uniqueness.sql
├── data/                       # DB・バックアップ（git 管理外）
├── skills/stock-analysis/
│   └── SKILL.md                # Claude スキル定義
├── docs/
│   ├── Japan_stock_mcp_design.md
│   └── implementation_plan.md
├── docker-compose.yml
├── Makefile
└── .env                        # API キー（git 管理外）
```

---

## 指標の仕様

| 指標 | 単位 | 備考 |
|------|------|------|
| `revenue`, `operating_income` 等 | 円 | 例: 1兆円 = 1,000,000,000,000 |
| `roe`, `roa`, `operating_profit_margin` 等 | % | 例: 15.5 = 15.5% |
| `per`, `pbr` | 倍 | |
| `dividend_yield` | % | 例: 1.5 = 1.5% |
| `screen_stocks` の `revenue_min` | **百万円** | 例: 1兆円 = 1,000,000 |

### 対応会計基準

- 日本 GAAP（JGAAP）
- IFRS（ソニー・日立・ホンダ等）

---

## Makefile コマンド

```bash
make build          # Docker イメージビルド
make init           # DB 初期化（マイグレーション適用）
make batch-init     # 初回バッチ（全銘柄・過去5年、非同期）
make batch          # 差分更新バッチ（非同期）
make batch-sector   # セクター指定バッチ（同期）
make prices         # 全銘柄株価取得（非同期）
make prices-sector  # セクター指定株価取得（同期）
make status         # バッチ進捗確認
make db-stats       # DB 統計
make backups        # バックアップ一覧
make mcp            # MCP サーバー起動（開発用）
```

# 日本株MCP サーバー 実装フェーズ計画

## Context

設計ドキュメント（`Japan_stock_mcp_design.md`）をもとに、日本株財務データMCPサーバーをスモールスタートで段階的に構築する。EDINET APIキー・uv・Docker・Claude Desktopはいずれも未セットアップの状態から開始する。有報PDF取得ツール（Phase 8）まで含めた完全実装を目指す。

---

## フェーズ全体像

| Phase | 内容 | 検証ゴール |
|-------|------|-----------|
| 0 | 環境構築 | uv / Docker / Claude Desktop 動作確認 |
| 1 | プロジェクト骨格 + MCPスタブ | Claude Desktop から MCP 接続成功 |
| 2 | DB スキーマ + 全MCPツールスタブ | 全ツールが空レスポンスを返す |
| 3 | EDINET コードリスト → companies | `list_sectors` / `get_company_info` が実データ |
| 4 | XBRL 財務データ取得 | `get_financials` / `screen_stocks` が実データ |
| 5 | yfinance 株価取得 | PER / PBR / 配当利回り込みスクリーニング |
| 6 | バッチトリガー MCP ツール | Claude から `update_data` でバッチ起動 |
| 7 | バックアップ・リストア | `backup_db` / `restore_db` E2E 動作 |
| 8 | 有報 PDF ツール | `get_annual_report_section` で任天堂の事業内容を取得 |
| 9 | 仕上げ | SKILL.md + README + Claude Desktop 設定ガイド完成 |

---

## Phase 0: 環境構築

**目標:** 開発ツールが一通り動く状態にする

### 手順

1. **uv インストール**（WSL2 ターミナルで実行）
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Docker Desktop for Windows インストール**
   - Windows 側で Docker Desktop をインストール
   - Settings → Resources → WSL Integration → WSL2 ディストリビューションを有効化
   - WSL2 ターミナルで `docker --version` が通ることを確認

3. **Claude Desktop インストール**
   - Windows 側で `claude.ai/download` からインストール

4. **EDINET API キー取得**
   - `https://disclosure2.edinet-fsa.go.jp/` → API 利用申請
   - 取得後、プロジェクトルートに `.env` を作成:
     ```
     EDINET_API_KEY=your_api_key_here
     S3_BUCKET=   # S3 バックアップ不要なら空欄のまま
     ```

---

## Phase 1: プロジェクト骨格 + MCP スタブ

**目標:** Claude Desktop から MCP 接続できる最小構成を作る

### 作成ファイル

```
japan-stock-mcp/
├── app/
│   ├── pyproject.toml          # uv 用（mcp, anyio 依存）
│   └── server.py               # MCPサーバー最小スタブ
├── .gitignore
├── Makefile                    # make mcp だけ動く最小版
└── data/                       # mkdir のみ
```

### `app/server.py` の最小スタブ
- `mcp` ライブラリで stdio サーバーを起動
- ツール: `list_sectors` のみ（ハードコード値を返す）
- Resource: `status://data-freshness`（固定値を返す）

### 検証
```bash
make mcp         # サーバーが起動すること
```
Claude Desktop の `claude_desktop_config.json` に追加して再起動し、「セクター一覧を教えて」に応答することを確認する。

---

## Phase 2: DB スキーマ + 全 MCP ツールスタブ

**目標:** 全 MCP ツールが実装され、空 DB でも Claude がエラーなく会話できる

### 作成ファイル

```
├── app/
│   ├── db.py                   # SQLite 接続 + 基本クエリユーティリティ
│   └── tools/
│       ├── screener.py         # screen_stocks（空リスト返し）
│       ├── financials.py       # get_financials, compare_companies
│       ├── metadata.py         # get_company_info, list_sectors
│       └── batch_trigger.py    # update_data, check_batch_status（stub）
├── batch/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── init_db.py              # マイグレーション適用スクリプト
│   └── migrations/
│       └── 001_initial.sql     # 全テーブル定義（設計書の SQL そのまま）
├── docker-compose.yml
└── Makefile                    # make init, make build を追加
```

### 検証
```bash
make build && make init
```
Claude から全ツールを呼んで「データがありません」系のレスポンスが返ることを確認する。

---

## Phase 3: EDINET コードリスト → companies テーブル

**目標:** `companies` テーブルに ~4,000 社が入り、企業検索が動く

### 作成ファイル

```
batch/
├── edinet.py                   # fetch_company_list() のみ実装
└── run.py                      # --mode init-companies のみ対応
```

### 実装詳細
- EDINET コードリスト CSV を取得し `companies` テーブルへ upsert
- `edinet_code`, `sec_code`, `company_name`, `sector`, `market` を格納
- レート制限対策: `time.sleep(1)`

### 検証
```bash
docker compose run --rm batch python run.py --mode init-companies
make db-stats   # 企業数が ~4,000 件になること
```
Claude から「任天堂の情報を教えて」と聞いて実データが返ることを確認する。

---

## Phase 4: XBRL 財務データ取得

**目標:** `financials` テーブルが埋まり、財務スクリーニングが動く（EDINET API キー必要）

### 作成ファイル

```
batch/
├── edinet.py           # fetch_document_list(), download_xbrl_zip() を追加
├── xbrl_parser.py      # TAG_CANDIDATES + コンテキスト判定 + 派生指標計算
└── run.py              # --mode initial / update + ギャップ検出ロジック
```

### 実装詳細
- `edinet.py`: 書類一覧 API (`/api/v2/documents.json`) + ZIP ダウンロード
- `xbrl_parser.py`:
  - `TAG_CANDIDATES`（設計書の定義をそのまま使用）
  - `CONTEXT_PRIORITY` / `CONTEXT_INSTANT_PRIORITY` でコンテキスト判定（連結優先）
  - 派生指標（利益率・ROE/ROA・安全性指標等）を計算して保存
  - ネットキャッシュ `approximate` フラグ
  - XBRL 失敗時は `logger.warning` + スキップして続行
- `run.py`: `detect_fetch_range()` でギャップ検出（設計書のロジックそのまま）

### テスト戦略（段階的）

1. 任天堂（7974）1社で動作確認
2. 半導体セクター（~50社）で確認
3. 全社初回バッチ（8〜15時間、デタッチ実行）

```bash
docker compose run --rm batch python run.py --mode update --sec-code 7974
```
Claude から「任天堂の過去5年の売上と営業利益を教えて」に実データが返ることを確認する。

---

## Phase 5: yfinance 株価データ取得

**目標:** `prices` テーブルが埋まり、PER / PBR 込みスクリーニングが動く

### 作成ファイル

```
batch/
└── price_fetcher.py
```

### 実装詳細
- `yfinance.Ticker("{sec_code}.T").info` から以下を取得:
  `currentPrice`, `marketCap`, `trailingPE`, `priceToBook`, `dividendYield`, `trailingEps`, `bookValue`
- PSR・配当性向は取得後に計算（`financials.revenue` を JOIN）
- レート調整: `time.sleep(0.5)`
- `prices` テーブルに upsert（`edinet_code`, `fetched_at` で UNIQUE）

### 検証
Claude から「ROE 20%以上、PER 20倍以下の銘柄を教えて」でバリュエーション込みの結果が返ることを確認する。

---

## Phase 6: バッチトリガー MCP ツール

**目標:** Claude Desktop からバッチの起動・進捗確認ができる

### 実装ファイル

```
app/tools/batch_trigger.py      # update_data, check_batch_status の本実装
```

### 実装詳細
- `update_data`:
  - `sector` 指定あり → `subprocess` で同期実行、完了後に結果を返す
  - `sector=None` → `docker compose run -d --rm batch` で非同期実行 → `"status": "started"` を即返却
- `check_batch_status`: `batch_log` テーブル + `data/batch_progress.json` から進捗を返す

### 検証
```bash
# 同期実行
# Claude から「半導体セクターのデータを更新して」→ 完了メッセージ

# 非同期実行
# Claude から「全銘柄を更新して」→ 開始メッセージ + 進捗確認の案内
```

---

## Phase 7: バックアップ・リストア

**目標:** `backup_db` / `restore_db` / `list_backups` MCP ツールが動く

### 作成ファイル

```
batch/backup.py
app/tools/db_ops.py     # backup_db, restore_db, list_backups
```

### 実装詳細
- `backup_local(tag)`: `shutil.copy2` で `data/backups/stocks_YYYYMMDD_HHMMSS_{tag}.db`
- 世代管理: 直近5件のみ保持
- `backup_to_s3()`: `boto3` + `S3_BUCKET` 環境変数（未設定時はスキップ）
- バッチ前後の自動バックアップを `run.py` に組み込み

### 検証
```bash
# Claude から「DBをバックアップして」→ ローカルバックアップ作成
make backups    # バックアップ一覧が表示される
```

---

## Phase 8: 有報 PDF ツール

**目標:** 有報の任意セクションをテキスト取得し、表ページは PDF で直接読める

### 実装ファイル

```
app/tools/annual_report.py
```

### 実装詳細

**`get_annual_report_section`**:
1. `companies` テーブルで `sec_code` → `edinet_code` を逆引き
2. EDINET 書類一覧 API で `docTypeCode=120`（有報）の最新 `doc_id` を取得
3. EDINET からオンデマンドで ZIP をダウンロード（`type=2`）
4. `pymupdf`（fitz）でキーワード検索 → マッチしたページ番号を特定
5. テキスト抽出 + `has_table` フラグを返す（`SECTION_KEYWORDS` で正規化）

**`get_annual_report_pages`**:
1. 同一 ZIP から指定ページを抽出
2. `pymupdf` でページを分割 → base64 エンコード
3. MCP `document` コンテンツとして返す

- PDF は**オンデマンド取得のみ**（ローカルキャッシュなし）
- `pymupdf` を `app/pyproject.toml` の依存に追加

### 検証
Claude から「任天堂の有報の事業内容を教えて」でテキストが返り、`has_table=true` のときに PDF ページが自動取得されることを確認する。

---

## Phase 9: 仕上げ

**目標:** 初見でも使えるドキュメントと Claude スキルの完成

### 作成・更新ファイル

```
skills/stock-analysis/SKILL.md  # 設計書の SKILL.md をそのまま配置
README.md                       # セットアップ手順
Makefile                        # 全コマンド整備
```

### Claude Desktop 最終設定（`claude_desktop_config.json`）

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

## 重要ファイル一覧

| ファイル | 役割 |
|---------|------|
| `app/server.py` | MCP サーバーエントリーポイント |
| `app/db.py` | SQLite 接続・クエリユーティリティ |
| `app/tools/screener.py` | `screen_stocks` |
| `app/tools/financials.py` | `get_financials`, `compare_companies` |
| `app/tools/metadata.py` | `get_company_info`, `list_sectors` |
| `app/tools/batch_trigger.py` | `update_data`, `check_batch_status` |
| `app/tools/annual_report.py` | `get_annual_report_section`, `get_annual_report_pages` |
| `batch/edinet.py` | EDINET API 取得（コードリスト・書類一覧・ZIP DL） |
| `batch/xbrl_parser.py` | XBRL 解析 + 派生指標計算 |
| `batch/price_fetcher.py` | yfinance 株価・指標取得 |
| `batch/init_db.py` | マイグレーション適用 |
| `batch/backup.py` | ローカル + S3 バックアップ |
| `batch/run.py` | バッチ実行エントリーポイント |
| `batch/migrations/001_initial.sql` | 全テーブル DDL |

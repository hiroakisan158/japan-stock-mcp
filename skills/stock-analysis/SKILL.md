# 日本株 財務分析スキル

このスキルは `japan-stocks` MCP サーバーを使って日本株の財務分析・銘柄スクリーニングを行います。

---

## 利用可能なツール

| ツール | 説明 |
|--------|------|
| `screen_stocks` | 財務指標で銘柄をフィルタリング |
| `get_financials` | 企業の財務データを時系列で取得 |
| `compare_companies` | 複数企業の財務指標を横並び比較 |
| `get_company_info` | 企業の基本情報・最新財務サマリー |
| `list_sectors` | セクター一覧と各セクターの銘柄数 |
| `get_annual_report_section` | 有価証券報告書のセクションをテキスト取得 |
| `get_annual_report_pages` | 有報の指定ページを PDF で取得（表・図）|
| `update_data` | EDINET から財務データを更新 |
| `update_prices` | yfinance で株価・バリュエーションを更新 |
| `check_batch_status` | バッチの進捗状況を確認 |
| `backup_db` | DB をバックアップ |
| `list_backups` | バックアップ一覧を表示 |
| `restore_db` | バックアップから DB をリストア |

---

## よく使う分析パターン

### バリュー株スクリーニング
```
ROE 15%以上、PER 15倍以下、PBR 1.5倍以下の銘柄を探して
→ screen_stocks(roe_min=15, per_max=15, pbr_max=1.5, sort_by="roe")
```

### セクター絞り込み
```
半導体セクターで営業利益率20%以上の銘柄は？
→ screen_stocks(sector="電気機器", op_margin_min=20, sort_by="op_margin")
```

### 企業の財務トレンド分析
```
任天堂の過去5年の業績推移を教えて
→ get_financials(sec_code="7974", years=5)
```

### 同業他社比較
```
トヨタ・ホンダ・日産を財務指標で比較して
→ compare_companies(sec_codes=["7203", "7267", "7201"])
```

### 有報からビジネス理解
```
任天堂の有報で事業内容を確認して
→ get_annual_report_section(sec_code="7974", section="事業内容")

表が含まれるページはPDFで直接確認
→ get_annual_report_pages(sec_code="7974", pages=[5, 6])
```

### データ更新
```
電気機器セクターのデータを更新して
→ update_data(sector="電気機器")

電気機器セクターの株価を更新して
→ update_prices(sector="電気機器")
```

---

## 指標の単位と注意点

- `revenue`, `operating_income`, `net_income`: 円（例: 1兆円 = 1,000,000,000,000）
- `roe`, `roa`, `equity_ratio`, `operating_profit_margin`: % 表示（例: 15.5 = 15.5%）
- `per`, `pbr`: 倍
- `dividend_yield`: % 表示
- `screen_stocks` の `revenue_min`: **百万円**単位で指定（1兆円 = 1,000,000）

---

## データソース

- 財務データ: EDINET（金融庁・有価証券報告書 XBRL）
- 株価・バリュエーション: yfinance（Yahoo Finance）
- 対象: 東証上場の有報提出企業 約3,800社
- 更新頻度: 手動実行（`update_data` / `update_prices` ツール）

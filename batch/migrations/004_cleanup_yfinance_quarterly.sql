-- Phase 1: yfinance 由来の四半期レコードを削除（J-Quants データで置き換えるため）
DELETE FROM financials WHERE source = 'yfinance' AND quarter IS NOT NULL;

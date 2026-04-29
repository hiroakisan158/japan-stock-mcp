-- quarter IS NULL の重複行を削除（最新の id のみ残す）
DELETE FROM financials
WHERE id NOT IN (
    SELECT MAX(id)
    FROM financials
    GROUP BY edinet_code, period_end, COALESCE(quarter, -1)
);

-- 年次レコード（quarter IS NULL）の一意性を保証する partial unique index
CREATE UNIQUE INDEX IF NOT EXISTS idx_financials_annual_unique
    ON financials(edinet_code, period_end)
    WHERE quarter IS NULL;

-- Add native currency for multi-market stock_prices (USD / INR).
ALTER TABLE stock_prices ADD COLUMN IF NOT EXISTS currency TEXT;

UPDATE stock_prices
SET currency = CASE WHEN symbol LIKE '%.NS' THEN 'INR' ELSE 'USD' END
WHERE currency IS NULL OR TRIM(currency) = '';

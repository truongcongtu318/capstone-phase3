-- product-reviews AIO02 guardrails upgrade — schema migration
--
-- RUN THIS BEFORE DEPLOYING THE NEW IMAGE. database.py queries
-- "... AND is_safe = TRUE"; if the column does not exist yet, every read of
-- product reviews fails immediately on the new pods.
--
-- Target: RDS techx-tf3-postgres, schema `reviews`, table `productreviews`.
-- This table is in a database SHARED with product-catalog and accounting — run
-- during a low-traffic window and verify each step.
--
-- NOTE ON STEP 2: it uses CREATE INDEX CONCURRENTLY, which CANNOT run inside a
-- transaction block. Do NOT wrap this file in BEGIN/COMMIT, and do NOT execute it
-- through a driver that opens an implicit transaction (psycopg2 does by default —
-- it needs autocommit, see db_migration_worker.py). Prefer running the steps by
-- hand with psql, checking each one, rather than piping the whole file blindly.

-- Step 1: Add is_safe column. Safe/online on PostgreSQL >= 11 — a column with a
-- non-volatile DEFAULT no longer rewrites the whole table; the lock is brief.
ALTER TABLE reviews.productreviews ADD COLUMN IF NOT EXISTS is_safe BOOLEAN DEFAULT TRUE;

-- Step 2: Composite index for (product_id, is_safe) lookups.
-- CONCURRENTLY so the build does not take a write lock on a table that
-- product-catalog/accounting also touch. Slower, but does not block writes.
-- If this ever fails midway it can leave an INVALID index behind — check with
--   SELECT indexrelid::regclass, indisvalid FROM pg_index
--   WHERE indexrelid = 'reviews.productreviews_prod_safe_idx'::regclass;
-- and DROP INDEX CONCURRENTLY before retrying.
CREATE INDEX CONCURRENTLY IF NOT EXISTS productreviews_prod_safe_idx
    ON reviews.productreviews (product_id, is_safe);

-- Step 3: Audit table for the asynchronous fidelity/judge logging path.
CREATE TABLE IF NOT EXISTS reviews.fidelity_audit (
    id SERIAL PRIMARY KEY,
    product_id VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    approved BOOLEAN NOT NULL,
    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL,
    response TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Step 4: Grant on the new table. `otelu` is the application user in
-- DB_CONNECTION_STRING (confirmed against src/postgresql/init.sql). The original
-- schema grant covered only tables existing at that time, so this new table needs
-- its own grant. The audit path also needs the sequence to INSERT via SERIAL.
GRANT SELECT, INSERT, UPDATE ON reviews.fidelity_audit TO otelu;
GRANT USAGE, SELECT ON SEQUENCE reviews.fidelity_audit_id_seq TO otelu;

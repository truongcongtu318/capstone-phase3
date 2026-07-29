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

-- Step 5: Tier-2 static summary store (product-reviews Sprint 3, Release A).
-- Giữ bản tóm tắt canonical gần nhất đã được judge duyệt, để phục vụ khi Bedrock
-- lỗi / circuit breaker OPEN / rate-limit / timeout. Additive: image cũ không đọc
-- bảng này, nên rollback image không cần drop table.
--
-- Khoá theo product_id: một sản phẩm giữ đúng MỘT bản tóm tắt canonical. Vì vậy
-- runtime chỉ persist câu trả lời cho câu hỏi dạng summary (is_summary_request) —
-- nếu không, câu trả lời hẹp ("có chống nước không?") sẽ ghi đè bản tóm tắt.
-- review_version = get_review_version() lúc sinh câu trả lời; fallback so giá trị
-- này với version hiện tại và bỏ qua row đã cũ (không có TTL, freshness theo version).
-- rating_distribution: giữ chỗ theo contract AIO, LUÔN NULL ở Release A (chưa caller nào ghi).
CREATE TABLE IF NOT EXISTS reviews.product_summaries (
    product_id VARCHAR(50) PRIMARY KEY,
    summary_text TEXT NOT NULL,
    rating_distribution TEXT,
    review_version VARCHAR(100),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Step 6: Grant cho `otelu`. Least privilege — runtime chỉ SELECT + upsert
-- (INSERT ... ON CONFLICT DO UPDATE). KHÔNG cấp DELETE: không có use case xoá ở
-- Release A, và row cũ đã được vô hiệu hoá bằng review_version chứ không bằng xoá.
-- PK là product_id (không phải SERIAL) nên không cần grant sequence.
GRANT SELECT, INSERT, UPDATE ON reviews.product_summaries TO otelu;

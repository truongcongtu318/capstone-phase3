#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# Python
import os
import hashlib
try:
    import simplejson as json
except ImportError:  # pragma: no cover - local unit-test fallback
    import json

# Postgres
import psycopg2
from psycopg2.pool import PoolError, ThreadedConnectionPool

import time
import logging

logger = logging.getLogger("database")

def must_map_env(key: str):
    value = os.environ.get(key)
    if value is None:
        raise Exception(f'{key} environment variable must be set')
    return value

db_connection_str = os.environ.get('DB_CONNECTION_STRING', '')
db_pool = None

# REL-05 sizing. This RDS is SHARED with product-catalog and accounting, and REL-05
# records connection exhaustion on it as a past incident cause.
#
# Measured 29/07/2026: the instance is db.t4g.micro (1 GiB), and the parameter group
# sets max_connections = LEAST({DBInstanceClassMemory/9531392},5000) => ~112 total
# for ALL services combined. product-catalog alone already sets SetMaxOpenConns(20)
# with an HPA ceiling of 8 pods (up to 160), so the cluster is already
# over-subscribed at theoretical max scale — this is a known latent risk, not
# something this service should make worse.
#
# The upstream AIO02 branch hardcodes minconn=5/maxconn=30: at product-reviews' HPA
# ceiling of 6 pods that is up to 180 connections from this service alone, well over
# the whole instance budget. So the default here stays at 10 — the value already
# running in production (REL-05) and known good — rather than any increase. Both are
# env-tunable so they can be adjusted WITHOUT an image rebuild if the instance is
# ever resized or the per-service budget is re-cut. Raise together with
# GRPC_MAX_WORKERS in product_reviews_server.py, never alone.
DB_POOL_MIN_CONN = int(os.environ.get('DB_POOL_MIN_CONN', '1'))
DB_POOL_MAX_CONN = int(os.environ.get('DB_POOL_MAX_CONN', '10'))

def init_db_pool(retries: int = 5, delay: float = 2.0):
    global db_pool
    if not db_connection_str:
        raise RuntimeError('DB_CONNECTION_STRING environment variable must be set')
    for attempt in range(1, retries + 1):
        try:
            db_pool = ThreadedConnectionPool(
                minconn=DB_POOL_MIN_CONN, maxconn=DB_POOL_MAX_CONN, dsn=db_connection_str
            )
            logger.info(
                f"[DATABASE] Connection pool initialized successfully "
                f"(minconn={DB_POOL_MIN_CONN}, maxconn={DB_POOL_MAX_CONN})."
            )
            return db_pool
        except Exception as e:
            logger.warning(f"[DATABASE] Connection pool init attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    # Final attempt or fallback creation
    db_pool = ThreadedConnectionPool(minconn=1, maxconn=DB_POOL_MAX_CONN, dsn=db_connection_str)
    return db_pool

try:
    init_db_pool()
except Exception as exc:
    logger.error(f"[DATABASE] Initial pool creation error: {exc}")


def get_db_connection():
    """Retrieve connection from pool with auto-reconnection retry."""
    global db_pool
    if db_pool is None or db_pool.closed:
        init_db_pool()
    try:
        conn = db_pool.getconn()
        if conn.closed != 0:
            db_pool.putconn(conn, close=True)
            conn = db_pool.getconn()
        return conn
    except PoolError:
        # Pool EXHAUSTED is not a broken pool — every connection is simply in use.
        # Rebuilding here (as the upstream AIO02 code did) would abandon the old
        # pool WITHOUT closing it, leaking maxconn live connections, and would do so
        # repeatedly under sustained load. On a shared RDS that is exactly the REL-05
        # connection-exhaustion failure mode, and it would take product-catalog and
        # accounting down with us. Fail this one request instead; the caller's error
        # path and the gRPC deadline handle it, and the pool recovers on its own as
        # in-flight requests return connections.
        logger.warning(
            "[DATABASE] Connection pool exhausted (maxconn=%s). Failing this request "
            "rather than rebuilding the pool.", DB_POOL_MAX_CONN
        )
        raise
    except Exception as e:
        # A genuinely broken pool (e.g. the DB went away). Close the old one before
        # replacing it so its sockets are not leaked.
        logger.warning(f"[DATABASE] Pool connection failed, re-initializing pool: {e}")
        old_pool = db_pool
        if old_pool is not None:
            try:
                old_pool.closeall()
            except Exception as close_exc:
                logger.warning(f"[DATABASE] Error closing old pool: {close_exc}")
        init_db_pool()
        return db_pool.getconn()


def fetch_product_reviews(product_id):
    try:
        return json.dumps(fetch_product_reviews_from_db(product_id), use_decimal=True)
    except Exception as e:
        return json.dumps({"error": str(e)})

def fetch_product_reviews_from_db(request_product_id):

    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Define the SQL query
            query = "SELECT username, description, score FROM reviews.productreviews WHERE product_id= %s AND is_safe = TRUE"

            # Execute the query
            cursor.execute(query, (request_product_id, ))

            # Fetch all the rows from the query result
            records = cursor.fetchall()
        connection.commit()
        return records

    except Exception as e:
        if connection is not None:
            connection.rollback()
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)

def fetch_avg_product_review_score_from_db(request_product_id):

    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Define the SQL query
            query = "SELECT AVG(score) FROM reviews.productreviews WHERE product_id= %s AND is_safe = TRUE"

            # Execute the query
            cursor.execute(query, (request_product_id, ))

            # Fetch all the rows from the query result
            records = cursor.fetchall()

            # Extract the average score
            if records:
                # records will be a list like [(average_score,)]
                average_score = records[0][0]
            else:
                # Handle the case where no records are returned (e.g., no reviews for the product)
                average_score = None

            # return the score as a string rounded to 1 decimal place
            result = f"{average_score:.1f}"
        connection.commit()
        return result

    except Exception as e:
        if connection is not None:
            connection.rollback()
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)

def get_review_version(product_id: str) -> str:
    """Tính mã phiên bản review dựa trên count + max id.
    Khi có review mới hoặc review bị đánh dấu unsafe → version thay đổi → Cache Miss tự động.
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            query = """
                SELECT COUNT(*), COALESCE(MAX(id), 0)
                FROM reviews.productreviews
                WHERE product_id = %s AND is_safe = TRUE
            """
            cursor.execute(query, (product_id,))
            count, max_id = cursor.fetchone()
        connection.commit()
        raw = f"{product_id}:{count}:{max_id}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]
    except Exception as e:
        if connection is not None:
            connection.rollback()
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)


def save_product_summary(product_id: str, summary_text: str, rating_distribution: str = None,
                         review_version: str = None) -> bool:
    """Upsert bản tóm tắt đã được duyệt vào reviews.product_summaries (Tier-2 fallback store).

    Chỉ được gọi cho canonical summary đã qua judge — xem _should_persist trong
    product_reviews_server.py. `review_version` là giá trị get_review_version() tại thời
    điểm sinh câu trả lời; nó là thứ quyết định summary còn dùng được hay đã cũ khi fallback.
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            query = """
                INSERT INTO reviews.product_summaries
                    (product_id, summary_text, rating_distribution, review_version, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (product_id)
                DO UPDATE SET
                    summary_text = EXCLUDED.summary_text,
                    rating_distribution = EXCLUDED.rating_distribution,
                    review_version = EXCLUDED.review_version,
                    updated_at = CURRENT_TIMESTAMP;
            """
            cursor.execute(query, (product_id, summary_text, rating_distribution, review_version))
        connection.commit()
        logger.info("[DATABASE] Saved static summary for product_id: %s", product_id)
        return True
    except Exception as e:
        if connection is not None:
            connection.rollback()
        logger.error("[DATABASE] Error saving product summary for product_id %s: %s", product_id, e)
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)


def fetch_product_summary_from_db(product_id: str) -> dict | None:
    """Đọc bản tóm tắt tĩnh đã lưu (Tier-2 fallback). None nếu chưa có.

    Trả cả `review_version` — caller PHẢI so nó với get_review_version(product_id) trước
    khi phục vụ, nếu không sẽ trả tóm tắt đã lỗi thời so với tập review hiện tại.
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            query = """
                SELECT product_id, summary_text, rating_distribution, review_version, updated_at
                FROM reviews.product_summaries
                WHERE product_id = %s
            """
            cursor.execute(query, (product_id,))
            row = cursor.fetchone()
        connection.commit()
        if row:
            return {
                "product_id": row[0],
                "summary_text": row[1],
                "rating_distribution": row[2],
                "review_version": row[3],
                "updated_at": row[4],
            }
        return None
    except Exception as e:
        if connection is not None:
            connection.rollback()
        logger.error("[DATABASE] Error fetching product summary for product_id %s: %s", product_id, e)
        raise e
    finally:
        if connection is not None:
            db_pool.putconn(connection)

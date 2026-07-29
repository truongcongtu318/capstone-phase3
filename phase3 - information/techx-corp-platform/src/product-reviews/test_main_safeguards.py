"""
test_main_safeguards.py
=======================
Chốt các safeguard reliability đang có trên `main` mà nhánh AIO đã gỡ.

Nhánh feature/product-review đã bỏ readiness DB-aware (REL-02), bỏ semaphore admission
(PM-0016) và bỏ xử lý PoolError (REL-05). Đợt port Sprint 3 này giữ cả ba, nhưng chúng
sẽ còn bị đề nghị gỡ ở các đợt port sau. Trước đây không test nào bảo vệ chúng — nên
việc gỡ diễn ra âm thầm. Các test dưới đây làm việc đó thành lỗi CI, có kèm lý do.
"""

import sys
import os
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psycopg2.pool import PoolError

import database
import product_reviews_server as srv


class TestDependencyAwareReadiness(unittest.TestCase):
    """REL-02: pod không tới được RDS phải bị rút khỏi Service endpoints.

    Readiness probe trong values-prod.yaml là gRPC health check vào chính Check().
    Trả SERVING vô điều kiện sẽ khiến pod hỏng DB vẫn nhận traffic nó chỉ có thể fail.
    """

    def setUp(self):
        self.service = srv.ProductReviewService()
        srv.shutdown_event.clear()

    def tearDown(self):
        srv.shutdown_event.clear()

    def test_healthy_db_reports_serving(self):
        with patch.object(srv, "fetch_avg_product_review_score_from_db", return_value=4.5):
            response = self.service.Check(MagicMock(), MagicMock())
        self.assertEqual(response.status, srv.health_pb2.HealthCheckResponse.SERVING)

    def test_db_failure_reports_not_serving(self):
        with patch.object(
            srv, "fetch_avg_product_review_score_from_db", side_effect=Exception("RDS unreachable")
        ):
            response = self.service.Check(MagicMock(), MagicMock())
        self.assertEqual(response.status, srv.health_pb2.HealthCheckResponse.NOT_SERVING)

    def test_shutdown_reports_not_serving_without_touching_db(self):
        """Sau SIGTERM phải NOT_SERVING ngay để k8s drain trước khi server dừng nhận việc."""
        srv.shutdown_event.set()
        with patch.object(srv, "fetch_avg_product_review_score_from_db") as mock_db:
            response = self.service.Check(MagicMock(), MagicMock())
        self.assertEqual(response.status, srv.health_pb2.HealthCheckResponse.NOT_SERVING)
        mock_db.assert_not_called()

    def test_service_itself_is_the_health_servicer(self):
        """Phải đăng ký servicer của ta, không phải HealthServicer tĩnh của grpc_health.

        Bản tĩnh luôn trả SERVING bất kể DB, làm probe DB-aware thành vô nghĩa.
        """
        self.assertTrue(hasattr(srv.ProductReviewService, "Check"))
        self.assertTrue(hasattr(srv.ProductReviewService, "Watch"))


class TestAiAdmissionControl(unittest.TestCase):
    """PM-0016: giới hạn đồng thời AI, shed nhanh, không chiếm hết gRPC worker."""

    def test_semaphore_exists_with_bounded_capacity(self):
        self.assertIsInstance(srv.ai_assistant_semaphore, threading.BoundedSemaphore().__class__)
        self.assertGreater(srv.AI_ASSISTANT_MAX_CONCURRENCY, 0)

    def test_admission_wait_stays_short(self):
        """Request không xin được slot vẫn chiếm gRPC worker của nó trong đúng khoảng chờ này.

        Frontend PRODUCT_REVIEWS_DEADLINE_MS là 500ms; chờ nhận vào phải nhỏ hơn hẳn.
        Bản feature thay bằng future.result(timeout=15.0) — chậm hơn 300 lần.
        """
        self.assertLessEqual(srv.AI_ASSISTANT_ADMISSION_TIMEOUT_SECONDS, 0.5)

    def test_shed_returns_fallback_and_counts_metric(self):
        service = srv.ProductReviewService()
        request = MagicMock(product_id="PROD001", question="Summarize the reviews")
        metrics = {"app_ai_fallback_total": MagicMock(), "app_ai_assistant_counter": MagicMock()}

        with patch.object(srv, "product_review_svc_metrics", metrics), \
             patch.object(srv.ai_assistant_semaphore, "acquire", return_value=False), \
             patch.object(srv, "get_ai_assistant_response") as mock_ai:
            response = service.AskProductAIAssistant(request, MagicMock())

        self.assertEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)
        mock_ai.assert_not_called()
        labels = metrics["app_ai_fallback_total"].add.call_args[0][1]
        self.assertEqual(labels["source"], "admission_control")

    def test_semaphore_released_when_handler_raises(self):
        service = srv.ProductReviewService()
        request = MagicMock(product_id="PROD001", question="Summarize the reviews")

        with patch.object(srv, "get_ai_assistant_response", side_effect=Exception("boom")), \
             patch.object(srv, "product_review_svc_metrics", {
                 "app_ai_fallback_total": MagicMock(), "app_ai_assistant_counter": MagicMock()
             }):
            with self.assertRaises(Exception):
                service.AskProductAIAssistant(request, MagicMock())

        # Rò rỉ slot ở đây sẽ làm service tự bóp nghẹt sau đúng N lần lỗi.
        self.assertTrue(srv.ai_assistant_semaphore.acquire(timeout=0.1))
        srv.ai_assistant_semaphore.release()


class TestConnectionPoolSafety(unittest.TestCase):
    """REL-05: pool cạn KHÁC pool hỏng. Không được dựng lại pool khi chỉ là cạn."""

    def test_pool_exhaustion_raises_without_rebuilding(self):
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.side_effect = PoolError("connection pool exhausted")

        with patch.object(database, "db_pool", mock_pool), \
             patch.object(database, "init_db_pool") as mock_init:
            with self.assertRaises(PoolError):
                database.get_db_connection()

        # Dựng lại ở đây sẽ bỏ rơi pool cũ mà không đóng -> rò maxconn connection mỗi lần,
        # và trên RDS dùng chung sẽ kéo sập cả product-catalog lẫn accounting.
        mock_init.assert_not_called()
        mock_pool.closeall.assert_not_called()

    def test_broken_pool_is_closed_before_rebuild(self):
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.side_effect = Exception("server closed the connection unexpectedly")

        with patch.object(database, "db_pool", mock_pool), \
             patch.object(database, "init_db_pool") as mock_init:
            try:
                database.get_db_connection()
            except Exception:
                pass

        mock_pool.closeall.assert_called_once()
        mock_init.assert_called_once()

    def test_pool_sizing_defaults_stay_conservative(self):
        """RDS db.t4g.micro dùng chung chỉ ~112 connection, HPA tối đa 6 pod.

        Bản feature hardcode 5/30 (=180 conn ở trần HPA). Giữ mặc định thấp và env-tunable.
        """
        self.assertLessEqual(database.DB_POOL_MAX_CONN, 15)
        self.assertLessEqual(database.DB_POOL_MIN_CONN, database.DB_POOL_MAX_CONN)


class TestFlagdReadsPreserved(unittest.TestCase):
    """Luật cấm của dự án: không được gỡ đường đọc flag từ flagd.

    BTC bơm sự cố qua các flag này; gỡ chúng là disqualify cả TF.
    """

    def test_check_feature_flag_helper_exists(self):
        self.assertTrue(callable(srv.check_feature_flag))

    def test_both_injection_flags_are_still_read(self):
        source_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "product_reviews_server.py"
        )
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('check_feature_flag("llmInaccurateResponse")', source)
        self.assertIn('check_feature_flag("llmRateLimitError")', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

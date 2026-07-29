"""
test_fallback_tier2.py
======================
Tier-2 fallback: khi không gọi được LLM, trả bản tóm tắt canonical đã duyệt trong
reviews.product_summaries — NHƯNG chỉ khi review_version của nó còn khớp version hiện
tại. Lệch version / thiếu version / DB lỗi / chưa có row đều phải rơi Tier-3.

Version guard là điểm khác biệt so với bản AIO gốc, vốn trả summary bất kể độ cũ. Một
bản tóm tắt mô tả tập review đã thay đổi là câu trả lời SAI, không phải câu trả lời cũ,
nên fail closed về thông báo tĩnh.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guardrails.error_injection as ei_module
import product_reviews_server as srv

CURRENT_VERSION = "v1_test"


def _base_patches(stack, question="Is this product good?"):
    """Cô lập get_ai_assistant_response khỏi mọi I/O thật.

    get_review_version bị pin về CURRENT_VERSION — đây là mốc mà review_version lưu
    trong DB sẽ được so vào.
    """
    stack.enter_context(patch.object(srv, "check_input", return_value=MagicMock(is_safe=True)))
    stack.enter_context(patch.object(srv, "filter_output", return_value=MagicMock(filtered_response=question)))
    stack.enter_context(patch.object(srv, "is_clearly_off_topic_question", return_value=False))
    stack.enter_context(patch.object(srv, "get_cached_response", return_value=None))
    stack.enter_context(patch.object(srv, "acquire_lock", return_value=True))
    stack.enter_context(patch.object(srv, "release_lock"))
    stack.enter_context(patch.object(srv, "get_review_version", return_value=CURRENT_VERSION))
    stack.enter_context(patch.object(srv, "generate_cache_key", return_value="cache_test"))
    stack.enter_context(patch.object(srv, "is_fallback_override_active", return_value=False))
    stack.enter_context(patch.object(srv, "get_injected_error_type", return_value=None))
    stack.enter_context(patch.object(srv.circuit_breaker, "allow_request", return_value=True))
    stack.enter_context(patch.object(ei_module, "redis_client", None))
    stack.enter_context(patch.object(srv, "write_llm_trace"))
    stack.enter_context(patch.object(srv, "build_runtime_trace_record", return_value={
        "guardrails": {}, "cache": {}, "candidate": {}, "judge": {}
    }))
    stack.enter_context(patch.object(srv, "finalize_runtime_trace", return_value={}))
    metrics = {
        "app_ai_fallback_total": MagicMock(),
        "app_ai_assistant_counter": MagicMock(),
    }
    stack.enter_context(patch.object(srv, "product_review_svc_metrics", metrics))
    mock_tracer = stack.enter_context(patch("product_reviews_server.tracer"))
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: mock_span
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
    return metrics


def _summary_row(summary_text, review_version=CURRENT_VERSION, product_id="PROD001"):
    return {
        "product_id": product_id,
        "summary_text": summary_text,
        "rating_distribution": None,
        "review_version": review_version,
        "updated_at": "2026-07-29 10:00:00",
    }


def _fallback_tier(metrics):
    """Đọc label `tier` của lần add() cuối trên app_ai_fallback_total."""
    return metrics["app_ai_fallback_total"].add.call_args[0][1]["tier"]


class TestTier2VersionGuard(unittest.TestCase):
    """review_version quyết định Tier-2 hay Tier-3."""

    def test_matching_version_serves_tier2(self):
        row = _summary_row("Reviewers praise the lens kit.", review_version=CURRENT_VERSION)
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, "Reviewers praise the lens kit.")
        self.assertEqual(_fallback_tier(metrics), "2")

    def test_stale_version_falls_through_to_tier3(self):
        """Đây chính là hành vi bản AIO gốc khẳng định ngược lại."""
        row = _summary_row("Summary written against an older review set.", review_version="v0_old")
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)
        self.assertEqual(_fallback_tier(metrics), "3")

    def test_null_version_falls_through_to_tier3(self):
        """Row ghi trước khi có version guard: không chứng minh được độ tươi -> không phục vụ."""
        row = _summary_row("Legacy summary with no version recorded.", review_version=None)
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)
        self.assertEqual(_fallback_tier(metrics), "3")


class TestTier2Availability(unittest.TestCase):
    """Bảng rỗng và DB lỗi đều phải suy biến về hành vi trước khi có Tier-2."""

    def test_missing_row_returns_tier3(self):
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=None))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)
        self.assertEqual(_fallback_tier(metrics), "3")

    def test_db_error_returns_tier3(self):
        """Bảng chưa migrate hoặc pool cạn: nuốt lỗi, không lan ra người dùng."""
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(
                srv, "fetch_product_summary_from_db",
                side_effect=Exception('relation "reviews.product_summaries" does not exist'),
            ))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)
        self.assertEqual(_fallback_tier(metrics), "3")

    def test_version_lookup_error_returns_tier3(self):
        """Có row nhưng không tính được version hiện tại -> không thể xác nhận tươi."""
        row = _summary_row("Summary we cannot validate.")
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="429"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            stack.enter_context(patch.object(srv, "get_review_version", side_effect=Exception("db down")))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, srv.FALLBACK_SUMMARY_MESSAGE)
        self.assertEqual(_fallback_tier(metrics), "3")


class TestTier2AcrossFallbackTriggers(unittest.TestCase):
    """Mọi đường fallback đều phải đi qua cùng một bộ giải Tier-2/Tier-3."""

    def test_circuit_breaker_open_serves_tier2(self):
        row = _summary_row("Circuit breaker fallback summary.", product_id="PROD002")
        with ExitStack() as stack:
            metrics = _base_patches(stack, question="Summarize the customer reviews")
            stack.enter_context(patch.object(srv.circuit_breaker, "allow_request", return_value=False))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            response = srv.get_ai_assistant_response("PROD002", "Summarize the customer reviews")

        self.assertEqual(response.response, "Circuit breaker fallback summary.")
        self.assertEqual(_fallback_tier(metrics), "2")

    def test_redis_override_serves_tier2(self):
        row = _summary_row("Redis override fallback summary.", product_id="PROD003")
        with ExitStack() as stack:
            metrics = _base_patches(stack, question="Summarize the customer reviews")
            stack.enter_context(patch.object(srv, "is_fallback_override_active", return_value=True))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            response = srv.get_ai_assistant_response("PROD003", "Summarize the customer reviews")

        self.assertEqual(response.response, "Redis override fallback summary.")
        self.assertEqual(_fallback_tier(metrics), "2")

    def test_forced_timeout_serves_tier2(self):
        row = _summary_row("Timeout fallback summary.")
        context = MagicMock()
        context.invocation_metadata.return_value = [("x-force-llm-error", "timeout")]
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?", context)

        self.assertEqual(response.response, "Timeout fallback summary.")
        self.assertEqual(_fallback_tier(metrics), "2")

    def test_injected_circuit_breaker_serves_tier2(self):
        row = _summary_row("Injected CB fallback summary.")
        with ExitStack() as stack:
            metrics = _base_patches(stack)
            stack.enter_context(patch.object(srv, "get_injected_error_type", return_value="circuit_breaker"))
            stack.enter_context(patch.object(srv.circuit_breaker, "record_failure"))
            stack.enter_context(patch.object(srv, "fetch_product_summary_from_db", return_value=row))
            response = srv.get_ai_assistant_response("PROD001", "Is this product good?")

        self.assertEqual(response.response, "Injected CB fallback summary.")
        self.assertEqual(_fallback_tier(metrics), "2")


class TestResolveFallbackSummaryUnit(unittest.TestCase):
    """Gọi thẳng resolve_fallback_summary, không qua gRPC handler."""

    def test_returns_tier_number_alongside_text(self):
        row = _summary_row("Direct call summary.")
        with patch.object(srv, "fetch_product_summary_from_db", return_value=row), \
             patch.object(srv, "get_review_version", return_value=CURRENT_VERSION):
            text, tier = srv.resolve_fallback_summary("PROD001")
        self.assertEqual(text, "Direct call summary.")
        self.assertEqual(tier, 2)

    def test_empty_summary_text_is_not_served(self):
        row = _summary_row("")
        with patch.object(srv, "fetch_product_summary_from_db", return_value=row), \
             patch.object(srv, "get_review_version", return_value=CURRENT_VERSION):
            text, tier = srv.resolve_fallback_summary("PROD001")
        self.assertEqual(text, srv.FALLBACK_SUMMARY_MESSAGE)
        self.assertEqual(tier, 3)

    def test_span_records_tier_attribute(self):
        row = _summary_row("Span-annotated summary.")
        span = MagicMock()
        with patch.object(srv, "fetch_product_summary_from_db", return_value=row), \
             patch.object(srv, "get_review_version", return_value=CURRENT_VERSION):
            srv.resolve_fallback_summary("PROD001", span)
        span.set_attribute.assert_any_call("app.fallback.tier", 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
test_summary_persistence.py
===========================
Điều kiện ghi vào reviews.product_summaries.

Bảng khoá theo product_id nên mỗi sản phẩm chỉ giữ MỘT bản tóm tắt canonical. Vì vậy
chỉ câu hỏi dạng summary mới được persist: nếu không, câu trả lời hẹp ("có chống nước
không?") sẽ ghi đè bản tóm tắt và lần fallback sau trả nhầm nó cho người hỏi "tóm tắt
review". Bản AIO gốc chỉ lọc theo judge_status nên dính đúng lỗi này.

Ghi phải là bất đồng bộ (db_write_executor) và không bao giờ làm hỏng response.
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
SUMMARY_QUESTION = "Can you summarize the customer reviews?"
NARROW_QUESTION = "Is this product waterproof?"


def _patches(stack, question, answer, judge_status, deterministic=False):
    """Chạy get_ai_assistant_response qua nhánh Bedrock tới tận khối finally.

    Hai đường tới persist:
      - deterministic=True  -> answer_deterministic_rating_question trả lời, hàm return
        sớm với judge_status="deterministic" (finally vẫn chạy);
      - deterministic=False -> đi hết đường LLM, apply_runtime_fidelity_gate bị mock để
        chốt thẳng (answer, judge_status).
    Phần đang test là điều kiện persist, không phải bản thân judge hay Bedrock.
    """
    stack.enter_context(patch.object(srv, "llm_provider", "bedrock"))
    stack.enter_context(patch.object(srv, "check_input", return_value=MagicMock(is_safe=True)))
    stack.enter_context(patch.object(srv, "filter_output", return_value=MagicMock(filtered_response=question)))
    stack.enter_context(patch.object(srv, "is_clearly_off_topic_question", return_value=False))
    stack.enter_context(patch.object(srv, "get_cached_response", return_value=None))
    stack.enter_context(patch.object(srv, "set_cached_response"))
    stack.enter_context(patch.object(srv, "should_cache", return_value=False))
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
    stack.enter_context(patch.object(srv, "product_review_svc_metrics", {
        "app_ai_fallback_total": MagicMock(),
        "app_ai_assistant_counter": MagicMock(),
    }))
    stack.enter_context(patch.object(srv, "check_feature_flag", return_value=False))
    stack.enter_context(patch.object(srv, "build_runtime_prompts", return_value=("u", "a", "i")))
    stack.enter_context(patch.object(srv, "build_system_prompt", return_value="sys"))
    stack.enter_context(patch.object(srv, "build_bedrock_user_prompt", return_value="grounded"))
    stack.enter_context(patch.object(srv, "fetch_product_reviews", return_value="[]"))
    stack.enter_context(patch.object(srv, "fetch_product_info", return_value="{}"))
    stack.enter_context(patch.object(srv, "normalize_reviews_for_context", return_value=("[]", [{"score": 5}])))
    stack.enter_context(patch.object(
        srv, "answer_deterministic_rating_question",
        return_value=answer if deterministic else None,
    ))
    stack.enter_context(patch.object(srv, "answer_deterministic_absence_question", return_value=None))
    stack.enter_context(patch.object(srv, "call_candidate_bedrock", return_value=answer))
    stack.enter_context(patch.object(srv, "post_process_output", return_value=answer))
    stack.enter_context(patch.object(
        srv, "apply_runtime_fidelity_gate", return_value=(answer, judge_status)
    ))
    mock_tracer = stack.enter_context(patch("product_reviews_server.tracer"))
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: mock_span
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
    return stack.enter_context(patch.object(srv, "save_product_summary_async"))


class TestPersistenceIntentGate(unittest.TestCase):
    """Gate is_summary_request — điểm khác biệt lớn nhất so với bản AIO gốc."""

    def test_summary_question_approved_is_persisted(self):
        with ExitStack() as stack:
            mock_save = _patches(stack, SUMMARY_QUESTION, "Reviewers love it.", "approved")
            srv.get_ai_assistant_response("PROD001", SUMMARY_QUESTION)

        mock_save.assert_called_once_with("PROD001", "Reviewers love it.", CURRENT_VERSION)

    def test_narrow_question_approved_is_not_persisted(self):
        """Bản AIO gốc GHI row ở đây và làm hỏng bản tóm tắt của sản phẩm."""
        with ExitStack() as stack:
            mock_save = _patches(stack, NARROW_QUESTION, "No reviews mention waterproofing.", "approved")
            srv.get_ai_assistant_response("PROD001", NARROW_QUESTION)

        mock_save.assert_not_called()

    def test_narrow_question_deterministic_is_not_persisted(self):
        """judge_status='deterministic' đến từ router trả lời câu hỏi hẹp.

        Đây là đường rò rỉ chính của bản AIO gốc: "điểm trung bình bao nhiêu?" trả về
        "4.2" và ghi đè bản tóm tắt của sản phẩm.
        """
        with ExitStack() as stack:
            mock_save = _patches(
                stack, NARROW_QUESTION, "The average score is 4.2.", "deterministic",
                deterministic=True,
            )
            srv.get_ai_assistant_response("PROD001", NARROW_QUESTION)

        mock_save.assert_not_called()

    def test_summary_question_deterministic_is_persisted(self):
        with ExitStack() as stack:
            mock_save = _patches(
                stack, SUMMARY_QUESTION, "Reviewers rate it 4.2 on average.", "deterministic",
                deterministic=True,
            )
            srv.get_ai_assistant_response("PROD001", SUMMARY_QUESTION)

        mock_save.assert_called_once_with(
            "PROD001", "Reviewers rate it 4.2 on average.", CURRENT_VERSION
        )


class TestPersistenceStatusGate(unittest.TestCase):
    """Câu trả lời không đáng tin thì không được thành bản tóm tắt canonical."""

    def test_rejected_status_is_not_persisted(self):
        with ExitStack() as stack:
            mock_save = _patches(stack, SUMMARY_QUESTION, "Fabricated claims.", "rejected")
            srv.get_ai_assistant_response("PROD001", SUMMARY_QUESTION)

        mock_save.assert_not_called()

    def test_no_info_message_is_not_persisted(self):
        with ExitStack() as stack:
            mock_save = _patches(stack, SUMMARY_QUESTION, srv.NO_INFO_MESSAGE, "approved")
            srv.get_ai_assistant_response("PROD001", SUMMARY_QUESTION)

        mock_save.assert_not_called()

    def test_unverified_message_is_not_persisted(self):
        with ExitStack() as stack:
            mock_save = _patches(stack, SUMMARY_QUESTION, srv.UNVERIFIED_SUMMARY_MESSAGE, "approved")
            srv.get_ai_assistant_response("PROD001", SUMMARY_QUESTION)

        mock_save.assert_not_called()

    def test_fallback_message_is_not_persisted(self):
        with ExitStack() as stack:
            mock_save = _patches(stack, SUMMARY_QUESTION, srv.FALLBACK_SUMMARY_MESSAGE, "approved")
            srv.get_ai_assistant_response("PROD001", SUMMARY_QUESTION)

        mock_save.assert_not_called()


class TestPersistenceIsNonFatal(unittest.TestCase):
    """Ghi DB hỏng không được kéo theo câu trả lời đã thành công.

    Persist nằm trong khối `finally:` và KHÔNG có try/except ở chỗ gọi — một exception
    thoát ra đây sẽ thay thế giá trị trả về của cả hàm. Toàn bộ lớp bảo vệ nằm trong
    save_product_summary_async, nên nó phải kín tuyệt đối.
    """

    def test_executor_failure_does_not_break_a_successful_answer(self):
        """End-to-end: dùng wrapper THẬT, chỉ làm executor hỏng."""
        with ExitStack() as stack:
            mock_save = _patches(stack, SUMMARY_QUESTION, "Reviewers love it.", "approved")
            stack.enter_context(patch.object(srv, "save_product_summary_async",
                                             srv.save_product_summary_async))
            mock_executor = stack.enter_context(patch.object(srv, "db_write_executor"))
            mock_executor.submit.side_effect = RuntimeError("executor shut down")
            response = srv.get_ai_assistant_response("PROD001", SUMMARY_QUESTION)

        self.assertEqual(response.response, "Reviewers love it.")

    def test_async_wrapper_swallows_submit_errors(self):
        with patch.object(srv, "db_write_executor") as mock_executor:
            mock_executor.submit.side_effect = RuntimeError("executor shut down")
            srv.save_product_summary_async("PROD001", "text", CURRENT_VERSION)

    def test_worker_swallows_db_errors(self):
        """Chạy trên executor nên không ai await — lỗi thoát ra sẽ chìm trong Future."""
        with patch.object(srv, "save_product_summary", side_effect=Exception("RDS unreachable")):
            srv._save_product_summary_safe("PROD001", "text", CURRENT_VERSION)

    def test_async_wrapper_submits_to_db_write_executor(self):
        """Ghi phải nằm ngoài đường request, không đồng bộ trong finally."""
        with patch.object(srv, "db_write_executor") as mock_executor:
            srv.save_product_summary_async("PROD001", "text", CURRENT_VERSION)
        mock_executor.submit.assert_called_once_with(
            srv._save_product_summary_safe, "PROD001", "text", CURRENT_VERSION
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

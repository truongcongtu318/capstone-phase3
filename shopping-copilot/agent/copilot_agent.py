"""
CopilotAgent — Bộ não orchestrator của Shopping Copilot.

Triển khai ReAct tool-calling loop với:
  - Session memory (multi-turn context, sliding window 20 messages)
  - Tool result cache (TTL-based, LRU eviction)
  - 6-layer guardrail pipeline (Rate Limiter → Input Filter → Tool Validator
    → Confirmation Gate → Output Filter → Fallback)
  - Audit log mỗi lần gọi tool
  - AWS Bedrock (Amazon Nova) làm LLM backend
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import grpc
import protos.demo_pb2 as demo_pb2
import protos.demo_pb2_grpc as demo_pb2_grpc

from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from agent.prompts import SYSTEM_PROMPT, CONFIRMATION_PENDING_TEMPLATE
from tools import all_shopping_tools
from guardrails import (
    rate_limiter,
    check_input,
    check_input_bedrock,
    validate_tool_call,
    request_confirmation,
    verify_confirmation_token,
    filter_output,
    with_fallback,
    MAX_TOOL_ITERATIONS,
)
from memory.store import SessionStore, CacheStore

load_dotenv(override=True)

logger = logging.getLogger("copilot_agent")

# ── LLM config — AWS Bedrock (Amazon Nova) ──
_BEDROCK_MODEL = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
_BEDROCK_REGION = os.getenv("BEDROCK_REGION", "ap-southeast-1")


def _build_llm():
    """
    Khởi tạo Bedrock LLM client với ChatBedrockConverse.

    Xác thực qua AWS credential chain:
      - Local dev: AWS_PROFILE hoặc AWS_ACCESS_KEY_ID/SECRET
      - EKS prod:  IAM Role for Service Account (IRSA)
    """
    try:
        return ChatBedrockConverse(
            model=_BEDROCK_MODEL,
            region_name=_BEDROCK_REGION,
            temperature=0.1,
            max_tokens=1024,
        )
    except Exception as e:
        logger.error(f"[AGENT] Không thể khởi tạo Bedrock LLM: {e}")
        return None


# ── Tool map: tên tool → callable ──
_TOOL_MAP = {t.name: t for t in all_shopping_tools}


class CopilotAgent:
    """
    Orchestrator chính của Shopping Copilot.

    Sử dụng:
        agent = CopilotAgent()
        result = agent.chat(session_id="abc", user_id="u123", user_message="Tìm tai nghe")
    """

    def __init__(self):
        self._llm = _build_llm()          # None nếu không có API key
        self._llm_with_tools = (
            self._llm.bind_tools(all_shopping_tools) if self._llm else None
        )
        self._sessions = SessionStore()
        self._cache = CacheStore()

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    @with_fallback
    def chat(self, session_id: str, user_id: str, user_message: str) -> dict:
        """
        Xử lý một lượt hội thoại.

        Returns:
            {
                "status": "ok" | "pending" | "error",
                "reply":  <câu trả lời cuối cùng — string>,
                "token":  <HMAC token nếu status=pending, None otherwise>,
            }
        """
        # ── Lớp 1: Rate Limiter ──
        rate_result = rate_limiter.check_rate_limit(user_id)
        if not rate_result.is_allowed:
            logger.warning(
                "[AGENT] Rate limit blocked | user=%s | reason=%s",
                user_id, rate_result.blocked_reason
            )
            return {
                "status": "error",
                "reply": rate_result.blocked_reason,
                "token": None,
            }

        # ── Lớp 2a: Input Filter — Regex (Tầng 1) ──
        filter_result = check_input(user_message)
        if not filter_result.is_safe:
            logger.warning(
                "[AGENT] Input blocked (Regex) | session=%s | reason=%s",
                session_id, filter_result.blocked_reason
            )
            return {
                "status": "error",
                "reply": filter_result.blocked_reason,
                "token": None,
            }

        # ── Lớp 2b: Input Filter — Bedrock Guardrails (Tầng 2) ──
        bedrock_result = check_input_bedrock(user_message)
        if not bedrock_result.is_safe:
            logger.warning(
                "[AGENT] Input blocked (Bedrock) | session=%s | reason=%s",
                session_id, bedrock_result.blocked_reason
            )
            return {
                "status": "error",
                "reply": bedrock_result.blocked_reason,
                "token": None,
            }

        # ── Lấy session; chặn nếu đang có pending confirmation ──
        session = self._sessions.get_or_create(session_id, user_id)

        if session.get("pending_confirmation", {}).get("token"):
            return {
                "status": "pending",
                "reply": (
                    "⏳ Có một hành động đang chờ xác nhận. "
                    "Vui lòng bấm Xác nhận hoặc Huỷ trước khi tiếp tục."
                ),
                "token": session["pending_confirmation"]["token"],
            }

        # ── Xây dựng message list gửi LLM ──
        messages = self._build_messages(session, user_message)

        # ── ReAct loop ──
        result = self._react_loop(session_id, user_id, messages)

        # ── Lớp 5: Output Filter ──
        if result["status"] == "ok":
            output_res = filter_output(result["reply"])
            result["reply"] = output_res.filtered_response

        # ── Lưu lịch sử ──
        if result["status"] in ("ok", "pending"):
            self._sessions.append_message(session_id, "user", user_message)
            self._sessions.append_message(session_id, "assistant", result["reply"])
            self._sessions.touch(session_id)

        return result

    @with_fallback
    def confirm(self, session_id: str, token: str) -> dict:
        """
        Xác nhận hành động ghi đang chờ (sau khi user bấm nút Xác nhận).

        Returns:
            {"status": "ok"|"error", "reply": <thông báo>}
        """
        is_valid, action_data = verify_confirmation_token(token)
        if not is_valid:
            return {
                "status": "error",
                "reply": "❌ Token không hợp lệ hoặc đã hết hạn (5 phút). Vui lòng thực hiện lại yêu cầu.",
            }

        # Thực thi tool thật
        product_id = action_data.get("params", {}).get("product_id", "?")
        quantity = action_data.get("params", {}).get("quantity", "?")
        user_id = action_data.get("user_id", "?")

        tool_fn = _TOOL_MAP.get("add_to_cart_tool")
        if tool_fn is None:
            return {"status": "error", "reply": "Tool add_to_cart_tool không tồn tại."}

        # Ghi audit log xác nhận
        logger.info(
            '[AUDIT] confirm | session=%s | user=%s | product=%s | qty=%s',
            session_id, user_id, product_id, quantity
        )

        # Gọi trực tiếp gRPC thay vì qua LangChain tool để tránh
        # trigger confirmation gate lần nữa (đã verify token rồi).
        cart_addr = os.getenv("CART_ADDR", "localhost:7070")
        channel = grpc.insecure_channel(cart_addr)
        stub = demo_pb2_grpc.CartServiceStub(channel)
        try:
            cart_item = demo_pb2.CartItem(product_id=product_id, quantity=int(quantity))
            request = demo_pb2.AddItemRequest(user_id=user_id, item=cart_item)
            stub.AddItem(request)
            reply = f"✅ Đã thêm {quantity} sản phẩm '{product_id}' vào giỏ hàng thành công!"
        except grpc.RpcError as e:
            reply = f"❌ Lỗi khi thêm vào giỏ hàng: {e.details()}"
        finally:
            channel.close()

        # Xoá pending confirmation
        self._sessions.clear_pending(session_id)

        return {"status": "ok", "reply": reply}

    # ──────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────

    def _build_messages(self, session: dict, user_message: str) -> list:
        """Xây dựng message list để gửi LLM, gồm system prompt + lịch sử + tin nhắn mới."""
        msgs = [SystemMessage(content=SYSTEM_PROMPT)]

        # Lịch sử hội thoại (sliding window đã được SessionStore xử lý)
        for m in session.get("messages", []):
            role = m["role"]
            content = m["content"]
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                msgs.append(AIMessage(content=content))
            # Tool messages không inject vào đây — chúng được xử lý trong loop

        # Tin nhắn mới nhất
        msgs.append(HumanMessage(content=user_message))
        return msgs

    def _react_loop(self, session_id: str, user_id: str, messages: list) -> dict:
        """
        ReAct loop chính — tối đa MAX_TOOL_ITERATIONS vòng gọi tool.
        Trả về dict với status, reply, token.
        """
        from guardrails.fallback import MaxIterationsExceeded, CopilotServiceError

        if self._llm_with_tools is None:
            raise CopilotServiceError(
                "LLM chưa được cấu hình. Vui lòng kiểm tra AWS credentials và BEDROCK_MODEL_ID.",
                "LLM_NOT_CONFIGURED",
            )

        iteration = 0

        while True:
            # Gọi LLM
            response = self._llm_with_tools.invoke(messages)


            # Nếu LLM không gọi tool → đây là câu trả lời cuối
            if not response.tool_calls:
                final_answer = response.content or "Tôi không có thông tin để trả lời câu hỏi này."
                if isinstance(final_answer, list):
                    text_parts = []
                    for part in final_answer:
                        if isinstance(part, dict) and "text" in part:
                            text_parts.append(part["text"])
                        elif isinstance(part, str):
                            text_parts.append(part)
                        elif hasattr(part, "text"):
                            text_parts.append(part.text)
                        else:
                            text_parts.append(str(part))
                    final_answer = "".join(text_parts)
                return {"status": "ok", "reply": final_answer, "token": None}

            # Kiểm tra giới hạn vòng lặp
            iteration += 1
            if iteration > MAX_TOOL_ITERATIONS:
                raise MaxIterationsExceeded(
                    f"Agent vượt quá {MAX_TOOL_ITERATIONS} vòng lặp tool-calling"
                )

            # Thêm AIMessage chứa tool_calls vào history để LLM tiếp tục
            messages.append(response)

            # Thực thi từng tool call
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_call_id = tool_call["id"]

                logger.info(
                    "[AUDIT] tool_call | session=%s | tool=%s | args=%s | iter=%d",
                    session_id, tool_name, tool_args, iteration
                )

                # ── Lớp 3: Tool Validator ──
                validation = validate_tool_call(tool_name, tool_args, user_id)
                if not validation.is_valid:
                    logger.warning(
                        "[AGENT] Tool call blocked | session=%s | tool=%s | reason=%s",
                        session_id, tool_name, validation.blocked_reason
                    )
                    messages.append(
                        ToolMessage(
                            content=f"[GUARDRAIL] {validation.blocked_reason}",
                            tool_call_id=tool_call_id
                        )
                    )
                    continue

                # ── Lớp 4: Confirmation Gate cho write actions ──
                if tool_name == "add_to_cart_tool":
                    gate_result = request_confirmation(
                        user_id=user_id,
                        action="AddItem",
                        action_params={
                            "product_id": tool_args.get("product_id", ""),
                            "quantity": tool_args.get("quantity", 1),
                        },
                    )

                    if gate_result.status == "DENIED":
                        tool_output = f"[GUARDRAIL] Hành động bị từ chối: {gate_result.message}"
                    elif gate_result.status == "PENDING":
                        # Lưu pending vào session
                        self._sessions.set_pending(
                            session_id=session_id,
                            token=gate_result.confirmation_token,
                            action="AddItem",
                            action_params=gate_result.action_data,
                        )
                        pending_msg = CONFIRMATION_PENDING_TEMPLATE.format(
                            quantity=tool_args.get("quantity", "?"),
                            product_id=tool_args.get("product_id", "?"),
                        )
                        return {
                            "status": "pending",
                            "reply": pending_msg,
                            "token": gate_result.confirmation_token,
                        }
                    else:
                        # APPROVED — không nên xảy ra với add_to_cart nhưng xử lý phòng thủ
                        tool_output = "[INFO] Hành động được phê duyệt nhưng chưa thực thi."
                else:
                    # Read tools — chạy với cache
                    t0 = time.monotonic()
                    tool_output, cache_hit = self._run_tool_cached(tool_name, tool_args)
                    latency_ms = int((time.monotonic() - t0) * 1000)

                    logger.info(
                        "[AUDIT] tool_result | tool=%s | cache_hit=%s | latency_ms=%d | preview=%.80s",
                        tool_name, cache_hit, latency_ms, tool_output
                    )

                # Thêm ToolMessage vào messages để LLM đọc kết quả
                messages.append(
                    ToolMessage(content=str(tool_output), tool_call_id=tool_call_id)
                )

    def _run_tool_cached(self, tool_name: str, tool_args: dict) -> tuple[str, bool]:
        """
        Chạy tool với cache layer.
        Returns: (result_string, cache_hit: bool)
        """
        cached = self._cache.get(tool_name, tool_args)
        if cached is not None:
            return cached, True

        tool_fn = _TOOL_MAP.get(tool_name)
        if tool_fn is None:
            return f"[ERROR] Tool '{tool_name}' không tồn tại.", False

        result = tool_fn.invoke(tool_args)
        self._cache.set(tool_name, tool_args, result)
        return result, False

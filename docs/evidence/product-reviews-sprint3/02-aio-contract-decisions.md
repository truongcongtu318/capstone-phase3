# Decision log — contract Tier-2 / Release A

**Trạng thái:** CDO đã chốt để không chặn release; **AIO02 ký xác nhận ở PR review**.
Mỗi quyết định dưới đây đều đã được hiện thực hoá trong code hoặc schema của PR này —
không có mục nào chỉ nằm trên giấy.

Nguồn câu hỏi: `docs/runbooks/aio02-product-reviews-sprint3-integration-deployment-plan.md` §6.
Cột "chốt" theo cột "Khuyến nghị CDO" của chính tài liệu đó.

---

## 6.1 Contract của PostgreSQL Tier-2

| ID | Câu hỏi | Đã chốt | Hiện thực ở đâu |
|---|---|---|---|
| AIO-01 | Tier-2 dùng cho mọi câu hỏi hay chỉ câu hỏi summary? | **Chỉ canonical summary.** Bảng khoá theo `product_id` nên mỗi sản phẩm giữ đúng một bản tóm tắt; persist mọi câu trả lời sẽ để câu hỏi hẹp ghi đè bản tóm tắt. | Gate `is_summary_request(safe_question)` trong `_should_persist`, `product_reviews_server.py` |
| AIO-02 | Nếu muốn fallback cho mọi câu hỏi thì key là gì? | **Không áp dụng ở Release A** — giữ key `product_id`. Muốn fallback theo từng câu hỏi thì phải đổi key sang `product_id + intent hash + review_version`, là thay đổi schema riêng, không làm cùng change window này. | `migration.sql` Step 5 |
| AIO-03 | Review đổi / bị sửa tại chỗ thì xử lý thế nào? | **Không bao giờ trả row cũ.** So `review_version` lưu kèm với `get_review_version()` hiện tại; lệch hoặc NULL → Tier-3. Fail closed: một bản tóm tắt mô tả tập review đã đổi là câu trả lời SAI, không phải câu trả lời cũ. | `resolve_fallback_summary()` |
| AIO-04 | Bảng rỗng lúc go-live có chấp nhận được không? | **Có, chấp nhận cold start.** Bảng rỗng → mọi request rơi Tier-3, đúng bằng hành vi production hiện tại, nên không có regression. Tự ấm dần khi các câu hỏi summary được duyệt. Không pre-warm. | Hành vi mặc định của `resolve_fallback_summary()` |
| AIO-05 | Kết quả nào được phép persist? | **Chỉ canonical summary đã duyệt.** Yêu cầu `judge_status ∈ {approved, deterministic}` **và** `is_summary_request` **và** không phải fallback/unverified/out-of-scope/no-info. | `_should_persist` |
| AIO-06 | `rating_distribution` có contract gì? | **Giữ cột, LUÔN NULL ở Release A.** Không caller nào ghi. Giữ cột để khỏi phải migrate lần nữa khi AIO chốt format; format là quyết định mở. | `migration.sql` Step 5, ghi rõ trong comment |
| AIO-07 | Retention/refresh của summary? | **Theo version, không theo thời gian.** Row cũ không bao giờ được phục vụ (AIO-03) và bị ghi đè ở lần summary duyệt kế tiếp. Không TTL, không xoá → **không cấp `DELETE`** cho `otelu`. | `migration.sql` Step 6 |

## 6.2 Contract của S6 isolation

| ID | Đã chốt |
|---|---|
| AIO-08…AIO-12 | **N/A ở release này.** Release B (S6) tách hoàn toàn, vẫn OPEN. Bản S6 của AIO không được port: nó gỡ semaphore admission của PM-0016, dùng hàng đợi không giới hạn, chờ 15s trong khi frontend deadline là 500ms, và không cancel future khi timeout. Xem `docs/postmortem/0016-*`. |

## 6.3 AWS, test và observability

| ID | Đã chốt | Hiện thực ở đâu |
|---|---|---|
| AIO-13 | **Bedrock Guardrail ngoài scope.** Không bật trong release này. | `.env.example` giữ `BEDROCK_GUARDRAIL_ID=` rỗng (không lấy ID `3ab7r29x59x4` của nhánh AIO — nó thuộc account khác, bật lên sẽ `AccessDenied` mọi lệnh gọi) |
| AIO-14 | **Chờ AIO cung cấp ARN/region/version hợp lệ trong account `197826770971`**, sẽ làm bằng PR Terraform riêng. | — |
| AIO-15 | **Eval set vẫn thiếu → không port nhóm thay đổi hành vi trả lời AI.** Prompt rewrite, 2 deterministic router mới, ép output tiếng Anh và nới regex off-topic đều bị giữ lại cho PR sau. Release A không đổi nội dung câu trả lời khi LLM khoẻ. | Denylist của PR này |
| AIO-16 | **Error injection giữ nguyên như `main`**, không expose thêm endpoint. | Không thay đổi |
| AIO-17 | **Thêm label `tier` vào `app_ai_fallback_total`** ở cả 7 đường fallback, cộng `source="admission_control"` cho đường shed vốn trước đây không đếm gì. Span mang `app.fallback.tier`. | `product_reviews_server.py` |

---

## Sai lệch so với code AIO gốc (và lý do)

| # | AIO làm | Ở đây làm | Lý do |
|---|---|---|---|
| 1 | Persist mọi câu trả lời `approved`/`deterministic` | Thêm gate `is_summary_request` | Bản gốc để câu trả lời "có chống nước không?" ghi đè bản tóm tắt; lần fallback sau trả nó cho người hỏi "tóm tắt review". Test `test_narrow_question_deterministic_is_not_persisted` khoá hành vi này |
| 2 | Trả summary bất kể `review_version` | So version, lệch → Tier-3 | Bản gốc trả tóm tắt lỗi thời so với tập review hiện tại. Test `test_stale_version_falls_through_to_tier3` khoá hành vi này (test của AIO khẳng định điều ngược lại) |
| 3 | Ghi đồng bộ trong `finally:` | Ghi qua `db_write_executor` | Cộng một round-trip RDS vào p99 của MỌI câu trả lời AI thành công, cho một bản ghi chỉ phục vụ sự cố tương lai |
| 4 | `GRANT ... DELETE` | Không cấp `DELETE` | Runtime chỉ read + upsert; least privilege (AIO-07) |
| 5 | `CREATE INDEX` thường | Giữ `CONCURRENTLY` của `main` | `productreviews` dùng chung với product-catalog/accounting; index thường khoá write |
| 6 | Bỏ grant `fidelity_audit_id_seq` | Giữ | Không có grant sequence thì `otelu` không INSERT được vào `fidelity_audit` (SERIAL cần `USAGE`) |

Cả 6 sai lệch đều có test bảo vệ hoặc là bất biến schema, không phải quy ước miệng.

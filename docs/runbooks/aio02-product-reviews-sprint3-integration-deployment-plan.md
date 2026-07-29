# Kế hoạch tích hợp và triển khai an toàn `product-reviews` BigUpdate Sprint 3

**Trạng thái:** ĐANG THỰC THI — Release A (Tier-2) đã qua G1–G4, đang ở G5 (review PR-B).
Release B (S6) vẫn **NO-GO**, chưa bắt đầu.

**Ngày lập:** 29/07/2026 · **Cập nhật:** 29/07/2026 (điền §14 và §16 sau khi port xong)

> **Blocker semantics §5.3 đã được ĐÓNG bằng code, không phải bằng miễn trừ.** Hai lỗi
> (persist không giới hạn theo intent; không so `review_version`) đã được vá khi port, mỗi lỗi
> có test khoá hành vi và đã được kiểm chứng bằng mutation test — bỏ gate `is_summary_request`
> hoặc bỏ so version đều làm CI đỏ. Chi tiết ở
> [`docs/evidence/product-reviews-sprint3/02-aio-contract-decisions.md`](../evidence/product-reviews-sprint3/02-aio-contract-decisions.md).
> AIO02 vẫn cần ký xác nhận contract AIO-01…07/13…17 ở PR review.

**Phạm vi:** Đối chiếu `feature/product-review` với `main`, port chọn lọc phần AIO mới, migrate schema và rollout lên production TF3

**Không phải:** Biên bản đã triển khai hoặc bằng chứng hệ thống production hiện đang PASS

## 1. Mục đích tài liệu

Tài liệu này dùng để:

1. Thông báo rõ cho CDO01, CDO02 và AIO02 trạng thái khác biệt giữa nhánh AIO và `main`.
2. Chỉ ra phần nào đã có trên `main`, phần nào thực sự mới, phần nào không được đưa sang production.
3. Liệt kê các điểm AIO02 cần xác nhận hoặc bổ sung trước khi CDO triển khai.
4. Chốt quy trình tích hợp, kiểm thử, migration, rollout và rollback theo từng cổng kiểm soát.
5. Làm checklist chung để cả hai team cùng ký xác nhận GO/NO-GO, tránh hiểu nhầm “merge code xong” là “đã deploy an toàn”.

Tài liệu này cụ thể hóa cho BigUpdate Sprint 3. Quy tắc đóng góp code lâu dài vẫn xem tại
[`aio02-product-reviews-code-contribution.md`](aio02-product-reviews-code-contribution.md).

---

## 2. Kết luận điều hành

### 2.1 Quyết định hiện tại

**NO-GO** với mọi phương án sau:

- merge trực tiếp `feature/product-review` vào `main`;
- rebase toàn bộ nhánh feature lên `main`;
- cherry-pick toàn bộ chuỗi 14 commit;
- checkout đè toàn bộ thư mục `src/product-reviews`;
- copy nguyên `values-aio-llm.yaml`, root `infra/iam.tf` hoặc chart templates từ nhánh feature;
- chạy `helm upgrade` tay theo `CDO_DEPLOYMENT_MESSAGE.md`.

**Hướng được phép:** tạo nhánh tích hợp mới từ `origin/main` mới nhất, port thủ công các hunk nghiệp vụ đã
review, chia migration và runtime rollout thành các gate độc lập, build image qua CI có Trivy/Cosign, sau
đó deploy bằng image-bump PR và Argo CD.

### 2.2 Tách thành hai release

| Release | Nội dung | Trạng thái hiện tại |
|---|---|---|
| **Release A — Tier-2 fallback** | PostgreSQL `product_summaries`, logic persist/read summary, fallback Tier-2/Tier-3, test và migration | Có thể tiếp tục sau khi chốt semantics ở §6.1 |
| **Release B — S6 isolation** | Cô lập tải AI khỏi read RPC | **Chưa đủ điều kiện**; implementation hiện tại chưa phải bulkhead thật, xem §5.2 |

Không gộp hai release nếu chưa có bằng chứng load test. Mỗi release chỉ nên kiểm chứng một nhóm giả thuyết
để khi có regression còn xác định được nguyên nhân và rollback đúng thay đổi.

### 2.3 Việc hai team cần làm ngay

| Team | Việc tiếp theo | Khi nào xong |
|---|---|---|
| AIO02 | Trả lời AIO-01…AIO-17, chốt behavior Tier-2, cung cấp eval set và bằng chứng S6 | Decision log có owner, câu trả lời và link evidence |
| CDO | Đóng CDO-01…CDO-11, tạo branch từ frozen main và port chọn lọc Release A | PR diff không làm mất production safeguards |
| AIO + CDO | Review output candidate và ký từng gate | Chỉ GO khi G0…G8 đều PASS trước rollout |
| Change owner/on-call | Chốt window, rollback reference và stop authority | Có tên người chịu trách nhiệm, không để trống |

Cho tới lúc đó: **chỉ review/chuẩn bị; không merge image-bump PR và không thay đổi production**.

---

## 3. Snapshot nguồn đã đối chiếu

Snapshot remote được fetch lại lúc 12:03 ICT ngày 29/07/2026:

| Nguồn | SHA | Ghi chú |
|---|---|---|
| `origin/main` | `52fa3f7cf9704a48a922c08bafbb8197aec24a8b` | Commit lúc 29/07/2026 11:49 ICT |
| `origin/feature/product-review` | `98f67031f55b6a1716b18a0431f3722a5a43c597` | Author 09:54, committer 09:59 ICT ngày 29/07/2026 |
| Merge base | `24e854ad33040a8194f2ed4900ba310c4970051b` | Nhánh đã tách từ 07/07/2026 |

So với `main`, nhánh feature có **14 commit riêng nhưng thiếu 1.430 commit của `main`**.

Diff trực tiếp giữa hai snapshot:

- 1.314 file thay đổi;
- 1.268 file bị xóa;
- 27 file sửa;
- 17 file thêm;
- 2 file đổi tên;
- khoảng 23.099 dòng thêm và 294.793 dòng xóa.

Commit `860c116` chủ động tối giản nhánh bằng cách xóa phần lớn nội dung không phải `product-reviews`.
Vì vậy diff lớn không phải thay đổi sản phẩm cần deploy mà là hệ quả của nhánh phát triển đã bỏ các service
khác khỏi cây mã nguồn.

Tham chiếu:

- [So sánh `main...feature/product-review`](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/compare/main...feature/product-review)
- [Feature head `98f6703`](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/commit/98f67031f55b6a1716b18a0431f3722a5a43c597)
- [Main head tại thời điểm lập plan `52fa3f7`](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/commit/52fa3f7cf9704a48a922c08bafbb8197aec24a8b)
- [CDO deployment message của AIO](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/blob/feature/product-review/CDO_DEPLOYMENT_MESSAGE.md)

Hai phép so sánh phục vụ hai mục đích khác nhau:

- `git diff MAIN_SHA AIO_SHA` là snapshot-vs-snapshot, dùng để thấy mọi file production có thể bị ghi
  đè/xóa nếu copy cả nhánh;
- GitHub `main...feature/product-review` dùng merge base, hữu ích để đọc ý định 14 commit của AIO nhưng
  không chứng minh merge/copy nguyên nhánh là an toàn.

> SHA trên là nguồn audit, không phải SHA mặc định để dùng mãi. Người thực hiện phải fetch lại và ghi
> `MAIN_BASE_SHA` thực tế ngay trước khi tạo nhánh tích hợp.

---

## 4. Những gì `main` đã có

Không triển khai lại các phần dưới như thể đây là tính năng mới:

| Thành phần | Trạng thái trên `main` |
|---|---|
| Redis LLM cache | Đã port và đã có cấu hình ElastiCache TLS/auth |
| Circuit breaker | Đã có |
| Fallback override qua Redis | Đã có |
| Input/output guardrails | Đã có |
| Error injection | Đã có |
| LLM trace | Đã có |
| Tool validator | Đã có |
| `app_ai_fallback_total` | Đã có |
| Dedicated IRSA | Đã có ServiceAccount `product-reviews-bedrock` trong namespace `techx-tf3` |
| Bedrock model access | Đã dùng role riêng, không cấp cho shared ServiceAccount |
| DB-aware readiness | Đã có, trả `NOT_SERVING` khi DB lỗi hoặc shutdown |
| Graceful shutdown | Đã có |
| AI admission control | Đã có semaphore, mặc định cap 4 và admission wait 0,05 giây |
| DB connection pool fix | Đã có xử lý `PoolError`, không rebuild/leak pool khi cạn |
| DB/gRPC sizing | DB pool mặc định 1/10, gRPC worker 12 |
| Hardened Dockerfile | Digest-pinned, vá OpenSSL, non-root UID/GID 65532 |
| NetworkPolicy cho product reviews | File staged trên hai nhánh byte-identical |
| Multi-arch ECR + Trivy + Cosign | Đã có pipeline production |
| Argo CD GitOps | Theo dõi `main`, deploy namespace `techx-tf3`, auto-sync/self-heal |

Các thay đổi này được đưa vào `main` qua:

- [PR #554 — port AIO02 và giữ các fix production](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/554)
- [PR #557 — sửa pool leak và sizing theo RDS thật](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/557)
- [PR #562 — bằng chứng verify sau upgrade](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/562)

Image `product-reviews` được pin trong `main` tại thời điểm audit:

```text
tag:    177d7d1-30382089768-product-reviews
digest: sha256:35f413f43f8840039383f4fe64440e7f06415c6e5fb70591480451ee84d54067
```

Trước rollout thật phải đọc lại digest đang live; không mặc định digest audit vẫn là digest rollback.

---

## 5. Delta mới và các vấn đề đã phát hiện

### 5.1 Phần mới có giá trị từ `8dacb55`

Các phần cần xem xét port chọn lọc:

- bảng `reviews.product_summaries`;
- `save_product_summary()` và `fetch_product_summary_from_db()`;
- Tier-2 PostgreSQL static-summary fallback;
- persist summary sau khi kết quả được judge/deterministic chấp nhận;
- deterministic-answer/routing refinements;
- các test mới:
  - `test_database_summary.py`;
  - `test_fallback_tier2.py`;
  - `test_summary_persistence.py`;
  - `test_runtime_guardrails.py`;
  - `test_circuit_breaker.py`;
  - `test_error_injection.py`;
  - `test_tool_validator.py`.

Trong nhóm guardrails, chỉ `fallback.py` và `routing.py` còn khác giữa hai snapshot. Cache, circuit breaker,
error injection, LLM trace, tool validator, metrics, `requirements.txt` và protobuf hiện đã giống `main`;
không port lại các file giống nhau và không coi đây là thay đổi contract gRPC.

### 5.2 S6 ở `98f6703` chưa phải bulkhead thật

Implementation AIO hiện tại:

1. Tạo `ThreadPoolExecutor(max_workers=15)`.
2. gRPC handler submit công việc AI.
3. Chính handler đó chờ `future.result(timeout=15)`.
4. gRPC server của feature hardcode 50 worker.

Vấn đề:

- `ThreadPoolExecutor` dùng hàng đợi không giới hạn, không phải bounded queue;
- mỗi request AI vẫn chiếm một gRPC worker trong lúc chờ;
- khi timeout, future không được cancel và vẫn có thể tiếp tục gọi Bedrock/DB;
- burst đủ lớn vẫn có thể chiếm hết gRPC worker và chặn read RPC;
- con số 15/50 không dựa trên RDS 112 connections, memory limit 150Mi hay baseline production hiện tại;
- feature làm mất semaphore shed nhanh hiện có trên `main`.

Do đó không được mô tả implementation hiện tại là “đã cô lập hoàn toàn read API”.

Hướng ưu tiên cho Release B:

1. Tách AI assistant thành Deployment/Service riêng theo postmortem PM-0016; hoặc
2. Nếu vẫn chọn in-process, phải có bounded admission trước khi chiếm gRPC worker, queue limit, cancellation,
   metrics saturation và load evidence với cache miss/Redis down.

### 5.3 Tier-2 fallback hiện có lỗi semantics

Schema feature dùng `product_id` làm primary key. Nhưng code persist mọi kết quả có trạng thái
`approved` hoặc `deterministic`, không giới hạn câu hỏi summary.

Ví dụ rủi ro:

1. User hỏi “Sản phẩm có bền không?”.
2. Câu trả lời được chấp nhận và ghi đè row `product_id=X`.
3. User khác hỏi “Tóm tắt toàn bộ review”.
4. Bedrock lỗi và Tier-2 trả câu trả lời “độ bền” của câu hỏi trước.

Ngoài ra:

- `review_version` được ghi nhưng không được kiểm tra khi fallback;
- cách tính version hiện chỉ hash `product_id + COUNT(*) + MAX(id)`, nên sửa nội dung/điểm review tại
  chỗ không làm version đổi;
- summary cũ có thể được trả sau khi review đã thay đổi;
- bảng mới ban đầu rỗng, nên Tier-2 vẫn rơi xuống Tier-3 cho tới khi có summary được duyệt;
- test feature đang xác nhận việc trả summary cũ dù `review_version` khác, chưa chứng minh đó là hành vi đúng.

Đây là blocker nghiệp vụ, không chỉ blocker hạ tầng. AIO phải chọn một trong hai contract: review
append-only có enforcement rõ ràng, hoặc version phải phản ánh mọi thay đổi nội dung/score/safety.

### 5.4 Những regression nếu copy nguyên feature

| Vùng | Feature sẽ làm gì | Hậu quả |
|---|---|---|
| `Dockerfile` | Bỏ digest pin, vá OpenSSL, non-root user và migration COPY | Trivy/Kyverno chặn hoặc Job migration thiếu file |
| `database.py` | Đổi pool sang 5/30, rebuild pool khi cạn | Có thể mở 180 connection ở HPA 6 pod và leak connection |
| Health | Trả `SERVING` vô điều kiện | Pod mất DB vẫn nhận traffic |
| gRPC | Hardcode 50 worker | Tăng contention và không khớp DB pool |
| `migration.sql` | Đổi `CREATE INDEX CONCURRENTLY` về index thường, bỏ sequence grant | Lock write hoặc lỗi permission |
| `values-aio-llm.yaml` | Bỏ IRSA riêng, DB secret, Redis TLS/auth; thêm Guardrail/OpenAI secret ref chưa xác nhận | Pod có thể lỗi DB/Redis/Bedrock hoặc thiếu Secret |
| Guardrail config | Dùng ID thuộc account khác | `AccessDenied` hoặc guardrail không tồn tại |
| Root Terraform | Dùng namespace/SA cũ `techx-corp:techx-corp`, `Resource="*"` | Sai trust policy và rộng quyền |
| Chart templates | Làm mất digest support, component SA, topology/probe/rollout controls | Regression trên nhiều workload |
| `.env.override` | Thêm placeholder static AWS access keys | Mẫu credential không phù hợp IRSA production |
| `rendered-test.yaml` | Commit 20.414 dòng generated manifest | Nhiễu review, nhanh stale |

### 5.5 Chuyển đổi hướng dẫn AIO sang quy trình production thật

Không áp dụng nguyên trạng các lệnh trong `CDO_DEPLOYMENT_MESSAGE.md`:

| Hướng dẫn cũ trong message AIO | Cách CDO phải thực hiện |
|---|---|
| Checkout/copy nguyên thư mục `product-reviews` | Port từng hunk đã review lên branch mới từ frozen `origin/main` |
| Copy root `infra/iam.tf` và `infra/outputs.tf` | Giữ IRSA module hiện có; chỉ mở Terraform PR riêng nếu AIO xác nhận quyền AWS mới |
| Push thẳng `main` | Branch → PR → required review/checks → merge |
| Chạy cả `migration.sql` và `postgresql/init.sql` | Chỉ chạy migration additive trong one-off Job; `init.sql` chỉ cho fresh bootstrap |
| Chạy backfill worker ngay | Dry-run, đo số row/lock/false-positive, review kết quả rồi mới quyết định |
| Chạy script build và `helm upgrade` tay | CI build/scan/sign → image-bump PR → Argo CD |
| Namespace `techx-corp` | Production namespace là `techx-tf3` |
| Shared ServiceAccount `techx-corp` | Dedicated ServiceAccount là `product-reviews-bedrock` |

---

## 6. Các câu hỏi bắt buộc team AIO02 trả lời

Không merge Release A/B cho tới khi các câu hỏi có câu trả lời được ghi vào PR hoặc decision log.

### 6.1 Contract của PostgreSQL Tier-2

| ID | Câu hỏi | Khuyến nghị CDO | Trạng thái |
|---|---|---|---|
| AIO-01 | Tier-2 dùng cho mọi câu hỏi hay chỉ câu hỏi “summary review”? | Chỉ dùng cho canonical summary nếu schema vẫn khóa theo `product_id` | Chờ AIO |
| AIO-02 | Nếu muốn fallback cho mọi câu hỏi, key chính là gì? | `product_id + normalized intent/question hash + review_version` | Chờ AIO |
| AIO-03 | Khi review đổi hoặc bị sửa tại chỗ, version/fallback xử lý thế nào? | Không trả stale row; chốt append-only có enforcement hoặc sửa version để bắt content/score/safety update | Chờ AIO |
| AIO-04 | Bảng mới rỗng lúc go-live có chấp nhận được không? | Chốt cold-start hoặc pre-warm bằng candidate đã được duyệt | Chờ AIO |
| AIO-05 | Kết quả nào được phép persist? | Chỉ approved canonical summary; không persist fallback/out-of-scope/narrow answer | Chờ AIO |
| AIO-06 | `rating_distribution` có contract/format gì? | Chốt JSON schema hoặc bỏ field nếu chưa dùng | Chờ AIO |
| AIO-07 | Retention/refresh của summary là gì? | Phải có rule theo version, không giữ vô hạn mà không kiểm freshness | Chờ AIO |

### 6.2 Contract của S6 isolation

| ID | Câu hỏi | Khuyến nghị CDO | Trạng thái |
|---|---|---|---|
| AIO-08 | S6 cần “mitigation” hay “bulkhead hoàn toàn”? | Nếu claim isolation thì dùng Deployment/Service riêng | Chờ AIO |
| AIO-09 | Vì sao chọn 15 AI workers và 50 gRPC workers? | Cần load/RDS/memory evidence; không lấy số mặc định feature | Chờ AIO |
| AIO-10 | Khi timeout có cancel request Bedrock không? | Phải ngăn timed-out work tiếp tục ăn quota/tài nguyên | Chờ AIO |
| AIO-11 | Queue đầy thì response/status/metric nào được trả? | Shed nhanh, có counter riêng và không block read worker | Chờ AIO |
| AIO-12 | Acceptance target cho read RPC dưới AI saturation là gì? | Dùng SLO/postmortem đã thống nhất, test cache miss và Redis down | Chờ AIO |

### 6.3 AWS, test và observability

| ID | Câu hỏi | Khuyến nghị CDO | Trạng thái |
|---|---|---|---|
| AIO-13 | Bedrock Guardrail có bắt buộc trong release này không? | Tách PR riêng; không dùng ID/account hoặc `Resource="*"` từ feature | Chờ AIO |
| AIO-14 | Nếu bật Guardrail, ARN/region/version đúng trong account `197826770971` là gì? | AIO cung cấp resource contract, CDO triển khai IAM least privilege | Chờ AIO |
| AIO-15 | Bộ câu hỏi/expected answer và thay đổi prompt/routing/language nào là chủ ý? | AIO cung cấp eval set gồm summary, rating, durability, exact attribute, off-topic và VI/EN | Chờ AIO |
| AIO-16 | Error injection có cần bật production endpoint không? | Mặc định không expose; nếu cần phải token hóa và giới hạn network | Chờ AIO |
| AIO-17 | Metric labels bắt buộc cho Tier-2/S6 là gì? | Ít nhất source, tier, outcome; S6 cần active/queued/shed/timeout | Chờ AIO |

---

## 7. Những việc CDO phải bổ sung

| ID | Việc | Lý do | Owner đề xuất |
|---|---|---|---|
| CDO-01 | Tạo integration branch từ `origin/main` mới nhất | Không mang lịch sử xóa file của feature | CDO integrator |
| CDO-02 | Port semantic diff thay vì copy snapshot | Giữ fix production | CDO + AIO reviewer |
| CDO-03 | Thêm CI chạy test product-reviews | Pipeline hiện build/scan/sign nhưng chưa chạy bộ test AIO mới | CDO CI |
| CDO-04 | Thêm regression test health/pool/semaphore/version/rolling compatibility | Test feature chưa bảo vệ các fix của `main` hoặc in-place review update | CDO reliability |
| CDO-05 | Mở rộng migration Job verify `product_summaries` và grants | Job hiện chỉ verify schema cũ | CDO DB |
| CDO-06 | Tạo candidate manifest tách khỏi production selector | Deployment hiện không có Argo Rollout canary | CDO platform |
| CDO-07 | Chụp baseline và chuẩn bị revert digest/PR | Rollback phải sẵn trước rollout | On-call |
| CDO-08 | Thêm dashboard/query cho Tier-2/S6 | Không thể PASS chỉ bằng pod `Running` | CDO observability |
| CDO-09 | Chốt change window và freeze rollout khác | Tránh nhiều thay đổi đồng thời | Change owner |
| CDO-10 | Lưu evidence pack | Phục vụ review, postmortem và audit | Change owner |
| CDO-11 | Sửa/kiểm chứng image-bump validation bằng đủ sáu values | Workflow hiện chỉ render `values.yaml`, flagd và prod, khác Argo production | CDO CI/platform |

---

## 8. Phạm vi file được phép và không được phép

### 8.1 Allowlist dự kiến cho Release A

```text
phase3 - information/techx-corp-platform/src/product-reviews/database.py
phase3 - information/techx-corp-platform/src/product-reviews/product_reviews_server.py
phase3 - information/techx-corp-platform/src/product-reviews/migration.sql
phase3 - information/techx-corp-platform/src/product-reviews/guardrails/fallback.py
phase3 - information/techx-corp-platform/src/product-reviews/guardrails/routing.py
phase3 - information/techx-corp-platform/src/product-reviews/test_*.py
phase3 - information/techx-corp-platform/src/product-reviews/requirements-test.txt
gitops/jobs/product-reviews-schema-migration.yaml
phase3 - information/techx-corp-chart/postgresql/init.sql
phase3 - information/techx-corp-platform/src/postgresql/init.sql
docs/...
```

Hai file `postgresql/init.sql` phải giữ đồng bộ nếu Release A hỗ trợ fresh install. Chúng chỉ dùng cho
bootstrap môi trường mới; production RDS **không** chạy các file này.

### 8.2 Denylist mặc định

Không đưa các file sau vào PR nếu chưa có decision riêng:

```text
infra/iam.tf
infra/outputs.tf
phase3 - information/deploy/values-aio-llm.yaml
phase3 - information/techx-corp-chart/templates/_objects.tpl
phase3 - information/techx-corp-chart/templates/serviceaccount.yaml
phase3 - information/techx-corp-chart/values.yaml
phase3 - information/techx-corp-chart/values.schema.json
phase3 - information/techx-corp-chart/rendered-test.yaml
phase3 - information/techx-corp-platform/.env.override
phase3 - information/deploy/build-push-images.sh
```

Nếu Release B cần manifest/service mới thì phải là PR riêng với allowlist riêng.

---

## 9. Kế hoạch thực thi theo từng gate

### Gate G0 — Freeze nguồn và phân công

**Thực hiện:**

```bash
cd /home/nvtank/year3/intern/phase3/Phase3-TF3-Infra-Sentinel
git fetch --prune origin main feature/product-review
MAIN_BASE_SHA="$(git rev-parse origin/main)"
AIO_SOURCE_SHA="$(git rev-parse origin/feature/product-review)"
printf 'main=%s\naio=%s\n' "$MAIN_BASE_SHA" "$AIO_SOURCE_SHA"
git rev-list --left-right --count "$MAIN_BASE_SHA...$AIO_SOURCE_SHA"
git diff --shortstat "$MAIN_BASE_SHA" "$AIO_SOURCE_SHA"
```

Ghi vào change record:

```text
MAIN_BASE_SHA=
AIO_SOURCE_SHA=
CHANGE_OWNER=
ON_CALL=
AIO_REVIEWER=
CDO_REVIEWER=
CHANGE_WINDOW=
ROLLBACK_DIGEST=
ROLLBACK_VALUES_COMMIT=
ROLLBACK_BRANCH_OR_PR=
ROLLBACK_DECISION_DEADLINE_MIN=
RESTORE_OBJECTIVE_MIN=
BREAK_GLASS_OWNER=
```

**PASS khi:**

- owner/on-call/reviewer/break-glass owner đã có tên;
- AIO source SHA được cố định;
- rollback digest/reference và thời hạn quyết định/khôi phục đã được team chốt;
- không có incident hoặc rollout production khác đang chạy.

**FAIL:** dừng, không tạo nhánh tích hợp.

### Gate G1 — Tạo nhánh tích hợp sạch

```bash
git worktree add -b feat/product-reviews-sprint3-port \
  /tmp/tf3-product-reviews-sprint3 "$MAIN_BASE_SHA"
cd /tmp/tf3-product-reviews-sprint3
```

Không dùng checkout hiện tại nếu nó đang chứa docs hoặc thay đổi của người khác.

**PASS khi:**

```bash
git status --short
test "$(git rev-parse HEAD)" = "$MAIN_BASE_SHA"
git merge-base --is-ancestor "$MAIN_BASE_SHA" HEAD
```

Working tree sạch và branch bắt đầu đúng từ main base đã ghi.

### Gate G2 — Port Release A theo commit nhỏ

Thứ tự commit đề xuất:

1. `db: add product_summaries additive schema and grants`
2. `db: add safe summary persistence helpers`
3. `feat: add version-aware Tier-2 fallback`
4. `feat: port reviewed deterministic routing changes`
5. `test: cover Tier-2 persistence, stale data and regressions`
6. `ops: extend one-off migration verification`

Sau mỗi commit:

```bash
git diff --check HEAD^ HEAD
git show --stat --oneline HEAD
```

Kiểm tra final scope:

```bash
git diff --name-status "$MAIN_BASE_SHA"...HEAD
git diff --stat "$MAIN_BASE_SHA"...HEAD
```

**PASS khi:**

- không có file ngoài allowlist;
- không mất flagd calls;
- Dockerfile, proto, values, IRSA, chart runtime templates không đổi;
- main health/pool/semaphore logic còn nguyên.

### Gate G3 — Code, contract và regression test

Tối thiểu phải có. Dùng Python 3.12 giống runtime image và thêm
`src/product-reviews/requirements-test.txt` pin `pytest==8.4.1`; không phụ thuộc vào package vô tình có
sẵn trên runner:

```bash
cd "phase3 - information/techx-corp-platform/src/product-reviews"

TEST_VENV="/tmp/product-reviews-sprint3-venv"
python3.12 -m venv "$TEST_VENV"
"$TEST_VENV/bin/python" -m pip install \
  --disable-pip-version-check \
  -r requirements.txt \
  -r requirements-test.txt

"$TEST_VENV/bin/python" -m compileall -q .
"$TEST_VENV/bin/python" -m pytest -q \
  test_database_summary.py \
  test_fallback_tier2.py \
  test_summary_persistence.py \
  test_runtime_guardrails.py \
  test_circuit_breaker.py \
  test_error_injection.py \
  test_tool_validator.py
```

Pytest thu thập được cả các class `unittest` và hai file pytest-style `test_circuit_breaker.py`,
`test_tool_validator.py`. Chạy riêng `python -m unittest` sẽ bỏ sót hai file pytest-style. Workflow hiện
mới chạy test ở `scripts/ci`, chưa chạy test service `product-reviews`.

CI hoặc evidence script phải bổ sung các case:

1. DB khỏe → health `SERVING`.
2. DB lỗi → health `NOT_SERVING`.
3. SIGTERM/shutdown event → health `NOT_SERVING`.
4. Pool exhausted → fail request, không tạo pool mới và không leak.
5. Tier-2 chỉ trả đúng summary đúng intent/version.
6. Thêm review và sửa content/score/safety tại chỗ đều làm version đổi, hoặc test chứng minh append-only
   được enforce; stale version phải miss/Tier-3.
7. DB summary write lỗi → response LLM thành công không bị fail theo.
8. Rejected/fallback/out-of-scope answer không được persist.
9. Redis down → hai read RPC vẫn hoạt động.
10. AI saturation bằng unique questions/cache miss → read RPC vẫn đạt acceptance target đã chốt.
11. Old/new pod dùng chung proto và response contract.
12. flagd paths `llmInaccurateResponse`/`llmRateLimitError` còn hoạt động.

Build image local:

```bash
cd "phase3 - information/techx-corp-platform"
docker compose build product-reviews
```

**PASS khi:** test log được đính kèm PR và AIO xác nhận expected behavior.

### Gate G4 — Helm/GitOps render

Argo CD production dùng đúng sáu values theo thứ tự:

1. `values.yaml`
2. `values-flagd-sync.yaml`
3. `values-prod.yaml`
4. `values-mandate13.yaml`
5. `values-aio-llm.yaml`
6. `values-serviceaccounts.yaml`

Workflow image-bump hiện mới render ba lớp `values.yaml`, `values-flagd-sync.yaml` và `values-prod.yaml`.
CDO-11 phải sửa hoặc bổ sung một required check dùng đủ sáu lớp dưới đây; không coi render ba lớp là
bằng chứng tương đương production.

```bash
helm dependency build "phase3 - information/techx-corp-chart"

helm lint "phase3 - information/techx-corp-chart" \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  -f "phase3 - information/deploy/values-mandate13.yaml" \
  -f "phase3 - information/deploy/values-aio-llm.yaml" \
  -f "phase3 - information/deploy/values-serviceaccounts.yaml"

helm template techx-corp "phase3 - information/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  -f "phase3 - information/deploy/values-mandate13.yaml" \
  -f "phase3 - information/deploy/values-aio-llm.yaml" \
  -f "phase3 - information/deploy/values-serviceaccounts.yaml" \
  > /tmp/product-reviews-sprint3-rendered.yaml
```

Nếu có quyền cluster:

```bash
kubectl apply --dry-run=server -f /tmp/product-reviews-sprint3-rendered.yaml
```

**PASS khi rendered Deployment vẫn có:**

- image dạng ECR repository + immutable digest;
- ServiceAccount `product-reviews-bedrock`;
- RDS secret `techx-tf3-postgres-conn`;
- Valkey TLS/auth secret;
- port 3551;
- DB-aware readiness và liveness;
- resource request/limit;
- `maxUnavailable: 0`, `maxSurge: 1`;
- PDB/HPA ownership và topology spread hiện tại;
- không có static AWS key hoặc secret ref lạ;
- không có manifest runtime ngoài phạm vi dự kiến.

### Gate G5 — Review và merge code-only PR

PR body phải có:

- main base SHA và AIO source SHA;
- danh sách hunk đã port;
- danh sách hunk cố ý không port;
- câu trả lời AIO-01…AIO-17;
- test/eval evidence;
- schema impact;
- rollout/rollback plan;
- xác nhận code merge chưa deploy image mới.

Yêu cầu review:

- ít nhất một AIO reviewer ký behavior;
- ít nhất một CDO reviewer ký platform/reliability;
- không unresolved comment;
- required checks PASS.

Sau merge, `.github/workflows/build-push-ecr.yml` phải:

1. build riêng service thay đổi;
2. scan local image với Trivy HIGH/CRITICAL;
3. push multi-arch image lên ECR;
4. resolve immutable digest;
5. scan post-push;
6. Cosign sign/verify;
7. tạo SBOM/provenance;
8. mở image-bump PR.

**Không merge image-bump PR ở Gate G5.**

### Gate G6 — Migration trước runtime rollout

Chỉ dùng `migration.sql` trong signed candidate image. Không chạy
`techx-corp-chart/postgresql/init.sql` trên production RDS.

Migration phải giữ:

- `CREATE INDEX CONCURRENTLY`;
- statement-by-statement execution;
- `fidelity_audit_id_seq` grant;
- toàn bộ DDL mới ở dạng additive/idempotent;
- không drop/rename/change type cột đang dùng.

Thêm:

```sql
CREATE TABLE IF NOT EXISTS reviews.product_summaries (
    product_id VARCHAR(50) PRIMARY KEY,
    summary_text TEXT NOT NULL,
    rating_distribution TEXT,
    review_version VARCHAR(100),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

GRANT SELECT, INSERT, UPDATE
ON reviews.product_summaries TO otelu;
```

Runtime hiện chỉ read/upsert, nên không cấp `DELETE` cho `otelu` nếu AIO chưa chứng minh use case. Nếu cần
retention/delete, dùng change và role vận hành riêng theo least privilege.

Nếu AIO quyết định key theo intent/question hash, schema trên phải được sửa trước migration, không migrate
schema tạm rồi đổi tiếp trong cùng change window.

Update `gitops/jobs/product-reviews-schema-migration.yaml` sang candidate digest đã ký, sau đó:

```bash
kubectl -n techx-tf3 get job product-reviews-schema-migration \
  --ignore-not-found
```

Job có tên cố định và PodTemplate của Job là immutable. Nếu lệnh kiểm tra đầu tiên trả về Job cũ:

1. Không replace/delete khi Job còn `Active`.
2. Nếu Job đã terminal, lưu status/log vào evidence pack trước.
3. Chỉ xóa Job terminal cũ sau khi owner xác nhận evidence đã lưu, hoặc đổi manifest sang tên duy nhất
   theo change/digest.
4. Chỉ `apply` candidate Job khi tên không còn xung đột.

Khi precondition trên đã PASS:

```bash
kubectl apply -f gitops/jobs/product-reviews-schema-migration.yaml
kubectl -n techx-tf3 wait \
  --for=condition=complete \
  job/product-reviews-schema-migration \
  --timeout=600s
kubectl -n techx-tf3 logs job/product-reviews-schema-migration
```

`CREATE TABLE IF NOT EXISTS` có thể thành công dù table cũ sai schema. Vì vậy Job/log phải verify đầy đủ,
không chỉ `to_regclass`:

```sql
SELECT to_regclass('reviews.product_summaries');

SELECT column_name, data_type, character_maximum_length,
       is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'reviews'
  AND table_name = 'product_summaries'
ORDER BY ordinal_position;

SELECT a.attname AS primary_key_column
FROM pg_index i
JOIN pg_attribute a
  ON a.attrelid = i.indrelid
 AND a.attnum = ANY(i.indkey)
WHERE i.indrelid = 'reviews.product_summaries'::regclass
  AND i.indisprimary;

SELECT tableowner
FROM pg_tables
WHERE schemaname = 'reviews'
  AND tablename = 'product_summaries';

SELECT privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'otelu'
  AND table_schema = 'reviews'
  AND table_name = 'product_summaries'
ORDER BY privilege_type;

SELECT indexrelid::regclass, indisvalid
FROM pg_index
WHERE indexrelid =
  'reviews.productreviews_prod_safe_idx'::regclass;
```

Expected schema:

| Column | Type | Nullable/default | Constraint |
|---|---|---|---|
| `product_id` | `varchar(50)` | NOT NULL | Primary key, hoặc key mới đã được AIO/CDO chốt trước migration |
| `summary_text` | `text` | NOT NULL |  |
| `rating_distribution` | `text` | NULL | Format phải theo decision AIO-06 |
| `review_version` | `varchar(100)` | NULL | Freshness phải theo decision AIO-03 |
| `updated_at` | `timestamptz` | Default current timestamp |  |

Qua đúng app DSN/role, chạy functional probe trong transaction rollback:

```sql
BEGIN;
SELECT current_user;
INSERT INTO reviews.product_summaries (
  product_id, summary_text, review_version
) VALUES (
  '__tf3_sprint3_schema_probe__', 'probe-v1', 'probe-v1'
)
ON CONFLICT (product_id) DO UPDATE
SET summary_text = EXCLUDED.summary_text,
    review_version = EXCLUDED.review_version;
SELECT product_id, summary_text, review_version
FROM reviews.product_summaries
WHERE product_id = '__tf3_sprint3_schema_probe__';
ROLLBACK;
```

PASS chỉ khi `current_user` là app role dự kiến, column/type/nullability/default/PK/owner đúng contract,
privileges không rộng hơn yêu cầu, probe read/upsert thành công và rollback không để lại row.

Trước migration:

- xác nhận RDS PITR/backup đang usable;
- chạy trong change window;
- chụp baseline DB connections và error;
- giữ người có quyền dừng change.

Không chạy lại `db_migration_worker.py` mặc định. Nếu input filter thay đổi, phải tạo dry-run mới và AIO
review false positive trước khi có bất kỳ `UPDATE`.

**PASS khi:**

- Job Complete;
- table/grants đúng;
- index cũ valid;
- product-catalog/accounting/storefront không regression;
- image-bump PR vẫn chưa merge.

### Gate G7 — Candidate smoke không nhận production traffic

`product-reviews` hiện là Kubernetes Deployment thường, không có Argo Rollout canary. Vì vậy trước rolling
deployment cần một candidate Deployment/Service tách label/selector khỏi Service production.

Candidate phải:

- dùng đúng signed digest từ image-bump PR;
- dùng cùng ServiceAccount/IRSA; dependency khỏe có thể đọc qua secret refs production;
- không được production `product-reviews` Service select;
- không expose public;
- mọi fault injection chỉ select candidate hoặc dùng candidate-only env/endpoint;
- tuyệt đối không sửa/xóa shared Secret/ExternalSecret, flush/stop Valkey, chặn RDS/Redis chung hoặc áp
  NetworkPolicy lên production pod;
- bị xóa sau change window.

Smoke:

1. gRPC health với DB khỏe.
2. `GetProductReviews`.
3. `GetAverageProductReviewScore`.
4. `AskProductAIAssistant` canonical summary.
5. Xác nhận summary được persist bằng test data đã được duyệt.
6. Ép circuit breaker/LLM error ở candidate và xác nhận Tier-2.
7. Product chưa có summary → Tier-3.
8. Trỏ **candidate riêng** tới endpoint Redis không reachable hoặc dùng candidate-only fault hook → read
   RPC vẫn sống; không làm shared Redis unavailable.
9. Bedrock/IRSA không `AccessDenied`.
10. Không log static secret/token.

Nếu candidate ghi vào production RDS, DB operator phải chọn `product_id` synthetic/được phê duyệt, snapshot
row `product_summaries` trước test, rồi restore hoặc xóa đúng row sau test và lưu SQL/result. Phương án ưu
tiên là DB/schema candidate tách biệt. Không được dùng review/product thật rồi để summary test tồn tại sau
window.

**PASS khi:** AIO xác nhận output; CDO xác nhận dependency/security/health; shared Redis/RDS không bị fault;
candidate data đã được cleanup/restore và có evidence.

### Gate G8 — Production preflight

```bash
kubectl -n argocd get application techx-corp \
  -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision}{"\n"}'

kubectl -n techx-tf3 get deploy product-reviews
kubectl -n techx-tf3 get hpa product-reviews-hpa
kubectl -n techx-tf3 get pdb product-reviews-pdb
kubectl -n techx-tf3 get pods \
  -l opentelemetry.io/name=product-reviews -o wide
kubectl -n techx-tf3 get endpointslice \
  -l kubernetes.io/service-name=product-reviews
kubectl -n techx-tf3 get externalsecret \
  postgres-connection valkey-auth
kubectl -n techx-tf3 get secret \
  techx-tf3-postgres-conn techx-tf3-valkey-auth
kubectl -n techx-tf3 get serviceaccount product-reviews-bedrock -o yaml
kubectl -n techx-tf3 get events --sort-by=.lastTimestamp
```

Ghi lại:

- Argo revision;
- current signed image digest;
- Ready/available replicas;
- restart count;
- HPA desired/current;
- DB connections;
- read RPC latency/error/deadline baseline;
- AI/cache/fallback baseline;
- Bedrock throttle/auth error;
- product-catalog/accounting health.

Ngay sau khi bot image-bump PR có final diff và **trước khi merge**, chuẩn bị rollback executable:

1. Chốt previous signed tag/digest và commit `values-prod.yaml` đang live.
2. Tạo rollback branch từ bot PR head, với một commit chỉ đưa `product-reviews` về previous digest.
3. Chạy lại exact-diff check và six-values render trên rollback branch.
4. Ghi URL branch, người có quyền mở/merge rollback PR, `ROLLBACK_DECISION_DEADLINE_MIN` và
   `RESTORE_OBJECTIVE_MIN` vào change record.
5. Không GO nếu rollback chỉ là câu mô tả mà chưa có reference dùng được.

Trước khi bot PR merge, rollback branch có thể có tree giống `main` nên GitHub chưa mở được PR có diff.
Ngay sau bot PR merge, mở rollback PR từ branch đã chuẩn bị; không đợi incident mới tạo branch.

**PASS khi:**

- Argo `Synced/Healthy`;
- replica hiện tại Ready, không restart bất thường;
- không có rollout/sync/incident khác;
- PDB/HPA/secrets/IRSA khỏe;
- rollback branch/PR/digest đã verify, deadline/restore objective đã chốt và on-call sẵn sàng.

### Gate G9 — Merge image-bump PR và rolling deployment

Bot PR phải chỉ thay đúng digest/tag của `product-reviews`. Nếu PR bump thay service khác, dừng và tách lại.

Khi merge, bắt đầu đồng hồ observation và rollback deadline đã ghi ở G0/G8. Nếu chạm stop condition hoặc
không đủ dữ liệu để kết luận trước deadline, mặc định rollback.

Sau merge:

```bash
kubectl -n techx-tf3 rollout status \
  deployment/product-reviews --timeout=10m

kubectl -n techx-tf3 get pods \
  -l opentelemetry.io/name=product-reviews -o wide

kubectl -n techx-tf3 logs \
  -l opentelemetry.io/name=product-reviews \
  --since=10m --prefix

kubectl -n argocd get application techx-corp \
  -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision}{"\n"}'
```

Đây là **rolling deployment**, không gọi là percentage canary.

Production smoke qua frontend contract:

```bash
STOREFRONT_URL="https://d2tn71186d7ilz.cloudfront.net"
PRODUCT_ID="L9ECAV7KIM"

curl -fsS "$STOREFRONT_URL/api/product-reviews/$PRODUCT_ID"
curl -fsS "$STOREFRONT_URL/api/product-reviews-avg-score/$PRODUCT_ID"
curl -fsS \
  -H 'content-type: application/json' \
  -d '{"question":"Can you summarize the product reviews?"}' \
  "$STOREFRONT_URL/api/product-ask-ai-assistant/$PRODUCT_ID"
```

Nếu URL production thay đổi trước window, change owner phải lấy endpoint từ runbook/current output và ghi
lại vào evidence; không âm thầm dùng URL cũ.

Theo dõi ít nhất một SLO window đã được team thống nhất:

- Ready replicas không tụt dưới baseline;
- không CrashLoop/OOM/admission rejection;
- read RPC p95/p99/error/deadline không regression;
- Tier-2/Tier-3 counter đúng source/outcome;
- không DB pool exhaustion hoặc connection spike;
- không Redis/Bedrock auth/TLS failure;
- product-catalog/accounting không bị ảnh hưởng;
- Argo trở lại `Synced/Healthy`.

### Gate G10 — Đóng change

Chỉ đánh dấu DONE khi:

- production đang chạy đúng signed digest;
- schema evidence lưu đủ;
- AIO smoke/eval PASS;
- CDO SLO/reliability checks PASS;
- không open incident;
- candidate resources đã xóa;
- evidence pack và decision log đã commit/link;
- phần Release B chưa làm vẫn ghi rõ OPEN, không gộp vào kết luận Release A.

---

## 10. Stop conditions và rollback

### 10.1 Dừng rollout ngay nếu

- new pod không Ready hoặc health trả sai;
- available replicas giảm dưới baseline;
- CrashLoopBackOff, OOMKilled hoặc Kyverno admission denied;
- RDS connections tăng bất thường hoặc xuất hiện pool exhaustion kéo dài;
- `DEADLINE_EXCEEDED`/503/read latency xấu hơn baseline hoặc vượt gate đã chốt;
- Redis TLS/auth hoặc Bedrock IRSA `AccessDenied`;
- Tier-2 trả sai intent/product/version;
- product-catalog hoặc accounting regression;
- Argo `Degraded`, `OutOfSync` kéo dài hoặc revision không đúng PR bump;
- phát hiện secret/static AWS credential trong manifest/log.

### 10.2 Cách rollback

1. Dừng load/ramp và thông báo on-call.
2. Mở/refresh rollback PR đã chuẩn bị ở G8, xác nhận nó chỉ restore previous signed digest.
3. Merge rollback PR qua review khẩn cấp trong thời hạn đã chốt.
4. Để Argo CD đồng bộ về signed digest trước.
5. Chờ rollout status và verify read RPC/storefront.
6. Giữ bảng `product_summaries`; schema additive được image cũ bỏ qua.
7. Không drop table trong lúc incident. Nếu cần dọn dữ liệu phải tạo change riêng sau backup/review.

Trong rollback bình thường, không dùng:

- `helm upgrade` tay;
- `kubectl set image`;
- patch Deployment trực tiếp;
- `kubectl rollout undo` làm trạng thái lâu dài.

Argo self-heal sẽ ghi đè live patch và tạo drift so với `main`.

### 10.3 Khi GitHub hoặc Argo control plane không khả dụng

Đây là break-glass incident, không phải đường deploy bình thường:

1. On-call declare incident và gọi đúng `BREAK_GLASS_OWNER`/incident commander đã ghi ở G0.
2. Xác nhận previous digest là digest đã ký và đang có trong evidence pack.
3. Incident commander quyết định biện pháp live tạm thời để đạt restore objective; mọi lệnh, người duyệt,
   timestamp và output phải được lưu.
4. Không coi live patch là trạng thái cuối, không đóng incident và không báo DONE.
5. Ngay khi GitHub/Argo phục hồi, tạo/merge Git rollback PR, để Argo reconcile về cùng digest rồi kiểm tra
   không còn drift.

`kubectl set image`, patch trực tiếp hoặc thay đổi auto-sync chỉ được cân nhắc trong break-glass đã declare,
do người được chỉ định phê duyệt; không được dùng để né PR/review trong change bình thường.

---

## 11. Cấu trúc PR đề xuất

| PR | Nội dung | Có deploy runtime không? |
|---|---|---|
| PR-A | Docs/contract: chốt AIO-01…AIO-17 | Không |
| PR-B | Release A source + tests + additive migration source | Chưa; digest trong values chưa đổi |
| PR-C | Pin candidate digest vào one-off migration/candidate manifest nếu cần | Không tự đưa image vào production Service |
| Bot PR-D | Bump đúng `product-reviews` digest | **Có**, khi merge Argo rolling deploy |
| PR-E | Release B S6 bulkhead | Tách change window sau |

Không trộn Terraform Guardrail, S6, Tier-2 schema và image bump thủ công trong cùng PR.

---

## 12. Phân công đề xuất

| Vai trò | Trách nhiệm |
|---|---|
| AIO02 feature owner | Chốt semantics, eval set, expected output, review code nghiệp vụ |
| CDO integrator | Port chọn lọc và bảo vệ main baseline |
| CDO reliability reviewer | Health, pool, concurrency, SLO và rollback |
| CDO platform/CI | Helm render, Trivy/Cosign, ECR digest, Argo |
| DB operator | PITR/backup, migration Job và schema evidence |
| Observability owner | Dashboard/query, before/after evidence |
| On-call/change owner | GO/NO-GO, stop authority, communication và incident response |

Một người có thể giữ nhiều vai trò, nhưng tên thật phải được ghi ở Gate G0.

---

## 13. Evidence pack bắt buộc

```text
docs/evidence/product-reviews-sprint3/
├── 00-source-shas.txt
├── 01-final-diff.txt
├── 02-aio-contract-decisions.md
├── 03-unit-regression-tests.txt
├── 04-helm-render-summary.txt
├── 05-ci-run-and-signed-digest.md
├── 06-db-migration-log.txt
├── 07-db-schema-verification.txt
├── 08-candidate-smoke.md
├── 09-production-preflight.md
├── 10-rollout-observation.md
└── 11-rollback-reference.md
```

Tên thư mục là đề xuất; nếu team dùng evidence system khác thì phải link được cùng các dữ liệu trên.

---

## 14. Bảng GO/NO-GO chung

| Gate | Điều kiện PASS | Owner ký | Kết quả |
|---|---|---|---|
| G0 | SHA/owner/window/rollback được chốt | Change owner | 🟡 **MỘT PHẦN** — SHA đã cố định (`MAIN_BASE_SHA=19d15be`, `AIO_SOURCE_SHA=98f6703`, xem `00-source-shas.txt`); owner/window/rollback chốt trước G8 |
| G1 | Branch sạch từ latest main | CDO integrator | ✅ **PASS** — worktree `feat/product-reviews-sprint3-port` tách đúng từ `MAIN_BASE_SHA`, tree sạch |
| G2 | Diff đúng allowlist, main safeguards còn nguyên | CDO reviewer | ✅ **PASS** — 3 file sửa + 6 file thêm, đều trong allowlist §8.1; denylist §8.2 không đụng tới; Dockerfile/proto/values/IRSA/chart không đổi; flagd nguyên vẹn |
| G3 | Unit/regression/load contract PASS | AIO + CDO | 🟡 **PASS (unit + regression)** — 55/55 xanh trên python:3.12, xem `03-unit-regression-tests.txt`. **Load contract N/A** ở Release A (thuộc Release B/S6) |
| G4 | Six-values render + dry-run PASS | CDO platform | 🟡 **PASS (render)** — lint + template đủ 6 lớp, output KHỚP TUYỆT ĐỐI baseline `origin/main` (PR code-only). **server dry-run** chạy ở G8 khi có tunnel cluster |
| G5 | PR review/CI/signed candidate PASS | AIO + CDO CI | Chưa chạy — PR-B đang chờ review |
| G6 | Migration/schema/grants PASS | DB operator | Chưa chạy — PR-C |
| G7 | Candidate smoke PASS | AIO + CDO | **N/A ở Release A** — CDO-06 (candidate Deployment tách selector) vẫn OPEN; thay bằng verify Tier-2 qua flagd sau rollout ở G9 |
| G8 | Production preflight PASS | On-call | Chưa chạy |
| G9 | Rollout/SLO observation PASS | On-call + observability | Chưa chạy |
| G10 | Evidence complete, no hidden OPEN item | Change owner | Chưa chạy |

**Quy tắc:** một gate chưa PASS thì gate sau không được bắt đầu. “Pod Running”, “build xanh” hoặc “Grafana
đang xanh” riêng lẻ không đủ để kết luận release an toàn.

---

## 15. Mẫu thông báo gửi TF3 và AIO02

```text
[TF3 CHANGE REVIEW] product-reviews BigUpdate Sprint 3

Nguồn AIO:
- branch: feature/product-review
- SHA: 98f67031f55b6a1716b18a0431f3722a5a43c597

Nguồn production:
- branch: main
- base SHA sẽ refresh trước khi tích hợp

Kết luận:
- Không merge/copy nguyên nhánh feature vì nhánh đã tối giản và sẽ làm mất các fix production.
- Main đã có cache Redis, circuit breaker, guardrails, IRSA, health và DB pool fix.
- Delta cần review là PostgreSQL Tier-2 fallback và đề xuất S6 isolation.
- Tier-2 và S6 hiện còn blocker semantics/architecture, chưa được GO deploy.

AIO02 cần phản hồi:
1. Tier-2 áp dụng cho loại câu hỏi nào?
2. Key/freshness/review_version, kể cả review bị sửa tại chỗ, và cold-start xử lý thế nào?
3. S6 yêu cầu mitigation hay bulkhead hoàn toàn?
4. Acceptance target và eval set là gì?
5. Bedrock Guardrail có thuộc scope release này không?

CDO sẽ:
- port chọn lọc trên branch mới từ latest main;
- giữ nguyên Docker/DB pool/health/IRSA/GitOps safeguards;
- bổ sung CI test, migration verification và candidate smoke;
- build signed digest, migrate trước, merge image-bump PR sau;
- rollout qua Argo CD và rollback bằng revert image-bump PR.

Đề nghị AIO02/CDO01/CDO02 comment trực tiếp vào decision table của plan trước khi chốt GO.
```

---

## 16. Decision log để team điền

| Decision | Lựa chọn đã chốt | Người chốt | Ngày | Link evidence/PR |
|---|---|---|---|---|
| Tier-2 question scope | **Chỉ canonical summary** — gate `is_summary_request` | CDO (chờ AIO ký ở PR) | 29/07/2026 | [`02-aio-contract-decisions.md`](../evidence/product-reviews-sprint3/02-aio-contract-decisions.md) AIO-01/05 |
| Summary key/schema | **Giữ PK `product_id`**; đổi sang key theo intent là schema change riêng | CDO (chờ AIO ký ở PR) | 29/07/2026 | `migration.sql` Step 5 · AIO-02 |
| Review-version freshness | **So `review_version`, lệch/NULL → Tier-3** (fail closed) | CDO (chờ AIO ký ở PR) | 29/07/2026 | `resolve_fallback_summary()` · AIO-03 |
| Cold-start/pre-warm | **Chấp nhận bảng rỗng, KHÔNG pre-warm** — bằng đúng hành vi production hiện tại | CDO (chờ AIO ký ở PR) | 29/07/2026 | AIO-04 |
| S6 architecture | **OPEN — tách Release B**, không port bản S6 của AIO | CDO | 29/07/2026 | §5.2 · postmortem 0016 |
| S6 acceptance target | **OPEN** — thuộc Release B | — | — | — |
| Bedrock Guardrail scope | **Ngoài scope**; `BEDROCK_GUARDRAIL_ID` giữ rỗng | CDO (chờ AIO ký ở PR) | 29/07/2026 | AIO-13/14 |
| Change window | Chưa chốt — cần xác nhận batch Karpenter elastic của CDO01 (PR #316→#330) đã xong |  |  |  |
| Rollback digest/PR | Chưa chốt — chốt ở G8, trước khi merge bot PR-D |  |  |  |
| Rollback decision/restore objective | Chưa chốt — chốt ở G8 |  |  |  |
| Break-glass owner/path | Chưa chốt |  |  |  |
| Candidate test data/cleanup | **Không dựng candidate Deployment ở Release A** (CDO-06 vẫn OPEN); verify Tier-2 sau rollout bằng flagd trên production, xong khôi phục row | CDO | 29/07/2026 | §9 G7 |
| Final GO | Chưa chốt |  |  |  |

---

## 17. Definition of Done

Release A chỉ DONE khi:

- [ ] AIO-01…AIO-17 đã được trả lời hoặc đánh dấu “không áp dụng” kèm lý do.
- [ ] CDO-01…CDO-11 đã đóng và có link bằng chứng.
- [ ] Code được port chọn lọc từ SHA đã ghi, không merge/copy snapshot.
- [ ] Main Docker/health/pool/semaphore/IRSA/flagd safeguards còn nguyên.
- [ ] Tier-2 không trả sai intent hoặc stale review version.
- [ ] Unit/regression/eval/load evidence PASS.
- [ ] Six-values render và server-side dry-run PASS.
- [ ] Candidate image qua Trivy/Cosign/SBOM/provenance.
- [ ] Migration chạy trước image rollout và schema/grants được verify.
- [ ] Candidate smoke PASS, shared dependencies không bị fault và test data đã cleanup/restore.
- [ ] Production rollout bằng bot image-bump PR + Argo CD.
- [ ] SLO/read path/shared RDS không regression.
- [ ] Rollback branch/PR/digest, deadline, restore objective và break-glass owner đã chuẩn bị.
- [ ] Release B/S6 nếu chưa làm vẫn được ghi OPEN, không báo cáo gộp là hoàn thành.

---

## 18. Tài liệu liên quan

- [`aio02-product-reviews-code-contribution.md`](aio02-product-reviews-code-contribution.md)
- [`../product-reviews-guardrails-upgrade-plan.md`](../product-reviews-guardrails-upgrade-plan.md)
- [`../postmortem/0016-product-reviews-deadline-exceeded-under-synthetic-load.md`](../postmortem/0016-product-reviews-deadline-exceeded-under-synthetic-load.md)
- [`../pm-0016-bao-cao-cong-viec-28-07.md`](../pm-0016-bao-cao-cong-viec-28-07.md)
- [`../../gitops/apps/techx-corp.yaml`](../../gitops/apps/techx-corp.yaml)
- [`../../gitops/jobs/product-reviews-schema-migration.yaml`](../../gitops/jobs/product-reviews-schema-migration.yaml)
- [`../../.github/workflows/build-push-ecr.yml`](../../.github/workflows/build-push-ecr.yml)

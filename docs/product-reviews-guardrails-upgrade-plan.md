# Plan + hồ sơ thực hiện: nâng cấp `product-reviews` theo bản AIO02

**Nguồn:** `https://github.com/DangThao195/AIO02_TF3_Phase3/tree/main/AIE1/techx-corp-platform/src/product-reviews`
(fetch từng file qua `raw.githubusercontent.com` ngày 28/07/2026, diff byte-by-byte với code hiện tại).

**Trạng thái:** code đã port xong + verify cục bộ trên nhánh
`feat/product-reviews-aio02-guardrails-upgrade`. **CHƯA deploy, CHƯA chạy migration DB.**
Các bước còn lại cần go-ahead riêng — xem §6.

**Yêu cầu gốc:** chỉ cập nhật phần chưa có, không đụng phần đã có nếu không cần.

---

## 1. Trả lời trực tiếp: có thay được không, đánh đổi gì, downtime không

**Có thay được**, nhưng KHÔNG thể "chỉ thêm file mới, giữ nguyên file cũ" như ý ban đầu. Lý do: các module
mới (circuit breaker, cache, tool validator, routing, llm_trace) đều được `product_reviews_server.py` của
bản AIO02 **import và gọi trực tiếp**. Chỉ copy file mới mà giữ server cũ → module nằm chết, vô dụng.
Vì vậy bắt buộc phải nhận cả `product_reviews_server.py` + `database.py` mới.

**Downtime: KHÔNG**, nếu làm đúng thứ tự §6 (migrate DB trước → build image → rolling deploy
`maxUnavailable:0`). Rollout thất bại sẽ tự dừng và giữ pod cũ phục vụ, không mất traffic.
**Có nguy cơ sập** nếu làm tắt: deploy code mới trước khi migrate DB → mọi request đọc review lỗi ngay
(code mới query `AND is_safe = TRUE`, cột chưa tồn tại).

**Đánh đổi đã chấp nhận:**

| Đánh đổi | Quyết định |
|---|---|
| Thêm phụ thuộc Redis | Dùng lại ElastiCache Valkey **có sẵn** (Mandate #8, cart đang dùng) → không tốn thêm chi phí. Key namespace `product_reviews:*` không đụng cart. |
| Tăng tải kết nối Postgres | **Không lấy nguyên số của AIO02.** Xem §3.2. |
| Tăng thread pool gRPC | **Không lấy nguyên số của AIO02.** Xem §3.2. |
| Thêm 1 HTTP server nhúng (`llm_trace`) | **Mặc định TẮT** (cần cả `PRODUCT_REVIEWS_TRACE_HTTP_PORT` lẫn token mới bật). Ta không set → không mở thêm cổng nào. An toàn với Mandate #1. |
| Message chặn guardrail đổi tiếng Việt → tiếng Anh | Nhận theo bản AIO02 (storefront TechX là tiếng Anh). Đây là thay đổi **người dùng nhìn thấy** — xem §5. |

**Thời gian:** phần khảo sát + port + verify cục bộ: đã xong. Migration DB: vài phút thao tác + thời gian
build index (tuỳ số dòng bảng). Build image + rollout: theo pipeline hiện có (~10-15 phút). Verify sau
deploy: 1 cửa sổ quan sát.

---

## 2. Kết quả diff — file nào cần đổi, file nào không

### 2.1 GIỐNG HỆT → không đụng (đã xác minh bằng `diff`, không suy đoán)

`demo_pb2.py`, `demo_pb2_grpc.py`, `guardrails/output_filter.py`, `guardrails/__init__.py`, `test_client.py`.

**`demo_pb2*` giống hệt là điểm quan trọng nhất về an toàn: gRPC/proto contract KHÔNG đổi** → `frontend`
không phải sửa gì, readiness probe gRPC không đổi, không có vấn đề tương thích old/new pod lúc rollout.

### 2.2 File MỚI hoàn toàn — thêm vào

| File | Vai trò |
|---|---|
| `guardrails/circuit_breaker.py` | Ngắt mạch khi Bedrock lỗi liên tiếp (Redis-backed, fallback in-memory) |
| `guardrails/cache.py` | Cache response LLM qua Redis, TTL mặc định 86400s |
| `guardrails/tool_validator.py` | Validate tham số tool-call trước khi model gọi |
| `guardrails/routing.py` | Chặn sớm câu hỏi lạc đề, không tốn call LLM |
| `guardrails/error_injection.py` | Chèn lỗi giả để test (không dùng trong production) |
| `guardrails/llm_trace.py` | Ghi trace chi tiết call LLM (đi kèm HTTP endpoint, mặc định tắt) |
| `migration.sql` | Schema migration (đã sửa, xem §3.3) |
| `db_migration_worker.py` | Chạy migration + quét gắn `is_safe` cho review cũ (đã sửa, xem §3.3) |
| `aiops_replay_sim.py` | Công cụ replay cho AIOps |

**KHÔNG copy `logs/`** — đó là file log output từ lần họ chạy thử, không phải code.

### 2.3 File đã có, nhận bản mới

`product_reviews_server.py`, `database.py`, `guardrails/{evaluator,fallback,input_filter}.py`,
`GUARDRAIL_DESIGN.md`, `metrics.py` (thêm 1 counter `app_ai_fallback_total`), `requirements.txt`
(+`redis>=5.0.0`), `.env.example`, `README.md`.

`input_filter.py` là nâng cấp bảo mật thật (+175/−28 dòng): chống né guardrail bằng base64/hex, leetspeak,
bỏ dấu tiếng Việt, ký tự điều khiển xen giữa từ.

---

## 3. Những chỗ CỐ Ý KHÔNG lấy nguyên bản AIO02 (và vì sao)

Đây là phần quan trọng nhất của việc port. Nếu dán đè nguyên xi sẽ mất fix / vi phạm gate của repo này.

### 3.1 Dockerfile — GIỮ bản hardened của repo

Bản AIO02 **bỏ** 4 thứ mà repo này bắt buộc phải có:

| Repo hiện tại (giữ) | Bản AIO02 |
|---|---|
| Pin digest base image `@sha256:...` | tag nổi, không pin |
| `apk upgrade libcrypto3 libssl3` | không có |
| `ENV PYTHONDONTWRITEBYTECODE=1` | không có |
| user `nonroot` 65532 + `USER 65532:65532` | không có → chạy **root** |

Copy nguyên sẽ bị **Kyverno chặn admission** (baseline security context: `runAsNonRoot`,
`allowPrivilegeEscalation`, `runAsUser=0`) và/hoặc **Trivy gate PM-101** chặn base image không pin digest.
→ Giữ nguyên Dockerfile của repo, chỉ thêm `COPY` cho `db_migration_worker.py` + `migration.sql`
(để chạy migration bằng Job trong cluster — RDS private, chỉ tới được từ trong VPC).
`COPY ... guardrails guardrails` sẵn có đã tự bao hết file guardrails mới.

### 3.2 Thread pool + DB pool — hạ xuống mức an toàn, cho chỉnh bằng env

| | AIO02 | Repo (sau port) |
|---|---|---|
| `max_workers` gRPC | 50 (hardcode) | **20**, env `GRPC_MAX_WORKERS` |
| DB pool | `minconn=5, maxconn=30` (hardcode) | **2/15**, env `DB_POOL_MIN_CONN`/`DB_POOL_MAX_CONN` |

Lý do: RDS này **dùng chung** với `product-catalog` + `accounting`, và REL-05 ghi nhận cạn connection trên
chính instance đó là nguyên nhân sự cố trong quá khứ. `maxconn=30` × HPA `maxReplicas=6` = tối đa **180
connection** chỉ riêng product-reviews. Chưa xác minh được `max_connections` thật của RDS (IAM read-only
không có quyền `rds:DescribeDBInstances`, cũng không có quyền `kubectl exec` để query trực tiếp) → chọn
mức thận trọng và **cho chỉnh bằng env, không cần rebuild image** khi đã đo được số thật.

### 3.3 `migration.sql` + `db_migration_worker.py` — sửa để không khoá bảng

- Bản gốc dùng `CREATE INDEX` thường → **khoá ghi** bảng `productreviews` suốt lúc build index, mà bảng này
  `product-catalog`/`accounting` cũng đụng. Đã đổi sang `CREATE INDEX CONCURRENTLY`.
- `CONCURRENTLY` **không chạy được trong transaction block**, mà `db_migration_worker.py` gốc chạy file SQL
  qua psycopg2 (mặc định mở transaction) → sẽ lỗi. Đã sửa worker bật `autocommit` cho riêng bước schema,
  rồi trả lại như cũ cho bước quét batch.
- Thêm `GRANT USAGE, SELECT ON SEQUENCE reviews.fidelity_audit_id_seq TO otelu` — bản gốc thiếu, mà bảng
  dùng `SERIAL` nên INSERT sẽ lỗi permission nếu không có.
- Đã xác minh: cột `id` tồn tại trên `reviews.productreviews` (`src/postgresql/init.sql`), và `otelu` đúng
  là user ứng dụng → 2 tiền đề của migration đều hợp lệ.

### 3.4 GIỮ LẠI fix PM-0016 (bản AIO02 không có)

**Bản AIO02 KHÔNG chứa `AI_ASSISTANT_MAX_CONCURRENCY` / semaphore** — tức là fix PM-0016 vừa deploy lên
production hôm nay (PR #531) sẽ **bị mất** nếu dán đè. Đã re-apply nguyên vẹn lên bản mới.

Circuit breaker của AIO02 **không thay thế được** nó: circuit breaker trip khi Bedrock **lỗi**, còn
semaphore giới hạn **số call đồng thời** ngay cả khi Bedrock vẫn trả lời (chỉ chậm) — đúng kịch bản
throttle đã quan sát được ở §13.5 của postmortem 0016. Hai cơ chế bổ sung cho nhau, giữ cả hai.

### 3.5 GIỮ LẠI health check REL-02 (bản AIO02 làm mất)

Bản AIO02 đổi `Check()` thành trả `SERVING` vô điều kiện, và đăng ký `grpc_health.HealthServicer` tĩnh.
Repo này **cố ý** làm readiness của product-reviews phụ thuộc DB (REL-02) để pod mất kết nối Postgres bị
rút khỏi Service endpoints thay vì tiếp tục nhận request rồi fail.

Đã hợp nhất **cả hai**: giữ probe DB của REL-02, đồng thời giữ cơ chế graceful shutdown mới của AIO02
(SIGTERM → `shutdown_event` → `Check()` trả `NOT_SERVING` → K8s rút traffic trước khi gRPC server dừng).
Đăng ký servicer của chính service (không phải HealthServicer tĩnh) để `Check()` thật sự được gọi.

Đồng thời vá một lỗi tiềm ẩn của bản AIO02: fallback `health_pb2` khi thiếu `grpc_health` chỉ định nghĩa
`SERVING`, thiếu `NOT_SERVING`/`UNIMPLEMENTED` → sẽ `AttributeError` trên nhánh unhealthy.

---

## 4. Đính chính so với bản plan đầu tiên

- **Bedrock Guardrail KHÔNG phải tính năng mới.** Repo hiện tại **đã có sẵn** code gọi `apply_guardrail`
  (`guardrails/input_filter.py`), chỉ là **chưa bật** vì `.env.example` không set `BEDROCK_GUARDRAIL_ID`
  (không set → code tự bỏ qua, fail-open). Bản AIO02 chỉ refactor cách đọc config từ hằng số module sang
  hàm (để `db_migration_worker` tạm tắt được). → **Không phải blocker**, không cần tạo tài nguyên AWS mới
  để deploy lần này. Việc bật Guardrail là quyết định riêng, thuộc AIO02.
- Plan đầu ước "diff `product_reviews_server.py` chưa đọc kỹ" — nay đã đọc và xử lý, kết quả ở §3.4/§3.5.

---

## 5. Rủi ro còn lại đã biết (không chặn deploy, nhưng phải nắm)

1. **Message guardrail đổi sang tiếng Anh.** Ví dụ `"Yêu cầu này không được phép..."` →
   `"This request is not allowed..."`. Người dùng cuối nhìn thấy. Nhận theo bản AIO02 vì storefront là
   tiếng Anh — nếu team muốn giữ tiếng Việt thì sửa `BLOCK_MESSAGES` trong `guardrails/input_filter.py`.
2. **`init_db_pool` retry 5 lần × 2s** khi DB không tới được → thêm tối đa ~10s vào thời gian khởi động pod
   trong kịch bản DB lỗi. Bình thường (DB khoẻ) không ảnh hưởng. Lưu ý vì P4 của postmortem 0016 đang theo
   dõi time-to-Ready.
3. **Chưa đo được `max_connections` thật của RDS** (thiếu quyền IAM) → số pool hiện đặt thận trọng, cần đo
   lại rồi mới nâng.
4. **Redis chỉ nằm trên đường AI.** Đã xác minh bằng đọc code: `get_product_reviews` và
   `get_average_product_review_score` **không** gọi cache/Redis → Valkey lỗi không thể ảnh hưởng 2 RPC mang
   deadline 500ms của frontend. Mọi call Redis đều bọc try/except, timeout 1s, circuit breaker fallback
   in-memory.

---

## 6. Các bước CÒN LẠI — theo đúng thứ tự này, không đảo

Mỗi bước cần xác nhận trước khi sang bước sau.

1. **Review + merge PR code** (nhánh `feat/product-reviews-aio02-guardrails-upgrade`).
   Merge PR này **chưa** đưa code mới lên cluster — image chưa được build/bump. Riêng thay đổi
   `values-aio-llm.yaml` (thêm env Redis) sẽ gây 1 lần rolling restart pod **với image CŨ** + env mới;
   code cũ bỏ qua env lạ nên vô hại, zero-downtime.
2. **Chạy migration DB** — giờ ít traffic, có xác nhận. RDS private nên phải chạy từ trong cluster
   (Job dùng đúng image mới, override command sang `python db_migration_worker.py`, hoặc chạy tay từng
   lệnh trong `migration.sql` bằng `psql`). **Verify sau khi chạy:** cột `is_safe` tồn tại và `TRUE` cho
   toàn bộ review cũ; index `productreviews_prod_safe_idx` `indisvalid = true`; bảng `fidelity_audit` +
   quyền `otelu` OK.
3. **Build image** qua `build-push-ecr.yml` (scoped `product-reviews`), phải qua Trivy + Cosign gate.
4. **Merge PR bump-image** do bot tạo → ArgoCD rolling update `maxUnavailable:0`.
5. **Verify sau deploy:** pod Ready không crash loop; log không lỗi kết nối Redis/DB; thử 1 request đọc
   review + 1 request hỏi AI; xác nhận `Check()` vẫn phản ánh đúng trạng thái DB; theo dõi 1 cửa sổ ổn định.
6. **Sau khi ổn định:** chạy phần batch scan của `db_migration_worker.py` để gắn `is_safe` thật cho review
   cũ (không chặn go-live vì cột mặc định `TRUE`).

**Rollback:** revert PR bump-image → ArgoCD sync về digest cũ. Schema migration **không cần rollback**
(thuần additive: thêm cột có DEFAULT, thêm index, thêm bảng — code cũ không dùng nhưng cũng không vướng).

---

## 7. Đã verify cục bộ những gì (28/07/2026)

- `py_compile` sạch toàn bộ 16 file Python.
- **Import thật** `product_reviews_server` với dependency thật (grpcio, boto3, psycopg2, redis, openai,
  tenacity, openfeature...) trong venv riêng → `IMPORT OK`, không NameError/AttributeError.
- **Test chức năng với gRPC server THẬT** (`grpc.server` + `demo_pb2_grpc` thật, stub DB và call AI),
  10/10 pass:
  - health `SERVING` khi DB khoẻ → chứng minh servicer REL-02 **thật sự được đăng ký**, không phải code chết;
  - health `NOT_SERVING` khi probe DB lỗi (REL-02 còn nguyên);
  - health `NOT_SERVING` khi `shutdown_event` set, và trở lại `SERVING` khi clear (graceful shutdown);
  - burst 25 request AI đồng thời: concurrency giữ đúng cap 4, 4 served + 21 shed, không request nào treo,
    semaphore không rò permit;
  - RPC đọc review vẫn phục vụ bình thường trong lúc đường AI bão hoà.
- **`helm template`** với đúng 6 value file mà ArgoCD dùng thật → render OK, env Redis vào đúng chỗ,
  `DB_CONNECTION_STRING` không bị clobber, serviceAccount `product-reviews-bedrock` giữ nguyên.

**Chưa verify được (cần cluster/DB thật):** hành vi cache/circuit breaker với Valkey thật, migration chạy
trên RDS thật, tương tác với Bedrock Guardrail nếu bật.

# Báo cáo công việc — PM-0016 `product-reviews` + nâng cấp bản AIO02 (28/07/2026)

**Người thực hiện:** CDO01 (qua Claude Code) · **Ngày:** 28/07/2026 · **Đối tượng:** team TF3 (CDO01 + CDO02 + AIO02)

> **Lưu ý về phân công:** sự cố PM-0016 thuộc trụ **Reliability** (CDO02), nhưng đợt xử lý này do **CDO01**
> thực hiện. Các việc còn lại ở mục 8 cần **CDO01 và CDO02 thống nhất ai nhận** — bảng dưới chỉ ghi theo
> trụ chuyên môn, chưa phải phân công chính thức.

**Tài liệu liên quan:**
- Postmortem đầy đủ: [`docs/postmortem/0016-product-reviews-deadline-exceeded-under-synthetic-load.md`](postmortem/0016-product-reviews-deadline-exceeded-under-synthetic-load.md)
- Báo cáo ngắn cho AIO02: [`docs/pm-0016-bao-cao-tong-hop.md`](pm-0016-bao-cao-tong-hop.md)
- Plan nâng cấp AIO02: [`docs/product-reviews-guardrails-upgrade-plan.md`](product-reviews-guardrails-upgrade-plan.md)

---

## 1. Tóm tắt điều hành

Trong 1 ngày đã xử lý xong sự cố PM-0016 (`product-reviews` timeout dưới tải), hoàn tất phần lớn action
item của postmortem, và nâng cấp `product-reviews` lên bản chuẩn của AIO02. **Tất cả đã LIVE trên
production, zero downtime.**

**Kết quả đo được, so cùng kịch bản 500 user:**

| Chỉ số | Trước | Sau |
|---|---|---|
| Bedrock `ThrottlingException` | hàng loạt | **0** |
| AI assistant response time | 15-25 giây | **0.15 giây** (cache hit) |
| Redis cache hit | không có tính năng | **2664** |
| HPA phải scale thêm pod | có (3→4) | **không cần**, giữ 2 pod |
| Lỗi `product-reviews` | có, kèm `500` mù | 2.5%, **100% `503` phân loại, 0 lỗi `500`** |
| Pod restart | 0 | **0** |

**Đáng chú ý:** trong quá trình làm đã **tự phát hiện và chặn 4 bug nghiêm trọng** trước khi lên
production — trong đó có 1 bug rò connection có thể kéo sập cả `product-catalog` và `accounting` (mục 5).

**13 PR đã merge, 1 đang chờ review.**

---

## 2. Bối cảnh sự cố gốc

Trong lúc chạy load test, gọi API lấy review sản phẩm bị `DEADLINE_EXCEEDED` (quá 500ms).

Nguyên nhân được khoanh vùng trong postmortem:
1. HPA scale `product-reviews` 2→3 pod, nhưng pod mới mất **70-80 giây** mới sẵn sàng (chờ Karpenter dựng
   node mới + pull image + khởi động app) → trong lúc đó 2 pod cũ gánh hết tải.
2. `product-reviews` dùng **chung 1 pool 10 luồng** cho cả API đọc review (nhanh) và API hỏi AI/Bedrock
   (chậm) → request AI có thể chiếm hết luồng.
3. Code không phân biệt "lỗi timeout" với "sản phẩm chưa có review" → hiển thị sai.

---

## 3. Phần 1 — Fix PM-0016 (PR #531, #533, #535, #538)

### 3.1 Đã làm

| Việc | Chi tiết |
|---|---|
| **P2 — phân loại lỗi** | 2 route `product-reviews` + `product-reviews-avg-score` bắt riêng gRPC `DEADLINE_EXCEEDED`/`UNAVAILABLE` → trả `503 DEPENDENCY_UNAVAILABLE` thay vì `500` mù |
| **P3 một phần — admission control** | Thêm `BoundedSemaphore` giới hạn tối đa 4 request AI đồng thời; vượt cap thì shed nhanh bằng message "AI đang bận" có sẵn |
| **Vá 2 CVE HIGH** | `brace-expansion` (CVE-2026-14257), `postcss` (GHSA-r28c-9q8g-f849) — chặn build ở Trivy gate, không liên quan sự cố |

### 3.2 Kiểm tra câu hỏi về rate-limit trong `values-prod.yaml`

Có nghi vấn config rate-limit Mandate #19 gây ra lỗi. **Đã kiểm tra và loại trừ:**
`BROWSE_RATE_LIMIT_ENFORCED_PERCENT` và `LOCAL_RATE_LIMIT_ENFORCED_PERCENT` đều `"0"` (shadow mode, không
enforce), và thuộc component `frontend-proxy` (Envoy, biên browse) — **không nằm trên đường**
`frontend → product-reviews` (gRPC nội bộ).

### 3.3 Bug tự phát hiện khi verify (ngoài phạm vi plan gốc)

`utils/Request.ts` — file dùng chung cho **mọi** gateway phía client — **không kiểm tra `response.ok`**:
parse JSON body bất kể status code rồi coi là thành công. Nếu không vá, response `503` ở trên sẽ bị client
nuốt thành "thành công" → rơi về `[]` → **đúng anti-pattern mà postmortem cấm**, chỉ khác là ở tầng client.
Đã vá.

---

## 4. Phần 2 — Hoàn tất action item postmortem (PR #542, #543, #545, #547)

### 4.1 P4 — đo time-to-Ready thật

Tận dụng chính đợt rollout để đo, thay vì suy đoán:

| Pod | Chờ schedule | Pull image | App start→Ready | **Tổng** |
|---|---|---|---|---|
| Pod **đầu** của scale event | **39s** (chờ Karpenter dựng node mới) | 11.7s | 22s | **77s** |
| Pod **thứ hai** (node đã sẵn) | 0s | 5.6s | 21s | **29s** |

→ Bằng chứng cụ thể cho khuyến nghị pre-scale: pod đầu chậm **2.7 lần** vì phải chờ dựng node.
`kubectl top nodes` xác nhận nút thắt **không phải** thiếu CPU/RAM trên node hiện có, mà là **thiếu sẵn 1
node mới**.

### 4.2 P0 + P1 — load test có kiểm soát trên production

Chạy đúng runbook §7: preflight → pre-scale (PR #543) → chờ 3/3 Ready → bắn tải theo stage → revert (#545).

| Stage | Users | Thời lượng | RPS | Kết quả |
|---|---|---|---|---|
| 1 | 60 | 3 phút | ~15 | **0 lỗi** |
| 2 | 200 | 6 phút | ~40 | **0 lỗi** |
| 3 | 500 | 7 phút | ~100 | HPA scale 3→4, tái hiện đúng capacity-arrival gap |

`checkout`/`cart`/`product-catalog`: **0 restart** suốt cả 3 stage.

### 4.3 Phát hiện mới: AWS Bedrock throttle

Log thật trong cửa sổ Stage 3:

```
ThrottlingException: An error occurred (ThrottlingException) when calling the Converse operation
(reached max retries: 4): Too many requests, please wait before trying again.
```

→ Giải thích đúng vì sao trace AI mất 15-25s. **Không phải bug code**, mà là **giới hạn tốc độ của AWS
Bedrock**. Đây là việc thuộc AIO02 → đã viết báo cáo riêng (PR #547).

---

## 5. Phần 3 — Nâng cấp bản AIO02 (PR #554, #557, #558, #559)

Nguồn: `DangThao195/AIO02_TF3_Phase3`, đã diff **byte-by-byte từng file**, không suy đoán.

### 5.1 Nhận vào những gì

**Module mới:** circuit breaker, cache LLM (Redis), tool validator, off-topic routing, llm-trace, error
injection, + công cụ migration schema.
**Nâng cấp:** `input_filter` chống né guardrail bằng base64/hex/leetspeak/bỏ dấu tiếng Việt (+175 dòng);
`evaluator`/`fallback` viết lại; `metrics` thêm counter.

**Điểm an toàn quan trọng:** `demo_pb2.py`/`demo_pb2_grpc.py` **giống hệt** upstream → **gRPC contract
không đổi** → `frontend` không phải sửa gì, không có vấn đề tương thích old/new pod lúc rollout.

### 5.2 Những chỗ CỐ Ý không lấy nguyên bản upstream

Nếu dán đè nguyên xi sẽ **làm hỏng 5 thứ** của repo này:

| | Vì sao không lấy nguyên |
|---|---|
| **Dockerfile** | Upstream bỏ pin digest base image, bỏ `apk upgrade libcrypto3/libssl3`, bỏ `PYTHONDONTWRITEBYTECODE`, **bỏ non-root user (chạy root)** → sẽ bị **Kyverno chặn admission** và **Trivy gate PM-101** chặn. Giữ nguyên Dockerfile repo. |
| **Fix PM-0016** | Upstream **không có** semaphore `AI_ASSISTANT_MAX_CONCURRENCY` → dán đè là **mất fix vừa deploy sáng cùng ngày**. Đã re-apply. Circuit breaker **không thay thế được**: breaker trip khi Bedrock **lỗi**, semaphore giới hạn **số call đồng thời** ngay cả khi Bedrock vẫn trả lời (chỉ chậm). |
| **Health check REL-02** | Upstream đổi `Check()` thành `SERVING` vô điều kiện → **mất** cơ chế rút pod khỏi Service khi mất kết nối DB. Đã khôi phục, đồng thời **giữ** graceful shutdown mới của upstream. |
| **Kích thước pool** | Xem mục 5.3 |
| **`migration.sql`** | Upstream dùng `CREATE INDEX` thường → **khoá ghi** bảng dùng chung. Đổi sang `CONCURRENTLY`. Thiếu `GRANT` trên SEQUENCE → INSERT sẽ lỗi permission. Đã bổ sung. |

### 5.3 Bug nghiêm trọng tự phát hiện — rò connection có thể kéo sập 3 service

Nhờ đổi sang account có quyền đọc RDS, lần đầu đo được thông số thật:

- RDS `techx-tf3-postgres` là **`db.t4g.micro` (1 GiB)** → `max_connections ≈ **112**` cho **TẤT CẢ** service.
- `product-catalog` đã đặt `SetMaxOpenConns(20)` × HPA tối đa 8 pod = **160** → cụm **vốn đã oversubscribed**.
- Bản AIO02 hardcode `maxconn=30` × HPA 6 pod = **180 riêng product-reviews** → vượt xa trần.

**Bug thật trong code AIO02:** khi pool cạn, `get_db_connection()` **dựng lại cả pool mới mà không đóng
pool cũ** → rò `maxconn` connection mỗi lần, **lặp lại liên tục dưới tải**. Trên RDS 112 connection dùng
chung, đây đúng là kịch bản sự cố **REL-05**, và sẽ **kéo sập cả `product-catalog` + `accounting`**.

**Đã sửa:**
- Pool cạn (`PoolError`) → fail đúng 1 request đó, **không** dựng lại pool (pool tự hồi phục khi request
  in-flight trả connection về).
- Chỉ dựng lại pool khi pool **thật sự hỏng**, và **`closeall()` pool cũ trước**.
- Hạ pool về **1/10** — **đúng bằng giá trị production đang chạy**, không tăng chút nào. Worker 50→**12**
  cho khớp pool. Cả hai **chỉnh được bằng env**, không cần rebuild image.

### 5.4 Migration schema — lỗi lần 1, đã sửa

Lần chạy đầu fail: `CREATE INDEX CONCURRENTLY cannot run inside a transaction block`.
Nguyên nhân: đặt `autocommit=True` **vẫn chưa đủ** — gửi **nhiều câu lệnh trong 1 `execute()`** khiến
PostgreSQL tự bọc thành 1 implicit transaction.

Đã sửa: tách từng câu lệnh chạy riêng. Phải **strip comment trước** vì `migration.sql` có dấu `;` nằm
trong comment (tách ngây thơ sẽ cắt sai chỗ).

**Lần 2 thành công**, log tự verify:
```
is_safe column present BEFORE: 0        ← lần fail trước rollback sạch, không có state dở dang
is_safe column: [('is_safe', 'boolean', 'true')]
index: [('reviews.productreviews_prod_safe_idx', True)]   ← indisvalid, không INVALID
fidelity_audit table: ('reviews.fidelity_audit',)
rows with is_safe not TRUE: (0,)
```
`product-catalog`/`accounting` **không restart**, storefront `200` — **không downtime**.

### 5.5 Back-fill `is_safe` — kiểm tra trước, hoá ra là no-op

Filter mới chặt hơn nhiều → chạy back-fill mù có rủi ro **đánh nhầm review hợp lệ thành unsafe**, mà mọi
query đều lọc `is_safe = TRUE` → review sẽ **biến mất khỏi storefront**.

Đã chạy **dry-run** (chỉ báo cáo, không ghi): **50 review, 0 bị đánh dấu** → no-op thật sự,
**không cần chạy**.

---

## 6. Quy trình review — 7 phát hiện, tất cả đã xử lý

PR #531 qua **2 vòng review độc lập**, cả 2 đều verify được là đúng:

**Vòng 1 (5 phát hiện):**
1. Semaphore chỉ là admission control, không phải bulkhead thật → đo bằng **grpc server thật**: burst 100
   request AI → read RPC chờ **~758ms, vượt deadline 500ms**. Đã sửa mô tả, bỏ overclaim.
2. React Query retry mặc định (3 lần) có thể **khuếch đại tải** vào lúc dependency đang quá tải → thêm
   policy không retry khi lỗi `503`.
3. Postmortem ghi "đã triển khai" trong khi PR chưa merge → sửa.
4. Docs lệch code (timeout 2s vs 0.05s) → đồng bộ.
5. `Request.ts` parse JSON trước khi check `response.ok` → bọc try/catch.

**Vòng 2 (2 phát hiện):**
1. **Không tương thích rolling rollout**: body lỗi `503` dạng JSON sẽ bị client bundle **cũ** parse thành
   "thành công" trong lúc pod cũ/mới cùng tồn tại → tái diễn đúng lỗi cần chặn. **Chính postmortem gốc đã
   cảnh báo điều này** ở mục P2 mà lần triển khai đầu bỏ sót. Đã đổi body sang **plain text** để
   `JSON.parse` throw ở cả 2 phiên bản client.
2. Bản vá vòng 1 bọc try/catch quá rộng, nuốt luôn lỗi parse của response `2xx` → chỉ bọc cho non-2xx.

---

## 7. Kiểm chứng cuối — đo lại đúng kịch bản gây sự cố

Chạy lại **500 user** sau khi nâng cấp:

**Đã hết:**
- **Bedrock throttle: 0** (trước là hàng loạt) — cache Redis hấp thụ **2664 hit**, AI response **0.15s**.
- **Semaphore shed: 0** — không cần tới, vì cache đã chặn tải trước đó.
- **HPA không cần scale** — AI hết ngốn CPU nên capacity-arrival gap **không bị kích hoạt**.
- **Lỗi hiển thị sai: hết** — 57/57 lỗi đều `503` phân loại, **0 lỗi `500` mù**.

**Chưa hết:**
- **~2.5% request đọc review vẫn vượt deadline 500ms** (57/2307) ở ~100 RPS với 2 pod. Khác biệt là
  **cách hỏng**, không phải hết hỏng.
- Nguyên nhân gốc còn nguyên: pod mới ~70-80s mới Ready; AI vẫn dùng chung thread pool với đường đọc.
  **Cache chỉ CHE được ở mức tải này, chưa phải cô lập thật.**

**Cảnh báo cho team:** cache chỉ hiệu quả khi câu hỏi **lặp lại**. Locust dùng vài câu cố định nên tỉ lệ
hit rất cao — người dùng thật hỏi đa dạng, hoặc TTL 24h hết, hoặc Redis lỗi → **Bedrock sẽ bị gọi thật trở
lại và throttle có thể quay lại**.

---

## 8. Còn lại (chưa làm)

Cột "trụ" ghi theo chuyên môn, **chưa phải phân công chính thức** — CDO01/CDO02 cần thống nhất ai nhận.

| Việc | Trụ liên quan | Mức độ |
|---|---|---|
| **P3 đầy đủ** — tách AI ra deployment/service riêng | Reliability (CDO02) | Quan trọng nhất. Cache che được ở mức tải hiện tại nhưng không phải cô lập thật |
| **P5** — xem lại deadline 500ms theo p95/p99 thật | Reliability (CDO02) | Cần export Locust CSV để có số chính xác |
| **Capacity-arrival gap** — pod mới ~70-80s mới Ready | Reliability (CDO02) + Perf (CDO01) | Hiện chỉ né được bằng pre-scale thủ công |
| Theo dõi quota Bedrock cho trường hợp cache miss cao | AIO02 | **Không còn gấp** sau khi có cache |
| `product-catalog` 20 conn/pod × 8 pod trên RDS 112 connection | Perf (CDO01) + Reliability (CDO02) | Rủi ro tiềm ẩn có sẵn, ngoài phạm vi đợt này |

**Incident PM-0016 chưa đóng chính thức** — xem tiêu chí đầy đủ ở postmortem §8/§14.

---

## 9. Danh sách PR

| PR | Nội dung | Trạng thái |
|---|---|---|
| #531 | Fix PM-0016: phân loại 503 + admission control AI | ✅ merged |
| #533 | Vá 2 CVE HIGH (brace-expansion, postcss) chặn build | ✅ merged |
| #535 | Bump image `frontend` | ✅ merged |
| #538 | Bump image `product-reviews` | ✅ merged |
| #542 | Docs: ghi lại deploy + số liệu P4 thật | ✅ merged |
| #543 | Ops: tạm pre-scale HPA 2→3 cho load test | ✅ merged |
| #545 | Ops: revert pre-scale sau test | ✅ merged |
| #547 | Docs: báo cáo cho AIO02 (Bedrock throttle) | ✅ merged |
| #554 | Port bản AIO02, giữ nguyên các fix của repo | ✅ merged |
| #556 | Bump image (digest cũ) | ❌ đã đóng — bị #557 thay thế |
| #557 | Fix rò connection pool + sizing theo RDS thật | ✅ merged |
| #558 | Fix Job migration (tách câu lệnh) | ✅ merged |
| #559 | Bump image `product-reviews` (bản cuối) | ✅ merged |
| #562 | Docs: đo lại sau nâng cấp | ⏳ chờ review |

---

## 10. Bài học rút ra

1. **Bản "chuẩn" của team khác không nhất thiết chuẩn với repo mình.** Nếu dán đè nguyên xi bản AIO02 sẽ
   mất 5 thứ: fix PM-0016 vừa deploy, health check REL-02, và Dockerfile hardening (sẽ bị Kyverno/Trivy
   chặn thẳng). Bắt buộc phải diff từng file, không copy cả thư mục.
2. **Đo trước khi chỉnh số.** Con số `maxconn=30` của upstream trông vô hại cho tới khi đo được RDS chỉ có
   112 connection tổng. Trước đó không đo được vì thiếu quyền IAM — đáng lẽ nên xin quyền sớm hơn.
3. **Dry-run trước khi chạy batch update trên dữ liệu thật.** Back-fill `is_safe` hoá ra là no-op, nhưng
   nếu filter mới có false positive thì review thật sẽ biến mất khỏi web mà không ai biết.
4. **Postmortem có giá trị khi được đọc kỹ.** Lỗi tương thích rolling rollout (vòng review 2) đã được
   chính postmortem cảnh báo ở mục P2 — bỏ sót vì đọc không kỹ.
5. **Thứ tự deploy quan trọng hơn tốc độ.** Nếu merge PR bump-image trước khi chạy migration DB, mọi
   request đọc review sẽ lỗi ngay lập tức. Đã chủ động comment chặn PR #556 vì lý do này.

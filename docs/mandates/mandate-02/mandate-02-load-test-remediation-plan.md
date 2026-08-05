# Mandate #2 — Review báo cáo readiness + Kế hoạch remediation trước khi chạy 200 users

**Ngày:** 15/07/2026 (cập nhật lần 2, sau khi merge PR #105 + #107)
**Báo cáo gốc được review:** đánh giá capacity/readiness do tutruong thực hiện (dán trực tiếp vào chat, tham chiếu `resource-quota.yaml`, `hpa.yaml`, `karpenter-nodepool.yaml`, `values-production.yaml`)
**Kết luận báo cáo gốc:** NO-GO cho bài đo chính thức 200 users.
**Trạng thái hiện tại:** 4/5 blocker cấu trúc đã fix + verify (`helm template` pass, giá trị đã confirm live sau merge) — xem mục 5. Còn 1 blocker (backup/restore) + 2 việc vận hành (abort threshold, flagd health check) chưa làm.

---

## 0. Tổng hợp toàn bộ thay đổi chuẩn bị trước test (để xác thực lại sau)

Toàn bộ nằm trong `phase3 - information/deploy/values-prod.yaml` trừ khi ghi chú khác. Đã verify từng
đợt bằng `helm template` (mô phỏng đúng lệnh ArgoCD dùng) trước khi merge — không có đợt nào fail schema.

### Observability — tránh OOM khi volume trace/metric/log tăng dưới 200 user

| Component | Trước | Sau | Lý do |
|---|---|---|---|
| Prometheus (`prometheus.server.resources`) | limit 800Mi | **limit 1200Mi** (request 450Mi) | Đã ở >80% limit ngay cả tải thấp |
| OpenSearch (`opensearch.resources`) | limit 1100Mi | **limit 1600Mi** (request 750Mi) | Tương tự Prometheus |
| Kafka (`components.kafka.resources`) | limit 1Gi | **limit 1.5Gi** (request 650Mi) | Tăng thêm lần 2 (tự làm) sau khi 1Gi vẫn chưa đủ dư |
| Jaeger (`jaeger.jaeger.resources`) | limit 1Gi | **limit 2Gi** (request 750Mi) | **OOMKilled thật** (Exit Code 137) giữa lúc load test 200 user lần trước — bị bỏ sót ở đợt tăng đầu tiên (chỉ tăng Prometheus/OpenSearch/Kafka), phát hiện muộn |
| OpenTelemetry Collector (`opentelemetry-collector.resources`) | không set (mặc định chart) | **limit 350Mi** (mới thêm) | Tự thêm — collector cũng ăn theo volume trace tăng, trước đó chưa có limit riêng nào ghi đè |

### App resources — memory limit quá mỏng cho 200 user, không có HPA để bù

| Component | Trước | Sau | Lý do |
|---|---|---|---|
| `payment` | limit 180Mi | **limit 300Mi** | Đã dùng ~50-54% limit chỉ với 10 user nền — đứng đường charge tiền, ưu tiên cao nhất |
| `shipping` | limit 20Mi | **limit 64Mi** | Quá mỏng, không HPA |
| `quote` | limit 40Mi | **limit 80Mi** | Tương tự, shipping phụ thuộc quote |

### Scheduling / hạ tầng scale

| Thay đổi | File | Chi tiết | Lý do |
|---|---|---|---|
| `topologySpreadConstraints` cho `checkout` | `values-prod.yaml` (+ schema `values.schema.json` + template `_objects.tpl`) | hostname (soft/`ScheduleAnyway`) + zone (hard/`DoNotSchedule`) | 2 pod stable từng nằm chung 1 node — mất node đó là mất cả 2 pod dù có PDB |
| `ResourceQuota.pods` | `gitops/infrastructure/resource-quota.yaml` | 90 → **100** | 42/90 pod, cộng dồn HPA max có thể chạm trần |
| Karpenter `consolidateAfter` | `gitops/karpenter/spot-nodepool.yaml` | 2m → 1h → **3m** | 2m ban đầu quá nhạy, gây rollout fail oan → tăng lên 1h để chặn hẳn trong lúc test → sau đó hạ về 3m vì 5 pod checkout-critical đã có `do-not-disrupt` riêng bảo vệ rồi (không phụ thuộc `consolidateAfter` nữa), nên hạ xuống để "co xuống" sau test hiện nhanh cho report thay vì đợi 1h |

### ⚠️ TẠM THỜI — phải dọn lại sau khi test xong

| Thay đổi | Vì sao là tạm | Cần làm gì sau test |
|---|---|---|
| `karpenter.sh/do-not-disrupt: "true"` trên `cart`, `checkout`, `payment`, `shipping`, `quote` (`podAnnotations`) — **cộng thêm `postgresql`, `valkey-cart` do PR #112 (tuu-ngo, Mandate #3 reliability) thêm vào khi merge, giờ là 7 component** | Đồng hồ `consolidateAfter` tính **riêng từng node**, và PDB (`minAvailable: 1`) **không** chặn được kiểu disruption này — đã xác nhận `DISRUPTIONS-ALLOWED: 1` trên cả 3 PDB payment/quote/shipping ngay lúc 2/2 pod khỏe, đúng kiểu evict đã xảy ra thật giữa lúc test trước (gây 503/500). Annotation này miễn nhiễm hoàn toàn với timer lẫn PDB-permitted eviction, chặn Karpenter dứt khoát trong lúc test — **giữ lại**, không gỡ theo đề xuất ban đầu vì PDB không thay thế được. | **Gỡ `podAnnotations.karpenter.sh/do-not-disrupt` khỏi cả 7 component** (`cart`, `checkout`, `payment`, `shipping`, `quote`, `postgresql`, `valkey-cart`) ngay sau khi xác nhận test xong + đã co xuống — để lại lâu sẽ chặn Karpenter tối ưu chi phí node, đi ngược đúng mục tiêu cost của Mandate 2 |
| Karpenter `consolidateAfter: 3m` (đã hạ từ 1h) | Hạ xuống để "co xuống" hiện nhanh cho report — an toàn vì 5 pod checkout-critical đã có `do-not-disrupt` riêng, không còn phụ thuộc giá trị này nữa | **Đổi lại `2m`** (giá trị gốc trước Mandate 2) trong `gitops/karpenter/spot-nodepool.yaml` sau khi xong hẳn Mandate 2 (đã ghi sẵn trong runbook Bước 3, cần cập nhật số từ "1h" thành "3m") |

### Dashboard (không phải hạ tầng, nhưng cùng đợt chuẩn bị)

| File | Thay đổi | Lý do |
|---|---|---|
| `slo-dashboard.json` — 4 panel Cart | Đổi query từ `service_name="cart"` sang `service_name="frontend", span_kind="SPAN_KIND_SERVER", span_name=~"GET /api/cart\|POST /api/cart"` | Panel cũ đo ở backend `cart`, service này **không bao giờ** đánh dấu span lỗi (xác nhận qua Prometheus: 100% `STATUS_CODE_UNSET`), nên dashboard luôn hiện 100% dù Locust thấy lỗi 503 thật. **Giới hạn đã biết:** vẫn không bắt được lỗi kiểu Envoy circuit-breaker (span tên chung `GET`/`POST`, không gắn được route cụ thể) — xem mục 2 phía dưới. |

---

## 1. Xác nhận báo cáo — đã verify trực tiếp trên cluster live

Đối chiếu lại các con số quan trọng nhất trong báo cáo với `kubectl` trực tiếp (không tin theo báo cáo mà không kiểm tra lại):

| Claim trong báo cáo | Verify live | Kết quả |
|---|---|---|
| ResourceQuota pods 42/90 | `kubectl -n techx-tf3 get resourcequota` | ✅ Khớp chính xác: `pods: "42"` / hard `90` |
| Memory request ~7.3/16Gi, limit ~13.2/24Gi | như trên | ✅ Khớp: `requests.memory: 7124Mi`/16Gi, `limits.memory: 13190Mi`/24Gi |
| CPU request tổng ~3.65 core, limit ~15.8 core | tính tổng từ `kubectl get pods -o json` toàn namespace | ✅ Khớp gần đúng: 3.65 core request, 16.1 core limit |
| 9 HPA, target CPU 65% | `kubectl -n techx-tf3 get hpa` | ✅ Khớp: đúng 9 HPA (ad, cart, checkout, currency, frontend, frontend-proxy, product-catalog, product-reviews, recommendation) |
| LOCUST_AUTOSTART=true, đang tự chạy | `kubectl -n techx-tf3 get deploy load-generator -o json` | ✅ Khớp: `LOCUST_AUTOSTART=true`, `LOCUST_USERS=10` |
| Checkout không có topology spread/anti-affinity | `kubectl -n techx-tf3 get deploy checkout -o json` | ✅ Khớp: `affinity: None`, `topologySpreadConstraints: None` |
| Không có VolumeSnapshot CRD / backup CronJob | `kubectl get crd` + `kubectl get cronjob -n techx-tf3` | ✅ Khớp: CRD không tồn tại, không có CronJob nào |

**Kết luận:** báo cáo chính xác cao, không có con số nào bị thổi phồng hay sai lệch đáng kể khi đối chiếu với live cluster. Có thể tin tưởng dùng làm nền cho kế hoạch remediation bên dưới.

## 2. Phát hiện mới — root cause chính xác của checkout-rollout Degraded (mục blocker #1 báo cáo đã nêu đúng hướng)

Đã đào sâu thêm phần báo cáo mới nêu chung chung ("Request-rate bằng 0 và p95 dùng fallback 999999"):

- `AnalysisRun checkout-rollout-5fc5959fb6-11-1` fail đúng 3/5 metric: `checkout-request-rate` (value `[0]`), `checkout-canary-p95-latency-ms` (fallback `[999999]`), `checkout-p95-regression-vs-stable-ms` (fallback `[999973]`). Cả 3 đều là metric **phụ thuộc traffic thật** đổ vào đúng pod canary (`rollouts_pod_template_hash="{{canary-hash}}"`).
- Đối chiếu ReplicaSet: pod canary (`checkout-rollout-5fc5959fb6`) chạy image `@sha256:a774cb6...`, pod stable (`checkout-rollout-5f6cdf58fc`) chạy tag `7527509-checkout` — **cùng chung digest** (khớp đúng bảng digest PR #95). Tức rollout #11 sinh ra chỉ vì đổi cú pháp tham chiếu image (thêm digest pin), không mang code mới nào — nhưng Argo Rollouts vẫn coi đây là 1 revision mới và bắt canary phải qua đủ vòng phân tích SLO.
- Vì lúc rollout #11 chạy không có traffic (load-gen giữa 2 lần test), canary có 0 request nên các metric traffic-dependent luôn fail theo đúng `successCondition`, dù ứng dụng không có lỗi gì — false negative, không phải regression thật.
- **Đã fix trực tiếp:** `kubectl argo rollouts retry rollout checkout-rollout -n techx-tf3` sau khi xác nhận load-generator đang có traffic thật chạy vào checkout. Tại thời điểm viết doc này, rollout đang Progressing lại bình thường (step 1/7, ActualWeight 33%, analysis chưa fail) — sẽ tự hoàn tất nếu traffic duy trì ổn định trong ~20-25 phút tới (2 bước analysis × 3 lần đo mỗi bước, cách nhau 2 phút, cộng 2 lần pause 5 phút).

**Rủi ro cấu trúc còn lại (chưa fix, cần đưa vào remediation):** bất kỳ thay đổi nào khiến `imageOverride` đổi (kể cả không đổi code, như đổi tag→digest) đều tự động kích hoạt 1 rollout mới, và rollout đó **chỉ pass được nếu đúng lúc có traffic thật chạy vào checkout**. Ngoài cửa sổ load test chính thức, service gần như luôn có ít traffic hoặc traffic lệch giữa canary/stable → cứ mỗi lần deploy checkout ngoài giờ load test là có rủi ro dính lại tình trạng Degraded giả này.

## 3. Kế hoạch remediation — theo đúng 5 blocker + các rủi ro nên xử lý của báo cáo gốc

### Blocker 1 — Đường đo checkout canary (đã xử lý xong phần root cause hạ tầng)

- [x] **Ngay lập tức:** retry rollout khi có traffic — đã làm 2 lần.
- [x] **Root cause thật sự tìm ra ở lần fail thứ 2:** không phải do thiếu traffic mà do Karpenter consolidation (`consolidateAfter: 2m`) evict pod checkout/otel-collector giữa lúc đang đo, gây latency spike giả (855ms) làm rollout fail oan. Đã sửa `gitops/karpenter/spot-nodepool.yaml`: `consolidateAfter: 2m → 1h` (PR #107). Rollout đã retry lại lần 3 sau khi merge — đang Progressing (xem log cuối doc này).
- [ ] **Cấu trúc, không blocking, nên làm sau Mandate 2:** sửa `checkout-slo` AnalysisTemplate để coi `checkout-request-rate` là *inconclusive* khi không có traffic, thay vì fail cứng — tránh tái diễn false-negative ngoài giờ load test/ngoài cửa sổ `consolidateAfter` đã nới.

### Blocker 2 — Locust autostart lệch runbook

- [ ] **Chưa làm — user sẽ tự xử lý qua UI Locust ngay trước giờ test** (stop + reset stats thủ công), không cần sửa code/values.
- [ ] Đối chiếu lại runbook `flash-sale-load-test.md` với giá trị thật (`LOCUST_AUTOSTART=true` hiện tại) để 2 nguồn hết lệch nhau — vẫn còn treo, nên làm trước ngày test để người trực không bị bất ngờ.

### Blocker 3 — Pod quota 42/90 — ✅ ĐÃ FIX

- [x] `gitops/infrastructure/resource-quota.yaml`: `pods: "90" → "100"` (PR #105). Verify live: `hard.pods: "100"`.

### Blocker 4 — Observability (Prometheus/OpenSearch/Kafka) gần chạm memory limit — ✅ ĐÃ FIX

- [x] `values-prod.yaml` (PR #105): OpenSearch limit 1100Mi → **1600Mi**, Prometheus limit 800Mi → **1200Mi**, Kafka limit 700Mi → **1Gi** (kèm request 650Mi). Verify: `helm template` render đúng, không lỗi schema.
- [ ] Còn thiếu: chạy 1 lần ramp thử nhỏ (vd 50 user) và theo dõi lại % dùng thật qua Grafana trước khi tin tưởng hoàn toàn — chưa làm.

### Blocker 5 — Backup/restore tối thiểu cho datastore — CHƯA LÀM

- [ ] Tối thiểu: chụp 1 bản snapshot thủ công (`pg_dump`/`valkey SAVE`/Kafka topic export) trước khi bắt đầu test 200 user — vẫn chưa ai làm, vì test tạo dữ liệu đơn hàng thật và cả 3 datastore đều singleton + reclaim policy `Delete`.
- [ ] Không bắt buộc dựng full VolumeSnapshot CRD/CronJob trước ngày test này nếu gấp — nhưng phải ghi rõ vào runbook đây là nợ kỹ thuật cần xử lý ngay sau Mandate 2.

### Các rủi ro nên xử lý hoặc chấp nhận rõ ràng (theo báo cáo gốc)

- [x] **`topologySpreadConstraints` cho `checkout`** — đã thêm (PR #107): hostname (soft/`ScheduleAnyway`) + zone (hard/`DoNotSchedule`). Verify: render đúng trong `helm template`.
- [x] **Tạm khóa Karpenter consolidation** — đã làm qua cách sửa `consolidateAfter` NodePool (không dùng annotation per-pod, xem mục 2 ở trên) — nhớ đổi lại `2m` sau khi test xong.
- [x] **Memory limit `payment`/`shipping`/`quote`** — đã tăng (PR #107): payment 180→**300Mi**, shipping 20→**64Mi**, quote 40→**80Mi**. (`currency` cũng đang tight — 20Mi limit tương tự shipping cũ — chưa ai đụng vào, để ý nếu OOM lúc test.)
- [ ] Thêm HPA cho `shipping`/`quote`/`payment` (hiện cố định 2 replica) — chưa làm, không blocking vì CPU đang dư nhiều, để backlog sau Mandate 2.
- [ ] **Chốt abort threshold cụ thể** (checkout success <99%, browse/cart <99.5%, p95 >1s, restart/OOM, datastore saturation) — viết vào runbook `flash-sale-load-test.md` — **chưa làm**.
- [ ] Ramp 10→50→100→200, reset Locust stats trước mốc 200 chính thức — việc vận hành lúc test, chưa cần làm trước.
- [ ] **Xác nhận flagd healthy**, không có fault đang bật ngoài kịch bản trước khi bắt đầu (đối chiếu OFREP hoặc `flagd-ui`) — **chưa làm**, tuyệt đối không tắt/bypass flagd để "test cho sạch".

## 4. Thứ tự thực hiện — cập nhật trạng thái

1. ~~Theo dõi checkout-rollout tự hoàn tất~~ — đã retry 2 lần, lần 2 lộ ra root cause thật (Karpenter, không phải thiếu traffic), đã sửa `consolidateAfter`, đang retry lần 3, chờ xác nhận Healthy.
2. ~~Tăng `ResourceQuota.pods`~~ — ✅ xong (90→100).
3. ~~Tăng memory limit Prometheus/OpenSearch/Kafka~~ — ✅ xong, chưa chạy ramp thử để xác nhận thực tế.
4. ~~Thêm `topologySpreadConstraints` cho checkout~~ — ✅ xong.
5. ~~Tăng memory limit payment/shipping/quote~~ — ✅ xong (không nằm trong plan ban đầu nhưng phát hiện thêm khi check kubectl theo yêu cầu).
6. **Còn lại, cần làm trước ngày test chính thức:**
   - Chạy thử ramp nhỏ (10→50 user) để xác nhận quota/observability/checkout-rollout đều ổn định với cấu hình mới — **chưa làm**.
   - Chốt abort threshold cụ thể, viết vào `flash-sale-load-test.md` — **chưa làm**.
   - Chuẩn bị backup thủ công 3 datastore (Postgres/Valkey/Kafka) ngay trước cửa sổ chính thức — **chưa làm**.
   - Xác nhận flagd healthy, không fault ngoài kịch bản — **chưa làm** (check ngay trước giờ chạy).
   - Dừng Locust autostart + reset stats — user tự làm qua UI ngay trước giờ chạy.

Đã đủ điều kiện nâng từ **NO-GO** lên **GO có điều kiện**: chờ xác nhận checkout-rollout Healthy + chạy xong 1 lần ramp thử nhỏ, cộng chốt xong abort threshold/backup/flagd check ở trên.

## 5. Log xác nhận rollout (để tham chiếu, không phải hướng dẫn)

- Lần fail #1 (11:1): do phân tích chạy đúng lúc không có traffic (`checkout-request-rate=0`) → retry sau khi loadgen có traffic.
- Lần fail #2 (11:4): traffic bình thường (0.7-3.0 req/s) nhưng `checkout-p95-regression-vs-stable-ms` fail vì 1/3 lần đo nhảy lên 855ms — trùng khớp thời điểm Karpenter `DisruptionTerminating: Underutilized` evict pod `checkout-rollout-5f6cdf58fc-fdrbc` (stable) + `otel-collector-agent`. → sửa `consolidateAfter: 2m → 1h`, retry lần 3.
- Lần retry #3: đang theo dõi tại thời điểm cập nhật doc này.

# Mandate 02 - HPA hardening follow-up cho payment/shipping/quote

**Ngày lập:** 2026-07-16  
**Phạm vi:** Đánh giá hậu Mandate 02 cho `payment`, `shipping`, `quote`  
**Liên quan:** `docs/../mandates/mandate-02/mandate-02-load-test-report.md`, `docs/../mandates/mandate-02/mandate-02-load-test-remediation-plan.md`, `docs/docx_cdo02/Task[121]_mandate2/`

## 1. Tóm tắt

Mandate 02 đã đạt mục tiêu 200 concurrent users / 15 phút mà **không cần HPA** cho `payment`, `shipping`, `quote`. Official run ghi nhận checkout success `99.9825%`, browse/cart `100%`, storefront p95 `46-48ms`, Locust `POST /api/checkout` 2399 request / 0 fail và `POST/GET /api/cart` 10700 request / 0 fail. HPA scale thật sự tập trung ở `frontend` và `product-reviews`; ba service trong phạm vi này vẫn giữ `replicas: 2`.

**Kết luận hiện tại:** chưa có HPA cho `payment`, `shipping`, `quote`, và theo evidence hiện có thì **đó là lựa chọn đúng ở thời điểm này**. Không nên thêm HPA ngay chỉ để "cho đủ" vì chưa có bằng chứng ba service này bão hòa CPU, tăng latency, OOM, restart, hoặc kéo SLO checkout xuống. Việc đúng hơn là giữ baseline 2 replicas và mở task đo riêng CPU/memory/throttling/latency dependency trong lần load/soak tiếp theo; chỉ thêm HPA nếu số liệu chứng minh có bottleneck thật.

## 2. Trạng thái hiện tại

### 2.1 HPA đang có

`gitops/infrastructure/hpa-hotpath.yaml` hiện khai báo 9 HPA:

| HPA | Target | Min | Max |
|---|---|---:|---:|
| `frontend-proxy-hpa` | `Deployment/frontend-proxy` | 2 | 8 |
| `frontend-hpa` | `Deployment/frontend` | 2 | 8 |
| `product-catalog-hpa` | `Deployment/product-catalog` | 2 | 8 |
| `cart-hpa` | `Deployment/cart` | 2 | 6 |
| `checkout-hpa` | `Rollout/checkout-rollout` | 2 | 8 |
| `currency-hpa` | `Deployment/currency` | 2 | 6 |
| `recommendation-hpa` | `Deployment/recommendation` | 1 | 4 |
| `product-reviews-hpa` | `Deployment/product-reviews` | 2 | 6 |
| `ad-hpa` | `Deployment/ad` | 1 | 4 |

Không có HPA cho `payment`, `shipping`, `quote`.

### 2.2 payment/shipping/quote đang được bảo vệ bằng baseline reliability

Trong `phase3 - information/deploy/values-prod.yaml`, cả 3 service đều có:

| Service | Replicas | CPU request | CPU limit | Memory request | Memory limit | Probe | Placement |
|---|---:|---:|---:|---:|---:|---|---|
| `payment` | 2 | 50m | 300m | 100Mi | 300Mi | TCP readiness/liveness | topology spread hostname + zone |
| `shipping` | 2 | 50m | 150m | 8Mi | 64Mi | TCP readiness/liveness | topology spread hostname + zone |
| `quote` | 2 | 50m | 150m | 24Mi | 80Mi | TCP readiness/liveness | topology spread hostname + zone |

`gitops/infrastructure/pdb-checkout.yaml` cũng có PDB `minAvailable: 1` cho cả `payment`, `shipping`, `quote`. Nghĩa là hiện tại chúng đã có baseline chống SPOF/drain: 2 replicas, PDB, graceful shutdown, probe và topology spread.

## 3. Vì sao chưa nên thêm HPA ngay

1. **Mandate 02 đã pass với 2 replicas.** Đây là bằng chứng mạnh nhất: nếu `payment`, `shipping`, hoặc `quote` là bottleneck ở mức 200 users thì checkout success, p95, OOM/restart hoặc Locust fail đã phản ánh.
2. **Chưa có evidence CPU saturation riêng.** Report hiện chứng minh SLO tổng thể pass và không có OOM/restart/Pending ảnh hưởng test, nhưng chưa có bảng CPU/memory/throttling riêng cho ba service này tại peak.
3. **CPU request hiện chỉ là 50m/pod.** Nếu copy target 65% từ các HPA hot-path, ngưỡng scale sẽ là khoảng `32.5m/pod`. Với service nhẹ, HPA có thể scale quá nhạy, tạo churn và tăng surface vận hành mà không cải thiện SLO.
4. **`shipping` và `quote` là dependency chain.** Thêm HPA cho `shipping` mà không đánh giá `quote` có thể chỉ đẩy bottleneck xuống downstream. Thêm HPA cho cả hai khi chưa có evidence thì lại làm câu chuyện cost optimization yếu đi.
5. **HPA không giải quyết mọi loại nghẽn.** Nếu rủi ro thật là memory limit, dependency latency, lỗi code ở `quote`, hoặc connection/downstream issue, thêm replica có thể không xử lý đúng nguyên nhân.

Vì vậy, quyết định hiện tại nên là: **không thêm HPA ngay; giữ 2 replicas; đo thêm trước khi thay đổi.**

## 4. Evidence từ Mandate 02

| Signal | Kết quả |
|---|---|
| Peak load | 200 users, cửa sổ chính khoảng 17 phút |
| Checkout | `99.9825%`, 2327 `PlaceOrder`, 0 `STATUS_CODE_ERROR` |
| Locust checkout | 2399 request, 0 fail |
| Browse/cart | `100.0000%`, Locust cart 10700 request, 0 fail |
| Storefront p95 | 46-48ms |
| HPA total | 16 -> 22 -> 16 |
| Scale-up nổi bật | `frontend` 2 -> 7, `product-reviews` 2 -> 3 |
| Node count/cost-hour | Không tăng |
| OOM/restart/Pending ảnh hưởng test | Không ghi nhận trong official run |

Ý nghĩa: nếu chỉ xét mục tiêu Mandate 02, `payment`, `shipping`, `quote` **không phải bottleneck đã được chứng minh**. Memory limit cũ quá mỏng đã được tăng trước test (`payment` 180Mi -> 300Mi, `shipping` 20Mi -> 64Mi, `quote` 40Mi -> 80Mi) và official run không còn phát sinh OOM/restart.

## 5. Khi nào nên thêm HPA

Chỉ nên mở implementation task thêm HPA nếu trong lần load test / soak test / production traffic có một trong các signal sau:

| Điều kiện | Threshold gợi ý | Hành động |
|---|---|---|
| CPU gần target liên tục | CPU trung bình >65% request trong 5 phút tại 2 replicas | Cân nhắc HPA |
| Latency dependency tăng | p95 span `PaymentService/Charge`, `ShippingService/GetQuote`, `ShippingService/ShipOrder`, hoặc `quote /getquote` tăng rõ và trùng với checkout p95/error | Trace root cause, rồi cân nhắc HPA |
| Memory gần trần | working set >75-80% limit trong peak | Tăng limit/request trước; HPA chưa chắc giải quyết |
| OOM/restart | bất kỳ OOM/restart nào trong peak | Fix resource/probe/root cause; HPA chỉ là bước sau |
| Checkout SLO bị ảnh hưởng | checkout success <99% hoặc p95 storefront >=1s, trace chỉ về payment/shipping/quote | Thêm HPA theo service gây nghẽn |

## 6. Đề xuất task hardening

### Option A - Khuyến nghị hiện tại: đo riêng và ghi evidence

Tạo một evidence pack nhỏ cho lần rerun/soak tiếp theo:

```bash
kubectl -n techx-tf3 top pod -l 'opentelemetry.io/name in (payment,shipping,quote)'
kubectl -n techx-tf3 get deploy payment shipping quote -o wide
kubectl -n techx-tf3 get hpa
kubectl -n techx-tf3 get events --sort-by=.lastTimestamp
```

PromQL nên thu:

```promql
sum by (pod) (
  rate(container_cpu_usage_seconds_total{
    namespace="techx-tf3",
    pod=~"(payment|shipping|quote)-.*",
    container!="",
    image!=""
  }[2m])
)
```

```promql
sum by (pod) (
  container_memory_working_set_bytes{
    namespace="techx-tf3",
    pod=~"(payment|shipping|quote)-.*",
    container!="",
    image!=""
  }
)
```

```promql
sum by (pod) (
  rate(container_cpu_cfs_throttled_periods_total{
    namespace="techx-tf3",
    pod=~"(payment|shipping|quote)-.*",
    container!="",
    image!=""
  }[2m])
)
```

Acceptance:

- Có bảng CPU/memory/throttling của `payment`, `shipping`, `quote` trong before/peak/after.
- Có kết luận service nào cần HPA hay không, dựa trên số liệu thay vì cảm tính.
- Nếu không service nào gần ngưỡng, ghi rõ "giữ 2 replicas" là quyết định cost-conscious.

### Option B - Chỉ implement HPA nếu evidence đạt ngưỡng

Nếu evidence cho thấy cần HPA, đề xuất cautious config:

| Service | Min | Max đề xuất ban đầu | Target | Ghi chú |
|---|---:|---:|---|---|
| `payment` | 2 | 4 | CPU 65% sau khi verify request | Đứng trên checkout charge path; ưu tiên cao nhất |
| `shipping` | 2 | 4 | CPU 65% sau khi verify request | Phụ thuộc `quote`; không scale lẻ nếu quote nghẽn |
| `quote` | 2 | 4 | CPU 65% sau khi verify request | Downstream của shipping; cần theo dõi p95 `/getquote` |

Trước khi merge HPA, cần quyết thêm:

- CPU request 50m có phù hợp làm mẫu số HPA không.
- Có cần tăng request lên 75m/100m để tránh HPA quá nhạy không.
- ArgoCD có ignore/runtime ownership nào liên quan replicas không.
- Test scale-up và scale-down riêng, đảm bảo pod về min sau peak.

Rollback:

- Xóa HPA mới và scale deployment về `replicas: 2`.
- Lưu ý: xóa HPA không tự động trả deployment về 2 replicas nếu HPA đang giữ giá trị cao hơn; phải scale explicit.


## 7. Kết luận

Trạng thái hiện tại của dự án nghiêng về **giữ 2 replicas + tiếp tục đo**, không phải **thêm HPA ngay**. Mandate 02 đã pass với cấu hình này, và các guardrail reliability quan trọng cho `payment`, `shipping`, `quote` đã có: replicas 2, PDB, probes, graceful shutdown, topology spread và memory limit đã tăng. Việc tiếp theo đáng giá nhất là bổ sung evidence riêng cho 3 service này trong lần load/soak tiếp theo, rồi mới quyết định HPA.

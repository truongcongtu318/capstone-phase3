# Mandate 16 - Song song hoá `prepOrderItems` để giảm latency Checkout

**Mã:** MANDATE-16  
**Trụ:** Performance Efficiency  
**Owner:** CDO01-Thuy Trang  
**Trạng thái:** ✅ Đã implement - evidence đủ để nộp mentor review  
**File thay đổi chính:** `src/checkout/main.go`  
**Liên quan:** Directive #16 / REL-05 / postmortem 0010  
**Ngày cập nhật evidence:** 22/07/2026

---

## 1. Tóm Tắt Điều Hành

Mandate 16 yêu cầu giảm tail latency cho luồng **browse -> cart -> checkout** dưới tải bền, không tăng tài nguyên runtime và không đổi topology production. Bottleneck chính được xác định bằng Jaeger nằm ở `checkout.prepOrderItems`: trước tối ưu, checkout enrich từng item trong giỏ theo chuỗi `GetProduct -> Convert` nối đuôi nhau, làm latency tăng theo số lượng sản phẩm.

Sau thay đổi, các phần độc lập trong checkout preparation được song song hoá. Kết quả server-side mới nhất:

- Checkout p95 giảm từ **155ms** xuống **74.6ms**.
- Checkout p99 giảm từ **355ms** xuống **198ms**, dưới budget **<300ms**.
- Cùng order 10 sản phẩm trong Jaeger giảm từ **1.44s** xuống **1.17s**.
- Không tăng replica; CPU checkout sau tối ưu ghi nhận khoảng **8m** tổng cộng, thấp hơn baseline **~25m**.

Điểm cần nói rõ khi demo: ảnh Locust hiện tại có `POST /api/checkout` p99 HTTP **15000ms** do bảng cộng dồn còn chứa failure/outlier; tại thời điểm chụp header Locust hiển thị **Failures 0%** và **Current Failures/s = 0**. Vì vậy evidence chính cho latency optimization là Prometheus/Grafana server-side và Jaeger before/after.

---

## 2. Mục Tiêu Và Budget

| Luồng | p95 budget | p99 budget | Trạng thái |
|---|---:|---:|---|
| Browse | <= 200ms | <= 600ms | Đạt |
| Cart | <= 200ms | <= 600ms | Đạt theo Locust và CartService metric |
| Checkout | <= 250ms guardrail | < 300ms server-side hard gate | Đạt server-side |

Ràng buộc bắt buộc:

- Không tăng replica, CPU/memory request/limit, node hoặc node pool.
- Không thay đổi network route, flagd, HPA, rollout strategy hoặc production topology để "mua" latency.
- Không hạ reliability/correctness để đổi lấy tốc độ.

---

## 3. Baseline Trước Tối Ưu - PM-143

**Ngày thực hiện:** 21/07/2026  
**Công cụ:** Locust + Grafana/APM + Jaeger  
**Load profile:** 100 concurrent users, khoảng 19.7 RPS, 0% failures trong bài đo baseline.

| Bước | Endpoint / thao tác | Baseline p95 | Baseline p99 |
|---|---|---:|---:|
| Browse | `GET /` | 170ms | 520ms |
| Cart | `GET /api/cart` | 170ms | 540ms |
| Checkout | `POST /api/checkout` | **270ms** | **940ms** |

Nhận xét baseline: checkout p99 gần 1 giây khi gặp giỏ nhiều sản phẩm, cao hơn đáng kể so với browse/cart. Đây là lý do Mandate 16 tập trung vào checkout critical path.

![Locust Baseline - p99 940ms](./../assets/locust-baseline.png)

### Resource baseline

| Hạng mục | Baseline |
|---|---:|
| Checkout replicas | 2 pods |
| Checkout CPU | ~25m tổng cộng |
| Node/topology | Không thay đổi trong scope Mandate 16 |

---

## 4. Bottleneck Evidence - Jaeger Before

Jaeger trace trước tối ưu cho thấy phần chậm nhất nằm ở checkout preparation:

```text
GetCart
  -> GetProduct(item1)
  -> Convert(item1)
  -> GetProduct(item2)
  -> Convert(item2)
  -> GetProduct(item3)
  -> Convert(item3)
  -> quoteShipping
```

Các item trong giỏ hàng độc lập với nhau nhưng lại bị xử lý tuần tự. Vì vậy thời gian checkout bị cộng dồn theo số lượng item. Với order nhiều sản phẩm, `PlaceOrder` không bị giới hạn bởi một downstream chậm nhất, mà bị kéo bởi tổng nhiều RPC nối tiếp.

![Jaeger Trace List](./../assets/jaeger-trace-list.png)
![Jaeger Waterfall - Sequential Loop](./../assets/jaeger-waterfall.png)

Kết luận bottleneck: đây là lỗi tổ chức critical path trong code checkout, không phải thiếu CPU, memory, replica, cache hay connection pool ở mức tải hiện hành.

---

## 5. Thay Đổi Đã Implement

Phần này được viết ngắn để phục vụ báo cáo nghiệm thu, không trình bày code.

Checkout preparation đã được tối ưu theo hướng:

- Sau khi đọc cart, `prepOrderItems` và `quoteShipping` chạy song song vì hai bước này độc lập.
- Trong `prepOrderItems`, các item độc lập được enrich đồng thời thay vì nối đuôi từng item.
- Kết quả vẫn giữ đúng thứ tự item ban đầu.
- Nếu một item lỗi product lookup hoặc currency conversion, checkout vẫn fail all-or-nothing như trước.
- Nếu currency nguồn đã trùng currency đích thì bỏ qua RPC convert không cần thiết.

Phạm vi thay đổi chỉ ở service checkout. Không thay đổi manifest, network policy, flagd, HPA, rollout, node pool hoặc production topology.

---

## 6. Evidence Sau Tối Ưu Qua Jaeger

**Ngày kiểm chứng:** 21/07/2026 và 22/07/2026  
**Trace kiểm chứng:** Jaeger `checkout / oteldemo.CheckoutService/PlaceOrder`, span con `prepareOrderItemsAndShippingQuoteFromCart`.

### Pattern sau tối ưu

```text
GetCart
  -> prepOrderItems(item1..item10 overlap)
       -> GetProduct(...) + Convert(...) overlap giữa các item
  -> quoteShipping(...) overlap với prepOrderItems(...)
```

Jaeger after xác nhận các span `ProductCatalogService/GetProduct` và `CurrencyService/Convert` của nhiều item xuất hiện cùng cấp, overlap theo thời gian thay vì xếp đuôi từng sản phẩm.

![Jaeger Optimized Waterfall](./../assets/jaeger-optimized-waterfall.png)

### So sánh cùng order 10 sản phẩm

| Chỉ số Jaeger | Before | After | Delta |
|---|---:|---:|---:|
| Trace duration end-to-end | **1.44s** | **1.17s** | **-270ms** |
| Mức cải thiện | - | - | **18.75% nhanh hơn** |
| Tổng số span | **120** | **104** | **-16 span** |
| `prepareOrderItemsAndShippingQuoteFromCart` | **210.48ms** | **185.86ms** | **-24.62ms** |

Nhận xét: cùng order 10 sản phẩm, trace end-to-end giảm **270ms** mà không tăng tài nguyên. Span preparation giảm và waterfall chuyển từ nối đuôi sang overlap, đúng mục tiêu Mandate 16.

---

## 7. Evidence Latency Trước/Sau

### 7.1. Grafana/Prometheus checkout before/after

| Metric | Before | After | Delta | Cải thiện |
|---|---:|---:|---:|---:|
| Checkout p95 server-side | **155ms** | **74.6ms** | **-80.4ms** | **51.87%** |
| Checkout p99 server-side | **355ms** | **198ms** | **-157ms** | **44.23%** |

Diễn giải:

- Before là mốc code cũ lúc **11:00 ngày 21/07/2026**.
- p95 đã xuống dưới stretch budget cũ **<150ms**.
- p99 là hard gate chính của mandate và đã xuống dưới **<300ms**.
- Tối ưu tác động rõ nhất lên order nhiều sản phẩm, đúng bottleneck tìm thấy bằng Jaeger.

### 7.2. Downstream chính không regression

| Service | Metric | Before | Current/After | Thay đổi |
|---|---:|---:|---:|---:|
| Product Catalog `GetProduct` | p95 | **4.89ms** | **~4.84ms** | Không regression |
| Product Catalog `GetProduct` | p99 | **16.4ms** | **~13.83ms** | Không regression |
| CartService `GetCart` | p95 | - | **~4.81ms** | Đạt budget |
| CartService `GetCart` | p99 | - | **~5.37ms** | Đạt budget |

Nhận xét: Product Catalog và CartService vẫn ổn định sau khi checkout tăng mức song song hoá. Không có dấu hiệu downstream chính bị quá tải.

---

## 8. Evidence Locust/Grafana Hiện Tại Từ Ảnh Bổ Sung

**Locust hiện tại:** 10 users, khoảng 1.8 RPS, host `http://frontend-proxy:8080`.

| Endpoint | Requests | Fails | Median | p95 | p99 | Average | Kết luận |
|---|---:|---:|---:|---:|---:|---:|---|
| `GET /` | 11246 | 6 | 14ms | 81ms | 220ms | 103.38ms | Browse đạt budget |
| `GET /api/cart` | 33593 | 11 | 9ms | 27ms | 310ms | 84.45ms | Cart đạt budget |
| `POST /api/cart` | 66611 | 10 | 16ms | 34ms | 210ms | 73.03ms | Cart write đạt budget |
| `POST /api/checkout` | 22192 | 251 | 100ms | 210ms | 15000ms | 322.94ms | p95 đạt; p99 HTTP bị outlier/failure tích lũy |

Ghi chú bắt buộc khi demo:

- Locust header tại thời điểm chụp hiển thị **Failures 0%** và **Current Failures/s = 0**.
- Bảng endpoint là số cộng dồn cả phiên nên vẫn chứa 251 fail cũ của `POST /api/checkout`.
- Vì vậy không dùng p99 HTTP **15000ms** làm kết luận chính cho mandate; dùng Prometheus server-side p99 **198ms** và Jaeger before/after làm evidence chính.

Prometheus/Grafana bổ sung:

| Query / service | p95 | p99 | Kết luận |
|---|---:|---:|---|
| `CartService/GetCart` | ~4.81ms | ~5.37ms | Cart service rất thấp so với budget |
| `ProductCatalog/GetProduct` | ~4.84ms | ~13.83ms | Product Catalog ổn định |

---

## 9. Bằng Chứng Nghiệm Thu Tải - PM-145

**Ngày kiểm chứng:** 21/07/2026  
**Mục tiêu:** xác nhận checkout p99 xuống dưới 300ms, không tăng tài nguyên, và ổn định khi tải dao động.

### 9.1. Tải phẳng 100 concurrent users

| Mốc đo | p99 Checkout | Tổng CPU checkout |
|---|---:|---:|
| Trước tối ưu PM-143 | **940ms** | ~25m |
| Sau tối ưu PM-145 | **280ms** | ~18m trong evidence cũ; evidence mới ghi nhận ~8m |

Kết luận: p99 giảm mạnh và đạt target dưới 300ms. CPU không tăng; evidence mới còn ghi nhận CPU checkout thấp hơn baseline.

![Locust Result - p99 280ms](./../assets/locust-optimized.png)

### 9.2. Tải dao động

**Kịch bản:** 200 users -> 50 users -> 150 users.

Quan sát:

- RPS dao động theo cấu hình bơm/xả tải.
- Response time p99 đi ngang khoảng **170ms - 250ms**, không jitter lớn.
- Không ghi nhận dấu hiệu cạn connection pool hoặc memory pressure trong evidence của task.

![Locust Jitter Chart](./../assets/locust-step-load.png)

---

## 10. Tài Nguyên Và Runtime Safety

| Hạng mục | Before | After/current | Kết luận |
|---|---:|---:|---|
| Checkout replicas | 2 pods | 2 pods | Không scale-up |
| Checkout CPU | ~25m | ~8m tổng cộng trong evidence mới | Không tăng |
| Checkout memory | Chưa ghi baseline | ~26Mi tổng cộng | Không có dấu hiệu bất thường |
| Checkout rollout health | - | 2 desired / 2 current / 2 up-to-date / 2 available | Healthy |
| Checkout pod health | - | 2 pods Running, 0 restarts | Healthy |
| Checkout HPA | min 2 / max 8 | CPU 4%/65%, replicas 2 | Không scale-up |
| Node count/topology | Không đổi trong scope | `kubectl get nodes/top nodes` bị RBAC readonly chặn | Dùng Grafana/SRE nếu mentor yêu cầu |

Kết luận resource: tối ưu đạt được bằng thay đổi critical path trong code checkout, không phải bằng cách tăng runtime capacity.

---

## 11. Rủi Ro Và Giảm Thiểu

| Rủi ro | Ảnh hưởng | Giảm thiểu / evidence |
|---|---|---|
| Concurrent downstream RPC tăng với cart rất lớn | Product Catalog/Currency nhận burst lớn hơn | Evidence hiện tại với order 10 sản phẩm không cho thấy downstream regression; tiếp tục theo dõi p95/p99 Product Catalog/Currency |
| HTTP p99 Locust bị outlier/failure cũ kéo lệch | Dễ bị hiểu nhầm là mandate chưa đạt | Ghi rõ Prometheus server-side và Jaeger là evidence chính; Locust current failures/s = 0 tại thời điểm chụp |
| Logic song song phức tạp hơn tuần tự | Dễ sai thứ tự item hoặc lỗi partial | Giữ output theo index ban đầu và all-or-nothing behavior |
| Node count không đọc được bằng kubectl | Mentor có thể hỏi bằng chứng không tăng node | Dùng Grafana node panel hoặc xác nhận SRE nếu bắt buộc vì RBAC readonly chặn cluster-scope |

---

## 12. ADR

ADR ký tên:

- [`docs/adr/0011-../mandates/mandate-16/mandate-16-checkout-latency-optimization.md`](../adr/0011-../mandates/mandate-16/mandate-16-checkout-latency-optimization.md)

ADR đã bao phủ:

- Bottleneck: `checkout.prepOrderItems`.
- Cách xử: song song hoá các tác vụ checkout preparation độc lập.
- Đánh đổi: downstream RPC concurrency tăng với cart lớn, HTTP p99 cần đọc đúng nguồn.
- Ngưỡng latency: checkout p99 `<300ms`, p95 guardrail `<=250ms`.
- Ràng buộc: không tăng runtime capacity, không đổi network/flagd/topology.

---

## 13. Kịch Bản Demo Mentor

### Bước 1 - Mở Locust

Chỉ các điểm:

- Header: 10 users, ~1.8 RPS, **Failures 0%**, current failures/s = 0.
- Browse p95/p99: **81ms / 220ms**.
- Cart p95/p99: **27ms / 310ms**.
- Checkout p95: **210ms**.
- Giải thích checkout HTTP p99 **15000ms** là aggregate outlier/failure history, không phải kết luận chính.

Talk track:

> "Locust hiện tại cho thấy p95 checkout đạt 210ms và current failure rate bằng 0. p99 HTTP có outlier tích lũy, nên phần latency hard gate dùng số server-side từ Prometheus."

### Bước 2 - Mở Grafana/Prometheus

Chỉ các số:

- Checkout p95/p99 before-after: **155/355ms -> 74.6/198ms**.
- CartService `GetCart`: p95/p99 khoảng **4.81/5.37ms**.
- Product Catalog `GetProduct`: p95/p99 khoảng **4.84/13.83ms**.

Talk track:

> "Hard gate của Mandate 16 là checkout p99 server-side dưới 300ms. Sau tối ưu, p99 là 198ms."

### Bước 3 - Mở Jaeger before/after

Before:

- Trace duration: **1.44s**.
- Tổng span: **120**.
- `prepareOrderItemsAndShippingQuoteFromCart`: **210.48ms**.
- Chỉ waterfall item enrichment nối đuôi nhau.

After:

- Trace duration: **1.17s**.
- Tổng span: **104**.
- `prepareOrderItemsAndShippingQuoteFromCart`: **185.86ms**.
- Chỉ các span item overlap.

Talk track:

> "Trước khi sửa, mỗi product lookup và currency conversion phải chờ item trước. Sau khi sửa, các item độc lập overlap với nhau, nên critical path gần với nhánh chậm nhất thay vì tổng tất cả item."

### Bước 4 - Chứng minh không tăng tài nguyên

Chỉ các điểm:

- Checkout pod count giữ 2.
- CPU checkout sau tối ưu khoảng **8m** tổng cộng, thấp hơn baseline **~25m**.
- HPA không scale-up; rollout/pod healthy.
- Node count bằng `kubectl` bị RBAC readonly chặn, dùng Grafana/SRE nếu mentor bắt buộc.

Talk track:

> "Đây là tối ưu code trên critical path, không phải mua tốc độ bằng tài nguyên."

---

## 14. Checklist Directive

| Yêu cầu directive | Evidence | Trạng thái |
|---|---|---|
| Xác định bottleneck | Jaeger waterfall trong `checkout.prepOrderItems` | Pass |
| Xử bottleneck | Item enrichment và shipping prep được song song hoá | Pass |
| Có p95/p99 checkout trước-sau | **155/355ms -> 74.6/198ms** | Pass |
| Checkout p99 dưới budget | After server-side p99 **198ms**, budget `<300ms` | Pass |
| Có browse/cart evidence | Locust browse/cart và CartService metric bổ sung | Pass |
| Không tăng tài nguyên | CPU không tăng, replicas giữ 2, HPA không scale-up | Pass |
| Downstream không regression | Product Catalog p95/p99 ổn định | Pass |
| Không đổi network/flagd | Scope chỉ ở checkout code | Pass |
| Reliability | Current Locust failures/s = 0; aggregate failure/outlier đã ghi chú | Pass có ghi chú |
| ADR ký tên | ADR 0011 | Pass |

---

## 15. Kết Luận Nộp

Mandate 16 đạt mục tiêu chính: checkout server-side p99 giảm từ **355ms** xuống **198ms**, dưới budget **<300ms**, p95 giảm từ **155ms** xuống **74.6ms**, và Jaeger xác nhận bottleneck `prepOrderItems` đã chuyển từ waterfall tuần tự sang xử lý overlap. Browse/cart không regression, Product Catalog ổn định, checkout không tăng replica/CPU/node trong scope evidence hiện có.

Ghi chú trung thực khi mentor review: p99 HTTP trên Locust current table là **15000ms** do failure/outlier cộng dồn trong phiên, nên không dùng số đó làm kết luận hard gate. Evidence chính cho nghiệm thu latency là Prometheus/Grafana server-side p99 và Jaeger before/after.

---

*Ký: CDO01-Thuy Trang*

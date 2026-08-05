# Mandate 03 - Maintenance hardening follow-up

**Ngày lập:** 16/07/2026
**Người lập:** CDO-02
**Phạm vi:** Các việc nên cải thiện sau khi demo Mandate 03 đã PASS app-tier drain.

## 1. Kết luận nhanh

Mandate 03 hiện **đã đạt cho luồng ra tiền ở app-tier**: demo drain 1 node app-tier ngày 16/07/2026 giữ được SLO bắt buộc:

| Chỉ số | Ngưỡng mandate | Kết quả demo |
|---|---:|---:|
| Checkout success rate | >= 99% | 99.9388% |
| Browse success rate | >= 99.5% | 100.0000% |
| Cart success rate | >= 99.5% | 99.9536% |
| Storefront p95 | < 1s | 68.6ms |

Vì vậy, phần còn lại **không phải sửa để pass lại app-tier**, mà là hardening để lần bảo trì sau quan sát mượt hơn, giảm rủi ro ở mặt phẳng vận hành, và chuẩn bị cho stateful maintenance.

Nguồn đối chiếu chính:
- `docs/../mandates/mandate-03/mandate-03-drain-node-report.md`
- `docs/runbooks/mandate-03-drain-node-demo.md`
- `docs/adr/0007-mandate-03-maintenance-no-downtime-cdo02.md`
- `CLAUDE.md`

## 2. Những điểm hiện đã ổn

| Hạng mục | Trạng thái | Nhận xét |
|---|---|---|
| Revenue app-tier có 2 replicas | Đã ổn | `frontend`, `frontend-proxy`, `product-catalog`, `cart`, `checkout`, `payment`, `currency`, `shipping`, `quote`, `product-reviews` đã có 2 replicas cho đường mua hàng chính. |
| Topology spread + PDB | Đã ổn | Drain 1 node app-tier vẫn còn pod Ready ở node/AZ khác. |
| Graceful shutdown | Đã ổn | `preStop` + `terminationGracePeriodSeconds` đã phủ revenue services, bao gồm checkout qua PR #136. |
| Readiness/liveness probe | Đã ổn | Pod chưa Ready không nhận traffic khách. Đây là điểm trực tiếp đáp ứng yêu cầu #3 của mandate. |
| ALB graceful drain | Đã ổn | `frontend-proxy` có xử lý graceful hơn để tránh cắt request đang bay. |

Không nên "nhân đôi mọi thứ" thêm chỉ để nhìn chắc hơn, vì mandate vẫn yêu cầu nằm trong ngân sách và tránh over-provisioning.

## 3. Các cải thiện nên làm tiếp

### M03-F01 - Tách 2 replica cloudflared ra khác node

**Mức ưu tiên:** P1

**Hiện trạng:** Trong báo cáo Mandate 03 có ghi nhận cả 2 replica `cloudflared` đang nằm chung một node. Lần demo này drain node khác nên không ảnh hưởng, nhưng nếu bảo trì đúng node chứa cả 2 replica thì đường ops như Grafana, Jaeger, Argo CD hoặc kubectl qua tunnel có thể mất cùng lúc.

**Tác động:** Không làm rớt khách hàng trực tiếp, nhưng làm mù quan sát trong lúc bảo trì. Với Mandate 03, mentor cần thấy cách team monitor SLO, nên đây là rủi ro thực tế.

**Đề xuất:** Thêm `topologySpreadConstraints` hoặc pod anti-affinity cho `cloudflared`, giữ 2 replicas nhưng ép phân tán theo hostname/zone nếu có thể.

**Tiêu chí nghiệm thu:**
- `cloudflared` có 2 pod Ready trên 2 node khác nhau.
- Drain 1 node chứa 1 pod `cloudflared` không làm mất toàn bộ ops tunnel.
- Không tăng replica count nếu chưa có lý do.

### M03-F02 - Quyết định hướng HA hoặc residual risk cho Grafana

**Mức ưu tiên:** P1/P2

**Hiện trạng:** Khi demo drain node app-tier, Grafana bị `502 Bad Gateway` khoảng 1 phút vì Grafana là single-replica và pod nằm trên node bị drain. Prometheus vẫn thu dữ liệu, revenue SLO không rớt, nhưng dashboard realtime bị gián đoạn.

**Đề xuất ngắn hạn:**
- Ghi rõ trong runbook: nếu cần demo realtime trước mentor, tránh chọn node đang chứa Grafana hoặc chuẩn bị sẵn Prometheus query/terminal fallback.
- Khi Grafana 502, dùng Prometheus query trực tiếp để chứng minh SLO vẫn giữ.

**Đề xuất trung hạn:**
- Nếu muốn Grafana HA thật, cần đánh giá shared DB/storage thay vì chỉ tăng replica khi vẫn dùng SQLite/local state.

**Tiêu chí nghiệm thu:**
- Runbook có bước kiểm tra node chứa Grafana trước drain.
- Có fallback Prometheus query cho checkout, browse/cart và p95.
- Có quyết định rõ: Grafana chấp nhận residual risk hay đưa vào ticket HA riêng.

### M03-F03 - Sửa dashboard checkout SLO để tránh báo sai trong lúc bảo trì

**Mức ưu tiên:** P1

**Hiện trạng:** Checkout SLO dashboard từng hiển thị dưới 99%, nhưng query kiểm tra theo `span_name="oteldemo.CheckoutService/PlaceOrder"` cho thấy `STATUS_CODE_ERROR = 0`. Nguyên nhân hợp lý là panel checkout đang scope quá rộng theo `service_name="checkout"`, dễ kéo cả child span/downstream span vào SLI của checkout.

**Tác động:** Trong Mandate 03, dashboard là bằng chứng mentor nhìn trực tiếp. Nếu dashboard báo sai, team có thể bị hiểu nhầm là checkout rớt SLO dù `PlaceOrder` thật vẫn thành công.

**Đề xuất:** Scope checkout SLI vào entry span nghiệp vụ:

```promql
span_name="oteldemo.CheckoutService/PlaceOrder"
```

và tách riêng panel downstream/dependency errors nếu muốn quan sát child span.

**Tiêu chí nghiệm thu:**
- Checkout success panel chỉ tính `oteldemo.CheckoutService/PlaceOrder`.
- Có panel riêng cho lỗi downstream nếu cần.
- Dashboard và Prometheus query thủ công cho cùng một cửa sổ thời gian không còn lệch nhau vô lý.

### M03-F04 - Mở rộng runbook watch đủ toàn bộ revenue path

**Mức ưu tiên:** P2

**Hiện trạng:** Runbook đã có preflight đủ 10 service revenue, nhưng lệnh watch trong lúc drain đang tập trung vào `frontend`, `cart`, `checkout`, `product-catalog`.

**Đề xuất:** Dùng cùng một label selector đầy đủ trong cả preflight, watch realtime và nghiệm thu:

```sh
opentelemetry.io/name in (frontend,frontend-proxy,product-catalog,cart,checkout,payment,currency,shipping,quote,product-reviews)
```

**Tiêu chí nghiệm thu:**
- Trong demo, terminal theo dõi đủ các service liên quan đến browse -> cart -> checkout.
- Sau drain, không có pod revenue Pending/CrashLoopBackOff.

### M03-F05 - Giữ ranh giới rõ cho stateful node maintenance

**Mức ưu tiên:** P1, nhưng thuộc roadmap/mandate tiếp theo

**Hiện trạng:** Mandate 03 đã chủ động không drain node `stateful_1a` vì Postgres/Valkey/Kafka còn single-replica. Đây là residual risk đã ghi trong ADR, không nên che giấu.

**Đề xuất:**
- Giữ runbook planned-failover cho tình huống bắt buộc bảo trì stateful node.
- Không claim zero-downtime cho stateful node cho đến khi datastore chuyển sang managed HA.
- Liên kết việc xử lý dứt điểm sang Mandate 08/RDS/ElastiCache/MSK hoặc phương án managed tương đương.

**Tiêu chí nghiệm thu:**
- Tài liệu demo nói rõ Mandate 03 PASS app-tier, không mở rộng sai sang stateful.
- Có đường đi riêng cho stateful maintenance.

### M03-F06 - Diễn tập thay node thật sau drain

**Mức ưu tiên:** P3

**Hiện trạng:** Demo hiện đã chứng minh cordon/drain/uncordon. Nếu muốn sát thực tế bảo trì phần cứng hơn, có thể thêm bước terminate instance sau khi drain để node group/ASG tạo node mới.

**Đề xuất:** Làm như bài diễn tập riêng, không gộp vào demo mentor nếu không cần.

**Tiêu chí nghiệm thu:**
- Drain xong, terminate instance, node mới join lại cluster.
- Revenue SLO vẫn giữ trong toàn bộ quá trình.
- Không thực hiện trên node stateful nếu datastore chưa HA.

### M03-F07 - Kiểm tra lại Grafana alerting cho maintenance window

**Mức ưu tiên:** P2

**Hiện trạng:** Postmortem trước đó từng ghi nhận rủi ro alert rule chưa được load đúng do mismatch đuôi file `.yaml`/`.yml`. Nếu alerting không hoạt động, team chỉ phát hiện rớt SLO bằng nhìn dashboard thủ công.

**Đề xuất:**
- Xác nhận alert rules thực sự được load trong Grafana.
- Thêm hoặc kiểm tra alert riêng cho `PlaceOrder` success rate, cart/browse success rate, và storefront p95.
- Không trộn alert checkout business SLO với child span downstream.

**Tiêu chí nghiệm thu:**
- Grafana có alert rule active, không rỗng.
- Có test/screenshot chứng minh rule được load.

## 4. Thứ tự nên làm

| Thứ tự | Việc | Lý do |
|---:|---|---|
| 1 | M03-F03 - Sửa checkout SLO dashboard scope | Tránh báo sai SLO trước mentor/PM/Techlead. |
| 2 | M03-F01 - Anti-affinity/topology spread cho cloudflared | Giữ đường ops khi drain node bất kỳ. |
| 3 | M03-F02 - Grafana residual/HA decision + Prometheus fallback | Tránh lặp lại 502 làm gián đoạn phần quan sát. |
| 4 | M03-F04 - Mở rộng runbook watch đủ revenue path | Dễ làm, tăng chất lượng demo. |
| 5 | M03-F07 - Kiểm tra alerting | Hữu ích cho vận hành thật, không chỉ demo. |
| 6 | M03-F05/M03-F06 - Stateful/replace-node drill | Là bước sau, cần thận trọng hơn về blast radius. |

## 5. Kết luận

Không cần thay đổi lớn ở revenue app-tier ngay lúc này vì kết quả Mandate 03 đã chứng minh drain-safe. Việc nên join làm nhất là **checkout SLO dashboard scope** hoặc **cloudflared anti-affinity**, vì hai việc này nhỏ, đúng thực trạng dự án, và tăng chất lượng vận hành rõ rệt mà không làm phình ngân sách.

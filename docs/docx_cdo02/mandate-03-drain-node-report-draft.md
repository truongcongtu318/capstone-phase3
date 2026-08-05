# [Nháp] Mandate #3 — Báo cáo demo bảo trì không downtime (drain node app-tier, giữ SLO)

**Ngày chạy demo:** [Dự kiến: DD/MM/YYYY]
**Người thực hiện:** [Nguyễn Thị Mến]
**Người xác nhận/chứng kiến (mentor, nếu có):** [Tên mentor, nếu có]
**Video demo:** [Sẽ chèn link sau khi quay]

> File này là bản nháp chuẩn bị báo cáo nộp cho Mandate #3 ("bảo trì không downtime"). Cơ sở kỹ thuật đầy đủ:
> [`docs/adr/0007-mandate-03-maintenance-no-downtime-cdo02.md`](adr/0007-mandate-03-maintenance-no-downtime-cdo02.md).
> Quy trình thao tác: [`docs/runbooks/mandate-03-drain-node-demo.md`](runbooks/mandate-03-drain-node-demo.md).

---

## 1. Mục tiêu & phạm vi

**Chứng minh:** drain (rút) **1 node app-tier** giữa giờ vận hành — mô phỏng bảo trì/thay phần cứng —
mà luồng doanh thu **browse → cart → checkout** vẫn **giữ SLO**, **không downtime** với khách hàng.

**Phạm vi (có ý thức):** chỉ drain **node APP tier**, KHÔNG drain node stateful. HA cho datastore là residual risk đã ghi rõ trong ADR 0007 (đường đi thật = RDS/ElastiCache, ngoài ngân sách hiện tại). Demo này không giả vờ zero-downtime cho datastore single-replica.

**Ngưỡng SLO bắt buộc:** Checkout success ≥ 99% · Browse/Cart success ≥ 99.5% · Storefront p95 < 1000ms.

## 2. Cơ sở kỹ thuật (đã build trước demo)

Node drain "không downtime" đứng được là nhờ 4 cơ chế, đều đã merge + deployed qua GitOps:

| Cơ chế | Tác dụng | Bằng chứng |
|---|---|---|
| **topologySpread + `maxUnavailable: 0`** cho revenue path | Ép mỗi service revenue có replica ở **2 AZ/node khác nhau** → drain 1 node vẫn còn bản phục vụ | PR #112 |
| **Graceful shutdown** (`preStop sleep 5s` + `terminationGracePeriodSeconds: 30`) | Pod đang tắt xử lý nốt request dở, không cắt ngang | PR #114 (service thường) + **PR #136 (checkout)** |
| **PodDisruptionBudget** | Chặn evict quá số cho phép trong lúc drain | REL-01 (PR #39) |
| **ALB graceful draining** (deregistration delay) cho `frontend-proxy` | ALB rút kết nối êm, không rơi request đang bay | PR #116 |

Bổ trợ: **quy trình planned-failover datastore** (PR #117 + runbook `stateful-node-planned-maintenance.md`) cho trường hợp buộc phải bảo trì node stateful.

## 3. Chuẩn bị & pre-flight (Cần làm trước khi quay)

- [ ] **Verify PR #136 đã rollout xuống pod checkout thật**:
  - ArgoCD app `techx-corp` Synced tới `main` HEAD.
  - Deployment `checkout` (workloadRef target) có `terminationGracePeriodSeconds=30` + `preStop={"sleep":{"seconds":5}}`.
  - Cả 2 pod checkout mang `preStop`, nằm trên **2 node khác nhau**.
- [ ] **Pre-flight theo runbook (Bước 1):**
  - Mỗi service revenue (gồm `checkout`) có 2 replica ở ≥2 node/AZ khác nhau (topologySpread).
  - PDB không có cái nào `ALLOWED DISRUPTIONS = 0`.
  - Node định drain KHÔNG có nhãn `techx.io/workload=stateful`.
- [ ] **Chọn node drain hợp lý:** [Ghi lại tên Node app-tier được chọn, ví dụ node chứa nhiều pod revenue nhưng an toàn]
- [ ] Grafana **SLO dashboard** mở sẵn để chụp baseline/so sánh.

## 4. Quy trình demo dự kiến

```sh
export AWS_PROFILE=techx-new
NODE=[Điền tên node sẽ drain]

# (Terminal B) theo dõi realtime pod nhảy node
kubectl -n techx-tf3 get pods -o wide \
  -l 'opentelemetry.io/name in (frontend,cart,checkout,payment,product-catalog)' -w

# (Terminal A) thao tác chính
kubectl cordon "$NODE"                       # chặn schedule pod mới xuống node
kubectl drain "$NODE" --ignore-daemonsets \
  --delete-emptydir-data --grace-period=30 --timeout=180s   # đuổi pod (tôn trọng PDB + preStop)

# nghiệm thu
kubectl -n techx-tf3 get pods -o wide \
  -l 'opentelemetry.io/name in (frontend,frontend-proxy,product-catalog,cart,checkout,payment,currency,shipping,quote,product-reviews)' \
  | grep -Ev "Running" || echo "OK: tat ca pod revenue Running"

# khôi phục
kubectl uncordon "$NODE"
```

## 5. Kết quả SLO (Dự kiến thu thập trong lúc drain)

Đo trực tiếp qua Prometheus (spanmetrics) trong đúng cửa sổ drain.

| SLO | Ngưỡng | Kết quả thực tế đo được | Đạt? |
|---|---|---|---|
| Checkout success rate | ≥ 99% | [Điền sau demo] | [?] |
| Browse/Cart success rate | ≥ 99.5% | [Điền sau demo] | [?] |
| Storefront p95 latency | < 1000ms | [Điền sau demo] | [?] |

**Bằng chứng cần thu thập:**
- [ ] Video ghi hình toàn bộ màn hình terminal (câu lệnh drain) và dashboard Grafana (biểu đồ SLO).
- [ ] Lệnh kiểm tra pod trên terminal báo cáo không có service luồng revenue nào bị Pending vô thời hạn.
- [ ] Ảnh chụp màn hình biểu đồ SLO của Grafana không bị rớt trong cửa sổ drain.

## 6. Nghiệm thu & Sự cố phát sinh (Ghi nhận trung thực)

- [ ] Xác nhận 0 pod revenue Pending. Nếu có pod phụ trợ (như DaemonSet agent) Pending, cần ghi chú rõ ràng nguyên nhân (do bị cordon).
- [ ] Ghi chú bất kỳ sự cố nào quan sát được trên mặt phẳng monitoring (ví dụ: Grafana 502) để báo cáo tính trung thực.

## 7. Đề xuất cải thiện sau Demo

1. [Điền các kiến nghị rút ra sau khi thực hiện xong mandate (ví dụ: cải thiện HA cho tool, v.v.)]

---

> **Lưu ý cho Team:** Khi bắt đầu quay, copy file nháp này thành bản chính (ví dụ `docs/../mandates/mandate-03/mandate-03-drain-node-report.md`) và điền các kết quả, bằng chứng cụ thể vào ngoặc vuông `[...]`.

# Mandate 17 — Bằng chứng nghiệm thu REL-17-04 + req#2 (sống sót mất 1 AZ)

**Ngày:** 2026-07-26
**Nhóm:** CDO02 — Reliability + Cost Optimization
**Phạm vi:** req#1/req#2 của Directive #17 (phần CDO02)
**Cluster:** `techx-corp-tf3` (EKS, account `197826770971`, ns `techx-tf3`)
**Cách lấy:** kubectl read-only qua SSM bastion tunnel (bastion `i-0f5959afa0eb31e7c`), profile `techx-new`.

Tài liệu này gói 2 bằng chứng live:
1. **REL-17-04** — Grafana và Prometheus đã tách sang 2 AZ khác nhau (anti-affinity hiệu lực thật).
2. **req#2** — mọi service trên luồng ra tiền có ≥1 replica sống ở ≥2 AZ, nên mất bất kỳ 1 AZ vẫn còn phục vụ.

Liên kết: [gap-analysis mandate 17](../../docx_cdo02/mandate-17-reliability-gap-analysis.md).

---

## 0. Bản đồ node → AZ (nền để đọc mọi bảng dưới)

```
NODE                ZONE   CAP      ARCH    LIFECYCLE   ITYPE
ip-10-0-10-199      1a     spot     amd64   spot        t3.medium
ip-10-0-24-177      1b     <none>   amd64   on-demand   t3.large
ip-10-0-26-153      1b     <none>   amd64   on-demand   t3.large
ip-10-0-31-242      1b     spot     arm64   spot        t4g.medium
ip-10-0-4-166       1a     <none>   amd64   on-demand   t3.medium   # node chaos exception (M13)
ip-10-0-40-78       1c     spot     amd64   spot        t3.medium
ip-10-0-43-83       1c     <none>   amd64   on-demand   t3.large
ip-10-0-46-49       1c     spot     arm64   spot        t4g.medium
ip-10-0-8-134       1a     <none>   amd64   on-demand   t3.large
```

Cụm trải **3 AZ**: `ap-southeast-1a`, `1b`, `1c`.

---

## 1. REL-17-04 — Grafana ≠ Prometheus theo AZ

### 1.1. Vị trí pod live

```
grafana-8697465f44-bhqcs      Running 4/4   node ip-10-0-43-83   -> AZ 1c
prometheus-5b74d99d6-j9k6r    Running 1/1   node ip-10-0-24-177  -> AZ 1b
```
(Pod prometheus cũ `6bf886fbf6-z7b26` ở node `ip-10-0-8-134`/AZ 1a đã ở trạng thái `Completed` — replicaset cũ, không còn phục vụ.)

→ **Grafana ở AZ 1c, Prometheus ở AZ 1b — khác AZ.** Mất 1 AZ không thể mất đồng thời cả dashboard lẫn nguồn metric.

### 1.2. Anti-affinity thật sự nằm trong pod spec đang chạy (không phải trùng hợp)

```
grafana  pod: podAntiAffinity.preferred -> matchLabels {app.kubernetes.io/name: prometheus}  topologyKey=topology.kubernetes.io/zone
prometh. pod: podAntiAffinity.preferred -> matchLabels {app.kubernetes.io/name: grafana}     topologyKey=topology.kubernetes.io/zone
```

Cả hai pod mang luật đối xứng (đẩy nhau theo zone) đúng như PR #388 / commit `20128a9`. Dùng `preferred` (soft) nên không rủi ro Pending; nền node trải 3 AZ nên thực tế luôn tách được.

**Kết luận REL-17-04: ĐẠT (verified live 26/07).**

---

## 2. req#2 — mất 1 AZ, luồng ra tiền vẫn sống

### 2.1. Phân bố AZ của service ra tiền (pod → node → AZ)

| Service | Replicas (ready) | AZ các replica | Mất bất kỳ 1 AZ vẫn còn? |
|---|---|---|---|
| frontend | 2/2 | **1c + 1a** | ✅ |
| frontend-proxy | 2/2 | **1c + 1a** | ✅ |
| product-catalog | 2/2 | **1b + 1c** (arm64/Graviton) | ✅ |
| cart | 2/2 | **1c + 1a** | ✅ |
| checkout (rollout) | 2/2 | **1c + 1a** | ✅ |
| payment | 2/2 | **1c + 1a** | ✅ |
| currency | 2/2 | **1c + 1a** | ✅ |
| shipping | 2/2 | **1a + 1c** | ✅ |
| quote | 2/2 | **1a + 1c** | ✅ |
| product-reviews | 2/2 | **1a + 1c** | ✅ |
| ad | 1/1 | 1b | ⚠️ 1 replica — xem §2.4 |
| recommendation | 1/1 | 1a | ⚠️ 1 replica — xem §2.4 |

Mọi service **cốt lõi** đều có 2 replica ở **2 AZ khác nhau** → mất bất kỳ 1 AZ, mỗi service vẫn còn ≥1 replica phục vụ.

### 2.2. PDB — chống mất cả 2 replica lúc drain/disruption tự nguyện

```
PDB                   MIN  CURRENT  DESIRED  ALLOWED
cart-pdb              1    2        1        1
checkout-pdb          1    2        1        1
currency-pdb          1    2        1        1
frontend-pdb          1    2        1        1
frontend-proxy-pdb    1    2        1        1
payment-pdb           1    2        1        1
product-catalog-pdb   1    2        1        1
product-reviews-pdb   1    2        1        1
quote-pdb             1    2        1        1
shipping-pdb          1    2        1        1
otel-gateway-pdb      1    2        1        1
```
Tất cả `currentHealthy=2`, `disruptionsAllowed=1` → luôn giữ tối thiểu 1 replica khi node bị drain.
(Lưu ý: `checkout` chạy qua Argo Rollouts — Deployment `checkout`=0, `checkout-rollout`=2/2; `checkout-pdb` chọn đúng pod của rollout nên `currentHealthy=2`.)

### 2.3. Tầng dữ liệu đã đa-AZ (mandate 8)

Luồng ra tiền còn phụ thuộc datastore — đã managed multi-AZ từ mandate 8: **RDS PostgreSQL Multi-AZ**, **MSK 3 broker / 3 AZ / RF=3**, **ElastiCache 2 node**. Mất 1 AZ, tầng dữ liệu tự failover, không phải SPOF. Xem `docs/mandate-08-nghiem-thu.md`.

### 2.4. Điều thành thật cần nói khi demo

**(a) ad + recommendation chạy 1 replica** (HPA `minReplicas: 1`) → mất AZ chứa nó là mất service đó. **Đây là chủ ý, không phải lỗ hổng:** cả hai là service làm giàu trang **không cốt lõi**, và đã được **REL-17-02 (deadline + fallback)** bọc — mất ad/reco thì trang vẫn load, chỉ thiếu quảng cáo/gợi ý. Tức 2 mảnh mandate 17 khớp nhau: cái không nhân đôi thì được degrade-to-empty.

**(b) Tập trung spot (REL-17-05).** Các service amd64 cốt lõi hiện chỉ trải **1a (`ip-10-0-10-199`) + 1c (`ip-10-0-40-78`)** — đúng 2 node spot amd64. `topologySpread minDomains:2` ép được 2 AZ, nhưng vì chỉ có 2 node spot amd64 nên spread dừng ở đúng 2 AZ. Hệ quả: **mất 1 AZ vẫn sống (đạt req#2), nhưng replica sống sót dồn về 1 node spot còn lại** — mỏng ở tầng node. Đây là căng thẳng M13↔M17 đã ghi ở REL-17-05, cần sync với CDO01 (turuong) về batch spot của mandate 13; không sửa đơn phương ở đây.

**Kết luận req#2: kiến trúc + phân bố live ĐẠT** — mất bất kỳ 1 AZ, mọi service cốt lõi giữ ≥1 replica ở AZ còn lại, PDB + graceful drain + datastore multi-AZ bảo toàn luồng. Caveat spot-concentration ghi rõ ở (b).

---

## 3. Cách tái lập (read-only)

```bash
export AWS_PROFILE=techx-new
# mở tunnel: scripts/kube-tunnel.sh  (resolve bastion động + SSM port-forward 8443)
kubectl get nodes -L topology.kubernetes.io/zone,techx.io/capacity,kubernetes.io/arch,karpenter.sh/capacity-type
kubectl -n techx-tf3 get pods -l app.kubernetes.io/name=grafana -o wide
kubectl -n techx-tf3 get pods -l app.kubernetes.io/name=prometheus -o wide
kubectl -n techx-tf3 get pods -o custom-columns='SVC:.metadata.labels.opentelemetry\.io/name,POD:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase'
kubectl -n techx-tf3 get pdb
```

## 4. Bước demo-day tuỳ chọn (chưa thực hiện ở đây)

Bằng chứng trên chứng minh **điều kiện đủ để sống sót** (mỗi service cốt lõi có replica ở ≥2 AZ + PDB + drain graceful + datastore multi-AZ). Nếu mentor muốn diễn tập trực tiếp "mất 1 AZ": `cordon` + `drain` **toàn bộ node của một AZ** (vd cả 1a) trong lúc có tải, quan sát checkout success ≥99% trên Grafana — dùng lại phương pháp drain của mandate 13, mở rộng ra cả AZ. **Không tự chạy vì gây gián đoạn thật; cần thực hiện có kiểm soát trước mặt mentor.**

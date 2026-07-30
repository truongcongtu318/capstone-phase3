# M9-01 — Chaos test: catalog stale-cache + readiness startup-latch

**Mandate:** #9 (zero-downtime ops) · **Task:** M9-01 · **Owner:** Hải · **Reviewer:** Đông
**Ngày soạn:** 30/07/2026 · **Đi kèm:** [`mandate-09-zero-downtime-ops-solution.md`](../docx_cdo02/mandate-09-zero-downtime-ops-solution.md) §3.1,
[`mandate-09-m9-01-catalog-implementation-notes.md`](../docx_cdo02/mandate-09-m9-01-catalog-implementation-notes.md),
`chaos-mesh-self-service-guide.md`.

> **Mục tiêu (acceptance M9-01):** trong một **DB outage 60–120s**, `product-catalog`
> **vẫn nằm trong endpoints**, browse (list/get/search) trả **200 với dữ liệu stale**, **0 lỗi
> khách**; và một **pod mới cold-start GIỮA outage KHÔNG vào endpoints** (đúng latch).

---

## 0. M9-01 đã đổi gì (để hiểu vì sao test này chứng minh được)

- list/get/search phục vụ từ **canonical snapshot in-memory** — đường đọc khách **không chạm DB**.
- Refresh nền ~30s; refresh lỗi **giữ last-known-good**, không bao giờ xoá cache.
- **Readiness = startup-latch:** Ready chỉ khi đã prime đầy đủ; sau đó `Ready = !shutdown &&
  cache_schema_valid`. **DB reachable KHÔNG còn quyết định readiness** (chỉ là degraded-signal).
  Health goroutine cũ (ping DB → NOT_SERVING) đã bị thay.
- Liveness vẫn là `tcpSocket` (độc lập DB) → pod not-ready **không bị kill**.
- Metrics (Prometheus, label `otel_scope_name="product-catalog"`): `cache_primed`, `ever_primed`,
  `cache_age_seconds`, `served_stale_total`, `db_retry_attempts_total`, `db_retry_recovered_total`,
  `db_retry_exhausted_total`.

**Điều kiện tiên quyết:** image product-catalog đã build từ nhánh
`feat/m9-01-catalog-stale-cache-readiness-startup-latch-go` và deploy (imageOverride digest cập nhật);
2 pod `Ready`, cache đã prime (`ever_primed=1`). Chưa deploy thì test này vô nghĩa.

---

## 1. Chuẩn bị phiên

Mở tunnel SSM tới cluster (xem `chaos-mesh-self-service-guide.md` §1.1). **Profile hiện tại là
`prod`** (không phải `techx-new` — đã ngừng tồn tại):

```bash
export AWS_PROFILE=prod; export MSYS_NO_PATHCONV=1
BASTION_ID=$(aws ec2 describe-instances --region ap-southeast-1 \
  --filters "Name=tag:Name,Values=techx-corp-tf3-bastion" "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" --output text)
EKS_HOST=$(aws eks describe-cluster --name techx-corp-tf3 --region ap-southeast-1 \
  --query "cluster.endpoint" --output text | sed 's~^https://~~')
aws ssm start-session --target "$BASTION_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host="$EKS_HOST",portNumber="443",localPortNumber="8443" --region ap-southeast-1
```

Kiểm tra baseline (phải xanh trước khi bơm lỗi):

```bash
# 2 pod Ready, đều đã prime
kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=product-catalog -o wide
kubectl -n techx-tf3 get endpoints product-catalog \
  -o jsonpath='{.subsets[*].addresses[*].ip}{"\n"}'   # 2 IP
```

Preflight bắt buộc (§2 solution): đọc trạng thái flagd/fault-injection — **có fault ACTIVE = NO-GO**.
**KHÔNG đụng flagd.**

Trong Grafana (SSO `https://grafana.arthur-ngo.org` → Explore → Prometheus) mở sẵn:

```promql
cache_primed{otel_scope_name="product-catalog"}
ever_primed{otel_scope_name="product-catalog"}
cache_age_seconds{otel_scope_name="product-catalog"}
increase(served_stale_total{otel_scope_name="product-catalog"}[1m])
increase(db_retry_attempts_total{otel_scope_name="product-catalog"}[1m])
increase(db_retry_exhausted_total{otel_scope_name="product-catalog"}[1m])
```

> Nếu series trống: xác nhận cách Prometheus OTLP đặt tên/label với **Đông (M9-00)**. Scope name
> `product-catalog` do SDK set nên `otel_scope_name` là label đáng tin; counter có hậu tố `_total`.

---

## 2. Scenario A — DB outage 60–120s (cache + latch giữ khách)

Cắt egress từ **product-catalog → RDS** bằng Chaos Mesh `NetworkChaos` (`partition`, external target
= endpoint RDS). Đây là "DB outage" nhìn từ catalog; **không đụng RDS thật, không ảnh hưởng service
khác** (chỉ pod catalog bị chặn tới đúng IP RDS).

`m9-01-catalog-db-partition.yaml`:

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: m9-01-catalog-db-partition
  namespace: techx-tf3
spec:
  action: partition
  mode: all                       # mọi pod catalog (kể cả pod scale thêm ở Scenario B)
  direction: to
  duration: 100s                  # trong khoảng 60–120s; hết giờ TỰ gỡ dù quên delete
  selector:
    namespaces: [techx-tf3]
    labelSelectors:
      app.kubernetes.io/name: product-catalog
  externalTargets:
    - techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com
```

### Các bước

1. **Giữ tải browse** suốt cửa sổ (Locust load-generator — xem guide §5.1). Reset stats để đo
   windowed:
   ```bash
   kubectl -n techx-tf3 port-forward svc/load-generator 8089:8089 &   # terminal riêng
   curl -s -X POST http://localhost:8089/stats/reset
   ```

2. **Apply chaos + lấy mốc t0:**
   ```bash
   kubectl apply -f m9-01-catalog-db-partition.yaml
   kubectl -n techx-tf3 get networkchaos m9-01-catalog-db-partition \
     -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}'    # AllInjected=True
   ```

3. **Bước ④ — verify lỗi ăn thật** (guide §5.2): xác nhận luật tc chứa IP RDS:
   ```bash
   kubectl -n techx-tf3 get podnetworkchaos -o yaml | grep -A3 -i "ipset\|external\|cidr" | head
   ```
   Và refresh **thật sự fail**: trong ~30s tiếp theo `db_retry_exhausted_total` phải tăng,
   `cache_age_seconds` bắt đầu bò lên, `served_stale_total` tăng theo mỗi browse.

4. **Xác nhận khách vẫn được phục vụ (điểm mấu chốt):**
   ```bash
   # (a) pod VẪN trong endpoints (2 IP không đổi)
   kubectl -n techx-tf3 get endpoints product-catalog \
     -o jsonpath='{.subsets[*].addresses[*].ip}{"\n"}'
   # (b) pod vẫn 2/2 Ready (readiness không phụ thuộc DB nữa)
   kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=product-catalog
   # (c) ListProducts vẫn trả dữ liệu (stale) — gRPC trực tiếp
   kubectl -n techx-tf3 port-forward svc/product-catalog 8080:8080 &   # terminal riêng
   grpcurl -plaintext localhost:8080 oteldemo.ProductCatalogService/ListProducts | head
   ```

5. **Đo customer-fail = 0** (windowed): Locust browse/list failures **không tăng**; Envoy non-2xx
   route khách = 0. Đây là tiêu chí PASS chính.

6. **Recovery:** để `duration` hết (hoặc `kubectl delete -f ...`). Trong ≤30s (một chu kỳ refresh)
   `served_stale_total` ngừng tăng, `cache_age_seconds` reset về ~0, `db_retry_recovered_total` có thể
   +1 nếu recovery rơi vào một retry.

### PASS Scenario A
- `ever_primed=1` và `cache_primed=1` **suốt** cửa sổ; pod **luôn trong endpoints**; 2/2 Ready.
- Browse 200 có dữ liệu; `served_stale_total` > 0 (bằng chứng phục vụ last-known-good).
- **Customer-fail delta = 0.** Retry nội bộ / stale > 0 là **được phép** (bằng chứng nuốt blip).

---

## 3. Scenario B — cold-start GIỮA outage không vào endpoints (latch)

Trong khi partition ở Scenario A **vẫn active**, tạo một pod catalog **mới**. Vì `mode: all`, chaos
áp cả pod mới → nó **không prime được** → `ever_primed=0` → readiness NOT_SERVING → **không vào
endpoints**. 2 pod cũ (đã prime) vẫn phục vụ khách bình thường.

```bash
# scale +1 (replicas do external quản + Argo ignoreDifferences /spec/replicas -> không bị revert)
kubectl -n techx-tf3 scale deploy/product-catalog --replicas=3

# pod mới: xác nhận CHAOS áp lên nó (nếu chưa, chờ reconcile vài giây rồi kiểm lại)
kubectl -n techx-tf3 get podnetworkchaos -o wide

# pod mới KHÔNG Ready, KHÔNG vào endpoints
kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=product-catalog     # pod mới 0/1, Running
kubectl -n techx-tf3 get endpoints product-catalog \
  -o jsonpath='{.subsets[*].addresses[*].ip}{"\n"}'                         # VẪN 2 IP (pod cũ)
# liveness (tcpSocket) vẫn pass -> pod mới KHÔNG bị CrashLoop, chỉ đứng chờ prime
kubectl -n techx-tf3 describe pod <pod-moi> | grep -A2 -i "readiness\|liveness\|Warning"
```

Gỡ chaos (hoặc để hết `duration`) → pod mới prime được → chuyển `1/1 Ready` → **giờ mới** vào
endpoints (3 IP). Sau đó scale về nền:

```bash
kubectl -n techx-tf3 delete -f m9-01-catalog-db-partition.yaml
kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=product-catalog -w   # pod mới -> 1/1
kubectl -n techx-tf3 scale deploy/product-catalog --replicas=2
```

### PASS Scenario B
- Pod mới cold-start giữa outage: `Running` nhưng **0/1 not-ready**, **vắng mặt trong endpoints**,
  **không CrashLoopBackOff** (liveness độc lập DB).
- Chỉ khi DB reachable trở lại và prime xong, pod mới mới vào endpoints.

> **Lưu ý (guide §6.2):** trên VPC CNI của cụm này chaos đôi khi báo `AllInjected` mà không ăn.
> Nếu pod mới **prime được dù đang outage**, kiểm tra `podnetworkchaos` xem nó có bị áp không.
> Phương án chuẩn-production cho cold-start latch là **reboot-with-failover RDS thật** (§4) —
> lúc đó DB down toàn cục nên mọi pod mới chắc chắn không prime.

---

## 4. Phiên bản chuẩn-production (rehearsal M9-12 / prod M9-13)

Chaos Mesh partition là bản isolate để dev/verify nhanh. Bản "thật" của outage này trong Mandate #9 là:
- **#3 reboot-with-failover RDS** (M9-08): Multi-AZ, ngắt kết nối ~60–120s **toàn cục**. Cache+latch
  của M9-01 chính là thứ giữ read path sống — không phải retry.
- **#4 rotation** và **#2 MSK rolling** cũng tạo blip; catalog read path (in-memory) không chạm.

Ở rehearsal, chạy đúng combined-check (Scenario A + B) **dưới tải**, đo bằng bộ gate M9-00 (7 điều
kiện + route matrix). `product-catalog` cover route: **list/get/search** — mỗi route phải có RPS>0,
đạt `N_route`, failure delta=0.

---

## 5. Max-staleness alert (bàn giao M9-00 / Đông)

Cache che outage tốt, nhưng **staleness không được vô hạn**. Cảnh báo khi snapshot cũ hơn **15 phút**
(nhiều lần ngân sách failover) — không tự ngắt phục vụ, chỉ để vận hành biết.

PromQL:
```promql
max by (otel_scope_name) (cache_age_seconds{otel_scope_name="product-catalog"}) > 900
```

Grafana provisioning (thêm vào `grafana/provisioning/alerting/platform-reliability-alerting.yml`,
group `techx-platform-reliability`, **khi image M9-01 đã live** — trước đó series trống sẽ NoData):

```yaml
- uid: techx-catalog-cache-stale
  title: TechXCatalogCacheStale
  condition: stale_threshold
  data:
    - refId: cache_age
      relativeTimeRange: { from: 600, to: 0 }
      datasourceUid: webstore-metrics
      model:
        editorMode: code
        expr: max by (otel_scope_name) (cache_age_seconds{otel_scope_name="product-catalog"})
        instant: true
        refId: cache_age
    - refId: stale_threshold
      datasourceUid: __expr__
      model:
        conditions:
          - evaluator: { type: gt, params: [900] }   # 15 phút
            operator: { type: and }
            query: { params: [C] }
            reducer: { type: last, params: [] }
            type: query
        datasource: { type: __expr__, uid: __expr__ }
        expression: cache_age
        refId: stale_threshold
        type: threshold
  noDataState: OK        # trước khi có traffic/metric coi như OK, không spam
  execErrState: Error
  for: 5m
  annotations:
    summary: "product-catalog cache stale > 15m (DB refresh đang fail?)"
    description: "cache_age_seconds = {{ $values.cache_age.Value }}s. Cache vẫn phục vụ last-known-good nhưng refresh đã fail lâu — kiểm tra RDS/credential/network."
  labels: { severity: warning, team_name: platform, category: staleness }
  isPaused: false
  notification_settings: { receiver: grafana-default-email }
```

---

## 6. Dừng khẩn cấp + an toàn

```bash
export AWS_PROFILE=prod
kubectl -n techx-tf3 delete networkchaos m9-01-catalog-db-partition --ignore-not-found
kubectl -n techx-tf3 scale deploy/product-catalog --replicas=2   # nếu đã scale ở Scenario B
```

- **product-catalog nằm trên đường khách** (browse). Dù chaos chỉ chặn catalog→RDS và cache che được,
  vẫn **báo CDO01+CDO02 trước** khung giờ chạy; chạy giờ ít traffic.
- **KHÔNG đụng flagd**; **KHÔNG** reboot/đổi RDS thật trong scenario này (đó là #3/M9-08, cửa sổ riêng).
- Luôn để `duration` trong CR — hết giờ tự gỡ dù quên delete.
- Sau buổi: xoá hết chaos, replicas về 2, xác nhận 2/2 Ready + `cache_age_seconds` ~0.

---

## 7. Bảng ánh xạ acceptance → bằng chứng

| Acceptance M9-01 | Bằng chứng ở runbook này |
|---|---|
| Prime canonical snapshot; list/get/search từ in-memory; refresh ~30s; lỗi → giữ LKG | §0 + §2 bước 4c (browse trả data khi DB bị cắt) + `cache_age_seconds` bò lên rồi reset |
| Startup-latch (STARTUP/STEADY/LIVENESS), revision khớp | §2 (steady: Ready khi DB down) + §3 (startup: cold-start không vào endpoints) |
| Retry blip 4×/700ms; ConnMaxLifetime 60s | `db_retry_attempts/recovered/exhausted_total`; unit test `TestRetryBudgetIs700ms` |
| Metrics + max-staleness alert 15′ | §1 (6 metric) + §5 (alert rule) |
| Chaos 60–120s: pod trong endpoints, browse 200 stale, 0 fail; cold-start không vào endpoints | §2 (Scenario A) + §3 (Scenario B) |

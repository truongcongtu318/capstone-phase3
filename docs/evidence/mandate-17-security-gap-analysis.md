# Đánh giá Bảo mật — NetworkPolicy & RBAC Gap Analysis

# Mandate 17: Khoanh Blast-Radius (Yêu cầu #3 & #4)

> [!NOTE]
> **HISTORICAL BASELINE (2026-07-20)**
> Tài liệu này là bằng chứng "before" cho PM-147, giữ nguyên kết quả chạy ngày 2026-07-20 để đối chiếu.
> **Current-state note:**
> - PM-149 SEC-01/SEC-02 đã production-verified (production evidence).
> - PM-148 staged/live pending.

## Người phụ trách

CDO01

## Thông tin đánh giá

| Trường           | Giá trị                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| Ngày đánh giá    | 2026-07-20                                                                                        |
| Cluster          | techx-corp-tf3                                                                                    |
| Region           | ap-southeast-1                                                                                    |
| Namespace        | techx-tf3                                                                                         |
| Người thực hiện  | CDO01                                                                                             |
| Phương pháp      | Live cluster verify qua SSM tunnel — `kubectl`, Python socket, `kubectl auth can-i` impersonation |
| Baseline so sánh | `docs/evidence/10-security-baseline-rbac.md` (2026-07-16)                                         |

---

## Tóm tắt điều hành

| ID     | Mức độ              | Mô tả                                                                                    | Thay đổi so với 16/07 |
| ------ | ------------------- | ---------------------------------------------------------------------------------------- | --------------------- |
| SEC-01 | CAO (HIGH)          | Grafana SA đọc được `secrets` toàn cluster (kể cả `kube-system`)                         | ❌ Chưa fix           |
| SEC-02 | TRUNG BÌNH (MEDIUM) | 22 workload (business deployments, supporting infra, component-scoped IRSA) mount SA token mặc định | ❌ Chưa fix           |
| SEC-03 | CAO (HIGH)          | 18+ business service không có NetworkPolicy — lateral movement tự do, egress internet mở | ❌ Chưa fix           |

**Kết luận:** Không có bất kỳ thay đổi bảo mật nào từ 16/07 đến 20/07. Cả ba gap đều còn nguyên.

---

## Phạm vi đánh giá

Verify đúng 2 yêu cầu của Mandate 17:

- **Yêu cầu #3 — Khoanh mạng (NetworkPolicy):** Mỗi pod chỉ nói được với đúng thứ nó cần; một pod bị chiếm không quét/kết nối được khắp cluster; egress bị khóa.
- **Yêu cầu #4 — Least-privilege K8s (RBAC / service account / token):** Mỗi service dùng service account riêng, quyền RBAC tối thiểu, không mount token quá rộng.

---

## Các lệnh đã chạy — kèm kết quả thực tế

### Bước 1 — Liệt kê NetworkPolicy đang tồn tại

```bash
$ kubectl -n techx-tf3 get networkpolicy

NAME                         POD-SELECTOR                                                           AGE
grafana-network-policy       app.kubernetes.io/instance=techx-corp,app.kubernetes.io/name=grafana   6d11h
jaeger-access                app.kubernetes.io/name=jaeger                                          4d9h
kafka-network-policy         app.kubernetes.io/component=kafka                                      6d11h
loadgen-deny-ingress         app.kubernetes.io/name=load-generator                                  4d9h
opensearch-access            app.kubernetes.io/name=opensearch                                      4d9h
postgres-network-policy      app.kubernetes.io/component=postgresql                                 7d1h
prometheus-access            app.kubernetes.io/name=prometheus                                      4d9h
valkey-cart-network-policy   app.kubernetes.io/component=valkey-cart                                6d11h
```

**Nhận xét:** 8 NetworkPolicy, 100% thuộc observability, datastore, và supporting workloads. Không có NetworkPolicy nào bảo vệ bất kỳ business service nào trong số:
`accounting`, `ad`, `cart`, `checkout`, `cloudflared`, `currency`, `email`, `flagd`, `fraud-detection`, `frontend`, `frontend-proxy`, `image-provider`, `kafka`(\*), `llm`, `payment`, `product-catalog`, `product-reviews`, `quote`, `recommendation`, `shipping`.

(\*) Kafka có NP nhưng chỉ giới hạn Ingress vào port 9092 — Egress của Kafka ra ngoài vẫn không bị kiểm soát.

---

### Bước 2 — Verify SEC-01: Grafana RBAC (không thay đổi so với 16/07)

```bash
# Xác minh quyền đọc secret ở kube-system qua impersonation
$ kubectl auth can-i list secrets \
    --as=system:serviceaccount:techx-tf3:grafana \
    -n kube-system
yes   ← [TRƯỚC] SEC-01 VẪN MỞ tính đến 2026-07-20
```

**Nhận xét:** Không thay đổi so với baseline ngày 16/07. `grafana-clusterrole` vẫn là ClusterRole với rule:

```yaml
- apiGroups: [""]
  resources: [configmaps, secrets]
  verbs: [get, watch, list]
```

Binding thông qua ClusterRoleBinding `grafana-clusterrolebinding` → SA `techx-tf3/grafana` có thể đọc mọi Secret ở mọi namespace.

---

### Bước 3 — Verify SEC-02: automountServiceAccountToken (không thay đổi so với 16/07)

```bash
$ kubectl -n techx-tf3 get deploy \
    -o jsonpath="{range .items[*]}{.metadata.name}{'\t'}{.spec.template.spec.automountServiceAccountToken}{'\t'}{.spec.template.spec.serviceAccountName}{'\n'}{end}"

accounting      [BLANK]   techx-corp            ← NOT SET → mount token theo default
ad              [BLANK]   techx-corp            ← NOT SET → mount token theo default
cart            [BLANK]   techx-corp            ← NOT SET → mount token theo default
checkout        [BLANK]   techx-corp            ← NOT SET → mount token theo default
currency        [BLANK]   techx-corp            ← NOT SET → mount token theo default
email           [BLANK]   techx-corp            ← NOT SET → mount token theo default
flagd           [BLANK]   techx-corp            ← NOT SET → mount token theo default
fraud-detection [BLANK]   techx-corp            ← NOT SET → mount token theo default
frontend        [BLANK]   techx-corp            ← NOT SET → mount token theo default
frontend-proxy  [BLANK]   techx-corp            ← NOT SET → mount token theo default
image-provider  [BLANK]   techx-corp            ← NOT SET → mount token theo default
kafka           [BLANK]   techx-corp            ← NOT SET → mount token theo default
llm             [BLANK]   techx-corp            ← NOT SET → mount token theo default
load-generator  [BLANK]   techx-corp            ← NOT SET → mount token theo default
payment         [BLANK]   techx-corp            ← NOT SET → mount token theo default
postgresql      [BLANK]   techx-corp            ← NOT SET → mount token theo default
product-catalog [BLANK]   techx-corp            ← NOT SET → mount token theo default
product-reviews [BLANK]   product-reviews-bedrock ← NOT SET → mount token theo default
quote           [BLANK]   techx-corp            ← NOT SET → mount token theo default
recommendation  [BLANK]   techx-corp            ← NOT SET → mount token theo default
shipping        [BLANK]   techx-corp            ← NOT SET → mount token theo default
valkey-cart     [BLANK]   techx-corp            ← NOT SET → mount token theo default
grafana         true      grafana               ← Explicit true (upstream Helm)
```

**Nhận xét:** 22/22 workload (bao gồm business deployments, supporting infrastructure, component-scoped IRSA) không có `automountServiceAccountToken: false`. Kubernetes mặc định là `true` khi không set → mọi pod đều có token SA được mount tại `/var/run/secrets/kubernetes.io/serviceaccount/token`. Token hợp lệ này có thể dùng để gọi Kubernetes API nếu SA được cấp thêm quyền sau này, hoặc bị dùng như credential khi pod bị compromise.

> **Lưu ý kỹ thuật:** `checkout` image là distroless — `sh`/`ls` không có. Lệnh `kubectl exec -- ls ...` sẽ fail với `executable file not found`. Thay thế: verify qua jsonpath Deployment spec (như trên) và đọc projected volume manifest.

---

### Bước 4 — Bằng chứng "TRƯỚC": Lateral Movement thật từ pod business

**Pod thực hiện:** `load-generator-d6b579584-4nstf` (business pod, namespace `techx-tf3`)

**Thời gian:** 2026-07-20 ~14:28 UTC (21:28 GMT+7)

```bash
# ── TEST 1: TCP sang payment:8080 (service khác, không liên quan load-generator) ──
$ kubectl -n techx-tf3 exec load-generator-d6b579584-4nstf -- \
    python3 -c "
import socket
s = socket.create_connection(('payment', 8080), timeout=3)
print('OPEN - lateral movement POSSIBLE')
s.close()
"
OPEN - lateral movement POSSIBLE
# [TRƯỚC] ← Load-generator KẾT NỐI THÀNH CÔNG sang payment:8080

# ── TEST 2: TCP sang checkout:8080 ──
$ kubectl -n techx-tf3 exec load-generator-d6b579584-4nstf -- \
    python3 -c "
import socket
s = socket.create_connection(('checkout', 8080), timeout=3)
print('OPEN - lateral movement POSSIBLE')
s.close()
"
OPEN - lateral movement POSSIBLE
# [TRƯỚC] ← Load-generator KẾT NỐI THÀNH CÔNG sang checkout:8080

# ── TEST 3: TCP sang ad:8080 ──
$ kubectl -n techx-tf3 exec load-generator-d6b579584-4nstf -- \
    python3 -c "
import socket
s = socket.create_connection(('ad', 8080), timeout=3)
print('AD OPEN')
s.close()
"
AD OPEN
# [TRƯỚC] ← Load-generator KẾT NỐI THÀNH CÔNG sang ad:8080

# ── TEST 4: Egress ra internet (ifconfig.me) ──
$ kubectl -n techx-tf3 exec load-generator-d6b579584-4nstf -- \
    python3 -c "
import urllib.request
resp = urllib.request.urlopen('http://ifconfig.me', timeout=5)
print('EGRESS OK:', resp.read().decode())
"
EGRESS OK: 13.213.127.91
# [TRƯỚC] ← Pod gọi được ra internet — public IP là 13.213.127.91 (NAT Gateway EKS)

# ── CONTROL: Datastore có NetworkPolicy — đúng là bị chặn ──
$ kubectl -n techx-tf3 exec load-generator-d6b579584-4nstf -- \
    python3 -c "
import socket
s = socket.create_connection(('postgresql', 5432), timeout=3)
print('DB OPEN')
s.close()
"
TimeoutError: timed out
# ← PostgreSQL bị chặn đúng (postgres-network-policy đang hoạt động)

$ kubectl -n techx-tf3 exec load-generator-d6b579584-4nstf -- \
    python3 -c "
import socket
s = socket.create_connection(('valkey-cart', 6379), timeout=3)
print('CACHE OPEN')
s.close()
"
TimeoutError: timed out
# ← Valkey bị chặn đúng (valkey-cart-network-policy đang hoạt động)
```

**Kết luận bằng chứng "TRƯỚC":**

| Kết nối                               | Kết quả                 | Kỳ vọng sau fix |
| ------------------------------------- | ----------------------- | --------------- |
| `load-generator` → `payment:8080`     | ✅ **THÀNH CÔNG** (gap) | ❌ Bị chặn      |
| `load-generator` → `checkout:8080`    | ✅ **THÀNH CÔNG** (gap) | ❌ Bị chặn      |
| `load-generator` → `ad:8080`          | ✅ **THÀNH CÔNG** (gap) | ❌ Bị chặn      |
| `load-generator` → internet           | ✅ **THÀNH CÔNG** (gap) | ❌ Bị chặn      |
| `load-generator` → `postgresql:5432`  | ❌ Timeout (NP đúng)    | ❌ Vẫn bị chặn  |
| `load-generator` → `valkey-cart:6379` | ❌ Timeout (NP đúng)    | ❌ Vẫn bị chặn  |

---

## FINDING SEC-01 — Grafana SA đọc được Secrets toàn cluster

**Mức độ:** CAO (HIGH)

**CWE:** CWE-269: Improper Privilege Management

**Mô tả:** ServiceAccount `grafana` (namespace `techx-tf3`) được bind với ClusterRole `grafana-clusterrole` thông qua ClusterRoleBinding cluster-wide. Rule trong ClusterRole cấp `get/watch/list` lên resource `secrets` không giới hạn namespace. Đây là hành vi mặc định của upstream Grafana Helm chart (`grafana/grafana`), không được override khi deploy.

**Blast radius nếu Grafana pod bị compromise:**

1. Lấy SA token từ `/var/run/secrets/kubernetes.io/serviceaccount/token`
2. Gọi K8s API từ bên ngoài: `curl -k https://<API>/api/v1/secrets -H "Authorization: Bearer $TOKEN"`
3. Đọc toàn bộ 11+ secrets bao gồm `aws-load-balancer-tls`, `sh.helm.release.v1.techx-corp.v*`.

**Fix đề xuất (task tiếp theo):**

- Xóa `secrets` khỏi `resources` trong `grafana-clusterrole`
- Hoặc downgrade từ ClusterRole → Role giới hạn trong namespace `techx-tf3`

---

## FINDING SEC-02 — automountServiceAccountToken không tắt trên workload pods

**Mức độ:** TRUNG BÌNH (MEDIUM)

**CWE:** CWE-272: Least Privilege Violation

**Mô tả:** Đây là default-automount configuration evidence: 22/22 workload (bao gồm business, supporting infra, component-scoped IRSA) không set `automountServiceAccountToken: false`. Theo mặc định của Kubernetes, việc không khai báo sẽ dẫn đến token được mount vào mọi Pod thực tế. Dù SA `techx-corp` hiện không có quyền K8s (xác nhận 16/07 còn đúng), token vẫn tồn tại trong pod và có thể bị dùng làm credential nếu:

- SA `techx-corp` bị grant thêm quyền sau này (configuration drift)
- Attacker dùng token để recon API server endpoints

**Fix đề xuất (task tiếp theo):**

- Set `automountServiceAccountToken: false` mặc định cho toàn bộ Deployment trong Helm chart
- Chỉ override `true` cho service thực sự cần gọi K8s API

> ⚠️ **Gotcha từ PM-0007:** Khi thay đổi pod template của `kafka` (strategy: Recreate), phải deploy riêng hoặc verify strategy đã đổi sang RollingUpdate trước — tránh lặp lại mất 22 sự kiện đơn hàng như 16/07/2026.

---

## FINDING SEC-03 — Business service không có NetworkPolicy

**Mức độ:** CAO (HIGH)

**CWE:** CWE-284: Improper Access Control

**Mô tả:** 18+ business service không có bất kỳ NetworkPolicy nào. Một pod business bị compromise có thể:

1. Quét tất cả port nội bộ (`nmap`/socket scan)
2. Kết nối TCP/HTTP tới bất kỳ service nào (payment, checkout, product-catalog, postgresql qua otel bypass, ...)
3. Gọi ra internet — exfiltrate dữ liệu, download malware, C2 callback

**Bằng chứng thực tế:** load-generator kết nối thành công tới payment:8080, checkout:8080, ad:8080, và gọi ra internet — tất cả trong 2026-07-20 14:28 UTC.

**Fix đề xuất (task tiếp theo):**

- Thêm NetworkPolicy cho từng business service theo đúng luồng giao tiếp thực tế
- Chặn egress mặc định (default-deny egress + whitelist DNS + otel-collector + các service được phép)

> ⚠️ **Gotcha từ PM-0006:** Khi thêm NP cho observability-adjacent services, PHẢI đảm bảo `otel-collector-agent` (DaemonSet, label `app.kubernetes.io/name: opentelemetry-collector`) được phép ingress vào mọi port cần thiết. Thiếu rule này gây cascading failure checkout 2h36m ngày 16/07/2026.

---



## Liên kết

- Baseline RBAC: [`docs/evidence/10-security-baseline-rbac.md`](./10-security-baseline-rbac.md)
- NetworkPolicy hiện có: [`gitops/infrastructure/network-policy-*.yaml`](../../gitops/infrastructure/)
- Postmortem NP outage: [`docs/postmortem/0006-networkpolicy-observability-outage.md`](../postmortem/0006-networkpolicy-observability-outage.md)
- Postmortem Kafka Recreate: [`docs/postmortem/0007-kafka-recreate-rollout-order-event-loss.md`](../postmortem/0007-kafka-recreate-rollout-order-event-loss.md)
- Mandate 17: [`phase3 - information/mandates/MANDATE-17-resilience-and-containment.md`](../../phase3%20-%20information/mandates/MANDATE-17-resilience-and-containment.md)

---

## Bổ sung: PR Description & DoD Mapping (PM-147)

**Mục tiêu PR:** Cung cấp Evidence Baseline cho PM-147 (Mandate 17).

**DoD Mapping:**
1. **NetworkPolicy inventory:** Đã liệt kê tại phần "Bước 1 — Liệt kê NetworkPolicy đang tồn tại" (8 NetworkPolicy cho observability/datastore).
2. **SEC-01/SEC-02 evidence:** Đã có bằng chứng lệnh và cấu hình tại "Bước 2" (Grafana SA đọc secrets) và "Bước 3" (automountServiceAccountToken).
3. **Lateral/egress "before" evidence:** Đã test thực tế tại "Bước 4" (load-generator truy cập payment, checkout, ad, và internet).

# Mandate 17 — Cập nhật tiến độ chung (CDO-02 + CDO-01)

**Ngày:** 2026-07-26
**Người tổng hợp:** CDO-02 (Reliability + Cost)
**Mục đích:** Chốt trạng thái thật của cả 4 yêu cầu mandate 17 trước buổi demo chung, để CDO-01 nắm phần req#3/#4 và các điểm hội tụ.
**Cách lấy:** verify read-only live qua SSM tunnel (`kubectl`, `kubectl auth can-i`) + đọc source/PR. Cluster `techx-corp-tf3`, ns `techx-tf3`, account `197826770971`.

> Mandate 17 nghiệm thu **một buổi demo chung**. req#1/#2 = CDO-02; req#3/#4 = CDO-01. Bảng dưới phản ánh trạng thái **đã kiểm chứng live 26/07**, không phải trạng thái PR.

---

## 0. TL;DR — trạng thái 4 yêu cầu

| Yêu cầu | Chủ | Trạng thái | Còn lại chính |
|---|---|---|---|
| **#1** Sống qua dependency chết | CDO-02 | 🛠️ Code xong, **chưa deploy** | Re-bump digest frontend để fallback lên thật |
| **#2** Chịu mất 1 AZ | CDO-02 | ✅ Đạt (verified live) | Caveat spot-concentration (REL-17-05) cần sync M13 |
| **#3** NetworkPolicy khoanh mạng | CDO-01 | 🟢 ~90%, enforce thật | Thiếu `default-deny` nền → egress pod lạ mở |
| **#4** RBAC least-privilege | CDO-01 | 🟠 Phần cốt xong, còn 1 leo thang | SA `default` quyền mạnh + token ở cloudflared |

**Đọc nhanh:** phần nền của cả 4 đều đã có và chạy thật. Rủi ro tập trung ở **2 lỗ của req#3/#4 hội tụ đúng vào bài "pod kẻ tấn công"** (§4), và **1 việc deploy còn treo của req#1** (§1).

---

## 1. req#1 — Sống qua một dependency chết (CDO-02)

| Item | Trạng thái |
|---|---|
| REL-17-01 — dual-write `cart` chặn 2s khi mất AZ | ✅ **Đóng** — `b881bf1` gỡ dual-write (live) |
| REL-17-06 — initContainer `wait-for-kafka` khoá khởi động | ✅ **Đóng** — `b881bf1` (live) |
| REL-17-02 — frontend gọi `ad`/`reco` không deadline+fallback | 🛠️ **Code merged (#375) nhưng CHƯA deploy** |
| REL-17-02b — `cart`/`checkout` gateway cũng thiếu deadline | 🟡 Cố ý ngoài scope (theo dõi) |

**Điểm cần biết về REL-17-02:** digest frontend đang chạy vẫn là bản **17/07** (`e6874914…`) — không có fallback. Image chứa fallback (`6e91e6c0…`, tag `ba46a27-30060412880-frontend`) **đã build, qua Trivy+Cosign, còn trong ECR**, nhưng bump digest (#448) từng bị revert (#450) như phòng ngừa lúc ổn định PM-129 (bug tooling trace-provenance đa-arch, **không phải lỗi supply-chain**). → chỉ cần re-bump 1 dòng digest trên main là fallback live. Đang chuẩn bị.

---

## 2. req#2 — Chịu mất cả một AZ (CDO-02) — ✅ ĐẠT (verified live 26/07)

**Phân bố AZ luồng ra tiền** (pod → AZ): 10/10 service cốt lõi có **2 replica ở 2 AZ khác nhau** → mất bất kỳ 1 AZ vẫn còn ≥1 replica:

| Service | AZ | | Service | AZ |
|---|---|---|---|---|
| frontend | 1c + 1a | | payment | 1c + 1a |
| frontend-proxy | 1c + 1a | | currency | 1c + 1a |
| product-catalog | 1b + 1c (arm64) | | shipping | 1a + 1c |
| cart | 1c + 1a | | quote | 1a + 1c |
| checkout | 1c + 1a | | product-reviews | 1a + 1c |

- **PDB** phủ đủ hot path (`disruptionsAllowed=1`, `currentHealthy=2`).
- **REL-17-04** — grafana (AZ 1c) ≠ prometheus (AZ 1b), anti-affinity `preferred` nằm thật trong pod spec (PR #388). ✅
- **Tầng dữ liệu** multi-AZ từ mandate 8 (RDS Multi-AZ, MSK 3-AZ, ElastiCache).

**Caveat ghi thẳng:**
- `ad`/`recommendation` chạy 1 replica → nhưng chính là 2 service mà REL-17-02 fallback bọc (degrade-to-empty). Hai mảnh khớp nhau.
- **REL-17-05 (🔴 còn):** service amd64 cốt lõi chỉ trải **2 node spot (1a + 1c)** → mất 1 AZ vẫn sống nhưng replica dồn về 1 node spot còn lại → mỏng tầng node. Do batch spot mandate-13.
- prometheus PVC/HA (giữ lịch sử metric): **cố ý KHÔNG làm** — EBS PVC zone-lock sẽ ghim prometheus vào 1 AZ, hại chính req#2.

---

## 3. Phần CDO-01 — verify live 26/07

### 3.1. req#3 — NetworkPolicy khoanh mạng: 🟢 ~90%, enforce THẬT

**Đã có (mạnh):**
- **27 NetworkPolicy đang chạy**, phủ mọi service. Mỗi service ra tiền có policy riêng **cả Ingress + Egress** (`*-business-policy`); observability/datastore/edge đều có.
- **Enforcement xác nhận**: `aws-eks-nodeagent --enable-network-policy=true`. Egress **bị khoá thật** (bằng chứng: loạt fix "allow DNS/ClusterIP" — chỉ cần khi policy đang chặn).
- Lateral-movement tới service đã biết **bị chặn** ở ingress đích. Rollout gần xong (cloudflared-policy merge ~26/07).

**Lỗ (🟠 TRUNG BÌNH–CAO): không có `default-deny` catch-all.** Không policy nào có selector rỗng `{}`. Mô hình "policy riêng từng service đã biết" → **pod kẻ tấn công mới (label lạ) không bị policy nào chạm → egress ra internet mở toang.** Phần "quét service khác" thì bị chặn (ingress đích từ chối), nhưng phần "khoá egress" của req#3 sẽ **fail** cho pod chưa được phủ.

*(Phụ: `grafana`/`kafka`/`postgres`/`valkey-cart` là policy Ingress-only — chưa khoá egress; datastore đã tắt nên nhẹ, grafana nên bổ sung egress.)*

### 3.2. req#4 — RBAC least-privilege: 🟠 phần cốt xong, còn 1 leo thang LIVE

**Đã có (tốt) — PM-149:**
- **Token automount = false cho cả 18 service** dùng SA `techx-corp` (xác nhận live: pod app không có volume `kube-api-access`). → app bị chiếm **không có token gọi K8s API**. Đây là thắng lớn.
- **Gỡ quyền đọc Secret cụm của Grafana** (SEC-01): Grafana chỉ còn Role namespaced trong techx-tf3.

**Lỗ 1 (🔴 CAO — khai thác được từ EDGE):** `cloudflared` (2 pod, hướng internet nhất) chạy SA **`default`**, automount **không tắt**, **có token thật** (`kube-api-access-*`). SA `default` bị bind role có `deployments/scale` + `pods/exec` + `pods` delete. Xác nhận trực tiếp:
```
kubectl auth can-i --as=system:serviceaccount:techx-tf3:default -n techx-tf3
  update deployments/scale → yes
  create pods/exec         → yes
  delete pods              → yes
```
→ **Chiếm cloudflared = scale deployment + exec vào pod bất kỳ + xoá pod.** Đúng thứ req#4 cấm. (aiops-engine, opensearch-0 cũng chung SA `default` này — phần aiops đụng cả AIO.)

**Lỗ 2 (🟡 phạm vi):** **Chưa làm per-service SA** — mọi service vẫn chung `techx-corp`. PM-149 tự ghi rõ điều này ngoài scope. Với app thì đỡ (không token nên vô hại), nhưng chưa đạt chữ "mỗi service SA riêng".

---

## 4. Điểm hội tụ — bài demo "pod kẻ tấn công" hôm nay sẽ ra sao

Mentor sẽ deploy 1 pod lạ vào `techx-tf3` và thử quét + gọi ra ngoài. Với trạng thái hiện tại:

| Hành vi attacker pod | Kết quả hiện tại | Vì sao |
|---|---|---|
| Kết nối sang service khác (lateral) | 🟢 **Bị chặn** | Ingress policy của đích từ chối |
| Gọi ra internet (egress/C2) | 🔴 **KHÔNG bị chặn** | Không có default-deny → pod lạ egress mở |
| Leo quyền K8s (scale/exec/delete) | 🔴 **Làm được** | Pod lạ dùng SA `default` → có token + quyền mạnh |

→ **2 lỗ req#3/#4 hội tụ đúng vào đây.** Muốn demo containment sạch, phải bịt cả hai trước.

---

## 5. Việc còn lại (theo chủ + ưu tiên)

| # | Việc | Chủ | Mức |
|---|---|---|---|
| 1 | Re-bump digest frontend `e6874914→6e91e6c0` để REL-17-02 fallback live | CDO-02 | 🔴 |
| 2 | Thêm `default-deny-all` NetworkPolicy nền (bịt egress pod lạ) | CDO-01 | 🟠 |
| 3 | Gỡ role mạnh khỏi SA `default`; cho aiops-engine SA riêng; tắt automount `default` | CDO-01 + AIO | 🔴 |
| 4 | cloudflared dùng SA riêng, automount=false (edge không cần K8s API) | CDO-01 | 🔴 |
| 5 | Sync REL-17-05 (spot-concentration) với batch M13 | CDO-01 + CDO-02 | 🟠 |
| 6 | (tuỳ mentor) per-service SA cho đủ chữ req#4 | CDO-01 | 🟡 |
| 7 | grafana bổ sung egress; đóng gói diễn tập AZ-drain trực tiếp | 2 bên | 🟡 |

---

## 6. Phụ lục — lệnh tái lập (read-only)

```bash
export AWS_PROFILE=techx-new   # + mở tunnel: scripts/kube-tunnel.sh
# req#2 (CDO-02)
kubectl get nodes -L topology.kubernetes.io/zone,techx.io/capacity,kubernetes.io/arch
kubectl -n techx-tf3 get pods -o custom-columns='SVC:.metadata.labels.opentelemetry\.io/name,NODE:.spec.nodeName'
kubectl -n techx-tf3 get pdb
# req#3 (CDO-01)
kubectl -n techx-tf3 get netpol
kubectl -n kube-system get ds aws-node -o jsonpath='{range .spec.template.spec.containers[?(@.name=="aws-eks-nodeagent")]}{.args}{end}'
# req#4 (CDO-01)
kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=cloudflared -o jsonpath='{range .items[*]}{.spec.serviceAccountName}{" "}{range .spec.volumes[*]}{.name}{" "}{end}{"\n"}{end}'
kubectl auth can-i update deployments/scale --as=system:serviceaccount:techx-tf3:default -n techx-tf3
kubectl auth can-i create pods/exec        --as=system:serviceaccount:techx-tf3:default -n techx-tf3
```

*Chi tiết req#2/REL-17-04: xem `rel-17-04-and-req2-az-resilience-2026-07-26.md` cùng thư mục.*

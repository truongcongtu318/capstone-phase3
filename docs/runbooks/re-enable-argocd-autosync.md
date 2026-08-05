# Runbook — Bật lại ArgoCD auto-sync an toàn (app `techx-corp`)

**Bối cảnh:** CDO01 đang **tắt auto-sync** trên app `techx-corp` để sửa security. Trong thời gian tắt,
main đã tích luỹ **15 commit** chưa xuống cluster. Bật lại = **apply tất cả cùng lúc** (big bang) kèm
`prune: true` + `selfHeal: true`.

**Mục đích file này:** biết trước chính xác điều gì sẽ xảy ra, kiểm tra trước khi bật, và verify sau khi bật.

| | |
|---|---|
| Revision cluster đang chạy | `1c5132e8` |
| Git định nghĩa (đúng) | `syncPolicy.automated: {prune: true, selfHeal: true}` |
| Live hiện tại | `automated` = **rỗng (TẮT)** — lệch khỏi git, do tắt tay |
| Commit tồn đọng | **15** |

---

## 1. Điều gì SẼ xảy ra khi bật lại

### 1.1 Bốn workload sẽ RESTART (do gỡ initContainer — Mandate #8)

| Workload | Thay đổi | Restart có an toàn? |
|---|---|---|
| `cart` | gỡ initContainer `wait-for-valkey-cart` + gỡ env `VALKEY_DUAL_WRITE_*` | ✅ **zero-downtime** — `replicas=2`, `maxUnavailable=0`, `maxSurge=1`, có PDB `minAvailable=1` |
| `checkout` | gỡ initContainer `wait-for-kafka` | ✅ **an toàn** — Deployment `replicas=0`, chạy qua **Argo Rollouts canary** (20%→50%→100% + analysis `checkout-slo`) |
| `accounting` | gỡ initContainer `wait-for-kafka` | ✅ 1 replica, consumer **async** — đơn chờ trong MSK, không mất (Earliest + manual commit) |
| `fraud-detection` | gỡ initContainer `wait-for-kafka` | ✅ 1 replica, consumer async |

> **Vì sao phải gỡ:** các initContainer này hardcode `nc -z kafka 9092` / `nc -z valkey-cart 6379` (**store CŨ**).
> Nếu không gỡ trước khi xoá store cũ ở §8, pod sẽ **kẹt vĩnh viễn ở `Init:0/1`** → cart/checkout chết.
> (PR #307 + #308.)

### 1.2 Thay đổi khác

| Thay đổi | Nguồn | Ghi chú |
|---|---|---|
| Gỡ receiver `kafkametrics` khỏi otel-collector + tham chiếu pipeline | CDO02 #307 | Metric MSK lấy qua CloudWatch |
| Gỡ credential **plaintext** khỏi `values.yaml` (3 chỗ) | CDO02 #307 | Yêu cầu bảo mật Mandate #8 |
| `otel-node-agent` (ConfigMap/SA/ClusterRole/ClusterRoleBinding) + resources | **CDO01 mandate05** | Đang OutOfSync sẵn |
| `namespace-observability-system.yaml`, `network-policy-prometheus.yaml` | **CDO01 mandate05** | Thuộc app `techx-infrastructure-app` |

### 1.3 KHÔNG đổi (kiểm tra rồi)

- ✅ **Image `checkout` giữ nguyên `efb7eff…`** — code parallelize `prepOrderItems` (#285) mới ở source, **chưa bump imageOverride** nên **không deploy**. Sync sẽ không đổi image.
- ✅ Không đụng RDS / ElastiCache / MSK (hạ tầng do Terraform quản, không phải ArgoCD).
- ✅ Không đụng 3 store cũ (việc xoá nằm ở PR §8 riêng, **chưa mở**).

---

## 2. ⚠️ CẢNH BÁO cho CDO01 trước khi bật

**`selfHeal: true` sẽ HOÀN NGUYÊN mọi sửa tay lên resource do ArgoCD quản lý.**

Nếu trong lúc tắt sync, CDO01 đã `kubectl edit`/`patch` bất kỳ resource nào thuộc app `techx-corp`
(Deployment, ConfigMap, Service…) mà **chưa commit vào git**, thì ngay khi bật lại, **selfHeal sẽ xoá
sạch các sửa đó**.

👉 **Trước khi bật: đưa toàn bộ thay đổi security vào git.** Kiểm tra nhanh:
```bash
# Liệt kê resource do ArgoCD quản lý đang khác git (se bi selfHeal ghi de)
kubectl -n argocd get application techx-corp -o json \
  | python -c "import sys,json;d=json.load(sys.stdin);print('\n'.join(f\"{r.get('kind')}/{r.get('name')} -> {r.get('status')}\" for r in d['status']['resources'] if r.get('status')!='Synced'))"
```

**`prune: true`** chỉ xoá resource **ArgoCD từng tạo** mà nay không còn trong git. Resource CDO01 tạo tay
bằng `kubectl` (không có tracking của ArgoCD) **KHÔNG bị prune** — nhưng cũng **không được ArgoCD bảo vệ**.

---

## 3. Trước khi bật — checklist

```bash
export AWS_PROFILE=techx-new
export NS=techx-tf3
```

- [ ] **PR #307 và #308 đã merge vào main** (gỡ hết initContainer trỏ store cũ)
```bash
git fetch origin
git show origin/main:"phase3 - information/techx-corp-chart/values.yaml" | grep -c "^      - name: wait-for-kafka"        # → 0
git show origin/main:"phase3 - information/techx-corp-chart/values.yaml" | grep -c "^      - name: wait-for-valkey-cart"  # → 0
```
- [ ] **CDO01 đã commit mọi sửa security vào git** (xem cảnh báo mục 2)
- [ ] **Chart render được** (không lỗi schema — `values.schema.json` là `additionalProperties:false`)
```bash
CHART="phase3 - information/techx-corp-chart"
helm template techx-corp "$CHART" --namespace $NS \
  -f "$CHART/values.yaml" -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" -f "phase3 - information/deploy/values-aio-llm.yaml" > /dev/null && echo RENDER_OK
```
- [ ] **Ghi lại trạng thái trước** để so sánh sau
```bash
kubectl -n $NS get pods --no-headers | wc -l
kubectl -n $NS get pods --no-headers | awk '{split($2,a,"/"); if($3!="Running"||a[1]!=a[2]) print}' # → rỗng
```
- [ ] **Chọn giờ ít traffic** (4 workload sẽ restart, checkout đi qua canary ~15 phút)

---

## 4. Bật lại

Cách **đúng** là sửa trong git (`gitops/apps/techx-corp.yaml` đã có sẵn `automated`), rồi để app-of-apps
`techx-corp-bootstrap` khôi phục. Nếu cần bật ngay bằng tay:

```bash
kubectl -n argocd patch application techx-corp --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

---

## 5. Sau khi bật — verify (theo thứ tự)

```bash
# 1. ArgoCD sync tới đúng revision main
kubectl -n argocd get application techx-corp -o jsonpath='sync={.status.sync.status} health={.status.health.status} rev={.status.sync.revision}{"\n"}'

# 2. Không pod nào rớt (theo dõi ~5 phút)
kubectl -n $NS get pods --no-headers | awk '{split($2,a,"/"); if($4!="Completed" && ($3!="Running"||a[1]!=a[2])) print}'

# 3. initContainer đã biến mất khỏi live (đây là mục tiêu chính)
for d in accounting checkout fraud-detection cart; do
  echo -n "$d: "; kubectl -n $NS get deploy $d -o jsonpath='{range .spec.template.spec.initContainers[*]}{.name}{" "}{end}'; echo " (rỗng = OK)"
done

# 4. cart hết dual-write, vẫn trỏ ElastiCache
kubectl -n $NS get deploy cart -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}' | grep -iE "VALKEY"

# 5. checkout rollout khoẻ (canary xong)
kubectl -n $NS get rollout checkout-rollout -o jsonpath='phase={.status.phase} ready={.status.readyReplicas}/{.status.replicas}{"\n"}'

# 6. otel-collector vẫn chạy (đã gỡ kafkametrics — bỏ sót pipeline sẽ làm nó chết)
kubectl -n $NS get pods | grep otel-collector

# 7. Pipeline đơn hàng còn thông: MSK LAG=0 (pod CLI trong cluster — xem runbook mandate-08 §0)
```

**Tiêu chí xanh:** không pod nào NotReady · 4 workload hết initContainer · checkout Rollout `Healthy` ·
otel-collector Running · MSK LAG=0.

---

## 6. Nếu có sự cố

| Triệu chứng | Xử lý |
|---|---|
| Pod kẹt `Init:0/1` | Còn sót initContainer trỏ store cũ → kiểm tra mục 3 checklist đầu tiên |
| otel-collector CrashLoop | Config sai (thiếu/thừa receiver trong pipeline) → revert PR #307 phần otel |
| checkout canary fail analysis | `kubectl argo rollouts abort checkout-rollout` → về revision stable |
| Sửa tay của CDO01 bị mất | Do `selfHeal` — commit vào git rồi sync lại (xem cảnh báo mục 2) |
| Cần dừng gấp | Tắt lại auto-sync: `kubectl -n argocd patch application techx-corp --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'` |

---

## 7. Sau khi bật thành công → mới tới §8

Chỉ khi **tất cả tiêu chí xanh ở mục 5** mới mở PR §8 (tắt 3 component `postgresql`/`valkey-cart`/`kafka`).
Xoá store cũ **trước khi** initContainer được gỡ khỏi cluster = **cart + checkout chết ngay**.

Xem [biên bản nghiệm thu Mandate #8](../mandates/mandate-08/mandate-08-nghiem-thu.md) mục H (thứ tự 6 bước).

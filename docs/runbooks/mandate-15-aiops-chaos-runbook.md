# Runbook — Bơm lỗi thật để chấm AIOps engine (Mandate #15)

**Cho:** AIO02 · **Hạ tầng do:** CDO02 · **Cập nhật:** 24/07/2026

Bộ 4 kịch bản bơm lỗi thật lên cụm `techx-corp-tf3`. Toàn bộ đã chạy nháp và kiểm chứng —
số đo thật ghi kèm từng kịch bản.

---

## 0. Những điều cần biết trước

**Không dùng flagd.** Flag (`paymentFailure`…) do BTC điều khiển tập trung, TF chỉ đọc
được. Đổi nguồn flag là disqualify cả TF. Bộ này dùng **Chaos Mesh**, bơm ở tầng
mạng/cgroup, không chạm đường đọc flag — nên AIO02 chủ động chạy được, không cần mentor.

**Lỗi tự hết.** Mỗi kịch bản có `duration` (10 phút). Hết giờ Chaos Mesh tự gỡ, kể cả khi
không ai nhớ xoá.

**Kịch bản 1, 2, 4 phá SLO thật.** Báo trước CDO01 khung giờ chạy, nếu không sẽ có người
mở postmortem cho sự cố do chính mình tạo ra.

**Mốc t0 để tính lead-time** lấy từ `AllInjected`, **không phải** lúc bấm apply —
chaos-daemon mất vài giây mới bơm xong:

```bash
kubectl -n techx-tf3 get networkchaos <ten> -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].lastTransitionTime}{"\n"}'
```

---

## 1. Chuẩn bị (làm 1 lần, giữ suốt buổi)

**Tunnel SSM** — terminal riêng. Nó **tự đóng sau ~10–20 phút idle**, mở lại khi mất kết nối:

```bash
export AWS_PROFILE=techx-new; export MSYS_NO_PATHCONV=1; BASTION_ID=$(aws ec2 describe-instances --region ap-southeast-1 --filters "Name=tag:Name,Values=techx-corp-tf3-bastion" "Name=instance-state-name,Values=running" --query "Reservations[].Instances[].InstanceId" --output text); EKS_HOST=$(aws eks describe-cluster --name techx-corp-tf3 --region ap-southeast-1 --query "cluster.endpoint" --output text | sed 's~^https://~~'); aws ssm start-session --target "$BASTION_ID" --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters host="$EKS_HOST",portNumber="443",localPortNumber="8443" --region ap-southeast-1
```

> PowerShell không hiểu `export`. Dùng Git Bash, hoặc đổi sang `$env:AWS_PROFILE = "techx-new"`.

**Locust** — terminal riêng, cần cho kịch bản 3 và để đo p95:

```bash
export AWS_PROFILE=techx-new; kubectl -n techx-tf3 port-forward svc/load-generator 8089:8089
```

**Kiểm tra sạch trước khi bắt đầu:**

```bash
export AWS_PROFILE=techx-new; kubectl -n techx-tf3 get networkchaos,stresschaos,podchaos
```

---

## 2. Bốn kịch bản

Thứ tự khuyến nghị: **3 → 1 → 2 → 4** (rủi ro thấp trước). Nghỉ ~5 phút giữa các lượt cho
metrics lắng.

### Kịch bản 3 — "Không kêu oan" (không phá SLO)

Tăng tải 10×, error rate 0%. Đo engine có báo động giả khi QPS cao không.

```bash
curl -s -X POST http://localhost:8089/swarm -d 'user_count=100&spawn_rate=5'
```

Giữ **10 phút**, rồi về nền:

```bash
curl -s -X POST http://localhost:8089/swarm -d 'user_count=10&spawn_rate=5'
```

**Chỉ hợp lệ khi** error rate 0%, p95 < 1s, không pod nào restart. Hệ thống gãy thật thì
engine báo động là đúng — huỷ lượt, đừng chấm.

**Đạt:** False positives = 0.

---

### Kịch bản 1 — "Bắt đúng"

Làm chậm 5s đường `checkout → payment`. Đo root cause, blast radius, lead-time.

```bash
export AWS_PROFILE=techx-new; kubectl apply -f chaos/experiments/scenario-1-payment-latency.yaml
```

**Đạt:** engine chỉ đúng gốc là `payment` (KHÔNG phải checkout/frontend), liệt kê blast
radius gồm checkout.

**Kiểm tra giữa chừng** — payment phải **giữ `1/1 Ready`**:

```bash
export AWS_PROFILE=techx-new; kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=payment
```

Thấy `0/1` hoặc restart tăng → **dừng lượt, báo CDO02**. Nghĩa là delay đang rơi nhầm lên
payment thay vì lên đường gọi.

---

### Kịch bản 2 — "Không bị che"

Hai lỗi **cùng lúc**: sự cố thật ở `payment` (10 phút) + nhiễu vô hại ở `recommendation`
(5 phút, error rate vẫn 0). Đo engine có tách được 2 cụm, không để nhiễu che sự cố thật.

Apply **cả hai cùng lúc**:

```bash
export AWS_PROFILE=techx-new; kubectl apply -f chaos/experiments/scenario-2a-payment-real-issue.yaml -f chaos/experiments/scenario-2b-recommendation-noise.yaml
```

| Giai đoạn | Ý nghĩa |
|---|---|
| T+0 → T+5 | cả hai cùng anomaly → chấm **tách 2 cluster hay không** |
| T+5 → T+10 | nhiễu tắt, chỉ còn payment → chấm **không bỏ sót sau khi nhiễu tắt** |

**Đạt:** đúng **2** incident cluster (không phải 1 do gộp, không phải 3+ do vỡ vụn),
`payment` xếp mức nghiêm trọng cao hơn, và **không bỏ sót** `payment`.

`recommendation` và `payment` không có cạnh nối nhau trong đồ thị phụ thuộc — tách được
là bằng chứng engine dùng topology chứ không chỉ dùng cửa sổ thời gian.

---

### Kịch bản 4 — "Tự khắc phục thành công"

Kịch bản **duy nhất** chấm được *sau khi engine hành động thì sự cố hết*. Làm chậm đúng
**1 pod** payment; pod còn lại khoẻ.

```bash
export AWS_PROFILE=techx-new; kubectl apply -f chaos/experiments/scenario-4-capacity-shortage.yaml
```

**Số đo thật từ chạy nháp 24/07 (100 user):**

| Mốc | checkout p95 | checkout avg |
|---|---|---|
| Baseline | 120ms | 44ms |
| Sau khi bơm | **1600ms** | 1169ms |
| Sau `scale 2→4` | 2000ms ❌ | 1226ms |
| Sau `rollout restart` | 1100ms | 165ms |
| Ổn định | **87ms** ✅ | 57ms |

Suốt quá trình: cart/products giữ 12–24ms, payment `1/1 Ready`, 0 restart, fail_ratio 0.

**Đạt:** p95 sau hành động của engine **tụt hẳn** so với lúc nghẽn. Vì `duration` là 10
phút, nên p95 hồi ở khoảng t_action+2 phút (lúc chưa tới T+10) **chắc chắn là do hành động
của engine**, không thể nhầm với "tự hết do hết hạn".

---

## 3. Lệnh khắc phục cho engine

Engine (`deployment/aiops-engine`, SA `default` + `aiops-engine-role`) đã đủ quyền:
`deployments`, `deployments/scale`, `pods`. `AIOPS_SIMULATION_MODE=false` → thực thi thật.

### ✅ Đã kiểm chứng có tác dụng

```bash
kubectl -n techx-tf3 rollout restart deploy/payment
```

### ❌ ĐÃ KIỂM CHỨNG LÀ VÔ DỤNG — đừng dùng cho payment

```bash
kubectl -n techx-tf3 scale deploy/payment --replicas=4
```

Chạy nháp cho thấy scale **không cải thiện gì** (p95 vẫn ~2000ms). Lý do: `checkout` gọi
payment qua **gRPC với kết nối HTTP/2 dài hạn** — thêm pod mới không kéo được traffic sang,
client vẫn bám các pod cũ gồm cả pod hỏng. Chỉ `rollout restart` mới buộc client kết nối lại.

### ⚠️ Chưa kiểm chứng

```bash
kubectl -n techx-tf3 scale deploy/recommendation --replicas=3
```

Chưa test xem `recommendation` có dính vấn đề gRPC stickiness như payment không. Nếu cần
dùng thì báo CDO02 kiểm chứng trước.

### Lưu ý cú pháp

`checkout` là **Argo Rollout**, không phải Deployment — gõ `deploy/checkout` sẽ lỗi:

```bash
kubectl -n techx-tf3 rollout restart rollout/checkout-rollout
```

### 🚫 Không cấp cho engine lệnh xoá chaos object

Xoá `networkchaos`/`stresschaos` là **gỡ máy bơm lỗi**, không phải khắc phục hệ thống.
Engine sẽ "thắng" một cách vô nghĩa.

---

## 4. Giới hạn phải biết khi chấm

**Kịch bản 1 và 2 KHÔNG đo được "sự cố có hết không".** Delay nằm trên đường
`checkout → payment` và Chaos Mesh giữ nó tới hết `duration`, nên restart hay scale đều
không dập được — sự cố hết là do **hết giờ**. Ở 2 kịch bản này chỉ chấm:

- engine **chọn đúng** hành động
- engine **thực thi được** (qua màng lọc an toàn C6)

Muốn chấm *khắc phục thành công* thì dùng **kịch bản 4** — nó được thiết kế riêng cho việc đó.

---

## 5. Dừng khẩn cấp

```bash
export AWS_PROFILE=techx-new; kubectl -n techx-tf3 delete networkchaos,stresschaos,podchaos --all
```

Gỡ ngay, không cần restart pod. Experiment nằm ngoài GitOps nên `delete` **không bị ArgoCD
tạo lại** — đây là lý do chúng cố ý không đặt trong `gitops/`.

Trả trạng thái về nền sau buổi chạy:

```bash
export AWS_PROFILE=techx-new; kubectl -n techx-tf3 scale deploy/payment --replicas=2
```

```bash
curl -s -X POST http://localhost:8089/swarm -d 'user_count=10&spawn_rate=5'
```

---

## 6. Xem chart trên Grafana

**https://grafana.arthur-ngo.org** (SSO, không cần kubectl) → **Explore** → Prometheus.

Lỗi phía `payment` — nếu đường này phẳng ở 0 thì lỗi **không** đến từ payment tự từ chối
(tức không phải flag BTC):

```
sum by (span_name) (increase(traces_span_metrics_calls_total{service_name="payment",status_code="STATUS_CODE_ERROR"}[2m]))
```

Lỗi phía `checkout`:

```
sum by (span_name) (increase(traces_span_metrics_calls_total{service_name="checkout",status_code="STATUS_CODE_ERROR"}[2m]))
```

p95 độ trễ checkout — panel chính để chấm kịch bản 4:

```
histogram_quantile(0.95, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{service_name="checkout",span_name="oteldemo.CheckoutService/PlaceOrder"}[2m])))
```

Restart container — bằng chứng probe fail:

```
sum by (k8s_pod_name) (increase(k8s_container_restarts{k8s_namespace_name="techx-tf3"}[5m]))
```

---

## 7. Đính chính về sự cố 15:05–15:12 ngày 24/07

Sự cố payment khung giờ đó là **do CDO02 chủ động bơm để test**, **không phải BTC bơm flag**.
Bằng chứng:

- Span `charge` của `payment`: **0 lỗi suốt 2 giờ**. Nếu là flag `paymentFailure` thì chính
  payment phải sinh lỗi ở đây (flag làm `charge()` throw).
- Lỗi chỉ xuất hiện **phía checkout khi gọi payment**, đúng khung 15:07–15:12.
- Flag `paymentFailure` và `paymentUnreachable` đều `off`.

Cơ chế thật: delay 5s làm probe kubelet tới payment timeout (probe chỉ chờ 2s) → pod bị
NotReady và loại khỏi endpoint. **Chữ ký sự cố là mất-dịch-vụ, không phải độ-trễ** — lưu ý
khi viết phần phân tích. Đã sửa: delay giờ đặt trên đường `checkout → payment` nên payment
giữ Ready và sự cố đúng bản chất "chậm". Các lượt chạy sau sẽ khác lượt đó.

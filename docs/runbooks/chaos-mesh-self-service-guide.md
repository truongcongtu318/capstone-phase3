# Chaos Mesh — hướng dẫn tự chạy (cho AIO02)

**Mục đích:** tự viết và chạy experiment bơm lỗi lên cụm `techx-corp-tf3` để test AIOps
engine, không cần CDO02 mỗi lần. Operator đã cài sẵn; bạn chỉ viết file YAML và `kubectl apply`.

**Cập nhật:** 24/07/2026 · **Người dựng hạ tầng:** CDO02

---

## 0. Mô hình

Hai phần tách biệt:

| Phần | Ai lo | Trạng thái |
|---|---|---|
| **Operator** (controller + daemon) | CDO02 đã cài qua ArgoCD | chạy sẵn ở namespace `chaos-mesh` |
| **Experiment** (file YAML mô tả lỗi) | **AIO02 tự viết + apply** | không có gì cho tới khi bạn apply |

Bơm lỗi = `kubectl apply` một Custom Resource (CR). Gỡ lỗi = `kubectl delete` CR đó. Operator
đọc CR rồi sai `chaos-daemon` trên node đích bơm lỗi vào network/cgroup của pod.

**Vì sao không dùng flagd:** flag do BTC điều khiển tập trung, TF chỉ đọc; đổi nguồn flag là
**disqualify cả TF**. Chaos Mesh không chạm đường đọc flag.

---

## 1. Chuẩn bị mỗi phiên

### 1.1. Mở tunnel tới cluster

EKS API là private. Cần tunnel SSM (Git Bash):

```bash
export AWS_PROFILE=techx-new; export MSYS_NO_PATHCONV=1
BASTION_ID=$(aws ec2 describe-instances --region ap-southeast-1 \
  --filters "Name=tag:Name,Values=techx-corp-tf3-bastion" "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" --output text)
EKS_HOST=$(aws eks describe-cluster --name techx-corp-tf3 --region ap-southeast-1 \
  --query "cluster.endpoint" --output text | sed 's~^https://~~')
aws ssm start-session --target "$BASTION_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host="$EKS_HOST",portNumber="443",localPortNumber="8443" --region ap-southeast-1
```

> **Tunnel tự đóng sau ~10–20 phút idle.** Đang chạy experiment mà `kubectl` báo
> `connection refused` / `TLS handshake timeout` là tunnel chết — mở lại. Bastion hay đông
> phiên nên handshake đôi lúc chậm vài chục giây, thử lại là được.
>
> `export` là cú pháp Bash. PowerShell dùng `$env:AWS_PROFILE = "techx-new"`.

### 1.2. Kiểm tra operator khoẻ

```bash
export AWS_PROFILE=techx-new; kubectl -n chaos-mesh get pod -o wide
```

Phải thấy **`chaos-controller-manager` ×2 Running** và **`chaos-daemon` chạy trên MỌI node**
(DaemonSet). Đếm cho khớp:

```bash
kubectl -n chaos-mesh get pod -l app.kubernetes.io/component=chaos-daemon --no-headers | wc -l
kubectl get nodes --no-headers | wc -l
```

**Hai số phải bằng nhau.** Thiếu daemon trên node nào thì pod đích nằm trên node đó sẽ
**không bị bơm lỗi mà không báo gì** — kiểu hỏng khó phát hiện nhất. Lệch số → báo CDO02.

### 1.3. Kiểm tra không có experiment cũ còn sót

```bash
kubectl -n techx-tf3 get networkchaos,stresschaos,podchaos
```

---

## 2. Quy trình chuẩn (bắt buộc theo đủ 5 bước)

```
① Viết YAML  →  ② apply  →  ③ verify AllInjected  →  ④ VERIFY LỖI ĂN THẬT  →  ⑤ delete
```

**Bước ④ là bước hay bị bỏ, và là bước quan trọng nhất.** `AllInjected: True` chỉ nghĩa là
Chaos Mesh đã *gắn* luật, KHÔNG bảo đảm traffic thật bị ảnh hưởng. Đã có trường hợp
`AllInjected: True` mà độ trễ không hề tác động (xem §6). **Luôn đo bằng số thật.**

### Bước ② apply

```bash
kubectl apply -f <file>.yaml
```

### Bước ③ verify + lấy mốc t0

```bash
kubectl -n techx-tf3 get networkchaos <ten> -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}'
```

`AllInjected=True` là đã gắn. **Lead-time tính từ mốc này, KHÔNG phải lúc bấm apply:**

```bash
kubectl -n techx-tf3 get networkchaos <ten> \
  -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].lastTransitionTime}{"\n"}'
```

Xem đúng pod nào bị bơm:

```bash
kubectl -n techx-tf3 get networkchaos <ten> -o jsonpath='{range .status.experiment.containerRecords[*]}{.id}{" -> "}{.phase}{"\n"}{end}'
```

### Bước ④ verify lỗi ăn thật — xem §5.

### Bước ⑤ delete

```bash
kubectl delete -f <file>.yaml
```

(Hoặc để `duration` hết giờ, Chaos Mesh tự gỡ.)

---

## 3. Ba loại lỗi + template chép được ngay

Đổi `app.kubernetes.io/name: <service>` theo bảng §4. Mọi CR đặt trong `namespace: techx-tf3`.

### 3.1. NetworkChaos — trễ / mất gói / ngắt kết nối

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: my-latency
  namespace: techx-tf3
spec:
  action: delay          # delay | loss | duplicate | corrupt | partition | bandwidth
  mode: all              # all | one | fixed | fixed-percent | random-max-percent
  # value: "1"           # số pod, dùng khi mode: fixed / fixed-percent
  duration: 10m          # BẮT BUỘC giữ — hết giờ tự gỡ dù quên delete
  selector:
    namespaces: [techx-tf3]
    labelSelectors:
      app.kubernetes.io/name: payment
  delay:
    latency: "1s"        # ĐỌC §6 trước khi đặt > probe timeout
    jitter: "100ms"
    correlation: "50"
```

`action: loss` thì thay khối `delay:` bằng `loss: { loss: "50", correlation: "50" }`.

### 3.2. StressChaos — ép CPU / RAM

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: my-cpu-stress
  namespace: techx-tf3
spec:
  mode: all
  duration: 5m
  selector:
    namespaces: [techx-tf3]
    labelSelectors:
      app.kubernetes.io/name: recommendation
  containerNames: [recommendation]   # PHẢI khớp tên container (= tên service)
  stressors:
    cpu:
      workers: 1         # số luồng
      load: 20           # % mỗi luồng. 20 ≈ 0.2 core. Xem §6 về giới hạn.
```

### 3.3. PodChaos — giết / treo pod

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: my-pod-kill
  namespace: techx-tf3
spec:
  action: pod-kill       # pod-kill | pod-failure | container-kill
  mode: one
  duration: 5m           # với pod-failure
  selector:
    namespaces: [techx-tf3]
    labelSelectors:
      app.kubernetes.io/name: payment
```

**Enum đã kiểm chứng với chart 2.8.3:**
- NetworkChaos `action`: `netem, delay, loss, duplicate, corrupt, partition, bandwidth`
- PodChaos `action`: `pod-kill, pod-failure, container-kill`
- `mode` (cả 3): `one, all, fixed, fixed-percent, random-max-percent` (fixed/percent cần `value`)

---

## 4. Bảng service + probe timeout (đọc kỹ cột probe)

Nhắm service bằng `app.kubernetes.io/name: <label>`. Cột probe timeout quyết định delay tối
đa an toàn — xem §6.

| label (`app.kubernetes.io/name`) | kind | replicas | readiness | liveness | gRPC? |
|---|---|---|---|---|---|
| payment | Deployment | 2 | tcp / 2s | tcp / 3s | bị checkout gọi qua gRPC |
| checkout | **Rollout** | 2 | grpc / 2s | tcp / 2s | ✅ |
| cart | Deployment | 2 | tcp / 2s | tcp / 3s | |
| currency | Deployment | 2 | tcp / 2s | tcp / 3s | |
| frontend | Deployment | 2 | tcp / 2s | tcp / 3s | |
| frontend-proxy | Deployment | 2 | tcp / 2s | tcp / 3s | |
| product-catalog | Deployment | 2 | grpc / 2s | tcp / 2s | ✅ |
| product-reviews | Deployment | 2 | grpc / 2s | tcp / 2s | ✅ |
| recommendation | Deployment | 1 | grpc / 2s | tcp / 2s | ✅ |
| quote | Deployment | 2 | tcp / 2s | tcp / 3s | |
| shipping | Deployment | 2 | tcp / 2s | tcp / 3s | |
| ad | Deployment | 1 | tcp / 2s | tcp / 3s | |
| email / image-provider / llm | Deployment | 1 | tcp / 2s | tcp / 3s | |
| accounting / fraud-detection | Deployment | 1 | (không probe) | (không probe) | |

> **`checkout` là Argo Rollout, không phải Deployment.** Selector chaos vẫn dùng
> `app.kubernetes.io/name: checkout` bình thường. Nhưng lệnh remediation phải là
> `rollout restart rollout/checkout-rollout`, không phải `deploy/checkout`.

---

## 5. Bước ④ — verify lỗi ăn thật (đừng bỏ)

### 5.1. Đo bằng Locust (nhanh nhất)

Terminal riêng:

```bash
export AWS_PROFILE=techx-new; kubectl -n techx-tf3 port-forward svc/load-generator 8089:8089
```

Reset rồi đọc số sau ~60s:

```bash
curl -s -X POST http://localhost:8089/stats/reset
curl -s http://localhost:8089/stats/requests | python -m json.tool | grep -A3 checkout
```

Tăng tải để có đủ mẫu khi cần:

```bash
curl -s -X POST http://localhost:8089/swarm -d 'user_count=100&spawn_rate=20'
```

**Nếu số đo giống baseline → lỗi KHÔNG ăn, dù `AllInjected: True`.** Đừng chấm, đi sang §6.

### 5.2. Khi nghi ngờ — xem luật tc thật Chaos Mesh áp

```bash
kubectl -n techx-tf3 get podnetworkchaos -o yaml | grep -A20 "tcs:"
```

Nếu `ipsets` rỗng hoặc `cidrs` không khớp IP pod đích thì filter sai.

### 5.3. Grafana (SSO, không cần kubectl): https://grafana.arthur-ngo.org → Explore → Prometheus

```
# p95 độ trễ 1 service
histogram_quantile(0.95, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{service_name="checkout",span_name="oteldemo.CheckoutService/PlaceOrder"}[2m])))

# lỗi theo span
sum by (span_name) (increase(traces_span_metrics_calls_total{service_name="payment",status_code="STATUS_CODE_ERROR"}[2m]))

# restart container
sum by (k8s_pod_name) (increase(k8s_container_restarts{k8s_namespace_name="techx-tf3"}[5m]))
```

---

## 6. Bài học đã trả giá — ĐỌC TRƯỚC KHI VIẾT SCENARIO

Những điều dưới đây phát hiện qua chạy thật, không có trong doc Chaos Mesh:

### 6.1. Delay > probe timeout ⇒ pod CHẾT, không phải chậm

netem làm chậm **mọi** gói vào pod, kể cả probe của kubelet. Đặt `latency: 5s` lên `payment`
(readiness timeout 2s, liveness 3s) → probe fail → pod bị loại khỏi endpoint + restart liên
tục. Sự cố trượt từ **"chậm"** thành **"mất dịch vụ"** — chữ ký hoàn toàn khác, engine chấm
theo latency sẽ thấy sai.

- Muốn **chữ ký độ-trễ** (pod vẫn sống): đặt `latency` **nhỏ hơn readiness timeout** của
  service đó (bảng §4). Payment: ≤ 1.5s. `latency: 1s` đo được checkout p95 120→1600ms mà
  payment vẫn `1/1 Ready`.
- Muốn **chữ ký mất-dịch-vụ**: cứ đặt lớn (5s), chấp nhận pod restart.

### 6.2. `AllInjected: True` KHÔNG bảo đảm lỗi ăn

Quan sát thực tế trên VPC CNI của cụm này: NetworkChaos với `direction: to` + khối `target:`
(lọc theo pod đích) báo `AllInjected: True`, ipset điền đúng IP, **nhưng traffic không hề bị
chậm** — checkout p95 giữ nguyên. Bơm **trực tiếp lên pod cần làm chậm** (selector trỏ thẳng
service đó, không dùng `direction`/`target`) thì ăn ngay.

→ Khuyến nghị: **bơm trực tiếp lên service muốn tác động.** Luôn làm bước ④ để xác nhận.

### 6.3. StressChaos CPU yếu với service ít dùng CPU ở tải thấp

Ở ~20 rps, `payment` (limit 300m) tiêu rất ít CPU nên bóp `load: 60` vẫn thừa sức phục vụ —
checkout p95 chỉ nhích 120→150ms. Đẩy tải lên 300 user thì p95 lên nhưng **mọi service cũng
chậm theo** → mất tín hiệu "service X là gốc". Muốn nghẽn 1 service rõ mà sạch, dùng
**NetworkChaos delay lên 1 pha của service đó** thay vì StressChaos.

### 6.4. Làm nghẽn 1 phần: `mode: fixed` + `value: "1"`

Chậm đúng 1 pod (service còn pod khoẻ để so sánh) — hữu ích khi test remediation: chỉ 1/2 pod
chậm → checkout p95 vọt, scale/restart lên thì tỉ lệ pod hỏng giảm → p95 tụt THẬT.

### 6.5. `scale` KHÔNG khắc phục được service gọi qua gRPC — phải `rollout restart`

Đo thật: làm chậm 1 pod payment → `scale deploy/payment 2→4` **không cải thiện** (p95 vẫn
~2000ms). `checkout` giữ kết nối HTTP/2 dài hạn tới payment, pod mới không nhận traffic.
**`rollout restart deploy/payment`** buộc client kết nối lại → p95 về 87ms.

→ Với service gRPC (cột "gRPC?" ở §4), remediation đúng là **`rollout restart`**, không phải
`scale`. Chưa kiểm chứng service HTTP thuần — đo trước khi kết luận.

---

## 7. Dừng khẩn cấp

Xoá sạch mọi lỗi ngay (dán sẵn tab riêng):

```bash
export AWS_PROFILE=techx-new
kubectl -n techx-tf3 delete networkchaos,stresschaos,podchaos --all
```

Gỡ trong vài giây, không cần restart pod. Experiment **không nằm trong GitOps** nên `delete`
không bị ArgoCD tạo lại. Ngoài ra mỗi CR có `duration` — hết giờ tự gỡ dù không ai delete.
**Luôn để `duration`**, đừng bỏ.

---

## 8. Ranh giới an toàn — phải tuân

- **Chỉ bơm được vào namespace `techx-tf3`.** Operator cấu hình `targetNamespace: techx-tf3`;
  gõ namespace khác trong CR cũng không có tác dụng. Đừng cố lách.
- **KHÔNG đụng flagd** (selector, delete, đổi token/URI) — disqualify cả TF.
- **Lỗi lên payment/checkout/cart phá SLO thật** (đây là cụm sống, có SLO chấm điểm). **Báo
  CDO01 + CDO02 trước** khung giờ chạy, nếu không sẽ bị mở postmortem cho sự cố tự tạo.
- Sau mỗi buổi: xoá hết chaos, trả replica/tải về nền, xác nhận service `Ready` lại.
- Chạy trong giờ ít traffic khi có thể.

---

## 9. Tham chiếu nhanh

```bash
# đang bơm gì
kubectl -n techx-tf3 get networkchaos,stresschaos,podchaos -o wide
# chi tiết 1 experiment
kubectl -n techx-tf3 describe networkchaos <ten>
# pod đích còn Ready không
kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=<service>
# dừng tất cả
kubectl -n techx-tf3 delete networkchaos,stresschaos,podchaos --all
```

Cần thêm loại lỗi ngoài 3 cái trên (HTTPChaos, IOChaos, DNSChaos, TimeChaos…), hoặc lệch
số daemon/node, hoặc muốn nới `targetNamespace` — báo CDO02. Đừng tự sửa manifest operator
(nó do ArgoCD quản, sửa tay sẽ bị revert).

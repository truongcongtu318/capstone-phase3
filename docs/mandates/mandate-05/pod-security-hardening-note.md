# Ghi chú Pod Security hardening

**Ngày:** 14/07/2026  
**Phạm vi:** P1 - Pod Security Standards + `securityContext` hardening  
**Branch:** `hieu`  
**Commit liên quan:** `ba58acb security: add pod security baseline hardening`

## Đã làm gì

### 1. Bật Pod Security Admission ở chế độ audit/warn

Đã thêm file `gitops/infrastructure/namespace-techx-tf3.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: techx-tf3
  labels:
    pod-security.kubernetes.io/audit: baseline
    pod-security.kubernetes.io/warn: baseline
```

Ý nghĩa: namespace `techx-tf3` bắt đầu được Kubernetes kiểm tra theo chuẩn Pod Security Admission mức `baseline`, nhưng mới ở chế độ cảnh báo và audit.

Cố ý **chưa bật**:

```yaml
pod-security.kubernetes.io/enforce: baseline
pod-security.kubernetes.io/enforce: restricted
```

Lý do: nếu bật enforce ngay, một workload đang chạy ổn nhưng chưa đạt chuẩn có thể bị chặn khi rollout/apply, gây rủi ro downtime.

## 2. Thêm baseline `securityContext` cho nhóm service ít rủi ro

Đã sửa file `phase3 - information/techx-corp-chart/values.yaml`.

Các service đã được harden mạnh hơn:

- `frontend`
- `checkout`
- `payment`
- `shipping`

Các setting đã thêm:

```yaml
securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  readOnlyRootFilesystem: true
podSecurityContext:
  seccompProfile:
    type: RuntimeDefault
```

Một số service có thêm `runAsUser` / `runAsGroup` vì image của chúng đã là non-root hoặc có user rõ ràng.

### 3. Harden một phần cho `cart`

Với `cart`, hiện chỉ thêm:

```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
podSecurityContext:
  seccompProfile:
    type: RuntimeDefault
```

Chưa ép `cart` chạy `runAsNonRoot` hoặc `readOnlyRootFilesystem` vì Dockerfile đang dùng Alpine runtime image và chưa có `USER` rõ ràng. Cần kiểm tra hoặc sửa Dockerfile trước khi siết tiếp.

## Vì sao làm như vậy

Task yêu cầu bật Pod Security Admission ở mức `baseline`, chế độ `audit/warn` trước, **không bật enforce/restricted ngay**.

Cách làm này cũng để tránh xung đột với các mandate hiện tại:

- **Mandate #3:** bảo trì/rolling update không được làm rớt luồng browse -> cart -> checkout.
- **Mandate #5:** runtime hardening phải tiến tới chặn cấu hình nguy hiểm, nhưng cần đi từ audit sang enforce có kiểm soát để không chặn nhầm workload thật.

Vì vậy thay đổi này là phase an toàn đầu tiên:

- Bật cảnh báo bằng PSA audit/warn.
- Harden trước các service ít rủi ro nhất.
- Chưa siết mạnh các service chạy root, stateful hoặc observability khi chưa kiểm tra write path.

## Exception hiện tại

Các exception dưới đây là có chủ đích, không phải bỏ sót:

| Workload | Lý do |
|---|---|
| `currency` | Image Alpine hiện chưa có `USER` rõ ràng; ép `runAsNonRoot` có thể làm container không start. |
| `llm` | Python Alpine image chưa có `USER`; cần harden Dockerfile trước. |
| `product-reviews` | Python Alpine image chưa có `USER`; lại nằm trên luồng review/AI nên không nên rollout rủi ro. |
| `cart` | Mới harden một phần; cần xác minh runtime user/write path trước khi bật full. |
| `postgresql`, `kafka`, `valkey-cart` | Stateful components cần ghi data/log/tmp; phải kiểm tra path ghi trước khi bật read-only root FS. |
| Grafana/Jaeger/Prometheus/OpenSearch/OTel Collector | Observability tools có thể cần ghi cache/data/plugin/temp; phải kiểm từng subchart trước khi bật read-only root FS. |

## Việc này chưa hoàn tất điều gì

Thay đổi này **chưa hoàn tất toàn bộ Mandate #5**.

Mandate #5 còn yêu cầu admission policy-as-code để reject manifest nguy hiểm ngay khi apply, ví dụ:

- container chạy root,
- image tag `latest`,
- thiếu CPU/memory requests hoặc limits,
- thiếu baseline security context.

Phần đó nên làm ở phase sau, bằng policy engine hoặc admission policy native của Kubernetes, sau khi các exception hiện tại được sửa hoặc được allowlist rõ ràng.

## Cách verify sau khi deploy

Kiểm tra label namespace:

```sh
kubectl get ns techx-tf3 --show-labels
```

Kỳ vọng thấy:

```text
pod-security.kubernetes.io/audit=baseline
pod-security.kubernetes.io/warn=baseline
```

Kiểm tra rollout:

```sh
kubectl -n techx-tf3 rollout status deploy/frontend
kubectl -n techx-tf3 rollout status deploy/checkout
kubectl -n techx-tf3 rollout status deploy/payment
kubectl -n techx-tf3 rollout status deploy/shipping
kubectl -n techx-tf3 rollout status deploy/cart
kubectl -n techx-tf3 get pods
kubectl -n techx-tf3 get events --sort-by=.lastTimestamp
```

Kiểm tra `securityContext` thực tế sau khi apply:

```sh
kubectl -n techx-tf3 get deploy frontend checkout payment shipping cart -o yaml
```

Cần thấy các field:

- `allowPrivilegeEscalation: false`
- `capabilities.drop: ["ALL"]`
- `seccompProfile.type: RuntimeDefault`
- `runAsNonRoot: true` ở service đã bật
- `readOnlyRootFilesystem: true` ở service đã bật

## Rollback nếu có lỗi

Nếu service bị `CrashLoopBackOff`, `CreateContainerConfigError`, hoặc log báo lỗi `read-only file system`, rollback ngay:

```sh
helm rollback techx-corp <previous-revision> -n techx-tf3
```

Nếu đi theo GitOps, nên revert commit rồi để ArgoCD sync lại:

```sh
git revert ba58acb
```

Không tiếp tục harden thêm service khác cho đến khi luồng browse/cart/checkout ổn định trở lại.

## Kết quả kiểm tra thực tế sau khi ArgoCD sync

Thời điểm kiểm tra: 14/07/2026.

### 1. PSA namespace

Lệnh kiểm tra:

```sh
kubectl get ns techx-tf3 --show-labels
```

Kết quả:

```text
techx-tf3 Active ... pod-security.kubernetes.io/audit=baseline,pod-security.kubernetes.io/warn=baseline
```

Kết luận: đạt. Namespace đã có PSA `audit/warn` mức `baseline`, và chưa bật `enforce`.

### 2. Rollout nhóm service đã harden

Lệnh kiểm tra:

```sh
kubectl -n techx-tf3 rollout status deploy/frontend
kubectl -n techx-tf3 rollout status deploy/checkout
kubectl -n techx-tf3 rollout status deploy/cart
kubectl -n techx-tf3 rollout status deploy/payment
kubectl -n techx-tf3 rollout status deploy/shipping
```

Kết quả:

```text
deployment "frontend" successfully rolled out
deployment "checkout" successfully rolled out
deployment "cart" successfully rolled out
deployment "payment" successfully rolled out
deployment "shipping" successfully rolled out
```

Kết luận: đạt. Nhóm service critical/low-risk đã rollout xong, không bị kẹt rollout.

### 3. Trạng thái pod

Lệnh kiểm tra:

```sh
kubectl -n techx-tf3 get pods --field-selector=status.phase!=Running
```

Kết quả:

```text
No resources found in techx-tf3 namespace.
```

Kết luận: đạt tại thời điểm kiểm tra. Không có pod nào đang ở trạng thái non-running.

Lưu ý: `kubectl get events` có ghi nhận một số warning gần thời điểm kiểm tra, như readiness probe `NOT_SERVING` ở vài service và một lần `BackOff` của `valkey-cart`. Tuy nhiên tại thời điểm tổng hợp, toàn bộ pod đang Running và nhóm service đã harden đã rollout thành công.

### 4. Storefront

Lệnh kiểm tra:

```sh
curl -I https://d2tn71186d7ilz.cloudfront.net/
```

Kết quả:

```text
HTTP/1.1 200 OK
```

Kết luận: đạt. Storefront vẫn truy cập được sau rollout.

### 5. Tỷ lệ container đạt baseline securityContext

Tiêu chí kiểm:

- `allowPrivilegeEscalation=false`
- `capabilities.drop=["ALL"]`
- `seccompProfile.type=RuntimeDefault`

Kết quả đếm từ toàn bộ Deployment containers trong namespace `techx-tf3`:

```text
TOTAL_CONTAINERS=28
BASELINE_SECURITY_CONTEXT_OK=5
PERCENT=17.9%
```

Các container đạt:

- `frontend`
- `checkout`
- `cart`
- `payment`
- `shipping`

Kết luận: chưa đạt nếu áp tiêu chí `>=80% app containers`. Nguyên nhân không phải do pod chưa Running; tất cả pod đang Running. Nguyên nhân là phase này mới harden nhóm low-risk trước, còn nhiều workload chưa đủ `securityContext` baseline.

Các nhóm chưa harden đầy đủ gồm:

- Image chưa có non-root user rõ ràng: `currency`, `llm`, `product-reviews`.
- Stateful cần kiểm write path: `postgresql`, `kafka`, `valkey-cart`.
- Observability có thể cần ghi cache/data/plugin/temp: Grafana, Jaeger, Prometheus, OpenSearch, OTel Collector.
- Một số service stateless khác chưa nằm trong batch hardening đầu tiên.

### Tổng kết kiểm tra

- PSA audit/warn baseline: đạt.
- Rollout critical services: đạt.
- Không có pod non-running tại thời điểm kiểm tra: đạt.
- Storefront còn hoạt động: đạt.
- Danh sách exception: có.
- Mốc `>=80% container app` có đủ baseline securityContext: chưa đạt, hiện là `5/28 = 17.9%`.

Vì vậy thay đổi hiện tại nên được xem là **Phase 1 hardening an toàn**, chưa phải hoàn tất toàn bộ runtime hardening.

---

## Phase 2: Kyverno Admission Controller & GitOps Enforcement

**Ngày:** 14/07/2026
**Phạm vi:** Bổ sung Policy Engine as Code (Kyverno) theo chuẩn T6/PM-92 và Mandate #5.

### 1. Đã làm gì

Để hoàn thiện yêu cầu ngăn chặn tự động từ Mandate #5 mà không làm gián đoạn hệ thống, tôi đã triển khai Kyverno thông qua kiến trúc GitOps:

- **Cài đặt Kyverno Core:** Tạo file `gitops/apps/kyverno-app.yaml` định nghĩa ArgoCD Application triển khai Kyverno (kèm tính năng ServerSideApply để sửa lỗi CRD lớn của Helm).
- **Cấu hình Policy-as-Code:** 
  - Tạo `baseline-security-context.yaml` để Audit bắt buộc `allowPrivilegeEscalation: false`, rớt quyền `capabilities.drop: ALL`, và `seccompProfile: RuntimeDefault`. Đã áp dụng `exclude` (whitelist) cho 3 service legacy: `currency`, `llm`, `product-reviews`.
  - Tạo `require-resource-requests.yaml` để Audit bắt buộc khai báo CPU/Memory Requests và Memory Limits cho toàn bộ container.
  - Quản lý các Policy bằng `gitops/apps/kyverno-policies-app.yaml`.

### 2. Trạng thái hiện tại (Audit Mode)

- Toàn bộ các Policies đang được chạy ở chế độ **Audit** (`validationFailureAction: Audit`). Do đó, không có bất kỳ workload nào bị chặn (Reject) trong quá trình rollout ở hiện tại, đảm bảo an toàn 100% cho production.
- Hệ thống Kyverno Background Controller liên tục quét các resource cũ và tạo ra các **PolicyReports**.

### 3. Kết quả Audit & Tính đúng đắn của Exception

Kết quả trích xuất thực tế từ PolicyReport xác nhận cơ chế Exception hoạt động đúng như thiết kế ở Phase 1:

- **Nhóm Low-Risk (đã harden ở Phase 1):** Không phát sinh lỗi liên quan đến SecurityContext, chỉ thiếu khai báo Limits/Requests.
- **Nhóm Legacy (được exclude):** Các Pod như `llm-7fb4cdbdfd-kcjfj` hay `currency` **KHÔNG** bị tính là vi phạm SecurityContext (không có 3 lỗi drop-all-capabilities, privilege-escalation, seccomp). Bằng chứng là PolicyReport của chúng chỉ báo `failures: 2` (thuộc về lỗi Resource Requests).
- **Nhóm Stateful/Observability (chưa exclude, chưa harden):** Bị Kyverno đánh giá là Fail toàn tập với cả 3 quy tắc SecurityContext (ví dụ: `jaeger`, `opensearch-0`, `frontend-proxy`).

### 4. Tiêu chí chuyển sang Enforce (Phase 3)

Để hoàn tất Mandate #5 và kích hoạt tính năng **Reject** manifest rác, cần đạt các tiêu chí sau:

1. Đội ngũ DEV/SRE xử lý dứt điểm các lỗi trong PolicyReport hiện tại (thêm resource requests/limits cho mọi dịch vụ, và fix security context cho nhóm Stateful/Observability).
2. Khi `kubectl get polr -n techx-tf3` cho ra số lượng Fail = 0 (ngoại trừ các exception hợp lệ).
3. Sửa cờ `validationFailureAction: Audit` thành `Enforce` trong file GitOps policy và push lên repo. ArgoCD sẽ lập tức biến Kyverno thành lớp khiên bảo vệ chủ động.

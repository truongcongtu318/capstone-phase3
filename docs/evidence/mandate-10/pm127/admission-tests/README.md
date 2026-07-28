# PM-127 — Bộ test admission (chạy trong `techx-tf3`)

Chứng minh yêu cầu #2 của Directive #10: *"Thử deploy một image chưa ký / chưa scan → admission phải từ chối"*.

---

## ⚠️ Bắt buộc chạy trong namespace `techx-tf3`

Cả hai ClusterPolicy đều `match.any[].resources.namespaces: [techx-tf3]`.

**Chạy ở namespace khác = pass giả.** Pod sẽ được tạo bình thường vì policy không áp — rồi kết luận nhầm là "không bị chặn". Đây là cái bẫy dễ mắc nhất khi nghiệm thu.

Manifest trong thư mục này đều ghi cứng `namespace: techx-tf3`.

## ⚠️ `techx-tf3` có 3 tầng admission TRƯỚC Kyverno

Đây là chỗ dễ mất thời gian nhất. Pod phải qua được cả 3 tầng dưới thì Kyverno mới được chấm — không thì request bị từ chối vì lý do khác và **kết quả test vô nghĩa**.

| Tầng | Đòi gì | Nếu thiếu |
|---|---|---|
| PodSecurity `restricted` | `runAsNonRoot` · `runAsUser` · `seccompProfile` · `allowPrivilegeEscalation: false` · `capabilities.drop: [ALL]` | `violates PodSecurity "restricted"` |
| `mandate05-native-resource-requirements` | `requests` **và** `limits` cho **cả** cpu lẫn memory | `must explicitly define requests.cpu, requests.memory, limits.cpu, limits.memory` |
| `mandate05-native-image-reference` | Image có tag hoặc digest · **cấm `:latest`** · `techx-corp` **bắt buộc `@sha256`** | `mandate05-native-image-reference ... denied` |

**Hệ quả với thiết kế test:** hai tình huống không thể dùng để test Kyverno vì VAP chặn trước —

- `techx-corp:<tag>` không digest → VAP bắt
- bất kỳ `:latest` nào → VAP bắt

Nên `deny-04` cố tình dùng `busybox:1.36` chứ **không** dùng `:latest`.

## ⚠️ Fixture phải thoả PodSecurity `restricted`

Namespace `techx-tf3` bật `pod-security.kubernetes.io/enforce=restricted`. PodSecurity là **admission plugin dựng sẵn của Kubernetes**, chạy độc lập với Kyverno.

Nếu pod thiếu `securityContext`, **PSA chặn trước** và Kyverno không kịp chấm. Lúc đó `deny-*` vẫn "lỗi" nhưng **sai lý do** — không chứng minh được gì về image policy; còn `allow-*` thì bị từ chối oan.

Đã xảy ra ở lần chạy đầu: 5/6 case bị PSA chặn, chỉ `deny-01` cho ra kết quả thật.

Mọi fixture nay đều đặt đủ: `runAsNonRoot` · `runAsUser: 10001` · `seccompProfile: RuntimeDefault` · `allowPrivilegeEscalation: false` · `capabilities.drop: [ALL]`.

**Cách nhận biết kết quả sai:** message nhắc `violates PodSecurity "restricted"` → PSA chặn, không phải Kyverno. Message hợp lệ phải nêu tên policy (`verify-first-party-signatures` hoặc `allow-approved-external-image-digests`).

## Các file này KHÔNG được ArgoCD quản lý

Chúng nằm dưới `docs/`, còn ArgoCD chỉ theo dõi `gitops/`. Nên không có nguy cơ bị sync nhầm vào cluster.

---

## Chạy thế nào

Mỗi file là một tình huống. Chạy bằng `--dry-run=server` để webhook admission **thật sự chấm** mà **không tạo object**:

```sh
kubectl apply --dry-run=server -f <file>
```

- **Case `deny-*`** → phải trả lỗi, và message phải nêu đúng lý do
- **Case `allow-*`** → phải trả `... created (server dry run)`

Muốn chứng minh "object không được tạo" theo đúng nghĩa đen thì bỏ `--dry-run=server`, apply thật rồi kiểm bằng `kubectl get pod <tên> -n techx-tf3` — phải `NotFound`.

---

## Danh sách case

| File | Policy | Kỳ vọng | Chứng minh điều gì |
|---|---|---|---|
| `deny-01-unsigned-first-party.yaml` | first-party | **DENY** | Image `techx-corp` thật trong ECR nhưng **chưa ký** — `cosign verify` trả `no signatures found` |
| `deny-02-first-party-bare-tag.yaml` | **native VAP**, không phải Kyverno | **DENY** | First-party pin bằng tag trần bị `mandate05-native-image-reference` chặn **trước** khi Kyverno chạy. Giữ lại làm bằng chứng hai tầng **chồng lấn** ở đây chứ không để hở |
| `deny-03-unapproved-external.yaml` | external | **DENY** | Image công khai ngoài catalog — đây là lỗ hổng nếu chỉ bật mỗi policy first-party |
| `deny-04-external-bare-tag.yaml` | external | **DENY** | Tag có thể bị trỏ lại ở upstream nên tag **không phải là pin**. Dùng `busybox:1.36`, **cố ý không dùng `:latest`** — `:latest` sẽ bị VAP chặn trước và test sai tầng |
| `deny-05-ephemeral-bypass.yaml` | external | **DENY** | `ephemeralContainers` không được thành đường lách (đúng loại đã bắt được `nicolaka/netshoot` bỏ quên trên pod `fraud-detection`) |
| `allow-01-valid-first-party.yaml` | first-party | **ACCEPT** | Image đã ký + có SBOM vẫn deploy được — chứng minh policy không chặn bừa |
| `allow-02-approved-external.yaml` | external | **ACCEPT** | External pin đúng digest trong catalog vẫn chạy được |

---

## Digest dùng trong test

| Mục đích | Digest | Ghi chú |
|---|---|---|
| First-party **chưa ký** | `sha256:5eb7fe61…` | Build `checkout` cũ (`01011a2-30186442291-checkout`, 26/07). Xác minh: `cosign verify` → `no signatures found`. Một trong **115** digest chưa ký còn trong ECR |
| First-party **đã ký + SBOM** | `sha256:5035d768…` | `quote`, build lại ở PR #502, provenance trỏ đúng commit gốc |
| External **đã duyệt** | `busybox@sha256:73aaf090…` | Có trong catalog |

## Dọn sau khi test

Nếu apply thật (không dùng dry-run):

```sh
kubectl delete pod -n techx-tf3 -l pm127-admission-test=true --ignore-not-found
```

Mọi pod test đều có label `pm127-admission-test: "true"`.

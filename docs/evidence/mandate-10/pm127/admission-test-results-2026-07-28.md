# PM-127 — Kết quả test admission (2026-07-28)

Chạy sau khi **cả hai** ClusterPolicy đã ở `Enforce/Ready=True` trên cluster.

```sh
for f in docs/evidence/mandate-10/pm127/admission-tests/*.yaml; do
  echo "======== $(basename "$f")"
  kubectl apply --dry-run=server -f "$f" 2>&1 | tail -3
done
```

`--dry-run=server` cho request đi qua **đầy đủ chuỗi admission** nhưng không ghi vào etcd — chấm thật, không tạo pod nào.

---

## Kết quả: 6/6 đúng kỳ vọng

| Case | Kết quả | Bị chặn bởi |
|---|---|---|
| `allow-01-valid-first-party` | ✅ **ACCEPT** | — |
| `allow-02-approved-external` | ✅ **ACCEPT** | — |
| `deny-01-unsigned-first-party` | ✅ **DENY** | `verify-first-party-signatures` |
| `deny-02-first-party-bare-tag` | ✅ **DENY** | `mandate05-native-image-reference` |
| `deny-03-unapproved-external` | ✅ **DENY** | `allow-approved-external-image-digests` |
| `deny-04-external-bare-tag` | ✅ **DENY** | `allow-approved-external-image-digests` |

---

## Output nguyên văn

### ✅ ACCEPT — policy không chặn bừa

```
======== allow-01-valid-first-party.yaml
pod/allow-01-valid-first-party created (server dry run)

======== allow-02-approved-external.yaml
pod/allow-02-approved-external created (server dry run)
```

Phần này **quan trọng ngang việc chặn đúng**. Một policy từ chối mọi thứ cũng "pass" hết case deny — hai case này chứng minh workload hợp lệ vẫn deploy được, tức **0 false-positive**.

### ✅ DENY — image first-party chưa ký

```
======== deny-01-unsigned-first-party.yaml
verify-first-party-signatures:
  verify-techx-main-workflow-signature: 'failed to verify image
    197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:5eb7fe61735c9176dd4d02b401b156c71151d13007824ab2e2c6dcfd81eec860:
    .attestors[0].entries[0].keyless: no signatures found'
```

**Đây là câu trả lời cho Directive #10 yêu cầu #2.**

Digest này là image `techx-corp` **thật đang nằm trong ECR** (một trong 115 digest chưa ký), không phải chuỗi bịa. Nên lỗi trả về chứng minh **kiểm chữ ký thất bại**, không phải "image không tồn tại".

### ✅ DENY — first-party pin bằng tag trần

```
======== deny-02-first-party-bare-tag.yaml
The pods "deny-02-first-party-bare-tag" is invalid: :
ValidatingAdmissionPolicy 'mandate05-native-image-reference' with binding
'mandate05-native-image-reference-techx-tf3' denied request:
Images from 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp
must use @sha256:<64 lowercase hex>.
```

Bị chặn bởi **native VAP**, không phải Kyverno — đúng như fixture đã ghi nhãn. Kyverno không bao giờ thấy request này.

Không phải thiếu sót: hai tầng **chồng lấn** ở đây thay vì để hở. Nói Kyverno chặn nó sẽ là sai sự thật.

### ✅ DENY — external ngoài catalog

```
======== deny-03-unapproved-external.yaml
allow-approved-external-image-digests:
  require-approved-external-image-digest: 'validation failure:
    External images must match the reviewed exact-digest catalog.'

======== deny-04-external-bare-tag.yaml
allow-approved-external-image-digests:
  require-approved-external-image-digest: 'validation failure:
    External images must match the reviewed exact-digest catalog.'
```

`deny-03` là image công khai pin digest nhưng ngoài catalog. **Đây chính là lỗ hổng nếu chỉ bật mỗi policy first-party** — không có vế này thì `nginx@sha256:…` chạy được trong `techx-tf3` và mệnh đề *"cluster chỉ chạy image đã ký"* sai.

`deny-04` dùng `busybox:1.36`, **cố ý không dùng `:latest`** — `:latest` bị native VAP chặn trước, fixture kiểu đó sẽ trông như chứng minh catalog rule trong khi thực ra chứng minh VAP.

---

## Ba lần chạy mới ra kết quả dùng được

| Lần | Kết quả | Nguyên nhân |
|---|---|---|
| 1 | 5/6 vô hiệu | Fixture thiếu `securityContext` → **PodSecurity** chặn trước |
| 2 | 5/6 vô hiệu | Thiếu `resources` → **`mandate05-native-resource-requirements`** chặn trước |
| 3 | **6/6 hợp lệ** | Đọc hết cả 3 tầng admission rồi mới viết lại |

Bài học: `techx-tf3` có **3 tầng admission trước Kyverno**. Vá từng cái một là chơi trò đập chuột — và tệ hơn, ở lần 1 và 2 các case `deny-*` **vẫn "lỗi"**, rất dễ đọc nhầm là test đã pass.

**Cách phân biệt:** message hợp lệ phải **nêu tên policy đang test**. Nếu nhắc `PodSecurity` hay `mandate05-native-resource-requirements` thì kết quả **bỏ**.

---

## Chốt lại

| DoD | |
|---|---|
| #2 — cả 2 policy `Enforce/Ready=True` | ✅ |
| #3 — image chưa ký bị từ chối, message rõ | ✅ `deny-01` |
| #4 — 0 false-positive trên workload hợp lệ | ✅ `allow-01`, `allow-02` |
| Directive #10 yêu cầu #2 | ✅ |

Không pod nào được tạo trong quá trình test (`--dry-run=server`).

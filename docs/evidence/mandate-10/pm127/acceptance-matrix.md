# PM-127 — Acceptance matrix

**Cập nhật:** 2026-07-28
**Directive #10** — Secure delivery pipeline

Cột *Bằng chứng* ghi thứ tự chạy lại được, không phải khẳng định suông.

---

## A. Definition of Done (Jira PM-127)

| # | DoD | Trạng thái | Bằng chứng |
|---|---|---|---|
| 1 | Mọi image tự build có SBOM, tra được theo digest **bằng 1 lệnh** | ✅ | `scripts/ci/get-sbom.sh <digest> --platform linux/amd64 --metadata` → CycloneDX, components > 0. **21/21** digest first-party. Wrapper tự chặn cosign sai version |
| 2 | `kubectl get clusterpolicy` cho **cả 2 policy**: `Enforce/Ready=True` | ✅ **2/2** | `allow-approved-external-image-digests` = `Enforce/True`; `verify-first-party-signatures` = `Enforce/True`. Cả hai **live trên cluster** |
| 3 | Deploy image chưa ký / sai identity → **bị từ chối**, message rõ | ✅ | **6/6 case đúng kỳ vọng** — [`admission-test-results-2026-07-28.md`](admission-test-results-2026-07-28.md). `deny-01`: image `techx-corp` thật chưa ký → `verify-first-party-signatures ... no signatures found` |
| 4 | **0 false-positive** trên PolicyReport cho image hợp lệ đang chạy sống | ✅ | 40 pod: first-party **30 pass / 0 fail**; external **0 bị chặn**. Vi phạm còn lại đều là **true positive trên resource đã chết** |

---

## B. Yêu cầu Directive #10

| # | Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|---|
| 1 | PR với CI đỏ → **chặn merge** | ✅ | PM-126: branch protection require `Secure delivery gate`, `required_approvals: 1`. PR #350/#351 bị `BLOCKED` thật |
| 2 | Deploy image chưa ký → **admission từ chối** | ✅ | Cả 2 policy `Enforce`; `deny-01` bị từ chối bởi `verify-first-party-signatures`, `deny-03`/`deny-04` bởi policy external. Workload hợp lệ vẫn được chấp nhận (`allow-01`, `allow-02`) |
| 3 | Chỉ vào pod đang chạy → **truy ngược full provenance** | ✅ | `provenance-walkthrough.md` — chuỗi đầy đủ cho pod `quote` |
| — | SBOM + provenance, ký cosign | ✅ | 21/21 digest có chữ ký keyless + CycloneDX 2 platform |
| — | Reference theo **digest**, cấm floating tag | ✅ | drift check `exit 0`: **11/11** external pin digest, khớp catalog từng ký tự |
| — | Actions pin commit SHA, base image pin digest | ✅ | `Immutable dependency pins` check pass mọi PR |
| — | Scan CVE/IaC/secret/SAST là **cổng chặn** | ✅ | Trivy pre-push + post-push; `Secure delivery gate` là required check |

---

## C. Chuỗi provenance (yêu cầu #3)

```
pod quote-79b77dd947-n6mrq
  └─ digest  sha256:5035d768…          imageID = spec.image, không qua tag
     └─ commit  947146d8…              lấy từ SBOM đã ký, không tra ngoài
        └─ PR #502  reviewer ThuyTrang9525
           └─ run 30334711133          Trivy pre-push + post-push pass
              └─ signer  build-push-ecr.yml@refs/heads/main   keyless
                 └─ SBOM  CycloneDX, 95 component, amd64 + arm64
```

Chi tiết + lệnh từng bước: [`provenance-walkthrough.md`](provenance-walkthrough.md)

---

## D. Phạm vi đã phủ

| Nhóm | Số lượng | Trạng thái |
|---|---|---|
| Digest first-party (chữ ký + SBOM) | **21** | ✅ verify bằng cosign v2.6.2, 0 fail |
| External pin digest + trong catalog | **11** | ✅ khớp chính xác từng ký tự |
| Image AIO02 (`tf-2-ai-engine` ×2, `shopping-copilot`) | **3** | ✅ pin digest + vào catalog (#529) |
| Pod đang chạy trong `techx-tf3` | **40** | ✅ không cái nào bị chặn |

---

## E. Non-regression (dưới 7A Enforce)

| Kiểm tra | Kết quả |
|---|---|
| Pod đang chạy | **40**, không có pod nào ngoài `Running`/`Completed` |
| Storefront (`frontend-proxy`) | 2/2 `Running` |
| `flagd` | `2/2 Running` — cơ chế đọc flag **không đổi** |
| Admission denial do policy | **0** |
| Kyverno controller | admission 3/3 · background 1/1 · reports 2/2 — đều `Running` |

### ⚠️ Cảnh báo `PolicyViolation` vẫn xuất hiện — và đó là đúng

Sau khi Enforce, event vẫn liên tục báo, ví dụ:

```
replicaset/accounting-5fcd9488db   no signatures found (sha256:8fc8a91f…)
replicaset/checkout-rollout-84b9cddbcd   no signatures found (sha256:993f61d6…)
```

**Không phải cụm đang hỏng.** Toàn bộ là ReplicaSet **đã chết** (`DESIRED=0`, 12-13 ngày tuổi) mà background scan vẫn quét. Deployment sống trỏ digest đã ký:

| Deployment | RS sống | Digest | |
|---|---|---|---|
| `accounting` | `accounting-796d8ffd88` 1/1 | `32aeb5e0…` | ✅ đã ký |
| `checkout-rollout` | `checkout-rollout-6c986b459` 2/2 | — | ✅ đã ký |

Enforce chặn ở **admission**, tức lúc tạo pod. ReplicaSet chết không tạo pod nào nên không có gì bị chặn.

Đây là **true positive trên resource chết** — cùng loại với mục F #4. Đừng đọc số violation thô rồi kết luận; **chỉ đo trên pod `Running`**.

---

## F. Những chỗ suýt kết luận sai — ghi lại để khỏi lặp

| Vấn đề | Vì sao nguy hiểm | Đã xử |
|---|---|---|
| **Cosign v3 báo SBOM missing** | Digest cũ còn OCI 1.1 referrers từ pipeline trước; v3 đọc referrers, thấy chữ ký cũ, kết luận thiếu CycloneDX — **false negative trông như bằng chứng hỏng** | `get-sbom.sh` chặn sai major version kèm hướng dẫn |
| **SBOM backfill ghi sai commit** | Bản đầu ghi commit **lúc backfill**, không phải commit build → truy vết dẫn tới commit không liên quan, hỏng đúng yêu cầu #3 | PR #498: truyền SHA gốc theo từng cặp, truy lại từ commit promotion |
| **Đọc PolicyReport ngay sau rollout** | Kyverno `backgroundScanInterval=1h` → thấy "fail" của lần scan cũ | Luôn đối chiếu bằng đánh giá tay trên pod sống |
| **Đếm số fail thô của report** | Gộp cả ReplicaSet đã chết → 46 fail trong khi runtime chỉ có 20 vấn đề | Chỉ đo trên pod `Running` |
| **Dùng danh sách `.sig` cache** | Snapshot lạc hậu (29 vs 31) → báo nhầm 2 ReplicaSet sống là chưa ký, suýt chặn 7B | Verify trực tiếp bằng cosign |
| **Digest đã ghi `.att` không sửa lại được** | ECR immutable chỉ cho ghi 1 lần/subject → `quote` phải **rebuild**, không vá được | Pre-flight từ chối cả lô nếu digest đã có `.att` |
| **Test bị tầng admission khác chặn trước** | `techx-tf3` có **3 tầng trước Kyverno**. Ở 2 lần chạy đầu, case `deny-*` **vẫn "lỗi"** nhưng do PodSecurity / resource VAP — rất dễ đọc nhầm là đã pass, trong khi Kyverno chưa hề được gọi | Fixture thoả đủ 3 tầng; message hợp lệ **phải nêu tên policy đang test** |

---

## G. Còn lại

**Không còn hạng mục nào thuộc DoD PM-127.** Cả 4 DoD và 3 yêu cầu Directive #10 đều đã có bằng chứng.

Hai việc **ngoài phạm vi** phát hiện được trong quá trình làm, nên chuyển thành ticket riêng:

| Việc | Vì sao ngoài phạm vi |
|---|---|
| CronJob `aiops-anomaly-training` **Failed 2 lần liên tiếp** (7 ngày và 42 giờ trước) | Hỏng sẵn từ trước, không liên quan supply chain. Của AIO02 |
| **266 ReplicaSet** trong `techx-tf3`, 79 cái tham chiếu digest chưa ký | Nên đặt `revisionHistoryLimit` để dọn. Không ảnh hưởng runtime |

### Ghi chú về `deny-05` (ephemeral container)

Chưa chạy vì không apply được bằng manifest — cần `kubectl debug` trên pod đang chạy. Nhánh `ephemeralContainers` của policy **đã được khoá bằng unit test** (`test_external_policy_defers_every_first_party_form_to_the_signature_policy`) và **đã chứng minh hoạt động trên thực tế**: chính nó bắt được 3 container `nicolaka/netshoot` bỏ quên trên pod `fraud-detection` ngày 28/07.

---

## H. Rủi ro đã biết, chấp nhận có chủ đích

**`kubectl rollout undo` sẽ bị chặn** — 79/266 ReplicaSet đã chết còn tham chiếu digest chưa ký. Không cái nào đang tạo pod.

Đường rollback được hỗ trợ là **`git revert` + ArgoCD**, deploy lại digest từ `values-prod.yaml` — toàn bộ đã ký, **không bị ảnh hưởng**.

Một revision cũ không chứng minh được nguồn gốc thì đúng ra không nên quay lại được.

**`kubectl debug` bị chặn** với image ngoài catalog. Có chủ đích — chính cơ chế này bắt được 3 container `nicolaka/netshoot` bỏ quên trên pod `fraud-detection`. Ai cần troubleshoot thì dùng image trong catalog hoặc thêm qua PR (CI drift gate kiểm).

**Gợi ý ngoài phạm vi:** 266 ReplicaSet là quá nhiều, nên đặt `revisionHistoryLimit`.

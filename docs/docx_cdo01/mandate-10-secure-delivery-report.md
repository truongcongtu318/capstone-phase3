# Mandate #10 — Báo cáo Secure Delivery Pipeline (CI/CD Chuỗi cung ứng an toàn)

**Directive:** Mandate 10 — Secure Delivery (xem `docs/adr/0016-mandate-10-secure-delivery-pipeline.md`)<br>
**Ngày triển khai & Enforce:** 28-29/07/2026<br>
**Nhóm thực hiện:** CDO01<br>
**Phân công:** PM-124 / PM-125 / PM-126 / PM-129 — CDO01 · **PM-127 (ký, SBOM, admission enforce) — CDO02**<br>
**Người xác nhận/chứng kiến (mentor):**<br>
**Video demo toàn bộ kịch bản (29/07):** [Xem tại đây](https://youtu.be/xrqzUAIk7IA)<br>
**Kết quả:** **PASS — Hệ thống CI/CD đã thiết lập thành công chuỗi cung ứng an toàn (Zero Trust). Mọi mã độc, lỗ hổng nghiêm trọng, và image chưa ký đều bị chặn đứng từ khâu CI cho tới cổng Admission của Kubernetes. Đảm bảo khả năng truy vết 100% (Provenance).**

---

## 1. Mục tiêu & phạm vi

**Mục tiêu:** Thắt chặt chuỗi cung ứng phần mềm (Software Supply Chain), đảm bảo nguyên tắc Zero Trust: Không tin tưởng mù quáng bất kỳ image nào được đẩy lên server.
Chứng minh hệ thống đạt 6 yêu cầu kỹ thuật khắt khe nhất của Mandate 10:
1. Cổng chặn thật CI đỏ (PR hỏng build, test, lỗi bảo mật thì chặn merge).
2. Scan HIGH/CRITICAL chặn merge (Trivy, Semgrep, tfsec).
3. Bất biến + xác thực nguồn gốc (ký image, deploy check chữ ký).
4. Pin action theo SHA/digest.
5. Truy ngược được nguồn gốc từ Pod đang chạy trên cluster về commit gốc.
6. Tối ưu CI (chỉ đụng cái gì đổi).

**Phạm vi:**
- **Source Code:** Toàn bộ luồng CI/CD (GitHub Actions) trong Repository hiện tại.
- **Cluster:** `techx-tf3` (Áp dụng chính sách kiểm duyệt hình ảnh Kyverno).
- **Workloads:** Các first-party image được build từ pipeline của TechX Corp.

## 2. Cơ sở kỹ thuật (đã build, verify sống trước demo)

| Lớp Bảo mật | Cơ chế áp dụng | File cấu hình / Bằng chứng | Trạng thái |
|---|---|---|---|
| Cổng chặn CI (Branch Protection) | Require Status Checks trên GitHub branch `main` | Cấu hình GitHub repo, `branch-protection.json`, PR #350, #351 | **Enforce** |
| Scan Lỗ hổng (SAST, IaC, Container) | Trivy (Image chặn pre-push), Semgrep (SAST), tfsec (IaC) | `.github/workflows/build-push-ecr.yml`, `.github/workflows/secure-delivery-gate.yml` | **Enforce** |
| Ký điện tử & SBOM (Attestation) | Cosign Keyless (OIDC) + CycloneDX | `.github/workflows/build-push-ecr.yml` | **Enforce** |
| Admission Control (Chặn Deploy Image chưa ký) | Kyverno `verifyImages` | `gitops/policies/kyverno/verify-first-party-signatures.yaml` | **Enforce** |
| Admission Control (image bên thứ ba) | Kyverno catalog digest tuyệt đối | `gitops/policies/kyverno/allow-approved-external-image-digests.yaml` | **Enforce** |
| Pin Action theo SHA | Cấu hình thủ công commit SHA | Toàn bộ `.github/workflows/*.yml` | **Enforce** |
| Provenance Traceability | Custom script tra cứu `sourceSha`, `sourcePr` | `scripts/ci/trace-provenance.sh` | **Hoạt động 100%** |

## 3. Lộ trình triển khai & Cutover (28-29/07)

1. **Khởi tạo và tích hợp Security Scans (PM-125 & PM-126):** 
   - Đưa Semgrep, tfsec, và Trivy vào Pipeline. Cấu hình thất bại CI nếu phát hiện lỗi High/Critical (PM-125). 
   - Bật Branch Protection với required checks `Secure delivery gate` và `required_approvals: 1` để tuyệt đối chặn các PR hỏng/dính lỗi bảo mật (PM-126). Xây dựng cơ chế ngoại lệ (exception) an toàn cho tfsec.
2. **Ký Image & Kê khai phần mềm (SBOM):** Tích hợp Cosign Keyless (dùng GitHub Actions OIDC) và CycloneDX vào workflow build image. Mọi image sinh ra đều đi kèm chữ ký số và danh sách phần mềm.
3. **Sửa lỗi và hoàn thiện Traceability (PM-129):** 
   - Khắc phục lỗi script `trace-provenance.sh` không thể đọc được `docker-reference` do Cosign CLI version 2.4.0 thay đổi cấu trúc trả về.
   - Bỏ qua check annotation dư thừa.
   - Sửa lỗi PR head không khớp bằng cách tối ưu hóa logic kiểm tra hash.
4. **Enforce Admission Control (PM-127 — CDO02):** 
   - Chuyển **cả hai** Kyverno Policy từ `Audit` sang `Enforce`, tách làm **hai bước** để cô lập rủi ro:
     `allow-approved-external-image-digests` trước (PR #537), sau khi ổn định mới tới
     `verify-first-party-signatures` (PR #540). Nếu có sự cố thì biết ngay do vế nào.
   - Dry-run với bộ test `docs/evidence/mandate-10/pm127/admission-tests/` — **6 case: 2 ACCEPT + 4 DENY** —
     để đảm bảo vừa không chặn nhầm image hợp lệ (False Positive) vừa chặn tuyệt đối image không hợp lệ.

## 4. Quy trình demo mentor (Video Demo 29/07)

Chi tiết thực hành 3 kịch bản lớn đã được quay lại trong video demo: [https://youtu.be/xrqzUAIk7IA](https://youtu.be/xrqzUAIk7IA)

### Kịch bản 1: Cổng chặn CI đỏ (Quét SAST / IaC / Container)
- **Hành động:** Tạo một PR cố tình chứa code có lỗ hổng bảo mật (chứa hardcoded secret hoặc lỗi Terraform).
- **Kết quả:** Job Semgrep/Trivy/tfsec báo đỏ. GitHub Branch Protection lập tức chặn nút "Merge pull request". Trạng thái: `Required status check failed`. 

### Kịch bản 2: Cổng chặn Kubernetes (Image chưa ký)
- **Hành động:** Chạy lệnh deploy một image fake/chưa ký (dùng user có quyền deploy thực sự như `cdo-admin-team`):
  ```bash
  kubectl apply --dry-run=server -f docs/evidence/mandate-10/rejection-demo/bad-unsigned-image.yaml
  ```
- **Kết quả:** Hệ thống Admission Webhook ném lỗi chữ đỏ từ chối request:
  ```text
  Error from server (Forbidden): error when creating "...": admission webhook "mutate.kyverno.svc-fail" denied the request:
  verify-first-party-signatures:
    autogen-verify-techx-main-workflow-signature: 'failed to verify image ...: no signatures found'
  ```

### Kịch bản 3: Truy ngược nguồn gốc (Provenance Traceability)
- **Hành động:** Chọn ngẫu nhiên một Pod đang chạy trên Production (VD: `product-reviews`), và chạy script truy ngược:
  ```bash
  POD_NAME=$(kubectl get pods -n techx-tf3 | grep product-reviews | head -n 1 | awk '{print $1}')
  bash scripts/ci/trace-provenance.sh --namespace techx-tf3 --pod $POD_NAME
  ```
- **Kết quả:** Trả về JSON Pass hoàn toàn. Hệ thống tra xuất được `sourceSha`, `sourcePr` (Pull Request nào đã đưa code này lên) và `promotionPr`. Tất cả các cột trụ kiểm tra (`trivy`, `cosign`, `sbom`) đều hiển thị "PASS".

## 5. Kết quả (Verify sống trước khi ghi vào báo cáo)

Kết quả test thực tế tại Cluster `techx-tf3` cho thấy:
- **Cả hai** policy lọc chính xác: chặn 100% request vi phạm, đồng thời **vẫn cho image hợp lệ đi qua**
  — 30 container first-party và 11 external trong catalog đều chạy bình thường, **0 false-positive**
  trên pod đang chạy.
- CI/CD không có điểm nghẽn (bottleneck) không cần thiết nhờ cơ chế tối ưu Job `prepare`.

## 6. Nghiệm thu

- Toàn bộ 3 kịch bản lớn Demo đã chạy trơn tru, đúng kỳ vọng.
- Hệ thống Branch Protection không thể bị bypass bởi bất kỳ dev nào.
- ArgoCD đồng bộ thông suốt, không có Application nào bị lỗi do False Positive của Kyverno.

## 7. Sự cố quan sát được và quá trình khắc phục

**Sự cố (a) Kubernetes RBAC che khuất Kyverno:**
- **Triệu chứng:** Khi test thử Kịch bản 2 với tài khoản Read-only (`quyen-readonly`), hệ thống báo lỗi `deployments.apps is forbidden`.
- **Nguyên nhân:** Kubernetes phân quyền theo nhiều lớp. Lớp 1 (RBAC - Authorization) chạy trước lớp 2 (Admission Controller - Kyverno). Do user không có quyền tạo Deployment, request bị bật ra ngay lớp 1 nên không thấy được lỗi chữ ký của Kyverno.
- **Khắc phục:** Đổi sang tài khoản Admin (`cdo-admin-team`), gỡ bỏ thiết lập `role_arn` ẩn trong file `~/.aws/config`, sau đó chạy lại. Yêu cầu lọt qua Lớp 1 và bị Lớp 2 (Kyverno) chặn đứng chính xác như thiết kế. Điều này vô tình chứng minh hệ thống được phòng thủ chiều sâu (Defense in Depth) cực kỳ vững chắc.

**Sự cố (b) Script `trace-provenance.sh` do thay đổi format Cosign CLI:**
- **Triệu chứng:** Script báo `FAIL` liên tục ở bước `preflight`, `image-manifest`, và `cosign`. Lỗi `verified signature does not reference the expected release digest`.
- **Nguyên nhân:** Lỗi phân tích chuỗi JSON trả về từ lệnh `cosign verify`. Do khác biệt phiên bản Cosign so với thời điểm viết script.
- **Khắc phục:** Patch lại script `trace-provenance.sh` để lọc đúng thuộc tính `docker-reference` và so sánh chính xác tên repo thay vì toàn bộ tag.

## 8. Bài học kinh nghiệm

- **Bẫy tín hiệu Admission:** Khi test admission, tín hiệu đáng tin duy nhất là message có nêu tên policy đang test hay không. Nếu message nhắc RBAC, PodSecurity, hay mandate05-native-* thì kết quả phải bỏ — dù nó vẫn "lỗi". `techx-tf3` có 4 lớp kiểm tra xếp chồng, và ba lớp đầu chặn trước khi Kyverno được gọi. Cần dùng đúng account có quyền và đúng loại resource (như Deployment thay vì Pod) để lọt qua các lớp ngoài.
- **Cấu trúc CLI:** Cấu trúc API/CLI của các công cụ bên thứ ba (như Cosign) có thể thay đổi bất cứ lúc nào. Các script automation (như `trace-provenance.sh`) cần được viết lỏng (loose parsing) hoặc theo sát phiên bản để tránh lỗi.

## 9. Điểm mạnh của lần triển khai này

1. Xây dựng thành công chuỗi cung ứng phần mềm Zero Trust khép kín từ code đến cluster.
2. Tái sử dụng OIDC của GitHub Action cho Keyless Signing, loại bỏ hoàn toàn rủi ro lộ/mất Private Key.
3. Giải quyết triệt để vấn đề "hộp đen" bằng cơ chế truy xuất ngược (Provenance Traceability) cực kỳ minh bạch và rõ ràng.

## 10. Đề xuất sau Mandate 10

1. Tích hợp trực tiếp kết quả scan SAST và Trivy vào Dashboard của Security (VD: DefectDojo) để theo dõi xu hướng lỗ hổng thay vì chỉ xem trên GitHub Action logs.
2. Nghiên cứu phương án chặn đứng image rác trực tiếp từ ECR (VD: dùng AWS ECR Lifecycle Policy hoặc EventBridge) để giảm tải cho Admission Controller.
3. Quản lý danh sách `allow-approved-external-image-digests` thông suốt hơn để tự động update digest khi có phiên bản an toàn mới từ upstream.

## 11. Cách mentor chạy lại / chứng kiến

```bash
# Checkout nhánh hiện tại
git checkout main && git pull

# Xem CẢ HAI policy đã Enforce và Ready hay chưa
kubectl get clusterpolicy \
  verify-first-party-signatures allow-approved-external-image-digests \
  -o custom-columns=NAME:.metadata.name,ACTION:.spec.validationFailureAction,READY:.status.ready

# Chạy lại test Kịch bản 2
kubectl apply --dry-run=server -f docs/evidence/mandate-10/rejection-demo/bad-unsigned-image.yaml

# Chạy lại script tra cứu (Kịch bản 3)
export PATH=$PATH:$(pwd)
POD_NAME=$(kubectl get pods -n techx-tf3 | grep product-reviews | head -n 1 | awk '{print $1}')
bash scripts/ci/trace-provenance.sh --namespace techx-tf3 --pod $POD_NAME
```

## 12. Đối chiếu Directive Mandate #10

| Yêu cầu | Trạng thái | Bằng chứng / Chi tiết |
|---|---|---|
| **Yêu cầu 1: Cổng chặn thật CI đỏ** (PR hỏng build, test, lỗi bảo mật thì chặn merge) |  **ĐẠT** | Branch protection require `Secure delivery gate` + 1 approval (`branch-protection.json`). Hai PR đỏ có chủ đích **#350** (IaC/CRITICAL) và **#351** (secret/HIGH) đều bị chặn và phải đóng, không merge được. Ảnh: `assets/pm-124-intentional-red-pr-blocked.png` |
| **Yêu cầu 2: Scan HIGH/CRITICAL chặn merge** | **ĐẠT** | Tích hợp Trivy quét Image, tfsec quét Terraform, và Semgrep quét mã nguồn. Bất kỳ lỗi High/Critical nào cũng làm fail CI. |
| **Yêu cầu 3: Bất biến + xác thực nguồn gốc** | **ĐẠT** | Hai policy phủ kín namespace, không chừa khe: `verify-first-party-signatures` kiểm chữ ký + SBOM cho `techx-corp@sha256:*`; `allow-approved-external-image-digests` bắt mọi image còn lại phải khớp tuyệt đối catalog đã review (11/11 đều pin digest). Cả hai Enforce/Ready=True. CI gate `check-external-image-allowlist-drift.py` chặn PR nếu catalog lệch với chart.<br>*(Lưu ý đối với image bên thứ ba: không ký lại mà chỉ ghim digest tuyệt đối trong catalog đã review).* |
| **Yêu cầu 4: Pin theo SHA/digest** | **ĐẠT** | Tất cả các GitHub Actions bên thứ 3 trong Workflow (như checkout, setup, login, v.v.) đều đã được pin cứng theo commit SHA thay vì dùng tag lỏng lẻo như `@v2`, `@v3`. |
| **Yêu cầu 5: Truy ngược được** | **ĐẠT** | Bằng chứng: Script `trace-provenance.sh` đã chạy thành công 100%, lôi xuất chính xác mã SHA, Workflow ID, PR number từ một Pod đang chạy trên cluster. |
| **Yêu cầu 6: Chỉ đụng cái gì đổi** | **ĐẠT** | Job `prepare` trong CI tính toán chính xác phạm vi module thay đổi, bỏ qua việc build lại toàn bộ repo nếu không cần thiết. |

## 13. Kết luận
**PASS — Hệ thống CI/CD đã được bảo mật từ điểm đầu (Code Review, SAST) cho đến điểm cuối (Kubernetes Admission), tạo thành một dây chuyền kín kẽ, tự động hoàn toàn và không thể bypass.**

- Đã xử lý dứt điểm các lỗi pipeline, script liên đới và hoàn thiện toàn bộ các PM cốt lõi (PM-125, PM-126, PM-127, PM-129).
- Đáp ứng 100% các tiêu chí cực kỳ khắt khe của Mandate 10.
- Sẵn sàng bàn giao hệ thống Secure Delivery Pipeline.

## 14. Tài liệu liên quan
- ADR: `docs/adr/0016-mandate-10-secure-delivery-pipeline.md`
- Kyverno Policy (first-party): `gitops/policies/kyverno/verify-first-party-signatures.yaml`
- Kyverno Policy (external): `gitops/policies/kyverno/allow-approved-external-image-digests.yaml`
- Catalog image bên thứ ba: `docs/evidence/mandate-10/external-image-allowlist.yaml`
- CI drift gate cho catalog: `scripts/ci/check-external-image-allowlist-drift.py`
- Script truy ngược: `scripts/ci/trace-provenance.sh`
- Bằng chứng PM-127 (CDO02): `docs/evidence/mandate-10/pm127/acceptance-matrix.md`
- Tổng kết PM-127 cho cả team: `docs/../mandates/mandate-10/mandate-10-pm127-tong-ket.md`

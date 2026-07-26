# Postmortem 0015 — EKS API endpoint bị mở ra internet (`0.0.0.0/0`) bằng thao tác tay ngoài IaC, phơi nhiễm 7 giờ 20 phút (24/07/2026)

**Ngày:** 24/07/2026 (viết ngay sau khi đóng lỗ hổng)
**Người xử lý:** CDO02 (Huu Tai Ngo) — phát hiện, truy vết & khắc phục
**Nguồn gốc thay đổi:** IAM user `KietBE` (group `AIO2-Admin`) — `aws eks update-cluster-config` chạy tay
**Mức độ ảnh hưởng:** **KHÔNG ảnh hưởng khách hàng.** Storefront/checkout/browse/cart không đụng. Ảnh hưởng là
**tư thế bảo mật**: API server của cụm production reachable từ internet trong 7h20m.
**Trạng thái:** ✅ Đã khắc phục — `endpointPublicAccess` về `false` lúc 18:36:29 (+07); code, state và live đã khớp lại.

---

## TL;DR

Cụm `techx-corp-tf3` được thiết kế **private-only** (`cluster_endpoint_public_access = false`), ghi trong
[`infra/modules/eks-platform/main.tf`](../../infra/modules/eks-platform/main.tf) và là một phần tư thế
least-exposure của Mandate #1. Lúc **11:16:07 (+07) ngày 24/07**, IAM user `KietBE` chạy `aws eks
update-cluster-config` **bằng tay từ máy cá nhân**, lật `endpointPublicAccess` thành `true` với
`publicAccessCidrs = ["0.0.0.0/0"]`. Endpoint chuyển từ resolve IP private trong VPC sang **IP public**
(`54.179.244.28`, `13.213.244.194`).

Thay đổi này **không đi qua Terraform, không có PR, không ai báo**. Nó cũng **không kích hoạt cảnh báo nào** —
module `audit_detection` đã có sẵn SNS + Lambda router nhưng không có rule cho `UpdateClusterConfig`. Sự cố chỉ
lộ ra lúc ~17:40 khi CDO02 tình cờ chạy một đợt rà drift thủ công. Đóng lại lúc **18:36:29**, tổng thời gian
phơi nhiễm **7 giờ 20 phút 22 giây**.

Audit log của control plane cho câu trả lời dứt khoát: **không có xâm nhập** — 313 request từ IP ngoài VPC đều
bị trả `401`, mọi truy cập thành công đều mang danh tính IAM hợp lệ của TF3. **Nhưng cụm đã bị dò quét thật:**
request từ IP ngoài đến chỉ **2 phút 29 giây** sau khi mở, và từ phút thứ ~14 có các IP nước ngoài gọi `GET /`
đều đặn mỗi ~20 phút suốt cửa sổ. Bài học không phải "may mà không sao" mà là: **một endpoint production mở ra
internet bị phát hiện trong vài phút, không phải vài ngày** — lần này chỉ có lớp xác thực IAM đứng giữa.

---

## When — Timeline

Giờ ghi theo **+07** (UTC+7), kèm UTC ở các mốc lấy trực tiếp từ CloudTrail.

- **2026-07-13 21:46:25 (14:46:25Z)** — `GitHubActions` (OIDC role `techx-corp-tf3-gha-terraform-apply`,
  Terraform 1.15.4) gọi `UpdateClusterConfig` set `endpointPublicAccess: false`, `endpointPrivateAccess: true`.
  Đây là **lần thay đổi hợp lệ cuối cùng** trước sự cố — cụm về đúng trạng thái private-only như code.
- **2026-07-24 11:00:13 → 11:00:25** — `GitHubActions` chạy một đợt `terraform apply` bình thường
  (`PutKeyPolicy`, `PutRolePolicy`, `UpdateFunctionCode` ở `us-east-1` — thuộc module `audit_detection`/M12).
  **Không đụng tới cấu hình endpoint.** Ghi lại mốc này để loại trừ pipeline khỏi nghi vấn.
- **2026-07-24 11:16:07 (04:16:07Z)** — **`KietBE` gọi `UpdateClusterConfig`**, đặt
  `endpointPublicAccess: true`, `endpointPrivateAccess: true`, `publicAccessCidrs: ["0.0.0.0/0"]`.
  - Update ID `a7c8b68d-6f4e-3caf-8297-adc9488df743`, `status: Successful`, `errors: []`.
  - `userIdentity.type: IAMUser`, ARN `arn:aws:iam::197826770971:user/KietBE`, access key `AKIA…IYOJ`
    (che bớt có chủ đích — access key ID không phải bí mật nhưng khớp pattern của gitleaks; tra đầy đủ trong
    CloudTrail theo `eventID` ở dòng trên).
  - `sourceIPAddress: 42.1.98.105`.
  - `userAgent: aws-cli/2.34.35 ... os/windows#11 ... md/command#eks.update-cluster-config` → **CLI trên máy
    cá nhân**, không phải runner CI, không phải Terraform (Terraform để lại UA `APN/1.0 HashiCorp/1.0 ...`).
  - Mốc này diễn ra **16 phút sau** lần apply của pipeline → xác nhận không phải hệ quả của CI.
- **2026-07-24 15:17:16 / 15:17:29** — `KietBE` gọi `StartSession` (SSM) 2 lần; **15:24:43** gọi
  `ListAccessEntries`. Cho thấy người này vẫn đang thao tác trên cụm trong ngày.
- **2026-07-24 ~17:40** — CDO02 chạy rà drift (`terraform plan -refresh-only` + `aws eks describe-cluster`),
  phát hiện lệch. **Phát hiện thủ công, không do cảnh báo.**
- **2026-07-24 ~17:45** — Đối chiếu 3 lớp: code = `false`, state S3 = `false`, live = `true` → xác định là
  drift một chiều do can thiệp tay. `nslookup` trả về IP public → xác nhận phơi nhiễm là thật, không phải cờ suông.
- **2026-07-24 18:35:03** — CDO02 chạy `aws eks update-cluster-config ... endpointPublicAccess=false`
  (update ID `f1bffd18-790e-36bf-bfdd-1bce81ad77a0`).
- **2026-07-24 18:36:29** — `status: Successful`; cụm về `ACTIVE`, `pub=false`, `priv=true`.
  `nslookup` trả về `10.0.8.89`, `10.0.23.132` → **đã đóng, xác minh bằng DNS chứ không chỉ bằng API response**.

**Cửa sổ phơi nhiễm: 11:16:07 → 18:36:29 = 7 giờ 20 phút 22 giây.**

---

## Why — Nguyên nhân gốc

Nguyên nhân trực tiếp là một thao tác tay. Nhưng thao tác đó **lẽ ra phải bị chặn, hoặc ít nhất bị phát hiện
trong vài phút**. Bốn lớp phòng thủ đều vắng mặt:

1. **Không có ràng buộc quyền.** `KietBE` thuộc group `AIO2-Admin` với quyền đủ rộng để gọi
   `eks:UpdateClusterConfig` trực tiếp lên production. Không có permission boundary, không có SCP, không có
   điều kiện IAM nào giới hạn hành động sửa cấu hình cụm cho riêng role `techx-corp-tf3-gha-terraform-apply`.
   Đây chính là hiện thực hoá của rủi ro **"4+ IAM user AdministratorAccess"** đã ghi trong `CLAUDE.md` từ
   lâu nhưng chưa thu hẹp — nay đã có case thật.

2. **Không có phát hiện.** Module `audit_detection` (M12) đã tồn tại và đang chạy — có SNS topic, Lambda
   router, DLQ, alarm — nhưng **không có rule nào bắt `eks.amazonaws.com:UpdateClusterConfig`** khi principal
   không phải role pipeline. Một sự kiện CloudTrail rõ ràng như vậy đáng lẽ phải bắn cảnh báo trong vài phút.
   Thay vào đó, nó nằm im 7 tiếng.

3. **Không có rà drift định kỳ.** Việc đối chiếu IaC với thực tế hoàn toàn phụ thuộc vào việc **có người
   nhớ chạy tay**. CI có `terraform-plan.yml` và `terraform-apply.yml` nhưng **không có job chạy
   `plan -refresh-only` theo lịch**. Nếu hôm nay không ai rà, drift này có thể sống tới lần apply tiếp theo —
   và khi đó nó sẽ bị lật ngược **âm thầm**, làm đứt kết nối của người đang dùng mà không ai hiểu vì sao.

4. **Không có kênh xử lý nhu cầu truy cập.** Động cơ của `KietBE` **chưa được xác nhận** (xem mục Chưa biết),
   nhưng giả thuyết hợp lý nhất là muốn `kubectl` trực tiếp mà không phải mở SSM tunnel. Đường vào đúng đã tồn
   tại — Cloudflare Zero Trust (`kubectl.arthur-ngo.org`) và SSM bastion — nhưng nếu nó đủ bất tiện để người ta
   chọn mở cả cụm ra internet thay vì dùng, thì **đó là vấn đề của quy trình chứ không chỉ của cá nhân**.

**Phân định:** nguyên nhân gốc là **thiếu guardrail + thiếu phát hiện**, không phải "một người làm sai".
Trong một hệ có ràng buộc quyền đúng, thao tác này đã fail ngay tại API. Trong một hệ có cảnh báo đúng, nó đã
được xử lý trong 5 phút thay vì 7 tiếng.

---

## Impact

- **Khách hàng: không.** Endpoint API của control plane không nằm trong luồng phục vụ. Storefront, checkout,
  browse, cart chạy bình thường suốt thời gian phơi nhiễm. Không có SLO nào bị chạm.
- **Bảo mật:** API server của cụm production reachable từ toàn bộ internet trong 7h20m. Cần nói rõ mức độ:
  **truy cập vẫn bị chặn bởi xác thực IAM + EKS access entry** — không phải "ai cũng vào được cụm". Rủi ro thật
  nằm ở: bề mặt tấn công mở rộng, phơi bày cụm trước hoạt động quét/dò tự động trên internet, và mất tính chất
  private-only vốn là một phần bằng chứng của Mandate #1.
- **Bằng chứng khai thác: không có xâm nhập thành công — nhưng cụm ĐÃ bị dò quét.** Xem mục
  "Bằng chứng từ audit log" bên dưới: 313 request từ IP ngoài VPC bị trả `401`, không request ẩn danh nào
  thành công. Toàn bộ truy cập thành công từ bên ngoài đều thuộc IAM user hợp lệ của team.
- **Tuân thủ/IaC:** live lệch khỏi code và state trong 7h20m. Bất kỳ `terraform apply` nào trong khoảng đó
  cũng sẽ lật ngược thay đổi mà người thực hiện không hề hay biết.
- **Nội bộ:** khi đóng lại lúc 18:36, mọi phiên `kubectl` đang đi qua public endpoint bị đứt đột ngột. `KietBE`
  vẫn đang hoạt động thời điểm đó, nên nhiều khả năng bị ảnh hưởng trực tiếp mà chưa được báo trước.

---

## Bằng chứng từ audit log — cụm bị dò quét trong bao lâu, và có ai vào được không

Cụm **đang bật control-plane logging** (`api`, `audit`, `authenticator` → CloudWatch Logs
`/aws/eks/techx-corp-tf3/cluster`). Nhờ đó câu hỏi "có ai khai thác không" trả lời được bằng dữ liệu chứ không
phải bằng phỏng đoán. Truy vấn CloudWatch Logs Insights trên **đúng cửa sổ 04:16:07Z → 11:36:29Z**, lọc các
request có `sourceIPs` **nằm ngoài VPC** (loại `10.*`, `172.*`, `::1`, `127.*`):

| Kết quả | Số request | Danh tính |
|---|---:|---|
| **HTTP 401** (từ chối, không xác thực được) | **313** | không có danh tính |
| HTTP 200 | 36 | `user/mentor-mandate-reviewer` |
| HTTP 200 | 32 | `user/aio2-admin-team` |
| HTTP 101 (websocket upgrade — `exec`/`port-forward`) | 18 | `user/aio2-admin-team` |

**Đọc bảng này cho đúng:**

1. **Không có một request ẩn danh nào thành công.** Toàn bộ 313 request không xác thực đều bị chặn ở lớp
   authenticator. Mọi truy cập thành công từ ngoài internet đều mang danh tính IAM hợp lệ của TF3. **Không có
   dấu hiệu xâm nhập.**
2. **Nhưng cụm đã bị dò quét thật, và rất nhanh.** Request đầu tiên từ IP ngoài đến lúc **04:18:36Z — chỉ
   2 phút 29 giây** sau khi endpoint được mở. Từ **04:30:12Z** (~14 phút sau khi mở) xuất hiện các IP không
   thuộc dải ISP Việt Nam (`137.184.232.145`, `104.248.49.124`, `71.6.134.233`, `46.161.50.108`,
   `195.96.139.95` …) gọi `GET /` **lặp lại đều đặn mỗi ~20 phút suốt cửa sổ** — dạng lưu lượng đặc trưng của
   quét internet tự động. Đây là bằng chứng cụ thể cho một điều thường bị coi nhẹ: **một endpoint production
   mở ra internet sẽ bị phát hiện trong vòng vài phút, không phải vài ngày.**
3. **Endpoint public đã được dùng thật trong lúc mở.** 18 request `101` (websocket) của `aio2-admin-team` là
   `kubectl exec`/`port-forward` đi qua đường public. Điều này (a) củng cố giả thuyết endpoint được mở cho
   tiện thao tác, và (b) xác nhận việc đóng lúc 18:36 **đã cắt phiên làm việc thật** của người khác.
4. **`mentor-mandate-reviewer` cũng truy cập qua đường public** (36 request `200`). Cần lưu ý khi rà quyền —
   user này đang giữ `AmazonEKSClusterAdminPolicy` qua access entry **nằm ngoài Terraform** (xem mục Rà soát).

Ngoài ra, rà CloudTrail trong đúng cửa sổ cho 9 loại sự kiện cấp/leo quyền — `CreateAccessEntry`,
`AssociateAccessPolicy`, `DeleteAccessEntry`, `CreateUser`, `CreateAccessKey`, `AttachUserPolicy`,
`AttachRolePolicy`, `CreateRole`, `PutUserPolicy` — **cả 9 đều không có sự kiện nào**.

*Giới hạn của rà soát này:* chỉ xét CloudTrail vùng `ap-southeast-1` + audit log control-plane. Chưa liệt kê
toàn bộ sự kiện ghi trong cửa sổ (phân trang quá lớn); việc rà là **có mục tiêu** vào nhóm sự kiện cấp quyền,
không phải quét vét cạn.

---

## Detection & Response — Điều làm ĐÚNG / SAI

**Đúng:**
- **Truy vết bằng bằng chứng cứng, không suy đoán**: CloudTrail (`eventTime`, `userIdentity`, `sourceIPAddress`,
  `userAgent`, `requestParameters`), `describe-update`, `describe-cluster`, và `terraform state show`.
  `userAgent` là mảnh quyết định — nó phân biệt dứt khoát CLI người dùng với Terraform và với CI runner.
- **Đối chiếu 3 lớp (code / state / live)** trước khi kết luận, thay vì tin một nguồn. Nhờ đó xác định được
  chiều của drift là `false → true`, ngược với giả định ban đầu.
- **Xác minh bằng tín hiệu độc lập**: `nslookup` trước và sau. API trả `endpointPublicAccess: false` là một
  chuyện; endpoint thật sự resolve về IP private trong VPC mới là bằng chứng đóng.
- **Loại trừ pipeline có căn cứ**: đối chiếu mốc apply 11:00 của `GitHubActions` với mốc 11:16 của `KietBE`.
- **Phân định nguyên nhân gốc (thiếu guardrail) với người thực hiện (`KietBE`)** — không quy toàn bộ trách
  nhiệm cho cá nhân khi hệ thống không có gì ngăn.
- **Trả lời câu hỏi "có bị khai thác không" bằng audit log, không bằng phỏng đoán.** Control-plane logging đã
  bật sẵn từ trước là thứ duy nhất biến câu hỏi này từ "chắc là không sao" thành một bảng số liệu kiểm chứng
  được. **Đây là khoản đầu tư hạ tầng đã cứu cả hồ sơ sự cố** — nếu log không bật, kết luận duy nhất có thể
  đưa ra sẽ là "không biết".

**Sai / thiếu:**
- **Phát hiện hoàn toàn nhờ may mắn.** Nếu hôm nay không có đợt rà drift, không rõ bao lâu nữa mới lộ.
  Đây là thiếu sót nghiêm trọng nhất của sự cố này.
- **Khắc phục cũng bằng thao tác tay** — đúng cái antipattern vừa gây ra sự cố. Chấp nhận có ý thức vì tính
  khẩn, và **hội tụ về đúng giá trị code + state đã ghi** nên không sinh drift mới (khác hẳn thao tác 11:16 vốn
  làm live rời khỏi IaC). Đường sạch hơn là `terraform apply`, nhưng plan đang **fail vì thiếu
  `CLOUDFLARE_API_TOKEN`** (xem Action item 6) và một apply toàn state sẽ cuốn theo diff của người khác —
  đúng bài học của [postmortem 0013](0013-terraform-forcenew-bastion-replacement-ssm-lockout.md).
- **Đóng trước khi báo.** Team AIO02 không được thông báo trước khi phiên của họ bị cắt. Với tính khẩn của một
  lỗ hổng phơi nhiễm thì ưu tiên đóng là hợp lý, nhưng lẽ ra phải gửi thông báo song song, không phải sau.
- **Chưa liên hệ `KietBE`** để xác nhận động cơ tại thời điểm viết. Không có xác nhận đó thì không biết nhu cầu
  gốc là gì, và **nguy cơ tái diễn vẫn còn nguyên**.

---

## Chưa biết / cần xác nhận

Ghi rõ để không ai đọc postmortem này rồi tưởng đã khép hồ sơ:

1. **Động cơ của `KietBE` chưa được xác nhận.** Giả thuyết "muốn kubectl trực tiếp" là **suy đoán**, dựa trên
   việc cùng ngày họ có `StartSession` và `ListAccessEntries`. Cần hỏi trực tiếp.
2. **Vì sao `mentor-mandate-reviewer` truy cập qua đường public** (36 request `200` trong cửa sổ) — là mentor
   chấm bài bình thường hay có nhu cầu khác? Liên quan tới việc user này giữ cluster-admin ngoài IaC.
3. **Drift ở module `cloudflare-access` chưa kiểm được** (thiếu token) — không loại trừ được khả năng còn lệch
   ở tầng Zero Trust.
4. **Đã rà xong (không còn là câu hỏi mở):** ai dùng public endpoint trong cửa sổ — đã trả lời bằng audit log,
   xem bảng ở mục trên.

---

## Rà soát kèm theo — drift ở các phần khác

Nhân đợt này đã quét rộng. Kết quả, phân loại theo mức nghiêm trọng:

**Drift thật do can thiệp tay:**
- `aws_eks_cluster.this[0]` — `endpoint_public_access: false → true`. **Chính là sự cố này. Đã đóng.**

**Tài nguyên nằm ngoài Terraform (rà thủ công, vì `plan` không nhìn thấy resource nó không quản):**
- Cụm có **11 EKS access entry** nhưng Terraform chỉ quản **4**. Ba entry mang
  `AmazonEKSClusterAdminPolicy` (**quyền cluster-admin**) được tạo tay và không nằm trong IaC:
  `user/aio2-admin-team` (tạo 14/07), `user/cdo-admin-team` (tạo 17/07), `user/mentor-mandate-reviewer`
  (tạo 14/07, kèm cả `AmazonEKSViewPolicy`). Ngoài ra `role/techx-tf3-mandate-reviewer` có entry nhưng
  **không gắn access policy nào** — cần xác định là cố ý hay sót.
  → Đây là **điểm mù có hệ thống**: `terraform plan` không bao giờ báo được loại drift này.

**Không phải can thiệp tay (đã loại trừ bằng CloudTrail):**
- `aws_sns_topic.audit_alerts` + 3 `aws_iam_role` của module `audit_detection` — lệch ở dạng biểu diễn policy
  và `inline_policy` (thuộc tính đã deprecated). Mọi `SetTopicAttributes`/`PutRolePolicy` gần nhất đều do
  `GitHubActions` thực hiện (11:00 hôm nay, 23/07). Là churn của provider/apply dở, không phải người sửa tay.
- `aws_db_instance.postgres` — chỉ lệch `latest_restorable_time`, thuộc tính thay đổi theo thời gian. Không phải drift.

**Tầng GitOps/ArgoCD — khớp git, nhưng để lại rủi ro mở:**
- `kyverno` và `kyverno-policies` đang `OutOfSync`, auto-sync `automated.enabled: false`. **Không phải drift
  live** — giá trị này **đã commit trong repo** (`gitops/apps/kyverno-app.yaml`, commit `349bff2` "fix(pm-127):
  gate Argo sync on IAM readiness"). Live khớp ý định của git.
  ⚠️ **Nhưng hệ quả cần nói rõ:** Kyverno hiện **không tồn tại trong cluster** — không có namespace `kyverno`,
  không có CRD `clusterpolicy`. Nghĩa là 2 policy `verify-first-party-signatures` và
  `allow-approved-external-image-digests` (**cổng chữ ký Cosign của PM-101**,
  [ADR 0008](../adr/0008-pm-101-image-supply-chain-gate.md)) **đang không được thực thi**.
  Phần nào được bù bằng ValidatingAdmissionPolicy native đang chạy (`mandate05-native-image-reference`,
  `mandate05-native-resource-requirements`), nhưng **kiểm chứng chữ ký thì không có gì thay thế**.
  Việc này thuộc CDO01/PM-127 — cần biết bao giờ gỡ gate.
- `flagd-secret-sync` `OutOfSync` ở `ExternalSecret/postgres-connection` — **lành tính**. Đối chiếu spec live
  với `gitops/secrets/datastores-secrets.yaml` cho thấy chỉ lệch ở các field CRD tự điền
  (`conversionStrategy`, `decodingStrategy`, `metadataPolicy`, `mergePolicy`, `metadata: {}`). Cả 4
  ExternalSecret đều `SecretSynced=True`. selfHeal không dọn được vì apply lại git thì CRD lại điền default —
  xử lý bằng `ignoreDifferences` hoặc ghi rõ field. **Không đụng cơ chế flagd.**

---

## Action items

1. **[CDO01 / Security — ưu tiên cao] Cảnh báo `UpdateClusterConfig` ngoài pipeline.** Thêm rule vào module
   `audit_detection` (đã có sẵn SNS + Lambda router + DLQ) bắn cảnh báo khi `eventSource=eks.amazonaws.com`,
   `eventName=UpdateClusterConfig` và principal **không phải** role `techx-corp-tf3-gha-terraform-apply`.
   Đây là thứ lẽ ra đã biến sự cố 7 tiếng thành sự cố 5 phút. Cân nhắc mở rộng cho `UpdateNodegroupConfig`,
   `CreateAccessEntry`, `AssociateAccessPolicy`.
2. **[CI — ưu tiên cao] Rà drift theo lịch.** Thêm job chạy `terraform plan -refresh-only -detailed-exitcode`
   hằng ngày, exit code 2 → thông báo. Không để việc phát hiện drift phụ thuộc vào việc có người nhớ chạy tay.
   Lưu ý job này **không** thấy được tài nguyên nằm ngoài state (xem Action item 5) — cần bổ sung riêng.
3. **[CDO01 / Security] Giữ control-plane logging BẬT và coi nó là bắt buộc.** `api`/`audit`/`authenticator`
   đang bật là lý do duy nhất trả lời được "có bị khai thác không". Đưa vào diện không được tắt, và cân nhắc
   metric filter cảnh báo khi **số `401` từ IP ngoài dải VPC vượt ngưỡng** — tín hiệu này xuất hiện chỉ
   **2 phút 29 giây** sau khi endpoint mở, sớm hơn bất kỳ đợt rà drift theo lịch nào có thể bắt được.
4. **[Security] Thu hẹp quyền sửa cấu hình cụm.** Chặn `eks:UpdateClusterConfig` (và các hành động sửa hạ tầng
   tương đương) đối với IAM user của người dùng; chỉ để role pipeline làm được. Gắn với việc thu hẹp **4+ IAM
   user `AdministratorAccess`** đang mở trong `CLAUDE.md` — sự cố này là bằng chứng cụ thể để đẩy việc đó.
5. **[CDO02] Đưa EKS access entry vào IaC hoặc lập sổ.** 3 grant cluster-admin đang nằm ngoài Terraform. Tối
   thiểu phải có danh sách được rà định kỳ, vì `terraform plan` **không** phát hiện được loại drift này.
   Xem lại riêng trường hợp `mentor-mandate-reviewer` giữ `AmazonEKSClusterAdminPolicy` — mentor có cần
   cluster-admin không, hay `AmazonEKSViewPolicy` là đủ.
6. **[CDO02 → AIO02] Xác nhận nhu cầu gốc.** Hỏi `KietBE` vì sao cần public endpoint. Nếu đường SSM/Cloudflare
   đang cản trở công việc thật thì sửa đường đó cho tử tế (hoặc mở đúng cách qua Terraform + PR), thay vì để
   người ta lặp lại thao tác tay. **Chưa làm tại thời điểm viết.**
7. **[CDO02] Hoàn tất quét drift Cloudflare.** Provider `cloudflare` thiếu credential nên
   `terraform plan` thoát code 1 (`providers.tf:38`) và **module `cloudflare-access` chưa từng được refresh**.
   Đưa `CLOUDFLARE_API_TOKEN` vào CI (qua secret, không vào file tracked) để plan chạy trọn.
   Lưu ý token này đang nằm trong hạng mục **cần rotate** ở `CLAUDE.md`.
8. **[CDO01 / PM-127] Chốt thời hạn cho gate Kyverno.** Trong lúc `automated.enabled: false`, cổng kiểm chứng
   chữ ký Cosign của PM-101 không được thực thi. Cần biết bao giờ bật lại, hoặc ghi nhận rủi ro chấp nhận có
   thời hạn.
9. **[Quy trình] Thông báo song song khi xử lý khẩn.** Khi một hành động khắc phục sẽ cắt truy cập của người
   khác, gửi thông báo **cùng lúc** với thao tác, không phải sau.

---

## Liên quan

- Postmortem [0013](0013-terraform-forcenew-bastion-replacement-ssm-lockout.md) — `terraform apply` áp lên toàn
  state và cuốn theo diff của người khác; lý do lần này không chọn `apply` để khắc phục.
- Postmortem [0012](0012-mandate5-networkpolicy-batch-outage.md) — thay đổi hạ tầng diện rộng không qua kiểm
  chứng đúng môi trường.
- Postmortem [0008](0008-ssm-bastion-to-cloudflare-zero-trust-retrospective.md) — đường truy cập SSM bastion &
  Cloudflare Zero Trust (các đường vào hợp lệ thay cho public endpoint).
- ADR [0008](../adr/0008-pm-101-image-supply-chain-gate.md) — cổng supply-chain image (Trivy + Cosign), hiện
  chưa được Kyverno thực thi.
- [`infra/modules/eks-platform/main.tf`](../../infra/modules/eks-platform/main.tf) — nguồn sự thật
  `cluster_endpoint_public_access = false`.
- [`infra/ACCESS_GUIDE.md`](../../infra/ACCESS_GUIDE.md), [`infra/README.md`](../../infra/README.md) — tài liệu
  khẳng định tư thế private-only.
- Runbook [`cloudflare-zero-trust-access.md`](../runbooks/cloudflare-zero-trust-access.md) — đường vào hợp lệ
  cho ops UI và kubectl.

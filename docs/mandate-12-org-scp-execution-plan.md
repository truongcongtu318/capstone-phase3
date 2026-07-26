# Mandate #12 — Audit Anti-Defeat · Kế hoạch thực thi **v2: Organization + SCP**

> **Trình duyệt:** Tech Lead / IaC owner · **Trạng thái:** `DRAFT — CHỜ CHỐT 1 QUYẾT ĐỊNH TIỀN (§2)`
> **Account A** (management, bật Organizations): **`593777010472`** — *chỉ* chứa Organization + SCP
> **Account B** (member, workload + toàn bộ audit plane): **`197826770971`** — *không đổi gì về kiến trúc*
> **Region:** `ap-southeast-1` + `us-east-1`
> **Quan hệ với bản trước:** [`mandate-12-execution-plan.md`](mandate-12-execution-plan.md) mô tả M12 v1 **đã merge + đã apply** (PR #403). v2 **không thay thế** v1 — v2 chỉ thêm **một lớp SCP từ ngoài** khoá cứng những gì v1 đã dựng.

> [!CAUTION]
> **Không gửi invite, không accept, không attach SCP** trước khi §2 được ký.
> Accept invitation là **nút một chiều về hoá đơn** trong tháng 7. Chi tiết trình tự triển khai ở §9.

---

## 1. Tóm tắt cho người duyệt

**Nguyên tắc của v2:** account A **không chạy gì cả**. Không trail, không bucket, không Lambda, không EventBridge, không SNS. A chỉ làm đúng một việc: **là management account của một Organization, và áp SCP xuống B**. Toàn bộ audit plane (trail, bucket, KMS, router Lambda, 8 EventBridge rule, 2 SNS topic) **ở nguyên trong B như đã dựng từ M11/M12 v1** — không di dời, không dựng lại, không chạy song song.

**Vì sao cần A.** v1 đã làm audit plane *kêu* rất tốt. Nhưng cả 4 IAM user trong B đều `AdministratorAccess`, nên admin của B vẫn `StopLogging` được — v1 chỉ đảm bảo là nó **kêu sau khi đã tắt**. Đề bài đòi *"không ai — **kể cả admin của chính TF4** — tắt được"*, và **gợi ý thẳng cơ chế: "chặn quyền StopLogging bằng SCP"**. SCP là thứ duy nhất đứng **trên** `AdministratorAccess`, và nó chỉ tồn tại khi có một account khác làm management. Đó là toàn bộ lý do A tồn tại.

**Hai SCP sẽ attach lên OU chứa B:**

| SCP | Khoá gì | Bắt buộc |
|---|---|---|
| `TF3-DenyAuditKillSwitch` | Đường ghi log: mọi action tắt/sửa/xoá CloudTrail · bucket archive · 2 KMS key · đường thoát khỏi org | ✅ Đây là thứ đề bài chấm |
| `TF3-DenyAlertPlaneKillSwitch` | Đường báo động: 8 EventBridge rule · 2 router Lambda + IAM role của chúng · 2 SNS topic · unsubscribe · DLQ · log group | ✅ Khuyến nghị mạnh |

**SCP-1 KHÔNG có ngoại lệ principal nào** — không chừa `gha-terraform-apply`, không chừa root. **SCP-2 có đúng một ngoại lệ hẹp, được bảo vệ và giám sát: role bảo trì R** (`techx-corp-tf3-audit-maintainer`) — chỉ role này update được code router và thêm/xoá được người nhận SNS, và **chính R cũng không sửa/xoá được mình**; chỉ account A đổi được R. Đó là điểm mạnh của thiết kế và cũng là ràng buộc vận hành phải hiểu rõ: **§6, §7.5**.

**Chi phí của v2: $0/tháng.** AWS Organizations miễn phí, SCP miễn phí, account A không chạy tài nguyên nào. Không có bản copy management event thứ hai, không có bucket mới, không có KMS key mới.

**Một quyết định duy nhất cần chốt — và là tiền thật: §2.**

---

## 2. ⚠️ Quyết định phải chốt trước: khoảng hở credit khi join giữa tháng

Kiến trúc v2 không tốn đồng nào. Nhưng **hành động kéo B vào org** thì có, vì quy tắc billing của AWS.

### 2.1 Sự thật về billing

Yêu cầu *"bật credit sharing để trừ credit ở account workload trước"* là **đúng và bắt buộc phải làm** (§9.1), nhưng nó quyết định *credit chảy đi đâu* — còn **ngày join quyết định credit có được áp hay không**.

AWS ([Applying AWS credits](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html)):

> *"An individual's account credits **don't cover the account usage from the day that the individual joined the organization to the end of that month**. For this period, the individual's account credits aren't applied to the bill. However, starting the next month, AWS applies the individual's account credits to the organization."*

Cộng với ([Effective billing date](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-effective.html)):

> *"When the member account owner accepts your request to join the organization, **you immediately become responsible for the member account's charges**."*

→ Kể từ giây B accept, hoá đơn của B chuyển sang A; **credit của B không theo sang cho tới ngày 1 tháng sau**. Phần usage từ ngày join đến 31/07 là **tiền thật trên phương thức thanh toán của A**.

### 2.2 Số tiền cụ thể (Cost Explorer, đo 24/07/2026)

Tháng 7 đến 24/07: usage `$577,65`, credit `−$577,65`, **thực trả $0** — credit đang phủ 100%.

| Ngày | Usage |
|---|---|
| 19/07 | $61,96 |
| 20/07 | $62,04 |
| 21/07 | $60,92 |
| 22/07 | $54,18 |
| 23/07 | $46,12 |

Trung bình 5 ngày: **$57,0/ngày**, xu hướng giảm.

**Join 24/07 → hở 8 ngày (24 → 31/07):**

| Kịch bản | $/ngày | Tiền thật trên thẻ của A |
|---|---|---|
| Giữ nguyên hiện trạng | $57,0 | **~$456** |
| Theo run-rate ngày mới nhất | $46,1 | **~$369** |
| Nếu kế hoạch cắt về $269,7/tuần đạt | $38,5 | **~$308** |
| Demo xong rồi scale cluster tối thiểu | ~$20 | **~$200** |

**Dải thực tế: $200 – $460.**

### 2.3 Không né được bằng cách chờ

Join đúng ngày 1 của tháng thì hở = 0. Nhưng `production.auto.tfvars` ghi bài tập kết thúc **31/07/2026** — join 01/08 là join sau khi chương trình xong.

### 2.4 Điểm giảm nhẹ

**Cả ba đòn nghiệm thu M12 đều không cần cluster EKS chạy:** `stop-logging` → AccessDenied; `s3 cp` / `get-secret-value` → vết trong log; `validate-logs`. Nên khoản $ ở trên do **các mandate khác** cần cluster sống quyết định, không phải do M12. Nếu M12 là việc cuối, scale xuống ngay sau các demo khác sẽ kéo về đầu dải.

### 2.5 Ba phương án — chọn 1

| | Phương án | Tiền thật | Được | Mất |
|---|---|---|---|---|
| **A** | **Join ngay (24–25/07)**, ép chi phí xuống trong 8 ngày còn lại | $200–460 | M12 v2 đầy đủ, demo trước 31/07 | Tiền thật trên thẻ của người mở account `593777010472` |
| **B** | Chuẩn bị hết ở Phase 0, **join 01/08** | ~$0 | Không mất đồng nào | Không demo được trong khung 31/07 |
| **C** | **Không join org**, giữ nguyên M12 v1 | $0 | Không rủi ro | Mất vế "bị chặn". Vẫn hợp lệ (đề cho phép *"bị chặn, **hoặc** kêu ngay"*) nhưng bỏ mất vế *"kể cả admin của chính TF4"* |

**Khuyến nghị: A.** Phần còn lại của tài liệu viết theo A; chọn B chỉ đổi ngày ở §9.

---

## 3. Bối cảnh

### 3.1 Đề bài đòi gì

| Yêu cầu | v1 đã có | v2 thêm |
|---|---|---|
| 1. Không cửa sổ mù — *"kể cả admin của chính TF4"*, gợi ý *"chặn quyền StopLogging bằng SCP"* | 🟡 chỉ **kêu** | 🟢 **chặn cứng + kêu** |
| 2. Đóng coverage gap — đọc S3 object / secret phải để lại vết | 🟢 đã có | — (giữ nguyên) |
| 3. Toàn vẹn mật mã — digest chain, `validate-logs` | 🟢 đã có | 🟢 SCP khoá luôn bucket + KMS |
| 4. Giữ đủ lâu | 🟡 14/30 ngày | 🟡 SCP-1 khoá xoá archive (bất biến qua policy) + lifecycle 30 ngày phủ trọn vòng đời chương trình (§5) |

**Ràng buộc:** ~$300/tuần/TF · storefront public, cổng vận hành riêng tư · **không đụng/vô hiệu hoá flagd** (§10.3).

### 3.2 Hiện trạng B — kiểm kê thật, verify trực tiếp 24/07/2026

```
$ aws organizations describe-organization
AWSOrganizationsNotInUseException: Your account is not a member of an organization.
```
→ B **chưa thuộc org nào**. Điểm xuất phát sạch.

**Toàn bộ audit plane đang chạy trong B** (đây chính là danh sách resource mà SCP sẽ khoá):

| Loại | Tên / ARN | Region |
|---|---|---|
| CloudTrail trail | `techx-corp-tf3-audit-detection-ap-southeast-1-trail` — multi-region, global events, `LogFileValidationEnabled=true` | aps1 |
| S3 archive | `techx-corp-tf3-audit-trail-ap-southeast-1-197826770971` — Object Lock **COMPLIANCE 14**, lifecycle **30** | aps1 |
| KMS key | `5d5b2295-a8e4-46ba-b6c5-fc08e81608be` (`alias/…-ap-southeast-1-audit`) | aps1 |
| KMS key | `083bbd40-69eb-49ed-b703-ef4d1bbfed99` (`alias/…-us-east-1-audit`) | use1 |
| Router Lambda | `techx-corp-tf3-audit-detection-ap-southeast-1-router` | aps1 |
| Router Lambda | `techx-corp-tf3-audit-detection-us-east-1-router` | use1 |
| IAM role | `techx-corp-tf3-audit-detection-{ap-southeast-1,us-east-1}-lambda-role` | global |
| SNS topic | `techx-corp-tf3-audit-detection-{ap-southeast-1,us-east-1}-alerts` — **2 topic duy nhất trong cả account** | |
| EventBridge | `…-ap-southeast-1-{g1-audit, g4-eks, g5-secrets, g6-destroy, g7-audit-controls}` | aps1 |
| EventBridge | `…-us-east-1-{g2-new-access, g3-privilege, g8-iam-controls}` | use1 |
| SQS DLQ | `techx-corp-tf3-audit-detection-{region}-lambda-dlq` | cả 2 |
| Log group | `/aws/lambda/techx-corp-tf3-audit-detection-{region}-router` (retention 14) | cả 2 |

**Điểm may mắn cho thiết kế SCP:** mọi thứ dùng chung tiền tố `techx-corp-tf3-audit-detection-*`, nên SCP viết được bằng wildcard, gọn và không chạm nhầm resource khác.

Advanced event selectors hiện tại: `ManagementReadWrite` (eventCategory=Management, Read+Write) + `ApprovedSensitiveS3Objects` (Data, `arn:aws:s3:::techx-tf3-197826770971-tfstate/`).

### 3.3 Vì sao v1 chưa đủ cho yêu cầu 1

1. Kẻ tấn công có credential của 1 trong 4 admin user (hoặc `gitlab-ci-deployer`)
2. `aws cloudtrail stop-logging` → **thành công**. Alert `g1` kêu, nhưng **trail đã dừng**
3. Từ giây đó mọi hành động không được ghi. Alert đã kêu một lần rồi im
4. Người trực có 1 cảnh báo và một hệ đã mù

v2 cắt ở bước 2: `AccessDenied`, trail **không dừng**, và lần thử vẫn sinh alert. Không mua được giây mù nào.

---

## 4. Kiến trúc

```
┌──────────────────────────────────────────────────────────┐
│  Account A   593777010472        KHÔNG CHẠY GÌ           │
│                                                          │
│  • AWS Organizations (all features)                      │
│  • OU: Workload                                          │
│  • SCP-1  TF3-DenyAuditKillSwitch                        │
│  • SCP-2  TF3-DenyAlertPlaneKillSwitch                   │
│                                                          │
│  Không trail · không bucket · không Lambda               │
│  Không EventBridge · không SNS · không KMS               │
│  Chi phí: $0                                             │
└───────────────────────┬──────────────────────────────────┘
                        │  SCP áp xuống, đứng TRÊN AdministratorAccess
                        ▼
┌──────────────────────────────────────────────────────────┐
│  Account B   197826770971   (member, trong OU Workload)  │
│                                                          │
│  WORKLOAD — không đổi                                    │
│    EKS · RDS · MSK · ElastiCache · CloudFront · flagd    │
│                                                          │
│  AUDIT PLANE — đã dựng từ M11/M12 v1, GIỮ NGUYÊN         │
│    CloudTrail trail  ──► S3 archive (Object Lock)        │
│         │                                                │
│    EventBridge g1..g8 ──► router Lambda ──► SNS ──► email│
│                                                          │
│  Sau khi SCP attach: toàn bộ khối trên trở thành          │
│  BẤT BIẾN với mọi principal trong B, kể cả root.         │
└──────────────────────────────────────────────────────────┘
```

### 4.1 Ba quyết định và lý do

**a. A là management, B là member — bắt buộc, không đảo được.**
AWS: *"SCPs don't affect users or roles in the management account. They affect only the member accounts in your organization."* Nếu B là management thì SCP vô tác dụng lên B và cả bài này vô nghĩa.

**b. Không tạo organization trail.**
Đề bài nêu **hai** cơ chế cho yêu cầu 1 và chấp nhận **một trong hai**: *"trail ở phạm vi tổ chức **/** chặn quyền StopLogging bằng SCP"*. Chọn SCP. Đổi lại được ba thứ: không phải trả bản copy management event thứ hai (**~$71/tháng** ở volume thật 117.486 event/ngày), không phải di dời digest chain đang chạy, và **không có rủi ro EventBridge tắt tiếng** khi đổi trail — đây từng là rủi ro cao nhất của phương án org trail.

**c. Ngoại lệ principal — chỉ một, có kiểm soát chặt.**
SCP-1 không chừa ai. SCP-2 chừa **đúng một role bảo trì R**, và chỉ cho **hai action** (`UpdateFunctionCode` + `Subscribe`/`Unsubscribe`) — không phải toàn bộ kill switch. Khác hẳn "chừa `gha-terraform-apply`" (một role vận hành thường, bị chiếm là mất tất cả): R bị đóng băng bởi chính SCP-2 (không tự leo thang, không ai sửa được trừ A), trust hẹp + MFA, và mọi hành động kêu `g7`. Đường lui vẫn đi qua account A (§12). Hệ quả vận hành: §6, §7.5.

### 4.2 Được gì / mất gì so với phương án organization trail

| | SCP-only (v2 này) | Organization trail |
|---|---|---|
| Chi phí | **$0** | ~$71/tháng nếu chạy song song |
| Rủi ro triển khai | **Thấp** — không đụng trail đang chạy | Cao — phải verify EventBridge còn nhận event |
| Khi SCP còn attach | Audit plane **bất khả xâm phạm** từ B | Như nhau |
| **Khi SCP bị detach ở A** | Audit plane trở lại **có thể đụng được** từ B | Bucket + trail vẫn ngoài tầm với của B |
| Đáp ứng đề bài | ✅ Đề nêu đích danh SCP là cơ chế hợp lệ | ✅ |

**Nói thẳng điểm yếu:** toàn bộ sức mạnh của v2 nằm ở việc SCP **còn được attach**. Xem §6.3 để biết vì sao điều đó vẫn cho một câu trả lời vững, và §13 rủi ro #1.

---

## 5. Ánh xạ yêu cầu → cơ chế → cách mentor kiểm

| Yêu cầu | Cơ chế | Mentor gõ (bằng admin trong B) | Phải thấy |
|---|---|---|---|
| **1. Không cửa sổ mù** | SCP-1 | `aws cloudtrail stop-logging --name …-trail` | `AccessDenied` + `errorMessage` **nêu đích danh ARN của SCP** |
| | | `aws cloudtrail delete-trail`, `update-trail`, `put-event-selectors` | `AccessDenied` |
| | | `aws organizations leave-organization` | `AccessDenied` |
| | | `aws s3api delete-bucket` / `put-bucket-policy` trên archive | `AccessDenied` |
| | | `aws kms schedule-key-deletion` trên key audit | `AccessDenied` |
| | SCP-2 | `aws events disable-rule --name …-g1-audit` | `AccessDenied` |
| | | `aws lambda update-function-code` trên router | `AccessDenied` |
| | | `aws sns unsubscribe` trên subscription alert | `AccessDenied` |
| | Vết + alert | (sau mỗi lệnh trên) | Alert `g1`/`g7` CRITICAL, có `errorCode=AccessDenied`, ai/gì/khi/từ đâu |
| **2. Coverage gap** | Data events (v1) | `aws s3 cp s3://techx-tf3-197826770971-tfstate/… .` | Vết `GetObject` trong trail |
| | Management read | `aws secretsmanager get-secret-value --secret-id <flagd>` | Vết + alert `g5` |
| **3. Toàn vẹn** | Digest chain (v1) | team chạy `aws cloudtrail validate-logs` trước mặt | 0 digest thiếu, 0 file `INVALID` |
| **4. Retention** | Object Lock COMPLIANCE 14 + lifecycle 30 **+ SCP-1 deny xoá archive** | `aws s3api get-object-lock-configuration` + `list-policies-for-target` | `COMPLIANCE / 14`; SCP-1 attach; lifecycle 30 ngày phủ trọn vòng đời chương trình tại demo. Bất biến chính do SCP-1 bảo đảm (deny xoá archive với mọi principal kể cả root), Object Lock là lớp lót. Nói thẳng: đây là mức phủ cửa sổ điều tra của bài tập, không phải lưu trữ bất biến nhiều tháng |

---

## 6. Bài toán trung tâm: SCP đóng băng thứ mà Terraform đang quản lý

Đây là phần kỹ thuật quan trọng nhất của v2. Đọc kỹ trước khi review §7.

### 6.1 Vấn đề

Toàn bộ audit plane trong B **do Terraform quản lý** (`infra/live/production/audit-detection.tf` + module). SCP-1/SCP-2 deny đúng những action mà Terraform dùng để sửa chúng. Nếu SCP có ngoại lệ cho `gha-terraform-apply` thì ngoại lệ đó chính là lỗ hổng — ai chiếm được role CI là vượt được SCP.

### 6.2 Lời giải: chỉ deny **mutation**, không deny **read** — và đóng băng audit plane có chủ ý

Ba quan sát làm cho việc này chạy được mà không gãy CI:

**a. `terraform plan` hoàn toàn không bị ảnh hưởng.** Plan chỉ gọi API đọc, và **không một action đọc nào nằm trong SCP**:

| Resource | Action plan dùng | Trong SCP? |
|---|---|---|
| CloudTrail | `DescribeTrails`, `GetTrail`, `GetTrailStatus`, `GetEventSelectors`, `ListTags` | ❌ không |
| S3 | `GetBucket*`, `GetObjectLockConfiguration`, `GetBucketPolicy` | ❌ không |
| Lambda | `GetFunction*`, `ListVersionsByFunction` | ❌ không |
| EventBridge | `DescribeRule`, `ListTargetsByRule` | ❌ không |
| SNS | `GetTopicAttributes`, `ListSubscriptionsByTopic` | ❌ không |
| KMS | `DescribeKey`, `GetKeyPolicy` | ❌ không |
| IAM / SQS / Logs | `GetRole*`, `GetQueueAttributes`, `DescribeLogGroups` | ❌ không |

**b. `terraform apply` chỉ gọi API ghi khi **có diff**.** Audit plane không có diff → apply đi qua bình thường, không chạm một action bị deny nào. CI tiếp tục chạy như cũ cho **mọi thứ khác** trong root `production` (EKS, network, edge, datastore…).

**c. Audit plane đã xong.** M11 + M12 v1 đều đã ship và apply. Từ giờ tới 31/07 không có kế hoạch đổi nó. "Đóng băng" không phải tác dụng phụ phải chịu đựng — nó **chính là** thứ đề bài muốn: kỷ luật cấu hình log (trụ Operational Excellence).

**d. Một ngoại lệ được uỷ quyền có kiểm soát: role bảo trì R.** Đóng băng tuyệt đối gây khó cho hai việc bảo trì thật hay cần: sửa code router và thêm/xoá người nhận alert. Thay vì mở change window mỗi lần, hệ uỷ quyền đúng hai năng lực đó cho **một role duy nhất, được đóng băng và giám sát** (`techx-corp-tf3-audit-maintainer`, §7.5). Đây **không** phá luận điểm "không ngoại lệ principal" ở §4.1: ngoại lệ chỉ mở cho `UpdateFunctionCode` + `Subscribe`/`Unsubscribe` (không phải toàn bộ kill switch), chỉ cho một role mà **chính SCP khoá không cho ai sửa/xoá**, và mọi lần R hành động đều kêu `g7`. Mọi thay đổi audit plane **khác** vẫn đi change window §6.3.

### 6.3 Quy trình đổi audit plane sau khi đóng băng (change window)

Khi thật sự cần sửa audit plane:

1. Từ **account A**: `aws organizations detach-policy --policy-id <scp> --target-id <ou>`
2. Từ B: `terraform apply` như bình thường
3. Từ A: `attach-policy` trở lại
4. Ghi change-ID + lý do vào `docs/evidence/mandate-12-org/change-log.md`

Bước 1 và 3 **phải do người khác** với người chạy bước 2 (two-person rule) — vì đó là lớp kiểm soát duy nhất còn lại.

### 6.4 Điều phải thừa nhận: detach SCP **không** để lại vết mà B thấy được

Organizations API chạy ở **account A**, và A **không có trail** (đúng theo yêu cầu "chỉ SCP ở A"). Nên `DetachPolicy` không sinh event nào trong B, không rule nào bắt, không alert nào kêu.

**Vì sao vẫn chấp nhận được — hệ suy biến an toàn, không suy biến im lặng:**

```
SCP còn attach   →  StopLogging bị CHẶN.  Trail vẫn ghi. Alert g1 kêu.        ← trạng thái đích
SCP bị detach    →  StopLogging THÀNH CÔNG… nhưng CloudTrail vẫn ghi lại
                    chính lệnh StopLogging đó trước khi ngừng, và g1 vẫn kêu.  ← đúng bằng M12 v1
```

Kẻ tấn công detach được SCP **không** mua được sự im lặng — chỉ quay về đúng mức bảo vệ mà v1 đã có, tức *"chỉ ra vết cuối cùng: ai tắt, lúc mấy giờ"* — đúng thứ đề bài yêu cầu tối thiểu. **v2 không bao giờ tệ hơn v1.**

**Canary tuỳ chọn (khuyến nghị, $0, không thêm resource AWS nào):** một scheduled GitHub Actions workflow chạy 30 phút/lần, dùng một OIDC role tối giản `techx-corp-tf3-gha-scp-canary` (chỉ có `cloudtrail:UpdateTrail` trên đúng trail ARN), gọi `update-trail` với **tham số y hệt hiện tại** (no-op):

- SCP còn attach → `AccessDenied` → **đúng kỳ vọng**, workflow pass
- SCP đã bị gỡ → lệnh **thành công** (vô hại, config không đổi) → workflow **fail** → và bản thân `UpdateTrail` đó sinh alert `g1` CRITICAL

Bắt được detach bằng hai đường độc lập, không cần Lambda (team đã cố ý gỡ heartbeat Lambda — canary này không dựng lại nó).

---

## 7. Thiết kế SCP

Attach lên **OU `Workload`**, không attach thẳng vào account — để rollback bằng cách move B ra khỏi OU. **Giữ nguyên `FullAWSAccess`**: AWS cảnh báo *"You should not remove the FullAWSAccess policy … otherwise all AWS actions from member accounts will fail."*

### 7.1 SCP-1 · `TF3-DenyAuditKillSwitch` — đường ghi log

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyTrailKillSwitch",
      "Effect": "Deny",
      "Action": [
        "cloudtrail:StopLogging",
        "cloudtrail:DeleteTrail",
        "cloudtrail:UpdateTrail",
        "cloudtrail:PutEventSelectors",
        "cloudtrail:PutInsightSelectors",
        "cloudtrail:DeleteEventDataStore",
        "cloudtrail:UpdateEventDataStore",
        "cloudtrail:StopEventDataStoreIngestion"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyAuditArchiveTampering",
      "Effect": "Deny",
      "Action": [
        "s3:DeleteBucket",
        "s3:PutBucketPolicy",
        "s3:DeleteBucketPolicy",
        "s3:PutBucketVersioning",
        "s3:PutObjectLockConfiguration",
        "s3:PutBucketLifecycleConfiguration",
        "s3:DeleteBucketLifecycle",
        "s3:PutBucketEncryption",
        "s3:DeleteBucketEncryption",
        "s3:PutBucketPublicAccessBlock",
        "s3:DeleteObject",
        "s3:DeleteObjectVersion",
        "s3:PutObjectRetention",
        "s3:PutObjectLegalHold",
        "s3:BypassGovernanceRetention"
      ],
      "Resource": [
        "arn:aws:s3:::techx-corp-tf3-audit-trail-ap-southeast-1-197826770971",
        "arn:aws:s3:::techx-corp-tf3-audit-trail-ap-southeast-1-197826770971/*"
      ]
    },
    {
      "Sid": "DenyAuditKmsDestruction",
      "Effect": "Deny",
      "Action": [
        "kms:ScheduleKeyDeletion",
        "kms:DisableKey",
        "kms:PutKeyPolicy",
        "kms:DisableKeyRotation"
      ],
      "Resource": [
        "arn:aws:kms:ap-southeast-1:197826770971:key/5d5b2295-a8e4-46ba-b6c5-fc08e81608be",
        "arn:aws:kms:us-east-1:197826770971:key/083bbd40-69eb-49ed-b703-ef4d1bbfed99"
      ]
    },
    {
      "Sid": "DenyOrgEscape",
      "Effect": "Deny",
      "Action": [
        "organizations:LeaveOrganization",
        "account:CloseAccount",
        "account:DisableRegion"
      ],
      "Resource": "*"
    }
  ]
}
```

**Bốn điểm phải hiểu khi review:**

1. **`organizations:LeaveOrganization` là đường thoát chí mạng.** B được *mời* vào org nên **tự rời được**, và rời org là SCP hết hiệu lực ngay lập tức — gỡ cả kiến trúc bằng đúng một lệnh. Không có statement này thì ba statement kia vô nghĩa.

2. **`s3:DeleteObject` deny không làm hỏng lifecycle.** Lifecycle rule (expire 30/100 ngày) do **chính S3 thực thi**, không qua principal IAM nào trong account → SCP không chạm. Tương tự, CloudTrail ghi log bằng service principal `cloudtrail.amazonaws.com`, không phải role trong B → `s3:PutObject` của trail không bị ảnh hưởng.

3. **`s3:GetObject` cố ý KHÔNG deny.** `validate-logs` và việc xuất bằng chứng cần đọc bucket.

4. **`cloudtrail:*` dùng `Resource: "*"` là có chủ ý.** Gọn hơn, và chặn luôn mọi trail tương lai. `CreateTrail` không deny — tạo thêm trail không phải hành vi tấn công.

### 7.2 SCP-2 · `TF3-DenyAlertPlaneKillSwitch` — đường báo động, **với một ngoại lệ duy nhất: role bảo trì R**

Khác bản trước ở chỗ: hai năng lực — **update code router** và **thêm/xoá người nhận SNS** — không còn bị khoá cứng với tất cả, mà được **uỷ quyền cho đúng một role** `techx-corp-tf3-audit-maintainer` (gọi tắt **R**, thiết kế đầy đủ ở §7.5). Mọi principal khác vẫn bị chặn. R **không thể tự sửa/xoá chính nó** — statement `DenyMaintainerRoleTampering` khoá R với **mọi principal kể cả root**, không ngoại lệ.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyDetectionRuleTampering",
      "Effect": "Deny",
      "Action": [
        "events:DeleteRule",
        "events:DisableRule",
        "events:RemoveTargets",
        "events:PutRule",
        "events:PutTargets"
      ],
      "Resource": "arn:aws:events:*:197826770971:rule/techx-corp-tf3-audit-detection-*"
    },
    {
      "Sid": "DenyRouterDestruction",
      "Effect": "Deny",
      "Action": [
        "lambda:DeleteFunction",
        "lambda:UpdateFunctionConfiguration",
        "lambda:PutFunctionConcurrency",
        "lambda:DeleteFunctionConcurrency",
        "lambda:AddPermission",
        "lambda:RemovePermission"
      ],
      "Resource": "arn:aws:lambda:*:197826770971:function:techx-corp-tf3-audit-detection-*"
    },
    {
      "Sid": "DenyRouterCodeUpdateExceptMaintainer",
      "Effect": "Deny",
      "Action": ["lambda:UpdateFunctionCode"],
      "Resource": "arn:aws:lambda:*:197826770971:function:techx-corp-tf3-audit-detection-*",
      "Condition": {
        "ArnNotLike": {
          "aws:PrincipalArn": "arn:aws:iam::197826770971:role/techx-corp-tf3-audit-maintainer"
        }
      }
    },
    {
      "Sid": "DenyAlertTopicTampering",
      "Effect": "Deny",
      "Action": [
        "sns:DeleteTopic",
        "sns:SetTopicAttributes",
        "sns:AddPermission",
        "sns:RemovePermission"
      ],
      "Resource": "arn:aws:sns:*:197826770971:techx-corp-tf3-audit-detection-*"
    },
    {
      "Sid": "DenySubscribeExceptMaintainer",
      "Effect": "Deny",
      "Action": ["sns:Subscribe"],
      "Resource": "arn:aws:sns:*:197826770971:techx-corp-tf3-audit-detection-*",
      "Condition": {
        "ArnNotLike": {
          "aws:PrincipalArn": "arn:aws:iam::197826770971:role/techx-corp-tf3-audit-maintainer"
        }
      }
    },
    {
      "Sid": "DenyUnsubscribeExceptMaintainer",
      "Effect": "Deny",
      "Action": [
        "sns:Unsubscribe",
        "sns:SetSubscriptionAttributes"
      ],
      "Resource": "*",
      "Condition": {
        "ArnNotLike": {
          "aws:PrincipalArn": "arn:aws:iam::197826770971:role/techx-corp-tf3-audit-maintainer"
        }
      }
    },
    {
      "Sid": "DenyRouterRoleTampering",
      "Effect": "Deny",
      "Action": [
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "iam:PutRolePolicy",
        "iam:DetachRolePolicy",
        "iam:AttachRolePolicy",
        "iam:UpdateAssumeRolePolicy",
        "iam:PutRolePermissionsBoundary"
      ],
      "Resource": "arn:aws:iam::197826770971:role/techx-corp-tf3-audit-detection-*"
    },
    {
      "Sid": "DenyMaintainerRoleTampering",
      "Effect": "Deny",
      "Action": [
        "iam:DeleteRole",
        "iam:UpdateRole",
        "iam:UpdateAssumeRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:TagRole",
        "iam:UntagRole"
      ],
      "Resource": "arn:aws:iam::197826770971:role/techx-corp-tf3-audit-maintainer"
    },
    {
      "Sid": "DenyDlqAndAuditLogTampering",
      "Effect": "Deny",
      "Action": [
        "sqs:DeleteQueue",
        "sqs:PurgeQueue",
        "sqs:SetQueueAttributes",
        "logs:DeleteLogGroup",
        "logs:PutRetentionPolicy",
        "logs:DeleteRetentionPolicy"
      ],
      "Resource": [
        "arn:aws:sqs:*:197826770971:techx-corp-tf3-audit-detection-*",
        "arn:aws:logs:*:197826770971:log-group:/aws/lambda/techx-corp-tf3-audit-detection-*"
      ]
    }
  ]
}
```

**Sáu điểm phải hiểu khi review:**

1. **Ngoại lệ chạy bằng `aws:PrincipalArn` + `ArnNotLike`, không phải bằng cách bỏ deny.** Ba statement `…ExceptMaintainer` vẫn **Deny với tất cả**, chỉ trừ đúng ARN của R. Đây là điểm khác biệt cốt lõi so với "chừa `gha-terraform-apply`" mà bản trước đã bác: ở đây ngoại lệ là **một role được bảo vệ, đóng băng, và giám sát** — không phải một role vận hành thông thường. `aws:PrincipalArn` khi R được assume trả về **ARN của role R** (không phải ARN session), nên điều kiện khớp đúng.

2. **`UpdateFunctionCode` tách khỏi `UpdateFunctionConfiguration`.** R chỉ được **update code** (đúng yêu cầu). `UpdateFunctionConfiguration` (đổi handler/role/env/timeout) vẫn nằm trong `DenyRouterDestruction` — **deny với tất cả kể cả R**, vì đổi được `role` hay `handler` là một đường leo thang tinh vi (trỏ router sang code khác hoặc role khác). Cần đổi config thật thì qua change window §6.3.

3. **`PutFunctionConcurrency` / `DeleteFunction` vẫn deny tuyệt đối, kể cả R.** R sửa được code nhưng **không** tắt được router bằng concurrency=0 hay xoá nó. Ngay cả maintainer cũng không cầm được kill switch im lặng nhất.

4. **`sns:Subscribe` tách resource-scoped, `sns:Unsubscribe` buộc `Resource:"*"`.** Subscribe hỗ trợ resource-level nên khoá đúng topic audit; Unsubscribe không hỗ trợ (v1 đã gặp) nên phải `*` — nhưng cả account chỉ có 2 topic đều là audit, ngoại lệ R không mở ra collateral nào. Kết quả: **chỉ R** thêm/xoá được người nhận; mọi người khác bị chặn cả hai chiều.

5. **`DenyMaintainerRoleTampering` là trái tim của yêu cầu "R không sửa/xoá được bởi ai khác".** Nó deny toàn bộ đường sửa R (`UpdateAssumeRolePolicy` = đổi ai được assume, `PutRolePolicy`/`Attach` = nới quyền, `DeleteRole` = xoá) với **mọi principal trong B, không có `Condition`, kể cả root, kể cả chính R**. R vì thế **không tự nới quyền cho mình được** — quyền của R bị đóng băng đúng bằng lúc attach. Xem §7.5 để hiểu vì sao "trừ A" là hệ quả tự nhiên, không cần cấp cho A quyền gì trong B.

6. **`DenyRouterRoleTampering` (role của router) vẫn giữ nguyên, tách khỏi R.** Hai role khác nhau: role thực thi của router (`…-audit-detection-*-lambda-role`) và role bảo trì R (`…-audit-maintainer`). Cái đầu bị khoá để không ai tước quyền publish SNS của router; cái sau bị khoá để không ai chiếm role bảo trì.

### 7.3 Kích thước và giới hạn

| | |
|---|---|
| Giới hạn AWS | 5.120 ký tự / SCP · tối đa 5 SCP / entity |
| SCP-1 (minify, đã đo) | **1.436** ký tự — 4 statement / 30 action ✅ |
| SCP-2 (minify, đã đo) | **2.701** ký tự — 9 statement / 43 action ✅ (đã gồm ngoại lệ R + bảo vệ R) |
| Đang dùng | 2/5 slot (cộng `FullAWSAccess` = 3/5) |

Cả hai đã `json.loads` sạch và mọi ARN đã đối chiếu với tên resource thật lấy từ account (§3.2) — không có wildcard nào bắt hụt hoặc bắt thừa.

Còn dư chỗ nếu sau này cần thêm guardrail. Nếu chạm trần ký tự: bỏ whitespace (visual editor của Organizations tự làm).

### 7.4 Cách test mà không sập production

IAM Policy Simulator **không** đánh giá SCP đầy đủ — đừng dựa vào nó. Quy trình thật:

1. Tạo SCP ở A, attach vào OU `Workload` **khi B chưa nằm trong OU** → xác nhận policy parse được
2. Move B vào OU
3. Chạy ma trận §10.2 — 3 bảng A/B/C
4. **Rollback nhanh nhất không phải sửa policy mà là move B ra khỏi OU** — một lệnh, hiệu lực gần như tức thì

### 7.5 Role bảo trì đặc quyền **R** — ngoại lệ duy nhất, và vì sao nó vẫn an toàn

Đây là role `techx-corp-tf3-audit-maintainer` mà bạn yêu cầu: **role duy nhất** update được code Lambda audit và thêm/xoá được người nhận SNS, và **không ai sửa/xoá được nó trừ A**. R là một resource **trong account B** (do Terraform ở root `production` tạo), nhưng sức mạnh của nó bị siết bởi SCP-2 ở A. Ba mảnh ghép:

#### Mảnh 1 — Quyền của R (identity policy, trong B)

Cấp **tối thiểu, đúng bằng việc R cần làm** — không hơn:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "UpdateRouterCode",
      "Effect": "Allow",
      "Action": ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"],
      "Resource": "arn:aws:lambda:*:197826770971:function:techx-corp-tf3-audit-detection-*"
    },
    {
      "Sid": "ManageAlertRecipients",
      "Effect": "Allow",
      "Action": ["sns:Subscribe", "sns:Unsubscribe", "sns:ListSubscriptionsByTopic", "sns:GetTopicAttributes"],
      "Resource": "arn:aws:sns:*:197826770971:techx-corp-tf3-audit-detection-*"
    },
    {
      "Sid": "UnsubscribeNeedsStar",
      "Effect": "Allow",
      "Action": ["sns:Unsubscribe"],
      "Resource": "*"
    }
  ]
}
```

`sns:Unsubscribe` phải có statement `Resource:"*"` riêng vì không hỗ trợ resource-level — khớp đúng ràng buộc ở SCP-2 điểm 4. R **không** có `UpdateFunctionConfiguration`, `DeleteFunction`, `PutFunctionConcurrency`, `DeleteTopic` — dù identity policy có lỡ cấp thì SCP-2 vẫn deny (SCP đứng trên). Đây là hai lớp trùng nhau có chủ ý.

#### Mảnh 2 — Ai được assume R (trust policy) — **ĐÃ CHỐT: user `CDOAuditTeam`**

Sức mạnh của R chảy qua đúng ai được phép `sts:AssumeRole` vào nó. Nếu trust policy rộng (ví dụ tin cả account B) thì "ngoại lệ của R" thành "ngoại lệ của mọi người" — hỏng toàn bộ. Vì vậy trust policy phải **hẹp nhất có thể** và **bị đóng băng** (SCP-2 `DenyMaintainerRoleTampering` deny `UpdateAssumeRolePolicy` → không ai nới được).

**Đã chốt mô hình T1 với một user chuyên biệt cho team audit** — đã tạo và verify trên account 25/07/2026:

| Thuộc tính | Giá trị (verify qua CLI) |
|---|---|
| ARN | `arn:aws:iam::197826770971:user/CDOAuditTeam` |
| UserId | `AIDAS4D3E7AN3GPQN3WLG` |
| MFA | ✅ bật, serial `arn:aws:iam::197826770971:mfa/AuditDevice` |
| Console login | ✅ có (password) |
| Access key | ❌ **không có** — chỉ console. Ảnh hưởng cách dùng R, xem cuối §7.5 |

Trust policy của R (giá trị thật, đưa vào Terraform):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::197826770971:user/CDOAuditTeam" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "Bool": { "aws:MultiFactorAuthPresent": "true" }
    }
  }]
}
```

> **Vì sao bỏ `aws:MultiFactorAuthAge`:** `CDOAuditTeam` đăng nhập console (phiên dài). Giới hạn tuổi MFA 1h sẽ làm switch-role fail giữa phiên console. `MultiFactorAuthPresent: true` là đủ — buộc phải có MFA, không siết tuổi để tránh ma sát vô ích. Nếu sau này dùng CLI với MFA tươi, có thể thêm lại Age.

Ba mô hình đã cân nhắc (giữ để đối chiếu):

| | Ai assume R | Kết luận |
|---|---|---|
| **T1 ✅ CHỌN** | User `CDOAuditTeam` (người thật, MFA) | Khớp đúng yêu cầu: *sửa/xoá* R chỉ A làm được (mảnh 3); *dùng* R để bảo trì thì người audit có MFA làm |
| T2 | Chỉ account A (`…:593777010472:root`) | Mạnh nhất nhưng A phải có principal để assume — trái "A không giữ IAM user". Bỏ |
| T3 | CI role `gha-terraform-apply` | CI bị chiếm là có R; CI vốn là thứ SCP-2 cố tình không chừa. Bỏ |

**Quyền của `CDOAuditTeam` đã thu hẹp — nhưng còn thiếu đúng một mảnh:** verify 25/07, user này giờ **chỉ còn `ReadOnlyAccess`** (đã gỡ `AdministratorAccess`). Tốt cho least-privilege, **nhưng có một bẫy phải bịt**:

> ⚠️ **`ReadOnlyAccess` KHÔNG chứa `sts:AssumeRole`** (kiểm chứng: chỉ có `sts:GetCallerIdentity`/`GetAccessKeyInfo`/`GetSessionToken`). Nghĩa là hiện tại `CDOAuditTeam` **chưa assume được R**. Phải thêm cho nó đúng một policy nhỏ cấp quyền assume R:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AssumeAuditMaintainerOnly",
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::197826770971:role/techx-corp-tf3-audit-maintainer"
  }]
}
```

Sau khi thêm, `CDOAuditTeam` = `ReadOnlyAccess` (điều tra) + assume-R (bảo trì). **Toàn bộ đặc quyền ghi của nó là "trở thành R"** — mà R thì bị siết đúng 2 việc. Đây là ranh giới quyền sạch nhất. Gắn policy này dạng inline hoặc customer-managed, và làm **trước** khi smoke test ở Phase 3.5.

> Lưu ý same-account: về lý thuyết, trust policy trỏ đích danh user *có thể* cho assume mà không cần `sts:AssumeRole` ở identity — nhưng đừng dựa vào đó cho một role break-glass. Cấp tường minh là cách tài liệu hoá và chắc chắn chạy mọi trường hợp (kể cả switch-role console).

#### Mảnh 3 — Vì sao "không ai sửa/xoá R được, trừ A" là đúng theo nghĩa đen

Điểm mấu chốt về cơ chế SCP, phải hiểu cho đúng để không hiểu nhầm là A có phép màu:

> **SCP áp lên MỌI role trong B, bất kể ai assume — kể cả một role mà A assume vào B.**

Suy ra chuỗi sau, đúng suốt thời gian SCP-2 còn attach:

1. Admin bất kỳ trong B (kể cả root) gọi `iam:UpdateAssumeRolePolicy`/`PutRolePolicy`/`DeleteRole` trên R → **SCP-2 deny**, không `Condition`, không thoát.
2. Kẻ tấn công tạo role mới rồi tự cấp quyền để sửa R → role mới cũng ở trong B → cũng bị SCP-2 deny.
3. Kẻ tấn công tạo **cross-account role trong B** cho A assume, hòng "mượn tay A" sửa R → role đó vẫn **là role trong B** → **vẫn bị SCP-2 deny**. Không có đường nào trong B thoát SCP.
4. Cách duy nhất để sửa R = **gỡ/sửa SCP-2**, mà SCP-2 nằm ở **A** và A không chịu SCP → **chỉ A làm được**.

Nên A **không cần** bất kỳ quyền nào trong B, **không cần** `OrganizationAccountAccessRole`, không cần chạm vào R. A chỉ cần cầm **chiếc chìa khoá duy nhất mở được ổ khoá** — đó chính là SCP. Đây vừa là câu trả lời đúng nhất cho yêu cầu của bạn, vừa giữ nguyên triết lý "A chỉ làm SCP, không đụng tài nguyên B".

#### Quy trình sửa R hợp lệ (change window)

Khi thật sự cần đổi R (xoay người được assume, sửa quyền):

1. Từ **A**: `detach-policy` SCP-2 khỏi OU (hoặc tạm gỡ đúng statement `DenyMaintainerRoleTampering`)
2. Từ **B**: sửa R (Terraform hoặc CLI)
3. Từ **A**: `attach-policy` lại
4. Ghi change-ID vào `docs/evidence/mandate-12-org/change-log.md`. Hai người khác nhau cho bước ở A và bước ở B (two-person rule)

#### R có bị theo dõi không? Có

Mọi hành động của R — `UpdateFunctionCode`, `Subscribe`, `Unsubscribe` — đều khớp rule `g7` (nhóm critical, **không** allowlist). Nên mỗi lần R bảo trì đều **sinh alert**. Đây là tính năng, không phải phiền: ngoại lệ duy nhất của hệ cũng là principal bị soi kỹ nhất. Giảm nhiễu bằng cách gắn change-ID cho mỗi lần dùng R (đối chiếu ở người trực), **không** bằng cách allowlist R.

#### Vòng đời & thứ tự triển khai

- R + hai policy của nó **phải được tạo và chốt xong TRƯỚC khi attach SCP-2** — sau khi attach, `PutRolePolicy`/`UpdateAssumeRolePolicy` trên R bị chính SCP-2 khoá.
- Terraform ở root `production` quản lý R. Sau khi khoá, Terraform cũng không sửa được R (đúng mô hình đóng băng §6.2) — đổi R đi qua change window ở trên.
- Chi phí: **$0** (IAM role + policy miễn phí).

#### Cách `CDOAuditTeam` dùng R — **console switch-role là đường chính** (vì user không có access key)

`CDOAuditTeam` chỉ có console login + MFA, **không có access key**. Nên đường tự nhiên nhất là **AWS Console → Switch Role**, không cần tạo key trần nào:

1. Đăng nhập console bằng `CDOAuditTeam` (password + MFA) → phiên có `aws:MultiFactorAuthPresent=true`.
2. Menu account (góc phải trên) → **Switch role** → nhập:
   - Account: `197826770971`
   - Role: `techx-corp-tf3-audit-maintainer`
3. Sau khi switch, làm hai việc bảo trì ngay trong console:
   - **Update code router:** Lambda console → function `…-audit-detection-ap-southeast-1-router` → tab Code → Upload from `.zip` (router chỉ 1 file `index.py`, upload nhẹ).
   - **Thêm/xoá người nhận:** SNS console → topic `…-alerts` → Create/Delete subscription.
4. Switch back khi xong.

**Nếu cần CLI** (deploy code bằng script), `CDOAuditTeam` chưa dùng CLI được vì không có access key. Hai lựa chọn:
- **(a)** Tạo access key cho `CDOAuditTeam` → cấu hình profile assume-role (`role_arn` + `source_profile` + `mfa_serial = …:mfa/AuditDevice`). Đổi lại có một key dài hạn phải giữ kỹ.
- **(b)** Giữ console-only, dùng switch-role như trên. Khuyến nghị (b) trừ khi thật sự cần tự động hoá.

> Runbook `mandate-12-org-scp-demo.md` sẽ chép nguyên các bước này kèm ảnh, để người audit tự làm không cần đứng cạnh.

**Nhắc lại giới hạn** (sẽ gặp `AccessDenied` dù đã là R, đây là chủ ý): R **không** xoá được function, **không** đặt concurrency=0, **không** đổi config/handler/role, **không** xoá topic, **không** sửa chính R. Chỉ đúng: update code + thêm/xoá người nhận.

---

## 8. Chi phí

| Hạng mục | $/tháng |
|---|---|
| AWS Organizations | **0** (miễn phí) |
| SCP (2 policy) | **0** (miễn phí) |
| Account A — tài nguyên chạy | **0** (không có gì) |
| Trail / bucket / Lambda / EventBridge / SNS ở B | **0 phát sinh thêm** — đã đang chạy từ M11/M12 v1 |
| Role bảo trì R (§7.5) | **0** — IAM role + policy miễn phí |
| Canary GitHub Actions (§6.3, tuỳ chọn) | **0** — chạy trên runner GitHub |
| **Tổng phát sinh của v2** | **~$0/tháng** (chỉ Organizations + SCP, đều miễn phí) |

**So sánh với phương án organization trail đã loại:** phương án đó tốn **~$71/tháng** cho bản copy management event thứ hai (đo thật: 117.486 event/ngày × 30,4 ÷ 100.000 × $2,00). Bỏ nó tiết kiệm **$16,5/tuần** và loại luôn rủi ro EventBridge tắt tiếng.

> Khoản $200–460 ở §2 **không phải chi phí của M12** — đó là chi phí workload hiện hữu tạm mất lớp phủ credit do quy tắc billing khi join giữa tháng. Đừng gộp hai thứ khi báo cáo trụ Cost.

---

## 9. Trình tự triển khai

**J** = ngày B accept invitation.

### Phase 0 — Chuẩn bị, **không đụng AWS đang chạy** (làm ngay được, trước khi §2 chốt)

| # | Việc |
|---|---|
| 0.1 | Viết 2 SCP dạng file JSON trong repo (`infra/org/scp/`), chưa tạo trên AWS |
| 0.1b | Viết Terraform cho role R (`techx-corp-tf3-audit-maintainer` + identity policy + trust policy) trong root `production` — §7.5. Chưa apply |
| 0.2 | Viết ma trận kiểm chứng §10.2 (gồm bảng D) thành script chạy được |
| 0.3 | Viết ADR `0013-mandate-12-org-scp-anti-defeat.md` + runbook demo |
| 0.4 | Chuẩn bị credential account A `593777010472`, xác nhận nó **chưa** thuộc org nào |
| 0.5 | (tuỳ chọn) Viết workflow canary §6.3 |
| **Gate 0** | **§2 được Tech Lead ký. Không qua thì dừng ở đây.** |

### Phase 1 — Baseline trước khi khoá

Một việc nhẹ, nên làm để có mốc so sánh: chạy `aws cloudtrail validate-logs` một lần **trước khi attach SCP** làm baseline, để đòn 3 (§11) có điểm tham chiếu "trước/sau". Không phải gate.

### Phase 2 — Dựng org ở A (J−1) · **chi tiết ở §9.3**

| # | Việc | Verify |
|---|---|---|
| 2.1 | Bật MFA cho root của A · thêm phương thức thanh toán | A chịu hoá đơn cả org từ lúc B join |
| 2.2 | `create-organization --feature-set ALL` | `describe-organization` → `FeatureSet: ALL` |
| 2.3 | Bật policy type `SERVICE_CONTROL_POLICY` ở root | `list-roots` → `PolicyTypes[].Status = ENABLED` |
| 2.4 | Tạo OU `Workload` | `list-organizational-units-for-parent` |
| 2.5 | **Billing preferences → Credit sharing: Activate All** | §9.1 |
| 2.6 | Tạo SCP-1 + SCP-2 — **chưa attach** | `list-policies` |
| 2.7 | Invite `197826770971` | `list-handshakes-for-organization` → `OPEN` |

### Phase 3 — B accept + move vào OU (J) · **chi tiết ở §9.4**

| # | Việc | Verify |
|---|---|---|
| 3.1 | **Từ B: accept handshake** ← nút một chiều về hoá đơn | từ B: `describe-organization` trả org id |
| 3.2 | Từ A: move B từ Root vào OU `Workload` | `list-accounts-for-parent` |
| 3.3 | Xác nhận CI vẫn xanh (chưa attach SCP) | 1 lần `terraform plan` qua workflow |

### Phase 3.5 — Tạo role bảo trì R ở B (§7.5) — **phải xong TRƯỚC khi attach SCP-2**

| # | Việc | Verify |
|---|---|---|
| 3.5.1 | Terraform (root `production`): tạo role `techx-corp-tf3-audit-maintainer` + identity policy (mảnh 1) + trust policy trỏ `user/CDOAuditTeam` + MFA (mảnh 2) | `aws iam get-role --role-name techx-corp-tf3-audit-maintainer` |
| 3.5.2 | Xác nhận `CDOAuditTeam` có MFA (đã verify 25/07: serial `…:mfa/AuditDevice`) | `aws iam list-mfa-devices --user-name CDOAuditTeam` |
| 3.5.3 | ✅ `CDOAuditTeam` đã còn `ReadOnlyAccess` (verify 25/07). **Thêm policy assume-R** cho nó — `ReadOnlyAccess` không có `sts:AssumeRole` nên chưa assume được nếu thiếu | `list-attached-user-policies` + thử assume |
| 3.5.4 | Smoke test **trước khi khoá**: `CDOAuditTeam` switch-role vào R (console) hoặc assume R, chạy `sns:Subscribe` một email test rồi `Unsubscribe` | thành công |
| **Gate 3.5** | **R tồn tại, quyền + trust đã chốt.** Sau bước này quyền/trust của R sẽ bị SCP-2 đóng băng | |

### Phase 4 — Attach SCP · **chi tiết ở §9.5**

| # | Việc | Ghi chú |
|---|---|---|
| 4.1 | Attach **SCP-1** vào OU `Workload` | |
| 4.2 | Chạy ma trận §10.2 phần SCP-1 | Bảng A allowed · B denied · C allowed |
| 4.3 | Quan sát 30 phút: ArgoCD, external-secrets, Karpenter, SLO | |
| 4.4 | Attach **SCP-2** | Tách riêng để cô lập nguyên nhân nếu có sự cố |
| 4.5 | Chạy ma trận §10.2 phần SCP-2 **+ bảng D (role R)** + quan sát 30 phút | Bảng D: R làm được / người khác không / không ai sửa được R |
| 4.6 | 1 lần `terraform plan` + `apply` (no-op) qua CI | Chứng minh §6.2: CI không gãy |

### Phase 5 — Nghiệm thu (§11)

---

### 9.1 Credit sharing — cấu hình chính xác

Billing and Cost Management console **ở account A** → **Billing preferences** → **Credit sharing preferences** → **Edit**:

- **Activate All** — cả A và B đều phải `activated`. AWS: *"Accounts must have credit sharing activated to participate in credit sharing. This includes both giving credits to and receiving credits from other accounts."*
- Tick **Default sharing for newly created member accounts**
- Tải **Download preference history (CSV)** làm evidence

**Thứ tự áp credit khi sharing ON** (nguyên văn AWS) — đúng thứ bạn yêu cầu:

> 1. *"Account that owns the credit is covered for the service charges"*
> 2. *"Credits are applied towards the AWS account with the highest spend"*

→ Credit của B phủ usage của B **trước**. Vì A không chạy gì, thực tế credit của B chỉ dùng cho chính B. Nếu để **OFF**: *"Credits are applied to only the account that received the credits"* — vẫn đúng về mặt kết quả trong kiến trúc này (A không tiêu gì), nhưng **vẫn phải bật ON** để phòng trường hợp A phát sinh chi phí ngoài dự kiến.

⚠️ **Kiểm lại preference vào 30–31/07**: hoá đơn tính theo preference đang active **ngày cuối tháng**, không phải ngày cấu hình.

---

### 9.2 Ai chạy được lệnh nào — quyền cần có

#### Ở account B: **KHÔNG cần root.** Access key IAM hiện tại là đủ.

AWS ([Managing account invitations](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_accounts_invites.html)):

> *"If you are the administrator of an AWS account, you also can accept or decline an invitation from an organization."*

Và luồng console ghi rõ thứ tự ưu tiên — root là lựa chọn **không khuyến nghị**:

> *"If prompted, sign in to the invited account as an IAM user, assume an IAM role, or sign in as the account's root user (**not recommended**)."*

**Quyền tối thiểu để accept** (nguyên văn hộp *Minimum permissions* của AWS):

| Action | Bắt buộc? |
|---|---|
| `organizations:ListHandshakesForAccount` | ✅ để thấy danh sách lời mời |
| `organizations:AcceptHandshake` | ✅ |
| `organizations:DeclineHandshake` | ✅ (nếu muốn từ chối) |
| `organizations:LeaveOrganization` | ❌ **chỉ cần khi account đang thuộc một org khác** — B đang đứng một mình nên không cần |
| `iam:CreateServiceLinkedRole` | ✅ để Organizations tạo `AWSServiceRoleForOrganizations` trong B |

**Đối chiếu với credential đang có trong CLI (kiểm tra thật 24/07/2026):**

```
User    : arn:aws:iam::197826770971:user/cdo-2-admin-team
Group   : AIO2-Admin
Policy  : arn:aws:iam::aws:policy/AdministratorAccess   ← "*" trên "*"
          arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess
```

`AdministratorAccess` phủ trọn 5 action trên → **access key hiện tại accept được, không cần đụng root của B.**

Root của B chỉ cần cho: đóng account, đổi email/số điện thoại root, đổi phương thức thanh toán, rời org khi bị khoá quyền. Không có việc nào trong kế hoạch này.

> ⚠️ Hai điều cần biết về chính credential này:
> - `cdo-2-admin-team` đang có **2 access key Active** và **không có MFA device nào**. Lệnh accept là hành động một chiều về hoá đơn — nên chạy bằng máy tin cậy, và MFA vẫn là việc còn mở trong backlog IAM hardening.
> - Hành động accept **được ghi vào CloudTrail của chính B** (AWS: *"If a member account or standalone account accepts or declines an account invitation, that action will be logged in the CloudTrail log of the acting account"*). Đây là một event có ích cho evidence — chụp lại.

#### Ở account A: root (có MFA), hoặc một IAM user tạm

A là account mới nên chưa có IAM user nào. Hai đường:

| | Cách | Ưu | Nhược |
|---|---|---|---|
| **A1** (khuyến nghị) | Làm **toàn bộ bằng console**, đăng nhập root + MFA. Không tạo access key nào trong A | Không có key nào để rò rỉ. A thật sự "ngoài tầm với" | Bấm tay, không script được |
| **A2** | Tạo 1 IAM user `tf3-org-admin` trong A (`AdministratorAccess` + bắt buộc MFA), dùng access key của nó cho CLI | Chạy được toàn bộ lệnh dưới đây | **Key của A nằm cùng máy với key của B** — máy bị chiếm là mất cả hai. Phải xoá user này ngay sau khi xong |

**Nếu chọn A2, phải hiểu rõ điều này:** toàn bộ giá trị của kiến trúc nằm ở chỗ A ngoài tầm với của kẻ đã chiếm được B. Để access key của A trên cùng laptop với key của B **làm hỏng đúng giả định đó**. Nếu vẫn chọn A2, hãy xoá access key của A ngay sau Phase 4 và ghi vào evidence.

Bạn có thể thử **CloudShell** trong console của A (biểu tượng `>_` góc trên) để chạy các lệnh CLI dưới đây mà không cần tạo access key — nếu account/vùng của bạn cho phép. Nếu CloudShell không mở được, quay lại A1 (console) hoặc A2.

> **Một điểm phân quyền quan trọng, có lợi cho thiết kế:** với account được **mời** vào org, AWS **không** tự tạo role `OrganizationAccountAccessRole`. Nghĩa là **A không có đường admin nào vào B** — A chỉ áp policy được, không sờ được tài nguyên của B. Đúng ý "A chỉ làm SCP". Đừng tạo role đó thủ công.

---

### 9.3 Phase 2 chi tiết — dựng org ở A

> Chạy ở **account A `593777010472`**. Organizations là service global, endpoint đặt ở `us-east-1` — luôn thêm `--region us-east-1`.

**Bước 0 — xác nhận A sạch và đang đúng account:**

```bash
aws sts get-caller-identity --output json          # Account phải là 593777010472
aws organizations describe-organization --region us-east-1
# Kỳ vọng: AWSOrganizationsNotInUseException  → A chưa thuộc org nào. Nếu nó TRẢ VỀ một org,
# dừng lại: A đã là member hoặc management của org khác, phải xử lý trước.
```

**Bước 1 — tạo organization với ALL features:**

```bash
aws organizations create-organization --feature-set ALL --region us-east-1
```

⚠️ Phải là `ALL`. Nếu lỡ tạo `CONSOLIDATED_BILLING` thì **không dùng được SCP** — AWS: *"SCPs aren't available if your organization has enabled only the consolidated billing features."* Sửa bằng `enable-all-features`, nhưng khi đó **mọi member account phải phê duyệt lại** — phiền hơn nhiều so với làm đúng ngay.

Ghi lại `Organization.Id` (`o-xxxxxxxxxx`) và `Organization.MasterAccountId`.

**Bước 2 — lấy Root ID và bật policy type SCP:**

```bash
ROOT_ID=$(aws organizations list-roots --region us-east-1 --query 'Roots[0].Id' --output text)
echo "ROOT_ID=$ROOT_ID"        # dạng r-xxxx

aws organizations list-roots --region us-east-1 --query 'Roots[0].PolicyTypes'
# Nếu chưa thấy SERVICE_CONTROL_POLICY / ENABLED thì bật:
aws organizations enable-policy-type \
  --root-id "$ROOT_ID" --policy-type SERVICE_CONTROL_POLICY --region us-east-1

# Xác nhận lại:
aws organizations list-roots --region us-east-1 --query 'Roots[0].PolicyTypes'
# Kỳ vọng: [{"Type":"SERVICE_CONTROL_POLICY","Status":"ENABLED"}]
```

**Bước 3 — tạo OU `Workload`:**

```bash
OU_ID=$(aws organizations create-organizational-unit \
  --parent-id "$ROOT_ID" --name Workload --region us-east-1 \
  --query 'OrganizationalUnit.Id' --output text)
echo "OU_ID=$OU_ID"            # dạng ou-xxxx-xxxxxxxx
```

**Bước 4 — bật credit sharing** — console, không có CLI: xem §9.1. **Làm ngay ở bước này**, đừng để sau, vì hoá đơn tính theo preference active ngày cuối tháng.

**Bước 5 — tạo 2 SCP (chưa attach):**

```bash
# File JSON lấy từ §7.1 và §7.2, lưu ở infra/org/scp/
SCP1_ID=$(aws organizations create-policy --region us-east-1 \
  --name TF3-DenyAuditKillSwitch --type SERVICE_CONTROL_POLICY \
  --description "M12: deny CloudTrail/S3-archive/KMS kill switches and org escape in account B" \
  --content file://infra/org/scp/scp-1-deny-audit-kill-switch.json \
  --query 'Policy.PolicySummary.Id' --output text)

SCP2_ID=$(aws organizations create-policy --region us-east-1 \
  --name TF3-DenyAlertPlaneKillSwitch --type SERVICE_CONTROL_POLICY \
  --description "M12: deny tampering with EventBridge/Lambda/SNS alert plane in account B" \
  --content file://infra/org/scp/scp-2-deny-alert-plane-kill-switch.json \
  --query 'Policy.PolicySummary.Id' --output text)

echo "SCP1_ID=$SCP1_ID  SCP2_ID=$SCP2_ID"     # dạng p-xxxxxxxx
```

Nếu `create-policy` báo lỗi cú pháp: đó là chỗ tốt để phát hiện, **trước** khi có bất kỳ account nào chịu ảnh hưởng.

**Bước 6 — mời B:**

```bash
aws organizations invite-account-to-organization --region us-east-1 \
  --target Id=197826770971,Type=ACCOUNT \
  --notes "TF3 Mandate 12 - audit anti-defeat guardrail"

aws organizations list-handshakes-for-organization --region us-east-1 \
  --query 'Handshakes[?State==`OPEN`].[Id,State,ExpirationTimestamp]' --output table
```

Lời mời có hiệu lực **15 ngày**. Ghi lại `HandshakeId` (`h-xxxxxxxx`).

> **🔴 Tuyệt đối không attach SCP vào `$ROOT_ID` ở bất kỳ bước nào.** AWS: *"If you have any policies attached to the root or the organizational unit (OU) that contains the invited account, **those policies immediately apply** to all users and roles in the invited account."* B accept xong sẽ nằm ở **Root** trước khi được move vào OU — SCP attach ở Root sẽ áp **ngay lập tức, không kịp chạy ma trận kiểm chứng**. Chỉ attach vào `$OU_ID`, và chỉ ở Phase 4.

**Checklist ra khỏi Phase 2:**

- [ ] `describe-organization` → `FeatureSet: ALL`
- [ ] `list-roots` → `SERVICE_CONTROL_POLICY: ENABLED`
- [ ] OU `Workload` tồn tại, `OU_ID` đã ghi lại
- [ ] Credit sharing = Activate All, đã tải CSV preference history
- [ ] 2 SCP tồn tại, `SCP1_ID`/`SCP2_ID` đã ghi lại, **chưa attach vào đâu cả**
- [ ] `list-policies-for-target --target-id $ROOT_ID` → **chỉ có `FullAWSAccess`**
- [ ] Handshake `OPEN`, `HandshakeId` đã ghi lại

---

### 9.4 Phase 3 chi tiết — B accept và move vào OU

> **Bước 1 chạy ở account B** bằng access key hiện tại (`cdo-2-admin-team`). **Bước 2–3 chạy ở account A.**

**Bước 1 — B accept (đây là nút một chiều về hoá đơn — §2 phải đã được ký):**

```bash
# Ở account B. Xác nhận đúng account trước khi bấm:
aws sts get-caller-identity --query Account --output text     # phải là 197826770971

# Xem lời mời:
aws organizations list-handshakes-for-account --region us-east-1 \
  --query 'Handshakes[?State==`OPEN`].[Id,Action,ExpirationTimestamp]' --output table

# Accept:
aws organizations accept-handshake --region us-east-1 \
  --handshake-id h-xxxxxxxxxxxxxxxxx

# Xác nhận:
aws organizations describe-organization --region us-east-1 \
  --query 'Organization.[Id,MasterAccountId,FeatureSet]' --output text
# Kỳ vọng: o-xxxxxxxxxx   593777010472   ALL
```

Kể từ giây này: hoá đơn của B thuộc về A, và **credit của B ngừng phủ usage của B cho tới 01/08** (§2).

**Bước 2 — từ A, move B từ Root vào OU `Workload`:**

```bash
# Ở account A
aws organizations list-accounts --region us-east-1 \
  --query 'Accounts[].[Id,Name,Status]' --output table    # phải thấy 197826770971 ACTIVE

aws organizations move-account --region us-east-1 \
  --account-id 197826770971 \
  --source-parent-id "$ROOT_ID" \
  --destination-parent-id "$OU_ID"

aws organizations list-accounts-for-parent --region us-east-1 \
  --parent-id "$OU_ID" --query 'Accounts[].Id' --output text
# Kỳ vọng: 197826770971
```

**Bước 3 — chứng minh chưa có gì thay đổi về quyền** (SCP chưa attach, nên B phải hoạt động y như trước):

```bash
# Ở account B
aws organizations list-policies-for-target --region us-east-1 \
  --target-id 197826770971 --filter SERVICE_CONTROL_POLICY \
  --query 'Policies[].Name' --output text
# Kỳ vọng: FullAWSAccess   (chỉ vậy thôi)

# Chạy 1 lần terraform plan qua CI → phải xanh
# Kiểm tra workload không đổi:
kubectl get applications -n argocd          # tất cả Synced/Healthy
aws cloudtrail get-trail-status \
  --name techx-corp-tf3-audit-detection-ap-southeast-1-trail \
  --region ap-southeast-1 --query IsLogging     # true
```

**Checklist ra khỏi Phase 3:**

- [ ] Từ B: `describe-organization` trả về org id của A
- [ ] B nằm trong OU `Workload`, không còn ở Root
- [ ] `list-policies-for-target` trên B → **chỉ `FullAWSAccess`**
- [ ] SLR `AWSServiceRoleForOrganizations` đã xuất hiện trong B (`aws iam get-role --role-name AWSServiceRoleForOrganizations`)
- [ ] `terraform plan` qua CI xanh · ArgoCD Synced/Healthy · trail vẫn `IsLogging: true`
- [ ] Đã chụp evidence: event `AcceptHandshake` trong CloudTrail của B

---

### 9.5 Phase 4 chi tiết — attach SCP

> Attach ở **account A**. Chạy ma trận kiểm chứng ở **account B**. **Attach từng SCP một** — không attach cả hai cùng lúc, để nếu có sự cố thì biết ngay cái nào gây ra.

**Bước 1 — attach SCP-1, đo ngay:**

```bash
# Ở A
aws organizations attach-policy --region us-east-1 \
  --policy-id "$SCP1_ID" --target-id "$OU_ID"

aws organizations list-policies-for-target --region us-east-1 \
  --target-id "$OU_ID" --filter SERVICE_CONTROL_POLICY \
  --query 'Policies[].Name' --output text
# Kỳ vọng: FullAWSAccess  TF3-DenyAuditKillSwitch
```

**Bước 2 — ở B, chạy ma trận §10.2 phần SCP-1.** Ba nhóm kiểm, làm đúng thứ tự:

```bash
# --- (a) BẢNG B: phải AccessDenied ---
aws cloudtrail stop-logging \
  --name techx-corp-tf3-audit-detection-ap-southeast-1-trail --region ap-southeast-1
# Kỳ vọng: AccessDeniedException ... with an explicit deny in a service control policy: arn:aws:organizations::593777010472:policy/...
# ⬅️ CHỤP MÀN HÌNH LỆNH NÀY. Đây là bằng chứng chính của đòn 1.

aws organizations leave-organization --region us-east-1              # AccessDenied
aws s3api delete-bucket --bucket techx-corp-tf3-audit-trail-ap-southeast-1-197826770971   # AccessDenied
aws kms schedule-key-deletion --key-id 5d5b2295-a8e4-46ba-b6c5-fc08e81608be \
  --pending-window-in-days 30 --region ap-southeast-1                # AccessDenied

# --- (b) BẢNG A: phải THÀNH CÔNG ---
aws eks describe-cluster --name techx-corp-tf3 --region ap-southeast-1 --query cluster.status
aws secretsmanager get-secret-value --secret-id <flagd-sync-secret> --region ap-southeast-1 --query Name
aws s3api get-object --bucket techx-corp-tf3-audit-trail-ap-southeast-1-197826770971 \
  --key <một key bất kỳ> /tmp/probe.gz          # đọc archive vẫn phải được
aws ecr describe-images --repository-name techx-corp --region ap-southeast-1 --max-items 1

# --- (c) XÁC NHẬN TRAIL KHÔNG HỀ DỪNG ---
aws cloudtrail get-trail-status \
  --name techx-corp-tf3-audit-detection-ap-southeast-1-trail \
  --region ap-southeast-1 --query IsLogging     # true
```

**Bước 3 — quan sát 30 phút.** Không attach tiếp cho tới khi cả 4 dòng dưới đều xanh:

| Kiểm | Lệnh / nơi xem |
|---|---|
| ArgoCD | `kubectl get applications -n argocd` → tất cả `Synced/Healthy` |
| external-secrets | `kubectl get externalsecret -A` → `SecretSynced`, không có lỗi refresh |
| Karpenter | `kubectl logs -n karpenter deploy/karpenter --tail=50` → không có `AccessDenied` |
| SLO sản phẩm | Grafana: checkout / browse / cart — tỉ lệ thành công và p95 không đổi |

**Bước 4 — attach SCP-2, lặp lại bước 2–3 với phần SCP-2 của ma trận:**

```bash
# Ở A
aws organizations attach-policy --region us-east-1 \
  --policy-id "$SCP2_ID" --target-id "$OU_ID"
```

```bash
# Ở B — bảng B phần alert plane
aws events disable-rule --name techx-corp-tf3-audit-detection-ap-southeast-1-g1-audit \
  --region ap-southeast-1                                            # AccessDenied
aws lambda put-function-concurrency \
  --function-name techx-corp-tf3-audit-detection-ap-southeast-1-router \
  --reserved-concurrent-executions 0 --region ap-southeast-1         # AccessDenied
aws sns unsubscribe --subscription-arn <một subscription alert> --region ap-southeast-1   # AccessDenied
aws logs delete-log-group \
  --log-group-name /aws/lambda/techx-corp-tf3-audit-detection-ap-southeast-1-router \
  --region ap-southeast-1                                            # AccessDenied

# Bảng A — thêm người nhận vẫn phải được (§7.2 điểm 2)
aws sns subscribe --topic-arn arn:aws:sns:ap-southeast-1:197826770971:techx-corp-tf3-audit-detection-ap-southeast-1-alerts \
  --protocol email --notification-endpoint <email mentor> --region ap-southeast-1
```

**Bước 5 — chứng minh CI không gãy (§6.2):**

```bash
# Chạy terraform-plan.yml qua workflow_dispatch → phải xanh, "No changes" cho audit plane
# Rồi chạy terraform-apply.yml với plan đó → phải xanh (no-op)
```

Đây là bằng chứng cho luận điểm cốt lõi §6.2: SCP chỉ deny **mutation**, `plan` toàn read nên không chạm, `apply` không gọi API ghi khi không có diff.

**Bước 6 — kiểm tra alert đã kêu.** Mỗi lệnh `AccessDenied` ở bước 2 và 4 phải sinh một alert:

| Lệnh đã thử | Rule bắt | Ghi lại |
|---|---|---|
| `stop-logging` | `g1-audit` | thời điểm email tới − `eventTime` = time-to-detect |
| `events disable-rule` | `g7-audit-controls` | |
| `lambda put-function-concurrency` | `g7-audit-controls` | |
| `sns unsubscribe` | `g7-audit-controls` | |

Trong nội dung alert phải thấy `errorCode = AccessDenied` — đó là thứ phân biệt "đã thử và bị chặn" với "đã làm thành công". Nếu router chưa đưa `errorCode` vào nội dung email thì bổ sung **trước** Phase 5 (đây là thay đổi ở `lambda/index.py`, phải làm **trước** khi khoá hoặc qua change window §6.3).

**Nếu bất kỳ dòng nào ở bảng A thất bại → rollback ngay:**

```bash
# Ở A — nhanh nhất, một lệnh:
aws organizations move-account --region us-east-1 \
  --account-id 197826770971 \
  --source-parent-id "$OU_ID" --destination-parent-id "$ROOT_ID"
# Hoặc gỡ đúng SCP gây lỗi:
aws organizations detach-policy --region us-east-1 --policy-id "$SCP2_ID" --target-id "$OU_ID"
```

**Checklist ra khỏi Phase 4:**

- [ ] `list-policies-for-target` trên OU → `FullAWSAccess` + 2 SCP
- [ ] Bảng B: **mọi lệnh** `AccessDenied`, `errorMessage` có chứa ARN của SCP — đã chụp màn hình
- [ ] Bảng A: **mọi lệnh** thành công
- [ ] Bảng C: mọi lệnh thành công (SCP không cản resource ngoài audit)
- [ ] **Bảng D: D1 thành công (R làm được) · D2 `AccessDenied` (người khác không) · D3 `AccessDenied` kể cả R tự sửa (không ai sửa được R)**
- [ ] Trail `IsLogging: true` xuyên suốt, không gián đoạn một giây nào
- [ ] ArgoCD / external-secrets / Karpenter / SLO không đổi sau 30 phút với **cả hai** SCP
- [ ] `terraform plan` + `apply` no-op qua CI xanh
- [ ] Mọi lệnh bảng B đều sinh alert, có `errorCode=AccessDenied`, time-to-detect đã ghi
- [ ] (nếu chọn A2) Access key của account A **đã xoá**

---

## 10. Verify

### 10.1 Org + SCP

```bash
# Từ account A (593777010472)
aws organizations describe-organization --query 'Organization.FeatureSet'            # ALL
aws organizations list-roots --query 'Roots[0].PolicyTypes'                          # SERVICE_CONTROL_POLICY ENABLED
aws organizations list-accounts-for-parent --parent-id <ou-workload-id>              # có 197826770971
aws organizations list-policies-for-target --target-id <ou-workload-id> \
  --filter SERVICE_CONTROL_POLICY                                                    # FullAWSAccess + 2 SCP

# Từ account B (197826770971)
aws organizations describe-organization --query 'Organization.Id'                    # trả org id, không throw
aws cloudtrail get-trail-status --name techx-corp-tf3-audit-detection-ap-southeast-1-trail \
  --query 'IsLogging'                                                                # true
aws s3api get-object-lock-configuration \
  --bucket techx-corp-tf3-audit-trail-ap-southeast-1-197826770971                    # COMPLIANCE / 90
```

### 10.2 Ma trận kiểm chứng SCP

Chạy **từ B**, bằng IAM user `AdministratorAccess` — đúng vai kẻ tấn công trong đề bài.

**Bảng A — BASELINE, tất cả phải THÀNH CÔNG.** Sai một dòng = SCP quá rộng, rollback ngay.

| Lệnh | Bảo vệ điều gì |
|---|---|
| `aws eks describe-cluster --name techx-corp-tf3` | EKS control plane |
| `aws secretsmanager get-secret-value --secret-id <flagd-sync>` | external-secrets |
| `aws ec2 describe-instances` · `run-instances --dry-run` | Karpenter |
| `aws s3 cp <file> s3://techx-tf3-197826770971-tfstate/probe` | Terraform state |
| `aws ecr describe-images --repository-name techx-corp` | CI push image |
| `aws rds describe-db-instances` · `aws kafka list-clusters` | datastore |
| `aws sns subscribe --topic-arn <alerts> --protocol email …` | thêm người nhận vẫn được (§7.2 điểm 2) |
| `aws s3api get-object --bucket <audit-archive> --key <bất kỳ>` | đọc archive để `validate-logs` |
| `terraform plan` qua CI | §6.2 |

**Bảng B — KILL SWITCH, tất cả phải `AccessDenied` kèm `errorMessage` nêu ARN SCP.**

| Lệnh | SCP |
|---|---|
| `aws cloudtrail stop-logging --name …-trail` | 1 |
| `aws cloudtrail delete-trail --name …-trail` | 1 |
| `aws cloudtrail update-trail --name …-trail --no-include-global-service-events` | 1 |
| `aws cloudtrail put-event-selectors --trail-name …-trail …` | 1 |
| `aws s3api delete-bucket --bucket techx-corp-tf3-audit-trail-…` | 1 |
| `aws s3api put-bucket-policy --bucket techx-corp-tf3-audit-trail-… …` | 1 |
| `aws s3api put-object-lock-configuration --bucket … --object-lock-configuration …` | 1 |
| `aws kms schedule-key-deletion --key-id 5d5b2295-…` | 1 |
| `aws organizations leave-organization` | 1 |
| `aws events disable-rule --name techx-corp-tf3-audit-detection-ap-southeast-1-g1-audit` | 2 |
| `aws events delete-rule --name …-g5-secrets` | 2 |
| `aws lambda update-function-code --function-name …-ap-southeast-1-router …` | 2 |
| `aws lambda put-function-concurrency --function-name …-router --reserved-concurrent-executions 0` | 2 |
| `aws sns delete-topic --topic-arn …-alerts` | 2 |
| `aws sns unsubscribe --subscription-arn <bất kỳ subscription alert nào>` | 2 |
| `aws iam delete-role-policy --role-name techx-corp-tf3-audit-detection-ap-southeast-1-lambda-role …` | 2 |
| `aws logs delete-log-group --log-group-name /aws/lambda/techx-corp-tf3-audit-detection-ap-southeast-1-router` | 2 |
| `aws sqs delete-queue --queue-url …-lambda-dlq` | 2 |

**Bảng C — CÙNG ACTION, RESOURCE KHÁC. Tất cả phải THÀNH CÔNG** — chứng minh SCP không cản vận hành bình thường.

| Lệnh |
|---|
| `aws kms schedule-key-deletion` trên một KMS key test (rồi `cancel-key-deletion`) |
| `aws s3api delete-bucket` trên một bucket test rỗng |
| `aws events delete-rule` trên một rule test không thuộc audit plane |
| `aws lambda delete-function` trên một function test |
| `aws logs delete-log-group` trên một log group không phải audit |

**Bảng D — ROLE BẢO TRÌ R (§7.5). Chứng minh: chỉ R làm được, không ai khác, và không ai sửa được R.**

Ba nhóm, chạy sau khi attach SCP-2:

*D1 — R LÀM ĐƯỢC hai việc được uỷ quyền* (assume R trước: `aws sts assume-role --role-arn arn:aws:iam::197826770971:role/techx-corp-tf3-audit-maintainer --role-session-name maint`, rồi export creds tạm):

| Lệnh (dưới danh nghĩa R) | Kỳ vọng |
|---|---|
| `aws lambda update-function-code --function-name techx-corp-tf3-audit-detection-ap-southeast-1-router --zip-file fileb://router.zip` | **thành công** |
| `aws sns subscribe --topic-arn …-alerts --protocol email --notification-endpoint <email test>` | **thành công** |
| `aws sns unsubscribe --subscription-arn <sub test>` | **thành công** |

*D2 — NGƯỜI KHÁC KHÔNG LÀM ĐƯỢC* (dưới danh nghĩa admin thường trong B, **không** phải R):

| Lệnh | Kỳ vọng |
|---|---|
| `aws lambda update-function-code …-router …` | `AccessDenied` (SCP-2 `DenyRouterCodeUpdateExceptMaintainer`) |
| `aws sns subscribe --topic-arn …-alerts …` | `AccessDenied` (`DenySubscribeExceptMaintainer`) |
| `aws sns unsubscribe --subscription-arn …` | `AccessDenied` (`DenyUnsubscribeExceptMaintainer`) |

*D3 — KHÔNG AI SỬA/XOÁ ĐƯỢC R* (thử dưới danh nghĩa admin thường **và** dưới danh nghĩa chính R — cả hai phải `AccessDenied`):

| Lệnh | Kỳ vọng |
|---|---|
| `aws iam delete-role --role-name techx-corp-tf3-audit-maintainer` | `AccessDenied` (`DenyMaintainerRoleTampering`) |
| `aws iam update-assume-role-policy --role-name techx-corp-tf3-audit-maintainer --policy-document …` (thử nới trust cho mình) | `AccessDenied` |
| `aws iam put-role-policy --role-name techx-corp-tf3-audit-maintainer …` (thử nới quyền cho R) | `AccessDenied` |
| `aws iam attach-role-policy --role-name techx-corp-tf3-audit-maintainer --policy-arn arn:aws:iam::aws:policy/AdministratorAccess` | `AccessDenied` |

D3 chạy **cả bằng R tự sửa mình** là quan trọng: chứng minh R không tự leo thang được. Nếu bất kỳ dòng D3 nào thành công → R chưa được đóng băng đúng, **dừng và sửa SCP-2 trước khi demo**.

### 10.3 Không có đường ảnh hưởng tới SLO sản phẩm

| Thứ | v2 có đụng không |
|---|---|
| `flagd` / `values-flagd-sync.yaml` / `/flagservice` trong Envoy | **Không.** v2 không chạm file nào trong `gitops/` hay chart |
| Filter `envoy.filters.http.fault` | **Không** |
| EKS workload, HPA, Karpenter, ArgoCD | **Không.** Không có resource Kubernetes nào |
| VPC / ALB / CloudFront / Cloudflare | **Không** |
| RDS / ElastiCache / MSK | **Không** |
| Đường đọc secret của external-secrets | **Không** — SCP không deny `secretsmanager:GetSecretValue`. Bảng A kiểm chứng |
| Đường CI build/push ECR | **Không.** Bảng A kiểm chứng |

Rủi ro duy nhất chạm được workload là **SCP quá rộng**. Bảng A + rollback move-OU (§12) là lớp bảo vệ.

### 10.4 Đo time-to-detect

Với mỗi đòn, ghi 3 mốc: `eventTime` trong CloudTrail → timestamp router xử lý → timestamp email nhận. Báo cáo `p50`/`max` trên ≥5 lần thử. Kiến trúc alert **không đổi** so với M11 nên ngưỡng đã cam kết ở M11 vẫn áp dụng — nhưng **phải đo lại** để chứng minh, vì event bây giờ mang `errorCode=AccessDenied` (nhánh xử lý có thể khác).

---

## 11. Nghiệm thu — ba đòn mentor tự thử

Mentor được cấp **IAM user `AdministratorAccess` trong B**, và **không có gì ở A**. Đó chính là mô hình đe doạ đề bài mô tả.

### Đòn 1 — Làm mù

```bash
aws cloudtrail stop-logging \
  --name techx-corp-tf3-audit-detection-ap-southeast-1-trail --region ap-southeast-1
```

**Phải thấy:**
```
An error occurred (AccessDeniedException) ... with an explicit deny in a service
control policy: arn:aws:organizations::593777010472:policy/o-xxxx/service_control_policy/p-xxxx
```

Team chỉ ra tiếp:
1. `get-trail-status` → `IsLogging: true` — **trail không hề dừng**
2. Email alert `g1` CRITICAL đã tới, có `errorCode=AccessDenied`, principal, IP nguồn, thời điểm
3. Bản ghi thô của chính lần thử đó trong trail (`eventName=StopLogging`) — vết *"ai tắt, lúc mấy giờ"*
4. `list-policies-for-target` từ A: SCP đang attach — thứ chặn nằm **ngoài** account mentor có quyền

Lặp lại với `delete-trail`, `put-event-selectors`, `leave-organization`, `events disable-rule`, `lambda put-function-concurrency`, `sns unsubscribe`.

### Đòn 2 — Làm hụt

```bash
aws s3 cp s3://techx-tf3-197826770971-tfstate/eks-baseline/terraform.tfstate /tmp/
aws secretsmanager get-secret-value --secret-id <flagd-sync-secret>
```

**Team chỉ ra:** vết `GetObject` (data event, advanced selector `ApprovedSensitiveS3Objects`) và `GetSecretValue` (management read event), kèm alert `g5`.

### Đòn 3 — Làm mỏng/sửa

```bash
aws cloudtrail validate-logs \
  --trail-arn arn:aws:cloudtrail:ap-southeast-1:197826770971:trail/techx-corp-tf3-audit-detection-ap-southeast-1-trail \
  --start-time <UTC> --region ap-southeast-1
```

**Phải ra:** 0 digest thiếu, 0 file `INVALID`. Kèm: mentor thử `aws s3api delete-object` trên archive → bị chặn **hai lớp độc lập**: (1) SCP-1 `DenyAuditArchiveTampering` chặn xoá với mọi principal kể cả root, suốt thời gian org+SCP còn hiệu lực; (2) Object Lock COMPLIANCE (14 ngày) chặn xoá object mới ở tầng S3, *không ai rút ngắn được kể cả root*. Về retention: 30 ngày lifecycle phủ trọn vòng đời chương trình tính đến ngày demo (§5) — nói thẳng đây là mức phủ cửa sổ điều tra của bài tập, không phải lưu trữ bất biến nhiều tháng.

### Câu hỏi mentor có thể hỏi ngược — chuẩn bị sẵn

| Câu hỏi | Trả lời |
|---|---|
| *"Thế người nắm account A thì sao?"* | Đúng, A không bị SCP che. Đó là mô hình niềm tin chuẩn của AWS, không sửa được bằng thiết kế. Giảm thiểu: root MFA, không IAM user/access key ở A, credential ≥2 người giữ, và mentor không được cấp gì ở A. §13 #1 |
| *"Detach SCP thì có kêu không?"* | Không — A không có trail. Nhưng hệ **suy biến an toàn**: detach xong vẫn phải `StopLogging`, và lệnh đó vẫn bị ghi + vẫn kêu `g1`. Không mua được sự im lặng. §6.4 |
| *"Ai đó gọi API Unsubscribe thì sao?"* | Bị chặn — `sns:Unsubscribe` giờ deny với mọi principal **trừ role bảo trì R**. Chỉ R thêm/xoá được người nhận. Lưu ý phân biệt: **API** Unsubscribe bị SCP chặn; còn **link** Unsubscribe trong email là hành động không cần IAM → SCP không chạm được, bù bằng kiểm `list-subscriptions-by-topic` định kỳ. §7.5 |
| *"Vậy chỉ role R sửa được audit plane — R có phải lỗ hổng không?"* | R chỉ làm đúng 2 việc (`UpdateFunctionCode` + thêm/xoá người nhận), trên đúng resource audit, không có `DeleteFunction`/`PutFunctionConcurrency`/đổi config. R **không tự nới quyền cho mình** được (SCP `DenyMaintainerRoleTampering`), **không ai assume trộm** (trust hẹp + MFA, đóng băng), và mọi lần R chạy đều kêu `g7`. Ai muốn đổi chính R phải đi qua account A. §7.5 |
| *"Thế A sửa R kiểu gì — A có tay trong B à?"* | Không. SCP áp lên **mọi** role trong B kể cả role A assume vào, nên không đường nào trong B sửa được R. A chỉ **gỡ SCP** (từ A) thì việc sửa R mới mở ra. A cầm chìa, không cầm tay. §7.5 mảnh 3 |
| *"CI vẫn deploy được chứ?"* | Được. SCP chỉ deny **mutation** trên audit plane; `terraform plan` toàn read, `apply` không gọi API ghi khi không có diff. Đã chứng minh ở Phase 4.6. §6.2 |

---

## 12. Rollback

| Tình huống | Rollback | Thời gian |
|---|---|---|
| SCP chặn nhầm, production đang hỏng | **Move B ra khỏi OU `Workload`** (từ A) | ~tức thì, 1 lệnh |
| Chỉ SCP-2 gây vấn đề | `detach-policy` riêng SCP-2 | ~tức thì |
| Cần sửa audit plane có kế hoạch | Change window §6.3 | ~5 phút |
| Cần huỷ toàn bộ lớp org | Từ A: `remove-account-from-organization`. B trở lại độc lập, audit plane **nguyên vẹn** vì nó chưa từng rời B | ~15 phút |

**Không rollback được:** hoá đơn khoảng hở credit (§2); object đang bị COMPLIANCE lock.

**Break-glass:** SCP-1 không có ngoại lệ principal nào; SCP-2 chỉ chừa role R cho hai việc bảo trì (§7.5). Đường lui để **gỡ/sửa guardrail** vẫn duy nhất đi qua A — R không tự gỡ SCP được. Root credential + MFA của A phải để ít nhất **2 người trong TF3** lấy được. Ghi vào runbook.

> Lưu ý quan trọng khác biệt với phương án organization trail: ở v2, **rời org không làm mất log**. Trail, bucket, digest chain đều ở B và không đi đâu cả. Rủi ro "gỡ org là mất bằng chứng" **không tồn tại** trong kiến trúc này.

---

## 13. Rủi ro tồn dư — cần ký nhận

| # | Rủi ro | Vì sao chấp nhận / giảm thiểu |
|---|---|---|
| 1 | **Account A không được SCP bảo vệ.** Ai vào A thì detach được tất cả | Không sửa được — theo thiết kế của AWS, SCP không áp lên management account. Giảm thiểu: root MFA, không IAM user/access key, credential ≥2 người, mentor không có gì ở A. Và §6.4: detach **không** mua được sự im lặng |
| 2 | **Detach SCP không sinh alert** (A không có trail) | §6.4 — hệ suy biến về đúng mức M12 v1, không bao giờ tệ hơn. Canary GitHub Actions (§6.3) bịt được, $0, tuỳ chọn |
| 3 | **Khoảng hở credit $200–460** | §2. Đã lượng hoá, 3 phương án, cần chữ ký |
| 4 | **Link Unsubscribe trong email SNS không cần IAM** → SCP không chặn được | Giảm thiểu: kiểm `list-subscriptions-by-topic` định kỳ; cân nhắc chuyển sang một mailing list làm endpoint duy nhất. API Unsubscribe thì đã bị SCP-2 chặn (trừ R) |
| 5 | **Audit plane bị đóng băng** — mọi thay đổi phải qua change window | Có chủ ý (§6.2c). Audit plane đã xong, không có kế hoạch đổi trước 31/07. Quy trình §6.3 |
| 6 | **`sns:Unsubscribe`/`Subscribe` deny ở `Resource:"*"`/topic** | Đã kiểm chứng cả account chỉ có 2 SNS topic, đều là topic alert → 0 collateral. Ngoại lệ chỉ mở cho role R. Nếu sau này có topic non-audit, `Subscribe` bị chặn cho principal thường — phải xem lại |
| 6b | **Retention 14/30 không cho lưu bất biến nhiều tháng hậu chương trình** | Chấp nhận có chủ ý (§5). 30 ngày phủ trọn vòng đời chương trình tại demo; SCP-1 chặn xoá archive suốt thời gian còn org. Nâng về sau là thay đổi một chiều qua change window |
| 6c | **Role R là đặc quyền tập trung** — điểm tin cậy dời về user `CDOAuditTeam` (ai giữ được credential + MFA của user này thì bảo trì được audit plane) | Giảm thiểu: quyền R tối thiểu (2 việc), trust chỉ `CDOAuditTeam` + MFA + đóng băng (`DenyMaintainerRoleTampering`), R không tự leo thang, mọi hành động R kêu `g7`. `CDOAuditTeam` đã còn `ReadOnlyAccess` (+ assume-R); giữ MFA của nó chặt là điểm mấu chốt còn lại |
| 7 | **Drift ngoài dự kiến giữa Terraform và AWS làm `apply` gãy sau khi khoá** | Giảm thiểu: đảm bảo `plan` sạch cho audit plane trước khi attach. Nếu vẫn gãy: change window §6.3 |
| 8 | **Cost Explorer đổi chỗ** — sau khi join, số liệu đọc từ A | Quy trình đo hàng tuần (`RECORD_TYPE=Usage`) phải thêm `GROUP_BY=LINKED_ACCOUNT`. Cập nhật runbook cost |
| 8b | **Nếu sau này B rời org, B MẤT quyền xem dữ liệu cost/usage của quãng thời gian nó là member.** AWS: *"the account no longer has access to cost and usage data from the time range when the account was a member of the organization"* | **Xuất dữ liệu cost trước và trong lúc là member** — số liệu §2/§8 và báo cáo trụ Cost đều dựa vào nó. Lưu CSV vào `docs/evidence/`. Nếu B rejoin đúng org cũ thì dữ liệu quay lại, nhưng đừng phụ thuộc vào điều đó |
| 9 | **Bucket archive vẫn ở B**, không phải account tách biệt | Đánh đổi có chủ ý để tiết kiệm $71/tháng và tránh rủi ro triển khai. Bù bằng 2 lớp: SCP-1 deny xoá + Object Lock COMPLIANCE. §4.2 |

---

## 14. Definition of Done

- [ ] §2 được Tech Lead ký, phương án timing đã chốt
- [ ] `validate-logs` baseline chạy **trước** khi attach SCP (mốc so sánh cho đòn 3)
- [ ] Account A `593777010472`: root có MFA, **không có IAM user / access key nào**, có payment method
- [ ] `describe-organization` từ A → `FeatureSet: ALL`; `list-roots` → `SERVICE_CONTROL_POLICY: ENABLED`
- [ ] B nằm trong OU `Workload`; `list-policies-for-target` thấy `FullAWSAccess` + `TF3-DenyAuditKillSwitch` + `TF3-DenyAlertPlaneKillSwitch`
- [ ] Role `techx-corp-tf3-audit-maintainer` (R) tồn tại, tạo **trước** khi attach SCP-2; trust policy trỏ `user/CDOAuditTeam` + `MultiFactorAuthPresent`; `CDOAuditTeam` có MFA (`…:mfa/AuditDevice` — đã verify)
- [ ] `CDOAuditTeam` = `ReadOnlyAccess` (đã gỡ AdminAccess) **+ policy assume-R đã thêm** (ReadOnlyAccess không có `sts:AssumeRole`)
- [ ] `CDOAuditTeam` switch-role vào R thành công (smoke test trước khi khoá)
- [ ] Ma trận §10.2: **bảng A toàn thành công · bảng B toàn `AccessDenied` · bảng C toàn thành công · bảng D (D1 R làm được / D2 người khác không / D3 không ai sửa được R kể cả R)**
- [ ] `errorMessage` của bảng B có chứa ARN SCP (chụp lại làm evidence)
- [ ] 30 phút sau mỗi lần attach: ArgoCD Synced/Healthy, SLO checkout/browse/cart không đổi
- [ ] 1 lần `terraform plan` + `apply` no-op qua CI sau khi khoá → xanh (chứng minh §6.2)
- [ ] Trail vẫn `IsLogging: true` xuyên suốt
- [ ] `validate-logs` chạy sạch trước mặt mentor
- [ ] Time-to-detect đo lại, `p50`/`max` trên ≥5 lần
- [ ] (tuỳ chọn) Canary §6.3 chạy và fail đúng khi test detach
- [ ] ADR `0013-mandate-12-org-scp-anti-defeat.md` ký tên
- [ ] Runbook `mandate-12-org-scp-demo.md` — mentor tự chạy được, không cần team đứng cạnh
- [ ] Evidence trong `docs/evidence/mandate-12-org/`: screenshot org + SCP, output 3 bảng ma trận, CSV credit sharing preference, change-log
- [ ] `CLAUDE.md` cập nhật: B là member của org `<org-id>`, management account `593777010472`, audit plane đóng băng + quy trình change window

---

## 15. Việc cần Tech Lead quyết

| # | Câu hỏi | Khuyến nghị |
|---|---|---|
| 1 | **§2 — A / B / C?** Chấp nhận $200–460 tiền thật để có vế "bị chặn"? | **A**, kèm cam kết ép chi phí xuống ngay sau khi các demo khác xong |
| 2 | Ai giữ credential account A `593777010472`? | Phải ≥2 người lấy được, root có MFA, không tạo IAM user |
| 3 | ~~Object Lock 90 hay 35 ngày?~~ **Đã chốt: giữ 14/30** | Bất biến archive do SCP-1 bảo đảm; 30 ngày phủ trọn chương trình (§5). Ghi lập luận yêu cầu 4 vào ADR |
| 4 | Attach cả SCP-2 hay chỉ SCP-1? | **Cả hai.** SCP-1 đủ để qua đề bài; SCP-2 là thứ chặn được các kill switch im lặng (concurrency=0, thay code router, unsubscribe) |
| 5 | Làm canary §6.3 không? | **Có** — $0, không thêm resource AWS, bịt được rủi ro #2 |
| 6 | ~~Trust model cho R?~~ **ĐÃ CHỐT: T1 với `user/CDOAuditTeam`** (§7.5 mảnh 2) | Đã tạo + MFA (`…:mfa/AuditDevice`), console-only. Trust policy trỏ user này + `MultiFactorAuthPresent`. Không còn là câu hỏi |
| 6b | ~~Thu hẹp `CDOAuditTeam`?~~ **ĐÃ LÀM: `ReadOnlyAccess`.** Việc còn lại: thêm policy `sts:AssumeRole` trên R (ReadOnlyAccess không có sẵn) | Không còn là câu hỏi — chỉ còn một bước thực thi ở Phase 3.5.3 |
| 7 | R được `UpdateFunctionCode` — có cần thêm `UpdateFunctionConfiguration` không? | **Không** (mặc định). Đổi config (handler/role/env) là đường leo thang tinh vi; để qua change window. Chỉ mở nếu vận hành thực tế đòi |

---

## 16. Tài liệu liên quan

- [`mandate-12-execution-plan.md`](mandate-12-execution-plan.md) — M12 v1, đã merge + apply (PR #403). v2 chồng lên, không thay thế
- [`docx_cdo02/mandate11-audit-detection-review.md`](docx_cdo02/mandate11-audit-detection-review.md) — thiết kế detection M11, nguồn của group 1–6
- [`docx_cdo02/mandate11-completion-evidence-guide.md`](docx_cdo02/mandate11-completion-evidence-guide.md)
- [`cost-breakdown-2026-07-22.md`](cost-breakdown-2026-07-22.md) — kế hoạch cắt về $269,7/tuần, liên quan trực tiếp §2
- AWS: [SCPs](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html) · [Applying AWS credits](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html) · [Consolidated billing effective date](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-effective.html) · [Troubleshoot SCP explicit deny](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_access-denied.html)

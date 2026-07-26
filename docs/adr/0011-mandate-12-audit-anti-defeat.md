# ADR 0011 — Mandate 12: Audit không thể bị đánh bại: các quyết định thiết kế

**Date:** 2026-07-22

**Decision owner (signed):** Huu Tai Ngo — CDO02 / TF3 Auditability lead

**Collaborators/reviewers:** Ban Kiểm toán & An ninh TechX Corp; CD01/IaC owner; mentor acceptance pending

**Status:** Accepted in design; deployment blocked pending mandatory gates (owner approval, SNS confirmation, MFA, IAM hardening)

**Pillars:** Auditability (primary), Security, Operational Excellence

---

## Context

Mandate 12 yêu cầu TF3 chứng minh audit trail **không thể bị vô hiệu hóa bằng ba thủ thuật** mà không cần xóa một dòng log nào:

- **Làm mù (Blind window):** tắt/dừng CloudTrail trước khi hành động.
- **Làm hụt (Coverage gap):** hành động ở vùng không được ghi — ví dụ đọc S3 object hoặc lấy secret khi data-event log chưa bật.
- **Làm mỏng/sửa (Thin/tampered log):** log quá sơ sài, không dựng lại được nội dung đã thay đổi; hoặc log bị sửa lén sau khi ghi.

Ở Mandate 11, hạ tầng đã tạo ra một CloudTrail trail multi-region, S3 archive có Object Lock `GOVERNANCE 14 ngày`, 6 EventBridge rules và 2 Lambda router. Discovery AWS CLI read-only ngày 21/07/2026 xác nhận đây là baseline live đang vận hành trên account `197826770971`, region `ap-southeast-1`.

Ràng buộc cứng: trong ngân sách ~$300/tuần/TF; không thay đổi storefront public, ops private, EKS workload, network, datastore, flagd hay application source.

---

## Decision 1: Tái sử dụng và nâng cấp hạ tầng M11 thay vì tạo trail/archive mới

**Quyết định chọn:** Upgrade trail M11 in-place bằng cách sửa `infra/modules/audit-detection` và `infra/live/production`. Không tạo trail M12 thứ hai.

### Alternatives considered

| Phương án | Lý do loại bỏ |
|---|---|
| Tạo trail M12 riêng biệt | Duplicate management events → tăng chi phí CloudTrail vô ích; hai archive song song làm phức tạp `validate-logs` và tăng storage; không đạt ngân sách $300/tuần |
| Cross-account / Organization trail | Boundary isolation mạnh hơn, nhưng yêu cầu ít nhất 2 AWS account và AWS Organizations — nằm ngoài tầm với của một account Free Tier đơn lẻ |
| CloudTrail Lake / Insights | Query SQL tiện lợi nhưng tốn thêm chi phí ingestion; không thay thế được digest chain WORM — không chọn cho MVP |

### Consequences and trade-offs

**Positive:**
- Một source of truth duy nhất cho management events; không duplicate cost.
- Tận dụng được ngay alert plane M11 (6 EventBridge rules, 2 Lambda routers, 2 SNS topics) làm nền để thêm group 7/8 và heartbeat M12.
- State Terraform rõ ràng: ai sở hữu resource thì sửa tại root đó.

**Negative / residual risk:**
- PR audit foundation phải sửa `infra/modules/audit-detection` và `infra/live/production` — không còn hoàn toàn độc lập với production root. Mọi thay đổi ngoài audit resources (EKS, network, datastore) là NO-GO và sẽ bị chặn ở gate review plan.
- Object đã ghi trước upgrade giữ retention cũ (`GOVERNANCE 14 ngày`). Claim M12 chỉ bắt đầu từ cutover timestamp khi selectors mới active, digest healthy và object mới có `COMPLIANCE`.

---

## Decision 2: Object Lock nâng lên COMPLIANCE, thời hạn đặt theo vòng đời bài tập

**Quyết định chọn:** Đổi default Object Lock cho object **mới** từ `GOVERNANCE 14 ngày` sang `COMPLIANCE 14 ngày`. Giữ lifecycle 30 ngày như M11.

Vì bài tập kết thúc vào 31/07/2026 và account chạy trên thẻ của owner cá nhân, thời hạn lưu trữ được căn chỉnh theo vòng đời bài tập (14 ngày đủ để phủ cửa sổ demo/nghiệm thu). Thay đổi thời hạn, **không** thay đổi mode — vì `COMPLIANCE` là cốt lõi để đảm bảo "kể cả root cũng không xóa được", điều mà GOVERNANCE không làm được.

### Alternatives considered

| Phương án | Lý do loại bỏ |
|---|---|
| Giữ GOVERNANCE 14 ngày của M11 | Admin vẫn có thể xóa object bằng `s3:BypassGovernanceRetention`; cả 4 IAM user đều `AdministratorAccess` nên đây là WORM trên danh nghĩa |
| COMPLIANCE 365 ngày | Vượt xa vòng đời bài tập. `COMPLIANCE` không thể rút ngắn sau khi set, nên chi phí lưu trữ sẽ đeo bám owner ròng rã 1 năm trời kể cả sau khi bài tập kết thúc |
| Bỏ hẳn lifecycle | Ngược mục tiêu: lifecycle chính là thứ xoá object. Bỏ đi thì log giữ vĩnh viễn, hoá đơn tăng chứ không giảm; và bucket `prevent_destroy` chỉ xoá được khi rỗng nên mất luôn đường dọn dẹp. Heartbeat cũng đọc lifecycle như một invariant |
| Dùng Glacier Instant Retrieval ngay lần đầu | Minimum storage duration 90 ngày dài hơn cả vòng đời dữ liệu ở cấu hình này — transition sẽ đắt hơn là để nguyên Standard |

### Consequences and trade-offs

**Positive:**
- `COMPLIANCE` mode: kể cả root user không thể xóa object trong thời hạn lock — WORM thực sự, không phải WORM "trên danh nghĩa". Đây là phần claim của mandate, và rút ngắn thời hạn không làm mất nó.
- 14 ngày phủ hết cửa sổ demo, nghiệm thu và điều tra sau bài tập (cutover ~24/07 → hết lock ~07/08).
- Lifecycle 30 ngày cho 16 ngày đệm sau khi hết lock: đủ để export bằng chứng, rồi object tự hết hạn và bucket dọn được.
- Không thay đổi lifecycle so với M11 → biến mất rủi ro "lifecycle 400 áp cho cả object hiện có" và không cần cost approval trước apply.

**Negative / residual risk:**
- Cửa sổ điều tra thực tế chỉ có 14 ngày. Nếu phát hiện sự cố muộn hơn 14 ngày, object gốc có thể đã hết hạn. Mức độ rủi ro này được **chấp nhận** vì hệ thống ngừng tồn tại sau 31/07/2026; nếu tái sử dụng kiến trúc này cho môi trường sống (production thật), phải nâng thời gian lưu trữ lên 365 ngày.
- `COMPLIANCE` vẫn không thể rút ngắn sau khi set — 14 ngày cũng là 14 ngày. Apply vẫn phải có saved plan hash và gate review trước.
- Áp dụng cho object **mới**; không hồi tố object đã ghi.

---

## Decision 3: Bổ sung S3 Object data-event selectors (chống làm hụt)

**Quyết định chọn:** Thêm advanced S3 Object data-event selectors với **exact ARN prefix** cho các bucket/prefix được owner phê duyệt là `Sensitive`. Không bật all-S3 data events.

### Alternatives considered

| Phương án | Lý do loại bỏ |
|---|---|
| Bật all-S3 data events (wildcard) | Chi phí không kiểm soát được — mỗi `GetObject` trên mọi bucket đều tốn phí; nhiễu log khổng lồ; không bám được vào ngân sách $300/tuần |
| Không bật data events | Coverage gap lớn nhất của Mandate 12: kẻ tấn công có thể dump toàn bộ S3 nhạy cảm mà không để lại vết — thất bại yêu cầu 2 của đề bài |
| Dùng S3 Server Access Log thay CloudTrail data events | Không có actor identity, không chain được vào digest CloudTrail, không đáp ứng "toàn vẹn mật mã" |

### Consequences and trade-offs

**Positive:**
- Mọi `GetObject` trên prefix nhạy cảm đều tạo CloudTrail event với actor/session/IP/resource — đóng hoàn toàn coverage gap exfiltration qua S3.
- Secrets Manager `GetSecretValue` đã nằm trong management events; không cần data events riêng cho secret.
- Audit archive bucket được **exclude** khỏi data selector để tránh vòng lặp logging (recursive).

**Negative / residual risk:**
- Chi phí tỷ lệ thuận với số lần đọc; cần forecast từ owner trước apply.
- Coverage chỉ bắt đầu từ cutover timestamp khi selector mới active.
- Blocker hiện tại: chưa có owner phê duyệt exact bucket/prefix; approval table trong `m12-coverage-v2.1.md` phải hoàn tất trước khi apply.

### S3 bucket scope — đề xuất phân loại (chờ owner duyệt)

Dựa trên inventory live trong `m12-coverage-v2.1.md`, đề xuất phân loại như sau. Tên prefix thực tế phải được owner xác nhận trước khi điền vào `production.auto.tfvars`.

#### Nên bật ưu tiên

| Bucket | Scope đề xuất | Lý do |
|---|---|---|
| `techx-aiops-playbooks-f6230446` | Prefix chứa playbook, hoặc toàn bucket nếu bucket chuyên dụng | Playbook có thể chứa quy trình vận hành, lệnh automation và thông tin nội bộ; bị đọc hoặc sửa đều nguy hiểm. |
| `tf3-aiops-models-197826770971` | Prefix chứa model/artifact production | Phát hiện tải trộm model, thay thế hoặc phá hoại artifact. |

Cấu hình minh họa (chờ owner xác nhận prefix thực tế):

```hcl
audit_detection_s3_data_event_arns = [
  "arn:aws:s3:::techx-aiops-playbooks-f6230446/",
  "arn:aws:s3:::tf3-aiops-models-197826770971/",
]
```

#### Bật có điều kiện

| Bucket | Quyết định | Rủi ro cần đánh giá trước |
|---|---|---|
| `techx-tf3-197826770971-tfstate` | **Bật có điều kiện** — chỉ sau khi owner đánh giá noise/cost | `terraform plan`/`apply` đọc state nhiều lần mỗi run; với vài chục run/tuần → hàng nghìn `GetObject`/tuần từ CI hợp lệ. Rủi ro exfil thực tế thấp hơn AIOps vì chỉ CI role có quyền đọc. Chi phí và nhiễu log cần được model trước khi đưa vào selector. |
| `sosflow-alb-logs-197826770971` | Bật có điều kiện | ALB log service ghi liên tục → volume `GetObject` rất cao. Cần forecast cost riêng và xác nhận exfil threat model trước khi apply. |
| `techx-products-catalog-2026` | Bật nếu catalog là private, có giá/metadata kinh doanh hoặc dữ liệu chưa công bố. Nếu toàn bộ là dữ liệu public thì có thể loại. | |
| `sosflow-frontend-197826770971` | Không bật cho static asset public. Chỉ bật prefix chứa config, deployment artifact hoặc file private. | |
| `thermal-power-plant-frontend-197826770971` | Tương tự: chỉ bật prefix private/config; loại các asset public để tránh lượng log lớn. | |

#### Bắt buộc loại khỏi selector

| Bucket | Lý do |
|---|---|
| `techx-corp-tf3-audit-trail-ap-southeast-1-197826770971` | Bucket CloudTrail archive — nếu ghi data events cho chính bucket này, mỗi lần CloudTrail ghi log sẽ tiếp tục sinh log mới, gây vòng lặp và tăng chi phí không kiểm soát. |

Danh sách tối thiểu nên trình owner duyệt trước: **Terraform state, AIOps playbooks, model artifacts và ALB logs**.

---

## Decision 4: Heartbeat Lambda 5 phút kiểm tra exact configuration (chống làm mù)

**Quyết định chọn:** Thêm Lambda heartbeat chạy mỗi 5 phút, kiểm tra đồng thời `IsLogging`, log age, digest age, validation flag, exact selectors, S3 lock/lifecycle/encryption, archive deny statement, rule pattern/target, full alarm config, CloudWatch topic policy, subscriptions và EKS audit log. Kết quả publish tới primary SNS M11 và global SNS M11; CloudWatch alarm về missing invocation và Lambda error publish vào topic primary M11 cùng region.

**Demo và test đường alert (`forceAlertTest`):** Heartbeat hỗ trợ chế độ test riêng: invoke Lambda với payload `{"forceAlertTest": true}`. Lambda bỏ qua toàn bộ kiểm tra cấu hình, publish thẳng một message TEST tới tất cả đường alert và trả về `TEST-PASS` nếu tất cả kênh nhận thành công, hoặc `TEST-FAIL` nếu có kênh lỗi. Cơ chế này cho phép mentor xác minh đường alert hoạt động trước khi chạy test tấn công thật, mà không gây nhiễu log heartbeat normal. Xem nhánh `forceAlertTest` trong `handler()` của [`heartbeat.py`](../infra/modules/audit-detection/lambda-heartbeat/heartbeat.py) (tham chiếu theo tên hàm, không theo số dòng — số dòng lệch mỗi lần sửa file).

### Alternatives considered

| Phương án | Lý do loại bỏ |
|---|---|
| Chỉ dùng EventBridge event-driven của M11 | Event-driven chỉ phát hiện khi có mutation; không phát hiện được "im lặng" — trail vẫn logging nhưng delivery bị nghẽn hoặc selectors bị drift silent |
| Dùng AWS Config conformance pack | Config live chưa có recorder; thêm Config mở rộng scope/cost; không phải yêu cầu bắt buộc M12 — có thể bổ sung bằng change riêng sau |
| Manual check định kỳ | Không liên tục, không phát hiện ngay, không đáp ứng "không có cửa sổ mù" của đề bài |

### Consequences and trade-offs

**Positive:**
- Phát hiện mọi dạng "làm mù" kể cả khi không có mutation nào trigger EventBridge: delivery ngừng, digest không đến, selector bị drift, rule bị disable mà không kêu.
- Hai kênh SNS (primary ap-southeast-1 + global us-east-1) cho heartbeat publish trực tiếp; alarm dùng primary vì CloudWatch chỉ publish được tới SNS cùng region.
- Heartbeat đóng vai trò "canary liên tục" — mentor có thể xem log heartbeat để chứng minh hệ thống healthy tại mọi thời điểm.

**Negative / residual risk:**
- Lambda heartbeat có thể bị tắt bởi admin có `AdministratorAccess` — lý do IAM hardening bắt buộc phải hoàn thành trước mentor verify test.
- Subscription chưa xác nhận **không còn là invariant FAIL** (sửa 23/07): một người chưa bấm link là trạng thái onboarding, không phải hệ thống hỏng, mà heartbeat chạy 5 phút/lần sẽ biến nó thành hàng trăm mail/ngày — và mail đó chỉ tới được đúng những người đã confirm. Số subscription confirmed vẫn được ghi vào output heartbeat làm bằng chứng nghiệm thu.

### Ước tính chi phí heartbeat (30 ngày)

**Giả định:** region `ap-southeast-1`; chạy mỗi 5 phút = 8.640 invocation/tháng; Lambda 256 MB, thời gian chạy trung bình 5 giây; CloudWatch Logs 5 KB/lần, retention 90 ngày; 2 standard alarms; 2 lần kiểm thử alert/tháng; không có alert storm.

| Thành phần | Mức sử dụng/tháng | Còn Free Tier | Hết Free Tier |
|---|---:|---:|---:|
| Lambda requests | 8.640 request | $0 | ~$0.002 |
| Lambda compute | 10.800 GB-s | $0 | ~$0.18 |
| EventBridge schedule | 8.640 invocation | $0 | <$0.01 |
| CloudWatch alarms | 2 standard alarms | $0 (quota 10) | ~$0.20 |
| CloudWatch Logs ingestion | ~43 MB | $0 (quota 5 GB) | ~$0.02–$0.04 |
| CloudWatch Logs storage | ~130 MB ổn định | ~$0 | <$0.01 |
| SNS requests + email | Chỉ khi lỗi/test | $0 | <$0.01 |
| AWS read-only API calls | Vài trăm nghìn call | $0 | Không đáng kể |

| Kịch bản | Ước tính/tháng |
|---|---:|
| Account còn đủ Free Tier | **~$0** |
| Hết Free Tier, trung bình 5 giây/lần | **~$0.40–$0.50** |
| Hết Free Tier, trung bình 10 giây/lần | **~$0.55–$0.70** |
| Xấu nhất: Lambda luôn chạy đủ timeout 60 giây | **~$2.40–$3.00** |

> Heartbeat chạy mỗi 5 phút, tương đương 8.640 lần gọi Lambda mỗi tháng. Với cấu hình 256 MB và thời gian thực thi trung bình 5 giây, mức sử dụng khoảng 10.800 GB-s/tháng. Chi phí gia tăng dự kiến là $0 khi tài khoản còn Free Tier và khoảng $0.40–$0.50/tháng khi toàn bộ Free Tier đã được sử dụng. **Ngân sách bảo thủ cho heartbeat: $1/tháng; ngưỡng cảnh báo bất thường: $3/tháng.**

Lambda có Free Tier 1 triệu request và 400.000 GB-s/tháng; heartbeat chỉ dùng ~0.86% request và ~2.7% compute của hạn mức này. Sau Decision 2 (retention theo vòng đời bài tập), chi phí chính của Mandate 12 là **CloudTrail S3 Data Events**, không phải storage: storage giữ nguyên lifecycle 30 ngày như M11. Các khoản không nằm trong bảng trên: CloudTrail S3 Object Data Events, alert storm nếu heartbeat liên tục FAIL, thuế và chênh lệch giá theo region.

---

## Decision 5: Loại bỏ automation allowlist suppress critical alert (nhóm 1-2-3-4-7-8)

**Quyết định chọn:** Các anti-audit alert nhóm critical **luôn được route tới security owner** kể cả khi actor là Terraform automation hoặc CI/CD. Không mute, không disable rule, không allowlist cho nhóm critical. Mỗi approved change phải có change ID chứa Git SHA, saved-plan hash, principal, UTC window để người trực đối chiếu alert.

### Alternatives considered

| Phương án | Lý do loại bỏ |
|---|---|
| Giữ automation allowlist của M11 — suppress alert khi actor là CI | Kẻ tấn công giả danh CI role có thể tắt trail mà không bị kêu; đây chính là gap M11 mà M12 phải bịt |
| Suppress alert sau khi verify người trực | Cửa sổ im lặng dù ngắn cũng là blind window — vi phạm yêu cầu 1 của đề bài |

### Consequences and trade-offs

**Positive:**
- Mọi thay đổi trail/archive/alert/IAM dù hợp lệ hay không đều để lại alert; đội trực có đủ thông tin để tự đối chiếu change record.
- Loại bỏ hoàn toàn kịch bản "CI bị chiếm để tắt audit mà không kêu".

**Phạm vi của g7 — lọc theo resource, không theo eventName:**

Rule `g7` khớp `eventName` trên 5 service và event pattern của EventBridge không
lọc được resource, nên bản đầu coi **mọi** `PutMetricAlarm`, `UpdateFunctionCode`,
`PutBucketPolicy` trong account là CRITICAL không tắt được — kể cả khi target
chẳng liên quan gì tới audit plane. Một `terraform apply` bình thường đủ sinh vài
chục mail CRITICAL, và đội trực sẽ lập filter: đúng cửa sổ mù mandate muốn chặn.

Đã chốt hướng lọc theo target **trong router** (`critical_group_7_target_keywords`),
không đưa `requestParameters` vào event pattern. Lý do là hướng hỏng: pattern sai
một tên field thì event không tới router — mất phát hiện, im lặng. Lọc trong
router sai thì cùng lắm thừa alert. Hai đường fail-safe cố ý: config thiếu keyword,
hoặc không trích được target, đều xử như audit plane và vẫn alert. Cùng shape với
`critical_group_6_target_keywords` đã dùng cho nhóm 6.

Đánh đổi: hành động g7 lên resource **ngoài** audit plane không còn sinh alert.
Vết vẫn nằm ở CloudTrail và ở log router (`reason=non_audit_target`), nên đây là
thu hẹp phạm vi **cảnh báo**, không phải thu hẹp phạm vi **ghi nhận**. Khoá bằng
`scripts/ci/test_audit_router_group7_targeting.py`.

**Negative / residual risk:**
- Approved Terraform PR chạm đúng resource audit plane vẫn tạo alert CRITICAL. Đội trực phải có quy trình đối chiếu change ID.
- Keyword là so khớp substring lowercase. Đặt tên resource mới cho audit plane mà không khớp tiền tố `<cluster>-audit-detection` / `<cluster>-audit-trail` / `<cluster>-m12-audit-heartbeat` thì phải bổ sung vào `additional_audit_plane_keywords`, nếu không event nhắm vào nó bị xử như resource thường.
- **Trạng thái hiện tại của `gitlab-ci-deployer` (tính đến 2026-07-22):** IAM user với `AdministratorAccess` trực tiếp, **chưa bật MFA**, còn **2 access key dài hạn đang hoạt động**, không migrate sang OIDC. Đây là identity nguy hiểm nhất trong allowlist — nếu key bị lộ, kẻ tấn công có đầy đủ quyền admin mà M11 không kêu. Phải migrate sang OIDC role và thu hồi key trước nghiệm thu mentor.

---

## Decision 6: IAM permissions boundary cho daily operator/CI (chống làm mù từ bên trong)

**Quyết định chọn:** Gắn permissions boundary vào tất cả daily operator và CI roles, deny rõ ràng: mutation trail/archive/alert/heartbeat; assume audit-admin/break-glass từ daily identity; IAM policy/boundary/trust mutation; `iam:PassRole` ngoài allowlist; role assumption ngoài allowlist. IAM hardening là **change riêng** sau khi audit foundation healthy.

**Implementation:** Boundary CI đã được implement tại [`infra/bootstrap/github-oidc/ci-audit-boundary.tf`](../infra/bootstrap/github-oidc/ci-audit-boundary.tf). Policy tạo nhưng chưa attach (`enable_ci_audit_boundary = false` mặc định); chỉ attach sau khi `iam:SimulatePrincipalPolicy` chứng minh baseline Terraform vẫn allowed và tất cả kill switch là `explicitDeny`.

### Alternatives considered

| Phương án | Lý do loại bỏ |
|---|---|
| Chỉ dùng EventBridge alert, không boundary | Alert thông báo sau khi lệnh đã chạy; boundary deny trước — cần cả hai lớp |
| SCP qua AWS Organizations | Không khả dụng với account Free Tier đơn lẻ |
| Boundary cho root user | AWS không hỗ trợ permissions boundary cho root; đây là residual risk bắt buộc phải ký acceptance |

### Consequences and trade-offs

**Positive:**
- Operator/CI bị deny cứng trước khi lệnh thực thi — không chỉ nhận alert sau.
- Tách bạch rõ: Operator làm công việc hàng ngày, không chạm được vào hệ thống bảo vệ audit.

**Negative / residual risk:**
- Root user không thể bị boundary — residual risk của kiến trúc single-account. Chấp nhận bằng: root MFA bật, không có root access key, named custodian, incident-only process, security/account-owner ký chấp nhận bằng văn bản.
- Migration IAM phải từng identity một, có simulation và rollback plan; không migrate hàng loạt cùng lúc với foundation apply.
- Nhiều identity chưa có owner rõ ràng (`cdo02testaudit`, `hieu-AdminAccess`); không tự sửa trước khi có owner approval.

---

## Decision 7: Chứng minh toàn vẹn mật mã bằng CloudTrail digest chain SHA-256

**Quyết định chọn:** Dùng `enable_log_file_validation=true` (đã có từ M11). Mỗi giờ CloudTrail tạo một digest file SHA-256 ký số, liên kết digest trước — tạo thành digest chain liên tục. Mentor verify bằng `aws cloudtrail validate-logs`. Bằng chứng chống "làm mỏng" phải nối: saved-plan hash → CloudTrail `requestParameters` (redacted) → post-state read-only.

### Alternatives considered

| Phương án | Lý do loại bỏ |
|---|---|
| Chỉ tuyên bố "append-only" mà không có digest chain | Đề bài từ chối tường minh: "không phải append-only nói suông mà là bằng chứng kỹ thuật" |
| Dùng hash file tự làm ngoài CloudTrail | Không được AWS ký; không chain được; không có `validate-logs` — không đủ tính chống chối bỏ |
| AWS CloudTrail Lake | Có query tốt nhưng không thay được WORM digest; thêm chi phí; không cần thiết cho MVP |

### Consequences and trade-offs

**Positive:**
- Mỗi digest được AWS ký bằng RSA private key; `validate-logs` dùng public key xác minh — không thể giả mạo mà không bị phát hiện.
- Chuỗi digest bị đứt (khoảng trống) sẽ bị phát hiện ngay cả khi attacker xóa một digest giữa chain.
- Kết hợp với Object Lock COMPLIANCE: log không xóa được + không sửa được + có bằng chứng nếu bị sửa.

**Negative / residual risk:**
- `validate-logs` chỉ xác minh từ lúc trail active và delivery healthy; không có bằng chứng hồi tố trước cutover.
- Nếu digest file bị thiếu do delivery lỗi (không phải tấn công), `validate-logs` vẫn báo gap. Phải monitor delivery health liên tục bằng heartbeat.

---

## Rollout sequence

1. Giải quyết blocker: SNS subscriptions Confirmed, MFA bật cho `cdo-2-admin-team`, owner phê duyệt exact S3 prefix và cost forecast, CD01/IaC owner xác nhận change window.
2. Apply audit foundation upgrade (trail selectors, Object Lock, lifecycle, router groups 7/8, heartbeat) — saved plan review bắt buộc trước.
3. Xác minh: `IsLogging=true`, delivery/digest healthy, heartbeat PASS, alert subscriptions Confirmed.
4. IAM hardening (change riêng): tạo audit-admin/break-glass roles, harden GitHub apply role, migrate daily admin users, gắn boundary theo thứ tự; từng bước có simulation + rollback.
5. Mentor verification: `StopLogging`/`DeleteTrail` bị deny + alert; `GetObject` canary có vết; `GetSecretValue` canary có vết; `validate-logs` PASS.
6. Ký residual-risk acceptance cho root single-account.

---

## Rollback

- Không rollback bằng cách tắt trail hoặc xóa archive.
- Object Lock COMPLIANCE đã set không thể rút ngắn ở bất kỳ thời hạn nào — 14 ngày cũng là 14 ngày. Phải chấp nhận điều này trước apply.
- IAM hardening rollback độc lập về role cũ trong change window đã duyệt; không rollback bằng cách gỡ audit foundation.
- Nếu selector hoặc alert plane gây noise, thu hẹp prefix non-sensitive sau approval; không tắt coverage bắt buộc.

---

## Verdict condition

`VERIFIED` chỉ đạt khi **đồng thời**:

- Trail delivery và digest healthy từ cutover timestamp.
- S3 Object data events active cho exact approved ARN prefixes.
- Object mới có `COMPLIANCE 14 ngày` với evidence `retain-until`.
- Heartbeat PASS liên tục.
- Tất cả anti-audit alert-plane rules match API call bị deny thật.
- IAM boundary test pass cho mọi daily identity đã inventory.
- `validate-logs` PASS trên UTC window.
- SNS subscriptions Confirmed trên hai topic M11 (primary, global) — ghi nhận số lượng, không phải gate chặn.
- **Router unit test 6/6 PASS:** `StopLogging`, `AttachRolePolicy`, `DisableRule`, `PutFunctionConcurrency`, `DeleteAlarms`, `DeleteRolePermissionsBoundary` từ principal trong allowlist đều được route đúng nhóm critical, không bị suppress. (Guard bắt buộc: syntax error trong `critical_group_numbers` có thể compile được nhưng bypass hoàn toàn — unit test là lớp duy nhất phát hiện trước khi PR merge.)
- Root residual-risk acceptance được ký bởi security owner và account owner.

`VERIFIED` không chứng minh root bị chặn tuyệt đối và không tạo coverage hồi tố trước cutover.

---

## Evidence

Implementation evidence được ghi tại:
- Execution plan: [`docs/mandate-12-execution-plan.md`](../mandate-12-execution-plan.md)
- Runbook: [`docs/runbooks/mandate-08-best-path.md`](../runbooks/mandate-08-best-path.md) *(runbook M12 riêng sẽ bổ sung tại `docs/runbooks/mandate-12-audit-anti-defeat-runbook.md` trước cutover)*

ADR này là `HANDOFF READY / NOT APPROVED FOR APPLY` cho đến khi tất cả blocker trong `docs/mandate-12-execution-plan.md §8` được giải quyết.

---

*Signed: Huu Tai Ngo — CDO02 / TF3 Auditability lead, 2026-07-22. Mentor/Security acceptance và residual-risk sign-off sẽ được ghi tại verdict record sau mentor verification.*

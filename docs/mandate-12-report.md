# Mandate #12 — Audit Anti-Defeat · Báo cáo tổng kết

> **Trạng thái:** `SKIP — được mentor phê duyệt` · không triển khai phần chống-đánh-bại bằng Organization/SCP
> **Người lập & ký:** **Lê Văn Hải — CDO-02**
> **Ngày:** 25/07/2026
> **Account workload:** `197826770971` (`ap-southeast-1`)
> **Tài liệu thiết kế kèm theo:** [`mandate-12-org-scp-execution-plan.md`](mandate-12-org-scp-execution-plan.md)

---

## 1. Kết luận

Nhóm **không triển khai** lớp "audit anti-defeat" bằng AWS Organizations + SCP của Mandate #12. Quyết định này **đã hỏi và được mentor đồng ý cho skip**, trên cơ sở rào cản chi phí mô tả ở §2 dưới đây (khoảng hở credit khi một account join organization giữa tháng — tiền thật, không thu hồi được).

Báo cáo này ghi lại trung thực: (a) phần đã làm được, (b) phần cố ý **không** làm và vì sao, (c) trạng thái thật để lại trên account, để phần này có thể được tiếp nối hoặc đóng lại minh bạch.

**Một điểm phải nói rõ để không hiểu nhầm "skip = không có gì":** lớp **phát hiện** của Mandate #12 (CloudTrail + data events + alert `g1`–`g8` + Object Lock COMPLIANCE) **đã live từ trước** qua M11 + M12 v1 (PR #403). Thứ bị skip là lớp **ngăn chặn cứng** (làm cho kill-switch **bất khả thi** bằng SCP từ một management account riêng). Nói theo yêu cầu đề bài: vế *"kêu ngay"* đã có; vế *"bị chặn"* là phần bỏ.

---

## 2. Lý do skip — rào cản chi phí khi join organization giữa tháng

Kiến trúc chống-đánh-bại đòi `197826770971` (account B) phải **join vào một AWS Organization** do một management account (account A) quản lý, để SCP có thể đứng **trên** quyền `AdministratorAccess` của B. Bản thân Organizations + SCP **miễn phí**, nhưng **hành động join** kích hoạt một quy tắc billing của AWS:

> AWS: *"An individual's account credits **don't cover the account usage from the day that the individual joined the organization to the end of that month**."* — cộng với *"you immediately become responsible for the member account's charges."*

Nghĩa là kể từ giây B accept join, hoá đơn của B chuyển sang thẻ của account A, **nhưng credit của B ngừng phủ phần usage từ ngày join đến cuối tháng**. Đo thực tế (Cost Explorer, 24/07/2026):

| | |
|---|---|
| Usage tháng 7 đến 24/07 | `$577,65`, credit `−$577,65` → **thực trả $0** (credit đang phủ 100%) |
| Run-rate 5 ngày gần nhất | ~**$46–57/ngày** |
| Join 24/07 → hở 8 ngày (24→31/07) | **~$200 – $460 tiền thật** trên thẻ account A |

Bài tập kết thúc **31/07/2026** nên không thể "chờ join đúng ngày 01/08 cho hở = 0" — join lúc đó là sau khi chương trình đã xong. Đây là rào cản đã trình bày ở §2 của execution-plan; **mentor đã đồng ý cho nhóm skip** thay vì chi khoản này.

---

## 3. Đã làm được gì

### 3.1 Thiết kế hoàn chỉnh (tài liệu hoá, sẵn sàng dùng lại)

Toàn bộ nằm ở [`mandate-12-org-scp-execution-plan.md`](mandate-12-org-scp-execution-plan.md) (16 mục, có kiểm chứng số liệu):

| Hạng mục | Trạng thái |
|---|---|
| Kiến trúc Org + SCP (A = management chỉ áp policy, B = member, audit plane giữ nguyên ở B) | ✅ thiết kế + biện luận đầy đủ |
| **SCP-1 `TF3-DenyAuditKillSwitch`** — khoá CloudTrail StopLogging/DeleteTrail/…, bucket archive, 2 KMS key, đường thoát org | ✅ JSON hợp lệ, minify **1.436** ký tự / 4 statement / 30 action |
| **SCP-2 `TF3-DenyAlertPlaneKillSwitch`** — khoá EventBridge/Lambda/SNS/DLQ/log, có ngoại lệ role bảo trì | ✅ JSON hợp lệ, minify **2.701** ký tự / 9 statement / 43 action |
| **Role bảo trì R** (`techx-corp-tf3-audit-maintainer`) — break-glass: chỉ role này update code router + thêm/xoá người nhận SNS, tự nó không sửa được | ✅ thiết kế identity policy + trust policy + statement bảo vệ |
| Ma trận kiểm chứng SCP (bảng A/B/C/D), quy trình nghiệm thu 3 đòn, rollback, change-window | ✅ viết sẵn |
| Phân tích chi phí (đo thật event volume 117.486 mgmt event/ngày), so sánh với phương án organization-trail (loại, vì +$71/tháng) | ✅ |

### 3.2 Thay đổi thật đã áp trên account (verify bằng CLI, profile `prod`)

| Việc | Trạng thái | Bằng chứng |
|---|---|---|
| Tạo IAM user chuyên biệt cho team audit `CDOAuditTeam` (console login + MFA `AuditDevice`) | ✅ đã tạo 25/07/2026 | `aws iam get-user --user-name CDOAuditTeam` |
| Thu hẹp `CDOAuditTeam` từ `AdministratorAccess` → **`ReadOnlyAccess`** | ✅ | `list-attached-user-policies` → `ReadOnlyAccess` |
| Gắn inline policy `AssumeAuditMaintainerOnly` (`sts:AssumeRole` scope đúng ARN role R) | ✅ | `get-user-policy` |

### 3.3 Xác minh hiện trạng (đo thật, làm nền cho mọi quyết định)

| Kiểm | Kết quả |
|---|---|
| Account B thuộc org nào chưa | **Chưa** — standalone (`AWSOrganizationsNotInUseException`) |
| Trail audit hiện có | `techx-corp-tf3-audit-detection-ap-southeast-1-trail`: multi-region, log file validation ON, Object Lock **COMPLIANCE 14**, lifecycle **30**, 2 KMS CMK |
| Alert plane M11/M12 v1 | 8 rule `g1`–`g8` + 2 router Lambda + 2 SNS topic — đang chạy |
| Credit đang phủ hoá đơn | 100% (net $0) |
| Volume CloudTrail | 117.486 management event/ngày |

---

## 4. Chỗ KHÔNG làm được / cố ý không triển khai

### 4.1 Các bước triển khai đã bỏ (do skip)

| Bước | Trạng thái | Ghi chú |
|---|---|---|
| Tạo account A + bật Organization (all features) | ❌ không làm | Rào cản chi phí §2 |
| B accept join organization | ❌ không làm | **Đây là nút một chiều về hoá đơn** — chính là điểm bị chặn |
| Tạo role bảo trì R trên account | ❌ không làm | `get-role techx-corp-tf3-audit-maintainer` → `NoSuchEntity` |
| Attach SCP-1 / SCP-2 | ❌ không làm | |
| Nghiệm thu 3 đòn (làm mù / làm hụt / làm mỏng) trước mentor | ❌ không diễn ra | |

### 4.2 Trạng thái 4 yêu cầu đề bài

| Yêu cầu | Thiết kế có lời giải? | Đã triển khai + chứng minh? |
|---|---|---|
| **1. Không cửa sổ mù** (kể cả admin TF không tắt được log) | ✅ SCP-1 chặn cứng | ❌ SCP chưa attach. *Lưu ý:* M12 v1 đã cho **"kêu ngay"** khi StopLogging — đạt mức tối thiểu của đề (bị chặn **hoặc** kêu), nhưng vế "bị chặn" thì chưa |
| **2. Đóng coverage gap** (đọc S3/secret để lại vết) | ✅ | 🟡 **Đã live sẵn từ M12 v1** (advanced selector data events cho bucket tfstate) — không phụ thuộc org |
| **3. Toàn vẹn mật mã** (validate-logs, không sửa lén) | ✅ SCP khoá bucket/KMS thêm | 🟡 Log file validation **đã live từ M11**; lớp SCP khoá thêm thì chưa |
| **4. Giữ đủ lâu** | 🟡 14/30 + SCP-1 deny xoá archive | ❌ SCP chưa attach; retention giữ mức 14/30 hiện tại |

**Diễn giải trung thực:** phần *phát hiện* của Mandate #12 xem như đã có (nhờ M11 + M12 v1 đang chạy). Phần *ngăn chặn không thể bị đánh bại* — điểm cốt lõi và khó nhất của đề — **chưa được chứng minh** vì không triển khai. Không claim Mandate #12 đạt.

---

## 5. Trạng thái thật để lại trên account (sau khi skip)

| Thành phần | Trạng thái | Cần xử lý? |
|---|---|---|
| Account B trong org | Không (standalone) | Không |
| SCP | Không tồn tại | Không |
| Role R `techx-corp-tf3-audit-maintainer` | Không tồn tại | Không |
| Audit plane M11/M12 v1 (trail, bucket, router, alert) | **Nguyên vẹn, đang chạy** (`IsLogging=True`) | Không — giữ nguyên |
| **User `CDOAuditTeam`** | Tồn tại: `ReadOnlyAccess` + inline `AssumeAuditMaintainerOnly` | 🟡 **cần quyết — xem dưới** |

**Điểm dư cần quyết:** inline policy `AssumeAuditMaintainerOnly` trên `CDOAuditTeam` đang trỏ `sts:AssumeRole` tới role R **không tồn tại**. Nó **vô hại** (không assume được gì), nhưng là một quyền "trỏ vào hư không" — về kỷ luật auditability nên xử lý:

- **Phương án A (giữ):** để nguyên nếu có ý định làm lại Mandate #12 sau 01/08 (khi rào cản credit tự đóng). `CDOAuditTeam` là user read-only có MFA — bản thân nó là tài sản tốt, nên giữ.
- **Phương án B (dọn):** gỡ inline policy cho sạch, giữ lại user với `ReadOnlyAccess`:
  ```bash
  aws iam delete-user-policy --user-name CDOAuditTeam --policy-name AssumeAuditMaintainerOnly --profile prod
  ```

*Khuyến nghị:* Phương án A nếu còn khả năng làm lại; B nếu đóng hẳn.

---

## 6. Chi phí thực tế phát sinh

**≈ $0.** Không có tài nguyên nào được tạo (không org, không SCP, không role — cả ba đều miễn phí kể cả nếu có). User `CDOAuditTeam` + policy: $0. Rào cản $200–460 ở §2 là khoản **đã tránh được nhờ skip**, không phát sinh.

---

## 7. Tài sản tái sử dụng nếu làm lại

Nếu chương trình gia hạn hoặc BTC nới lịch qua tháng 8:

- **Điều kiện vàng để làm lại rẻ:** join organization **đúng ngày 01 của tháng** → khoảng hở credit = 0 (§2). Khi đó toàn bộ thiết kế áp được với chi phí steady-state gần $0.
- Dùng lại nguyên: [`mandate-12-org-scp-execution-plan.md`](mandate-12-org-scp-execution-plan.md) (2 SCP đã validate, role R, ma trận kiểm chứng, trình tự Phase 0–5).
- `CDOAuditTeam` + inline assume-R đã sẵn — chỉ cần tạo role R (Phase 3.5) là khớp.

---

## 8. Ký nhận

Quyết định skip Mandate #12 dựa trên rào cản chi phí §2, **đã trao đổi và được mentor đồng ý**. Báo cáo phản ánh đúng hiện trạng account tại thời điểm ký.

| | |
|---|---|
| **Người lập & ký quyết định** | **Lê Văn Hải — CDO-02** |
| **Ngày** | 25/07/2026 |
| **Phê duyệt skip** | Mentor (đồng ý theo trao đổi; ghi nhận bởi CDO-02) |
| **Trạng thái Mandate #12** | Đóng — SKIP có phê duyệt |

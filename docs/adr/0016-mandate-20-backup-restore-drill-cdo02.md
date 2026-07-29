# ADR 0016 - Mandate #20: RDS PITR restore drill for CDO02 backup/recovery proof

**Ngày:** 2026-07-28  
**Người quyết định (ký):** Nguyễn Đỗ Hoàng Phúc - CDO02 (Reliability + Operations)  
**Directive:** `MANDATE-20-dr-backup-restore.md` - Backup/Restore DR  
**Trạng thái:** Accepted for drill execution - chưa claim Mandate #20 Done khi chưa có evidence restore thật  
**Tham chiếu:** `docs/docx_cdo02/mandate-20-rds-pitr-restore-solution.md`

## Bối cảnh

Mandate #20 yêu cầu chứng minh hệ thống khôi phục được dữ liệu sau mất/hỏng dữ liệu, bằng một restore drill thật, có RPO/RTO đo được. Yêu cầu không được tính là đạt chỉ vì đã bật backup.

TF3 hiện đã migrate datastore chính lên managed service theo Mandate #8:

- RDS PostgreSQL `techx-tf3-postgres`
- ElastiCache Valkey `techx-tf3-valkey`
- MSK Kafka `techx-tf3-kafka`

RDS hiện là ứng viên tốt nhất để làm proof chính vì có Point-in-Time Restore native, có thể restore về mốc trước lỗi sang DB instance tách biệt, rồi kiểm chứng bằng SQL mà không đổi traffic production.

## Quyết định

CDO02 chọn **RDS PostgreSQL `techx-tf3-postgres` làm restore drill chính** cho phần Reliability/Operations của Mandate #20.

Drill sẽ chạy theo mô hình:

1. Tạo marker dữ liệu tốt với id duy nhất theo lần drill trong schema probe riêng `dr_drill` trên production RDS.
2. Ghi lại `T_good_commit`.
3. Gây hỏng có kiểm soát chỉ trên row probe, chuyển payload sang `CORRUPTED_AFTER_GOOD_TIME`.
4. Chọn `T_restore` nằm sau `T_good_commit` và trước `T_corrupt_commit`.
5. Restore RDS về `T_restore` sang DB instance tạm/tách biệt.
6. Query DB restored, chứng minh marker quay lại `GOOD_BEFORE_CORRUPTION`.
7. Đo RTO từ lúc bắt đầu restore tới lúc query restored DB thành công.
8. Lưu raw evidence và cleanup DB drill sau khi mentor/PM xác nhận đủ.

Target trước drill:

```text
RDS RPO target: <= 5 phút
RDS RTO target: <= 45 phút
Expected data loss in probe: 0 row
```

## Ranh giới an toàn

Trong drill CDO02 không được:

- Restore đè lên production RDS.
- Đổi `DB_CONNECTION_STRING` hoặc secret production.
- Repoint app sang DB drill.
- Rebuild image hoặc đổi Helm values.
- Chạy `DROP`, `DELETE`, `TRUNCATE`, `UPDATE` trên bảng khách hàng.
- Cleanup DB drill trước khi evidence được mentor/PM xác nhận.
- Drop schema/table probe trên production trong cleanup thường lệ.

DB drill chỉ là tài nguyên tạm để chứng minh restore, ví dụ:

```text
techx-tf3-postgres-drill-YYYYMMDD-HHMMSS
```

## Phạm vi CDO02 claim

CDO02 claim các phần sau:

- RPO/RTO vận hành cho RDS restore drill.
- Runbook restore an toàn, không ảnh hưởng production traffic.
- Evidence SQL: GOOD -> CORRUPTED -> RESTORED GOOD.
- RTO measured.
- Cleanup DB drill; production marker cleanup nếu có thì chỉ xóa đúng marker id của lần drill, hoặc giữ lại làm audit trail.
- Coverage matrix cho store khác: ElastiCache, MSK, DynamoDB lock, EBS legacy, GitOps/IaC state.

CDO02 không tự claim hoàn tất toàn bộ yêu cầu Security của Mandate #20 nếu chưa có verdict từ CDO01.

## Phụ thuộc CDO01 / Security

Phần Security do CDO01 review/claim:

- Encryption/KMS posture của datastore và backup/snapshot.
- Ai được phép xóa RDS snapshot/automated backup.
- IAM deny, permission boundary, hoặc process break-glass cho hành động xóa backup.
- Retention/security guardrail.
- Accepted limitation nếu account còn admin rộng hoặc không dùng SCP.

Trong account hiện tại có nhiều principal quyền rộng, nên ADR này **không claim chống xóa backup tuyệt đối** nếu CDO01 chưa có evidence riêng.

## Mandate #20 data-tier commitments

ADR này ghi cam kết vận hành theo từng tầng dữ liệu để khớp yêu cầu Mandate #20. Các target dưới đây là target trước drill/evidence; trạng thái pass chỉ được cập nhật sau khi có raw evidence.

| Tầng dữ liệu / state | Vai trò trong hệ thống | RPO target | RTO target | Backup / recovery strategy | Cadence / retention | CDO02 claim | Security / delete-permission verdict |
|---|---|---|---|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | Store chính cho catalog/reviews/accounting/order data | `<= 5 phút` theo PITR window | `<= 45 phút` cho restore drill | RDS automated backup + PITR; restore về `T_restore` sang DB drill tách biệt | Automated backup retention 7 ngày; manual snapshot phụ nếu có | **Claim chính của CDO02**; phải chạy drill thật | CDO01 cần xác nhận ai được xóa snapshot/automated backup và KMS posture |
| ElastiCache Valkey `techx-tf3-valkey` | Cart/session cache trên luồng browse -> cart -> checkout | Target theo snapshot window; nếu không claim restore cart, ghi accepted cart-state strategy | Target theo restore snapshot hoặc accepted recovery strategy | ElastiCache snapshot/restore hoặc accepted limitation: cart state là soft-state, không dùng làm PITR proof chính | Snapshot retention quan sát: 3 ngày | CDO02 ghi coverage verdict, không thay RDS PITR drill | CDO01 xác nhận encryption/snapshot delete permission nếu claim backup |
| MSK Kafka `techx-tf3-kafka` | Order event stream cho checkout -> accounting/fraud | Target: `0 acknowledged order lost` trong retention window nếu producer/consumer replay đúng | Target theo consumer replay/reconciliation, cần evidence sau drill/record riêng | MSK retention/replay; không gọi là PITR backup | Topic retention cần được capture trong evidence; prior docs ghi 168h | CDO02 ghi replay/reconciliation strategy, không dùng làm PITR proof chính | CDO01 xác nhận KMS/IAM/delete topic/config destructive control nếu cần |
| DynamoDB `techx-tf3-terraform-lock` | Terraform lock table, không phải dữ liệu khách hàng | Excluded nếu chỉ là lock tái tạo được | Rebuild/recreate lock table nếu mất | Exclusion with reason, không dùng làm data restore proof | Không yêu cầu retention khách hàng nếu exclude | CDO02 claim exclude nếu team xác nhận chỉ là lock | Nếu team muốn protect, CDO01 phải xác nhận PITR/IAM |
| EBS/PVC legacy volumes | Legacy artifacts từ pre-managed datastore / Mandate #8/#18 | Không claim RPO/RTO cho production data | Không claim restore path trong M20 drill | Không dùng làm backup proof chính; pending Mandate #8 acceptance / Mandate #18 cleanup | Không dùng làm retention proof nếu legacy/available | CDO02 ghi pending/accepted limitation để không gạt M8/M18 | Nếu giữ làm artifact, CDO01 cần encryption/delete policy verdict |
| GitOps/IaC state | Manifest, config, Terraform state/source of truth | Git RPO: last pushed commit; Terraform state RPO phụ thuộc backend versioning | Target restore/reconcile phải được đo trong DR/state runbook nếu claim | Git history + Terraform state backend/versioning/Object Lock nếu có | Retention/versioning phải capture từ backend thực tế | CDO02 claim GitOps source-of-truth process; state backend cần evidence riêng | CDO01 xác nhận state bucket/Object Lock/IAM delete protection |

## Backup deletion authority

Mandate #20 yêu cầu ghi rõ **ai được xóa backup**. Vì CDO02 không sở hữu toàn bộ Security/IAM boundary, ADR này ghi policy mong muốn và phần cần CDO01 xác nhận.

| Principal / nhóm | Quyền xóa backup mong muốn | Trạng thái trong ADR này | Evidence cần có |
|---|---|---|---|
| Read-only / reviewer / mentor viewer | Không được xóa | Policy target | IAM policy hoặc console role evidence từ CDO01 |
| CDO02 operator chạy drill | Không được xóa backup production; chỉ được tạo/xóa DB drill tạm sau approval | CDO02 operating rule | Runbook/evidence cleanup chỉ áp dụng DB drill identifier |
| CI Terraform plan role | Không được xóa backup; chỉ plan/read | Policy target | CI/IAM evidence từ CDO01 |
| CI Terraform apply role | Không được xóa backup production ngoài PR được review và approved | CDO01/Security dependency | IAM guard, permission boundary, hoặc accepted limitation |
| Break-glass / account owner | Có thể xóa trong tình huống khẩn cấp có ticket/MFA/owner approval | Accepted operational reality nếu account còn admin rộng | CloudTrail/audit process + named owner từ CDO01/PM |
| Unknown/admin-wide principals | Không claim đã chặn tuyệt đối nếu chưa có SCP/permission boundary | **Open risk** | CDO01 verdict hoặc accepted risk |

Kết luận: trước khi có CDO01 evidence, CDO02 chỉ claim phần restore drill và ghi rõ delete-protection là dependency. Mandate #20 overall chưa nên claim Done nếu bảng deletion authority chưa được review hoặc accepted-risk chưa được PM/mentor chấp nhận.

## Coverage matrix

| Store / state | Quyết định CDO02 | Điều kiện evidence |
|---|---|---|
| RDS PostgreSQL | Drill chính bằng PITR | Restored DB trả marker GOOD, RTO measured |
| ElastiCache Valkey | Coverage phụ | Snapshot/restore evidence hoặc accepted cart-state strategy |
| MSK Kafka | Coverage riêng bằng retention/replay | Producer/consumer replay hoặc order reconciliation; không gọi là PITR |
| DynamoDB lock | Exclude nếu chỉ là Terraform lock | Ghi rõ tái tạo được, không phải dữ liệu khách hàng |
| EBS legacy | Không dùng làm backup proof chính | Pending Mandate #8/#18 hoặc cleanup sau nghiệm thu |
| GitOps/IaC state | Covered bằng Git/state/versioning nếu team claim | Link commit, state bucket/versioning/Object Lock nếu có |

## Hệ quả

Ưu điểm:

- Chứng minh đúng trọng tâm Mandate #20: restore thật, RPO/RTO thật.
- Không cần sửa code ứng dụng.
- Không đụng traffic production.
- Dễ mentor kiểm chứng bằng console/CLI/SQL.

Đánh đổi:

- Chỉ RDS là proof chính; store khác cần coverage matrix hoặc evidence riêng.
- Tạo DB drill tạm phát sinh chi phí nhỏ trong cửa sổ nghiệm thu.
- Security/delete-permission vẫn cần CDO01 xác nhận, không được gộp vào claim CDO02.

## Evidence cần có sau drill

Sau khi chạy thật, tạo evidence record dưới `docs/evidence/mandate-20/` gồm:

```text
Git baseline:
AWS caller/account/region:
RDS source inventory:
T_good_commit:
T_restore:
T_corrupt_commit:
DB drill identifier:
Drill marker id:
Restore start/end:
RTO measured:
Production corrupt query:
Restored DB GOOD query:
Cleanup result:
Mentor/PM witness:
```

## Trạng thái pass/fail hiện tại

Tại thời điểm ADR này:

- Thiết kế RDS PITR drill: **Accepted**
- Hạ tầng nền để chạy drill: **Sẵn sàng**
- Restore drill evidence: **Chưa có**
- Data-tier commitment matrix: **Đã ghi target/verdict cần evidence**
- CDO01 Security/delete-permission verdict: **Open dependency / cần review hoặc accepted risk**

Vì vậy CDO02 chỉ claim: **ready to execute Mandate #20 RDS PITR restore drill**, chưa claim Mandate #20 Done.

## Chữ ký

Nguyễn Đỗ Hoàng Phúc - CDO02 (Reliability + Operations) - 2026-07-28


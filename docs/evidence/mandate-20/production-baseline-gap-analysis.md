# Mandate 20 - Production baseline and gap analysis

Tài liệu này nối giữa:

- directive gốc `MANDATE-20-dr-backup-restore.md`
- ADR `docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md`
- runbook `docs/runbooks/mandate-20-rds-pitr-drill.md`

Mục tiêu là trả lời 3 câu hỏi trước khi claim pass Mandate 20:

1. ADR/runbook hiện đã cover được bao nhiêu phần của directive.
2. Production thật còn thiếu evidence nào.
3. CDO02 còn phải làm gì tiếp, phần nào cần CDO01/Security chốt.

## 1. Tóm tắt trạng thái hiện tại

Hiện tại CDO02 đã có:

- ADR chốt hướng `RDS PITR restore drill` làm proof chính.
- Runbook restore drill an toàn, restore ra DB tách biệt.
- Evidence index cho Mandate 20.

Hiện tại CDO02 chưa có:

- Record restore drill thật với `RTO measured`.
- Live inventory record cho từng tầng dữ liệu/state.
- Security verdict về quyền xóa backup/snapshot.
- Coverage evidence cuối cùng cho các state ngoài RDS.

Kết luận ngắn: trạng thái hiện tại là **ready to execute**, chưa phải **ready to claim pass**.

## 2. Đối chiếu directive với artifact đã merge

| Yêu cầu directive | Artifact hiện có | Trạng thái |
|---|---|---|
| 1. Không sót store nào trên luồng ra tiền | ADR đã có data-tier commitments và coverage matrix | `Partial` |
| 2. RPO/RTO rõ ràng, cadence tương xứng | ADR đã ghi target cho RDS, có hướng cho store khác | `Partial` |
| 3. Point-in-time restore chứng minh được | ADR + runbook đã mô tả PITR restore cho RDS | `Design-ready` |
| 4. Tested restore drill | Chưa có evidence thật | `Missing` |
| 5. Backup an toàn, tách quyền xóa | ADR đã nêu dependency CDO01 | `Open dependency` |

## 3. Data-tier baseline cần có trước buổi drill

Mandate 20 không cho phép chỉ nhìn mỗi RDS. Trước buổi drill, cần có một baseline record cho từng tầng dưới đây.

| Tầng dữ liệu / state | CDO02 hiện claim gì | Baseline production cần lưu | Trạng thái |
|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | PITR proof chính | backup retention, latest restorable time, deletion protection, encryption, Multi-AZ, restore target window | Chờ capture live |
| ElastiCache Valkey `techx-tf3-valkey` | Coverage phụ, không phải proof chính | snapshot cadence/retention, encryption, recovery stance cho cart-state | Chờ capture live |
| MSK Kafka `techx-tf3-kafka` | Replay/reconciliation, không gọi PITR | retention window, encryption, replay/reconciliation path, destructive-control note | Chờ capture live |
| DynamoDB lock table | Có thể exclude nếu chỉ là Terraform lock | tên bảng, chức năng thực tế, PITR có bật hay exclude có lý do | Chờ verdict |
| EBS / volume legacy | Không dùng làm proof chính | volume/snapshot ownership hoặc accepted limitation | Chờ verdict |
| GitOps / IaC state | Covered bằng source-of-truth process nếu team claim | Git baseline, state backend/versioning/Object Lock nếu có, secret reference path | Chờ capture live |

## 4. Gap còn thiếu để pass theo từng yêu cầu

### Requirement 1 - Không sót store nào trên luồng ra tiền

ADR đã ghi đủ các store/state cần nói tới, nhưng chưa có một baseline record gom lại production thật cho:

- RDS
- Valkey
- MSK
- DynamoDB lock
- legacy volume/EBS
- GitOps/IaC state

Phần còn thiếu:

- chụp inventory production thật cho từng tầng
- chốt rõ tầng nào `covered`, tầng nào `excluded`, tầng nào `accepted limitation`

### Requirement 2 - RPO/RTO và cadence

RDS đã có target cụ thể trong ADR.

Phần còn thiếu:

- điền cadence/retention production thật của Valkey, MSK, state backend
- chỉ ra vì sao cadence đó đủ hoặc chưa đủ so với target
- nếu chưa đủ, phải ghi accepted limitation hoặc dependency rõ ràng

### Requirement 3 - PITR restore

RDS đã đáp ứng về mặt thiết kế.

Phần còn thiếu:

- chọn `T_good_commit`, `T_restore`, `T_corrupt_commit` trong buổi drill thật
- lưu raw output chứng minh restore đúng về thời điểm trước sự cố

### Requirement 4 - Tested restore drill

Đây là gap lớn nhất hiện tại.

Phần còn thiếu:

- chạy thật trước mentor/PM hoặc quay video đầy đủ
- đo `RTO measured`
- lưu evidence production corrupt query và restored DB GOOD query

### Requirement 5 - Backup an toàn

ADR đã đúng khi không overclaim phần Security.

Phần còn thiếu:

- ai được phép xóa backup/snapshot
- ai không được phép xóa
- accepted risk nếu account còn admin rộng
- encryption / delete-permission verdict từ CDO01

## 5. Checklist production baseline cần chụp trước khi drill

Lưu thành raw evidence trong thư mục `docs/evidence/mandate-20/`.

### 5.1. RDS

Phải có:

- `DBInstanceIdentifier`
- `BackupRetentionPeriod`
- `LatestRestorableTime`
- `StorageEncrypted`
- `DeletionProtection`
- `MultiAZ`
- `PubliclyAccessible = false`

### 5.2. DynamoDB

Phải có:

- danh sách bảng liên quan
- nếu chỉ có Terraform lock thì ghi rõ `exclude with reason`
- nếu claim backup thì phải có trạng thái PITR

### 5.3. Valkey

Phải có:

- snapshot cadence / retention
- encryption posture
- accepted recovery stance cho cart-state

### 5.4. MSK

Phải có:

- cluster status
- retention / replay stance
- encryption posture
- giải thích vì sao đây không phải PITR nhưng vẫn có recovery path

### 5.5. GitOps / IaC state

Phải có:

- Git baseline commit
- manifest source of truth
- state backend / versioning / Object Lock nếu team claim
- đường tham chiếu secret/config để dựng lại

## 6. Việc CDO02 nên làm tiếp ngay

1. Chạy một lượt capture baseline production cho toàn bộ data-tier/state.
2. Tạo file evidence đầu tiên, ví dụ:
   `docs/evidence/mandate-20/production-baseline-YYYYMMDD.md`
3. Sau đó mới chạy restore drill RDS theo runbook.
4. Khi có raw evidence, cập nhật lại `docs/evidence/mandate-20/README.md`.

## 7. Việc cần CDO01 / Security chốt

- bảng quyền xóa backup/snapshot
- verdict cho DynamoDB PITR / exclusion
- verdict cho state backend protection nếu team claim
- accepted risk nếu còn admin-wide principal

## 8. Kết luận

ADR 0016 và runbook hiện tại đã đưa Mandate 20 từ mức "ý tưởng" lên mức "có hướng chạy thật".

Để pass theo đúng directive, CDO02 vẫn cần bổ sung 2 lớp evidence:

1. **production baseline cho mọi tầng dữ liệu/state**
2. **restore drill thật với RTO measured**

Cho đến khi đủ hai lớp này và có security verdict tương ứng, Mandate 20 nên được xem là:

```text
Design accepted
Execution pending
Not claimable as Done yet
```

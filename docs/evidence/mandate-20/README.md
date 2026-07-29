# Mandate 20 evidence index

Evidence index cho Mandate #20 Backup/Restore DR.

**ADR:** `docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md`  
**Runbook:** `docs/runbooks/mandate-20-rds-pitr-drill.md`  
**Solution:** `docs/docx_cdo02/mandate-20-rds-pitr-restore-solution.md`

## Current status

```text
CDO02 design/ADR: ready
RDS PITR drill evidence: pending
CDO01 security/delete-permission verdict: pending
Mandate #20 overall: not Done until restore drill evidence exists
```

## Evidence files

Add drill records here after execution:

| File | Purpose |
|---|---|
| `production-baseline-gap-analysis.md` | Đối chiếu directive với ADR/runbook hiện tại và liệt kê gap còn thiếu |
| `production-baseline-template.md` | Mẫu điền baseline production thật cho từng tầng dữ liệu/state trước buổi drill |
| `production-baseline-YYYYMMDD.md` | Baseline production thật cho mọi data-tier/state trước buổi drill |
| `rds-pitr-drill-YYYYMMDD.md` | Main RDS restore drill result |
| `rds-pitr-drill-YYYYMMDD-raw/` | Raw CLI/SQL output and screenshots, if needed |

## Required evidence fields

Each drill record must include:

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

## Coverage matrix status

| Store / state | RPO/RTO status | Backup/retention status | Evidence |
|---|---|---|---|
| RDS PostgreSQL | Target set: RPO <= 5 phút, RTO <= 45 phút | Automated backup/PITR 7 ngày, pending drill evidence | PITR restore record required |
| ElastiCache Valkey | Pending final target or accepted cart-state limitation | Snapshot retention observed as 3 ngày, needs verdict | Snapshot/restore evidence or accepted cart-state strategy |
| MSK Kafka | Pending replay/reconciliation target; do not call PITR | Retention/replay strategy needs capture | Retention/replay or order reconciliation explanation |
| DynamoDB lock | Pending exclusion/verdict | Exclude if Terraform lock only | Exclusion reason |
| EBS legacy | Pending M8/M18 decision | Do not use as M20 proof unless ownership is clarified | Pending/accepted limitation |
| GitOps/IaC state | Pending state restore target if claimed | Git/state/versioning/Object Lock evidence if claimed | Commit/state/backend evidence |
| IAM/KMS/delete permission | CDO01 dependency | Delete authority matrix needs review/accepted risk | Security verdict required |

## Current recommendation

Trước khi chạy restore drill, CDO02 nên tạo thêm:

- `production-baseline-YYYYMMDD.md`
- raw inventory/screenshot tương ứng cho từng tầng dữ liệu/state

Lý do: Mandate 20 chấm trên toàn bộ tầng dữ liệu và trạng thái cụm/hạ tầng, không chỉ riêng RDS PITR drill.

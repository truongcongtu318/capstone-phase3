# Mandate 20 - Production baseline 2026-07-29

Baseline này dùng để khóa trạng thái production thật trước khi chạy restore drill Mandate 20.

Nguyên tắc:

- Chỉ thu thập inventory/evidence read-only.
- Không apply tay, không sửa production trực tiếp.
- Mọi thay đổi repo tiếp theo phải đi qua PR/GitHub.

## Metadata

```text
Capture date: 2026-07-29
Captured by: CDO02
AWS caller/account/region: arn:aws:iam::197826770971:user/cdo-2-admin-team / 197826770971 / ap-southeast-1
Git baseline: <fill after capture>
Mentor/PM window: <pending>
Notes: Baseline recorded before executing RDS PITR restore drill.
```

## 1. RDS PostgreSQL

Mục tiêu: chứng minh store chính đã có PITR-capable baseline trước buổi drill.

### Cần ghi nhận

```text
DB identifier:
Status:
Engine/version:
Backup retention:
Latest restorable time:
Encryption at rest:
Deletion protection:
Multi-AZ:
Publicly accessible:
Subnet group:
Security groups:
Manual snapshots observed:
RPO target: <= 5 phút
RTO target: <= 45 phút
Assessment:
```

### Lệnh capture

```powershell
aws rds describe-db-instances `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres `
  --query "DBInstances[0].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Engine:Engine,EngineVersion:EngineVersion,Encrypted:StorageEncrypted,BackupRetention:BackupRetentionPeriod,LatestRestorableTime:LatestRestorableTime,DeletionProtection:DeletionProtection,MultiAZ:MultiAZ,Public:PubliclyAccessible,SubnetGroup:DBSubnetGroup.DBSubnetGroupName,VpcSecurityGroups:VpcSecurityGroups[].VpcSecurityGroupId}" `
  --output json

aws rds describe-db-snapshots `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres `
  --output json
```

### Raw output / screenshots

```text
<paste here>
```

### Assessment

```text
<fill here>
```

## 2. ElastiCache Valkey

Mục tiêu: chốt snapshot/recovery stance cho cart-state, dù không dùng làm PITR proof chính.

### Cần ghi nhận

```text
Cluster / replication group:
Status:
Engine/version:
Snapshot retention / cadence:
Encryption at rest:
Transit encryption:
Recovery stance:
RPO target:
RTO target:
Assessment:
```

### Lệnh capture

```powershell
aws elasticache describe-replication-groups `
  --region ap-southeast-1 `
  --output json

aws elasticache describe-cache-clusters `
  --region ap-southeast-1 `
  --show-cache-node-info `
  --output json
```

### Raw output / screenshots

```text
<paste here>
```

### Assessment

```text
<fill here>
```

## 3. MSK Kafka

Mục tiêu: chốt recovery path theo retention/replay, không gọi nhầm đây là PITR.

### Cần ghi nhận

```text
Cluster name:
Status:
Kafka version:
Retention / replay stance:
Encryption at rest:
Transit encryption:
Recovery path:
RPO target:
RTO target:
Assessment:
```

### Lệnh capture

```powershell
aws kafka list-clusters-v2 `
  --region ap-southeast-1 `
  --output json
```

### Raw output / screenshots

```text
<paste here>
```

### Assessment

```text
<fill here>
```

## 4. DynamoDB

Mục tiêu: xác nhận có bảng nào thuộc scope mandate hay chỉ là Terraform lock để exclude hợp lệ.

### Cần ghi nhận

```text
Relevant tables:
If exclude, why:
PITR enabled:
Recovery stance:
RPO target:
RTO target:
Assessment:
```

### Lệnh capture

```powershell
aws dynamodb list-tables `
  --region ap-southeast-1 `
  --output json
```

Nếu có bảng trong scope và cần kiểm PITR:

```powershell
aws dynamodb describe-continuous-backups `
  --region ap-southeast-1 `
  --table-name <table-name> `
  --output json
```

### Raw output / screenshots

```text
<paste here>
```

### Assessment

```text
<fill here>
```

## 5. EBS / legacy volumes

Mục tiêu: chốt rõ legacy artifact nào còn cần tính trong M20, artifact nào chỉ là pending M8/M18.

### Cần ghi nhận

```text
Relevant legacy volume / snapshot artifacts:
Still in scope for production data:
If excluded, why:
Recovery stance:
Assessment:
```

### Nguồn evidence

```text
AWS console screenshot / existing repo evidence / linked incident note
```

### Raw output / screenshots

```text
<paste here>
```

### Assessment

```text
<fill here>
```

## 6. GitOps / IaC state

Mục tiêu: chứng minh phần trạng thái cụm/hạ tầng có source-of-truth và recovery path, đúng yêu cầu directive.

### Cần ghi nhận

```text
Git source of truth:
Current commit / revision:
Terraform state backend:
Versioning / Object Lock:
Secret / config reference path:
Recovery stance:
RPO target:
RTO target:
Assessment:
```

### Lệnh / nguồn capture

```powershell
git rev-parse --short origin/main
```

```text
Thêm screenshot / note từ backend state nếu team claim versioning/Object Lock.
```

### Raw output / screenshots

```text
<paste here>
```

### Assessment

```text
<fill here>
```

## 7. Backup deletion authority

Mục tiêu: khóa rõ phần CDO02 claim được và phần phụ thuộc CDO01/Security.

| Principal / nhóm | Có được xóa backup không | Evidence / note |
|---|---|---|
| Read-only / reviewer | `pending` | CDO01 xác nhận |
| CDO02 operator | `không nên có quyền xóa backup production` | chỉ xóa DB drill tạm sau approval |
| CI plan role | `pending` | CDO01 xác nhận |
| CI apply role | `pending` | CDO01 xác nhận |
| Break-glass / owner | `pending` | accepted risk / security verdict |
| Admin-wide principal | `open risk` | cần accepted risk hoặc boundary từ CDO01 |

## 8. Overall verdict before drill

```text
Requirement 1 - all stores covered: pending baseline completion
Requirement 2 - RPO/RTO and cadence: partial
Requirement 3 - PITR-ready store selected: yes (RDS)
Requirement 4 - restore drill can proceed: pending baseline + mentor window
Requirement 5 - backup safety/delete authority: open dependency on CDO01
Open dependencies:
- production inventory capture
- security/delete authority verdict
- restore drill execution evidence
Go / No-Go: No-Go until sections above are filled with live evidence
```

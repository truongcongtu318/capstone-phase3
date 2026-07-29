# Mandate 20 - Production baseline template

Điền file này trước khi chạy restore drill để chứng minh production thật đang có đủ nền backup/recovery cho từng tầng dữ liệu/state mà directive yêu cầu.

## Metadata

```text
Capture date:
Captured by:
AWS caller/account/region:
Git baseline:
Mentor/PM window:
Notes:
```

## 1. RDS PostgreSQL

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
RPO target:
RTO target:
Assessment:
```

## 2. ElastiCache Valkey

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

## 3. MSK Kafka

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

## 4. DynamoDB

```text
Relevant tables:
If exclude, why:
PITR enabled:
Recovery stance:
RPO target:
RTO target:
Assessment:
```

## 5. EBS / legacy volumes

```text
Relevant legacy volume / snapshot artifacts:
Still in scope for production data:
If excluded, why:
Recovery stance:
Assessment:
```

## 6. GitOps / IaC state

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

## 7. Backup deletion authority

| Principal / nhóm | Có được xóa backup không | Evidence / note |
|---|---|---|
| Read-only / reviewer |  |  |
| CDO02 operator |  |  |
| CI plan role |  |  |
| CI apply role |  |  |
| Break-glass / owner |  |  |
| Admin-wide principal |  |  |

## 8. Overall verdict before drill

```text
Requirement 1 - all stores covered:
Requirement 2 - RPO/RTO and cadence:
Requirement 3 - PITR-ready store selected:
Requirement 4 - restore drill can proceed:
Requirement 5 - backup safety/delete authority:
Open dependencies:
Go / No-Go:
```

# GitHub OIDC bootstrap

Root này giữ ownership riêng cho IAM roles được GitHub Actions dùng để plan/apply production.
State riêng nằm tại key `bootstrap/github-oidc/terraform.tfstate`, không thuộc production EKS
state.

Sau migration, plan role chỉ trust protected `main` và pull-request subject; deploy branch cũ
không còn quyền assume role. Apply chỉ được gọi thủ công từ workflow trên `main` thông qua
GitHub Environment `production`.

## Mandate 12 — CI audit boundary

Apply role vẫn giữ `AdministratorAccess`. Thay vì thu hẹp thành policy Terraform riêng (việc
lớn, còn mở), Mandate 12 gắn một **permissions boundary chuyên biệt**: cho phép IAM CRUD chung
và mọi thao tác Terraform cần để quản audit foundation, nhưng deny các "kill switch" mà
Terraform không bao giờ cần trên resource audit — `StopLogging`, `DeleteTrail`, xoá/ghi đè
object archive, `BypassGovernanceRetention`, `DisableRule`/`DeleteRule`/`RemoveTargets`,
`DeleteTopic`/`Unsubscribe`, `DeleteFunction`/`PutFunctionConcurrency`,
`DeleteAlarms`/`DisableAlarmActions` — cộng với chặn CI tự gỡ hoặc tự sửa boundary của nó.

Chi tiết thiết kế và giới hạn: [`ci-audit-boundary.tf`](ci-audit-boundary.tf) và
[`docs/../../../docs/mandates/mandate-12/mandate-12-execution-plan.md`](../../../docs/../../../docs/mandates/mandate-12/mandate-12-execution-plan.md) §9.

### Quy trình attach

Root này apply **thủ công** bởi người có MFA, không qua CI.

1. `enable_ci_audit_boundary = false` (mặc định) → apply chỉ **tạo policy**, chưa attach.
   CI chạy như cũ. Đây là trạng thái sau khi merge PR.
2. Chạy `iam:SimulatePrincipalPolicy` cho `terraform_apply` với cả nhóm baseline
   (phải `allowed`) và nhóm kill switch (phải `explicitDeny`).
3. Chỉ khi simulation pass mới đặt `enable_ci_audit_boundary = true` và apply lại.
4. Chạy một `terraform plan` production qua CI để xác nhận baseline không hỏng,
   rồi mới tới `apply`.

### Rollback

Đặt `enable_ci_audit_boundary = false` và apply lại root này. Boundary được gỡ ngay.
Không cần đụng tới role hay workload nào khác.

Lưu ý: khi boundary đã attach, CI **không tự gỡ được** (statement `DenyRemovingOwnBoundary`).
Rollback bắt buộc do người có MFA thực hiện tại root này.

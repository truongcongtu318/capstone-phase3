# Mandate 12 — permissions boundary cho GitHub Actions Terraform roles.
#
# BÀI TOÁN
# `gha-terraform-apply` có AdministratorAccess và là identity dùng để apply
# `infra/live/production` — tức là chính nó deploy audit foundation. Nếu gắn
# boundary strict (deny toàn bộ iam:Create*/Attach*/Put*) thì CI chết cho mọi
# thay đổi IAM. Nhưng để nguyên AdministratorAccess thì một `terraform apply`
# duy nhất có thể tắt trail, xoá rule, giết router và huỷ subscription cùng
# lúc — khi alert plane cũng bị phá thì không còn tín hiệu nào.
#
# HƯỚNG ĐÃ CHỌN (option b)
# Boundary riêng cho CI: cho phép IAM CRUD chung và mọi thao tác Terraform cần
# để quản audit foundation, nhưng deny đúng những action mà Terraform KHÔNG bao
# giờ cần trên resource audit — các "kill switch" tức thời.
#
#   Terraform vẫn làm được: PutRule, PutTargets, UpdateFunctionCode,
#   PutBucketPolicy, PutObjectLockConfiguration, PutBucketLifecycleConfiguration,
#   PutMetricAlarm, Subscribe, SetTopicAttributes, PutEventSelectors,
#   UpdateTrail, StartLogging, CreateRole, AttachRolePolicy...
#
#   CI KHÔNG làm được: StopLogging, DeleteTrail, xoá/ghi đè object archive,
#   BypassGovernanceRetention, DisableRule/DeleteRule/RemoveTargets,
#   DeleteTopic/Unsubscribe, DeleteFunction, PutFunctionConcurrency,
#   DeleteAlarms/DisableAlarmActions, gỡ boundary của chính nó, sửa nội dung
#   boundary này.
#
# GIỚI HẠN PHẢI BIẾT
# Boundary này KHÔNG làm CI hoàn toàn không thể làm yếu audit. `PutEventSelectors`,
# `UpdateTrail` và `PutBucketPolicy` vẫn được phép vì Terraform cần chúng — nghĩa
# là một PR độc hại vẫn có thể thu hẹp selector hoặc gỡ Deny trong bucket policy.
# Ba lớp còn lại xử lý phần đó: review PR bắt buộc, group 1/g7 alert (đã bypass
# automation allowlist nên kêu cả khi actor là CI role), và heartbeat so exact
# selector + bucket policy mỗi 5 phút. Boundary chỉ loại bỏ các đường tắt tức thời.
#
# THỨ TỰ TRIỂN KHAI
# Root này apply THỦ CÔNG bởi người có MFA, không qua CI. `enable_ci_audit_boundary`
# mặc định false: apply lần đầu chỉ TẠO policy, chưa attach. Chỉ bật true sau khi
# `iam:SimulatePrincipalPolicy` chứng minh baseline Terraform vẫn allowed và các
# kill switch là explicitDeny. Xem docs/mandate-12-execution-plan.md §9.

locals {
  m12_account_id = data.aws_caller_identity.current.account_id

  # ARN dựng bằng prefix pattern chứ không lấy từ output của production root:
  # hai root dùng state khác nhau. Pattern cũng giúp resource mới cùng tiền tố
  # được bảo vệ tự động.
  m12_trail_arns = [
    "arn:aws:cloudtrail:*:${local.m12_account_id}:trail/${var.cluster_name}-audit-detection-*",
  ]

  m12_archive_bucket_arns = [
    "arn:aws:s3:::${var.cluster_name}-audit-trail-*",
  ]

  m12_archive_object_arns = [
    "arn:aws:s3:::${var.cluster_name}-audit-trail-*/*",
  ]

  m12_rule_arns = [
    "arn:aws:events:*:${local.m12_account_id}:rule/${var.cluster_name}-audit-detection-*",
    "arn:aws:events:*:${local.m12_account_id}:rule/${var.cluster_name}-m12-audit-heartbeat-*",
  ]

  # M12 không có topic riêng: alert đi qua đúng hai topic alert của M11.
  m12_topic_arns = [
    "arn:aws:sns:*:${local.m12_account_id}:${var.cluster_name}-audit-detection-*",
  ]

  m12_function_arns = [
    "arn:aws:lambda:*:${local.m12_account_id}:function:${var.cluster_name}-audit-detection-*-router",
    "arn:aws:lambda:*:${local.m12_account_id}:function:${var.cluster_name}-m12-audit-heartbeat",
  ]

  m12_alarm_arns = [
    "arn:aws:cloudwatch:*:${local.m12_account_id}:alarm:${var.cluster_name}-m12-audit-heartbeat-*",
  ]

  # Dựng ARN từ tên thay vì tham chiếu aws_iam_policy.ci_audit_boundary.arn:
  # policy không thể tự tham chiếu chính nó trong document của nó (cycle).
  m12_ci_boundary_policy_arn = "arn:aws:iam::${local.m12_account_id}:policy/${var.ci_audit_boundary_name}"

  m12_ci_role_arns = [
    "arn:aws:iam::${local.m12_account_id}:role/${var.cluster_name}-gha-terraform-plan",
    "arn:aws:iam::${local.m12_account_id}:role/${var.cluster_name}-gha-terraform-apply",
  ]

  # Danh sách principal mang boundary này. Hai statement Deny bên dưới dùng
  # Resource "*" chứ không dùng danh sách này (đường vượt rào là tạo principal
  # MỚI, chưa tồn tại lúc viết policy). Danh sách tồn tại để sinh output cho
  # heartbeat canh boundary còn attach — xem output ci_audit_boundary_expected_map.
  m12_bounded_principal_arns = concat(
    local.m12_ci_role_arns,
    var.additional_bounded_principal_arns,
  )
}

data "aws_iam_policy_document" "ci_audit_boundary" {
  # Permissions boundary là TRẦN, không tự cấp quyền. Không có statement Allow
  # thì mọi thứ bị chặn. Allow rộng ở đây không mở thêm quyền nào — quyền thật
  # vẫn do policy gắn trực tiếp quyết định, và explicit Deny bên dưới luôn thắng.
  # IAM Access Analyzer sẽ cảnh báo về Action "*"; đây là cảnh báo đã biết và
  # được chấp nhận có văn bản, không phải grant mới.
  statement {
    sid       = "AllowEverythingWithinBoundary"
    effect    = "Allow"
    actions   = ["*"]
    resources = ["*"]
  }

  # Terraform đặt enable_logging = true nên chỉ gọi StartLogging, không bao giờ
  # gọi StopLogging. DeleteTrail đã bị prevent_destroy chặn ở tầng Terraform;
  # đây là lớp thứ hai ở tầng IAM.
  statement {
    sid    = "DenyAuditTrailKillSwitch"
    effect = "Deny"

    actions = [
      "cloudtrail:StopLogging",
      "cloudtrail:DeleteTrail",
    ]

    resources = local.m12_trail_arns
  }

  statement {
    sid    = "DenyAuditArchiveDestruction"
    effect = "Deny"

    actions = [
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:DeleteBucketLifecycle",
    ]

    resources = local.m12_archive_bucket_arns
  }

  # Terraform không bao giờ đụng object trong archive. Bucket policy đã có Deny
  # tương đương cho principal không phải CloudTrail; giữ ở đây để vẫn còn hiệu
  # lực nếu bucket policy bị làm yếu.
  statement {
    sid    = "DenyAuditArchiveObjectMutation"
    effect = "Deny"

    actions = [
      "s3:AbortMultipartUpload",
      "s3:BypassGovernanceRetention",
      "s3:DeleteObject",
      "s3:DeleteObjectTagging",
      "s3:DeleteObjectVersion",
      "s3:DeleteObjectVersionTagging",
      "s3:PutObject",
      "s3:PutObjectAcl",
      "s3:PutObjectLegalHold",
      "s3:PutObjectRetention",
      "s3:PutObjectTagging",
      "s3:PutObjectVersionAcl",
      "s3:RestoreObject",
    ]

    resources = local.m12_archive_object_arns
  }

  # PutRule/PutTargets vẫn được phép để Terraform quản rule. Chỉ chặn ba đường
  # làm rule ngừng bắn: tắt, xoá, và gỡ target.
  statement {
    sid    = "DenyAuditRuleDisableOrDelete"
    effect = "Deny"

    actions = [
      "events:DisableRule",
      "events:DeleteRule",
      "events:RemoveTargets",
    ]

    resources = local.m12_rule_arns
  }

  # Subscribe và SetTopicAttributes vẫn được phép (thêm người nhận, sửa config).
  statement {
    sid    = "DenyAuditAlertTopicTeardown"
    effect = "Deny"

    actions = [
      "sns:DeleteTopic",
      "sns:RemovePermission",
    ]

    resources = local.m12_topic_arns
  }

  # SNS KHÔNG có resource type cho subscription: sns:Unsubscribe và
  # sns:SetSubscriptionAttributes chỉ authorize được với Resource "*". Deny scope
  # theo topic ARN sẽ không bao giờ match, tức là vô hiệu.
  #
  # Deny toàn cục ở đây không gây thiệt hại phụ: toàn repo chỉ có hai
  # aws_sns_topic_subscription và cả hai đều thuộc audit plane. Hệ quả là CI
  # không gỡ được người nhận alert của BẤT KỲ topic nào — gỡ recipient trở thành
  # thao tác human-approved, đúng ý đồ. Thêm recipient (sns:Subscribe) vẫn chạy.
  statement {
    sid    = "DenySubscriptionTeardownAccountWide"
    effect = "Deny"

    actions = [
      "sns:Unsubscribe",
      "sns:SetSubscriptionAttributes",
    ]

    resources = ["*"]
  }

  # PutFunctionConcurrency = 0 làm router ngừng xử lý mà không xoá gì —
  # đường tắt im lặng nhất để vô hiệu alert plane.
  statement {
    sid    = "DenyAuditFunctionTeardown"
    effect = "Deny"

    actions = [
      "lambda:DeleteFunction",
      "lambda:PutFunctionConcurrency",
      "lambda:DeleteFunctionConcurrency",
      "lambda:RemovePermission",
    ]

    resources = local.m12_function_arns
  }

  statement {
    sid    = "DenyAuditAlarmTeardown"
    effect = "Deny"

    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:DisableAlarmActions",
    ]

    resources = local.m12_alarm_arns
  }

  # Không có statement này thì boundary vô nghĩa: chỉ cần gỡ boundary rồi làm gì
  # cũng được. Scope "*" chứ không chỉ các principal đang mang boundary, vì
  # đường vượt rào là: tạo role mới -> gắn boundary -> gỡ ra -> assume.
  # CI không có nhu cầu hợp lệ nào phải GỠ boundary khỏi bất kỳ principal nào;
  # rollback boundary đi qua root bootstrap do người có MFA apply.
  statement {
    sid    = "DenyRemovingAnyBoundary"
    effect = "Deny"

    actions = [
      "iam:DeleteRolePermissionsBoundary",
      "iam:DeleteUserPermissionsBoundary",
    ]

    resources = ["*"]
  }

  # Cho phép GẮN boundary, nhưng chỉ đúng boundary này. Nếu không có điều kiện,
  # CI gắn được một boundary rỗng/yếu lên principal bất kỳ rồi dùng nó vượt rào.
  # Khi phase IAM hardening cần gắn operator boundary khác, việc đó do executor
  # MFA thực hiện (§9), không qua CI — nên điều kiện này không cản.
  statement {
    sid    = "DenyAttachingAnyOtherBoundary"
    effect = "Deny"

    actions = [
      "iam:PutRolePermissionsBoundary",
      "iam:PutUserPermissionsBoundary",
    ]

    resources = ["*"]

    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.m12_ci_boundary_policy_arn]
    }
  }

  # Chặn đường lấy credential cho một principal không mang boundary.
  #
  # sts:AssumeRole: đã verify workflow dùng OIDC trực tiếp làm caller identity,
  # không chain assume-role, và provider Terraform không có block assume_role.
  # KHÔNG chặn AssumeRoleWithWebIdentity/WithSAML: đó là đường GitHub dùng để
  # tạo chính session này, và boundary của role không áp lên bước assume đó —
  # nhưng để nguyên cho chắc chắn không phá OIDC.
  #
  # iam:CreateAccessKey / LoginProfile: đã verify Terraform không quản
  # aws_iam_access_key nào. CI không có nhu cầu hợp lệ phát hành credential
  # dài hạn hay mật khẩu console.
  statement {
    sid    = "DenyCredentialIssuanceForEscalation"
    effect = "Deny"

    actions = [
      "sts:AssumeRole",
      "sts:GetFederationToken",
      "iam:CreateAccessKey",
      "iam:UpdateAccessKey",
      "iam:CreateLoginProfile",
      "iam:UpdateLoginProfile",
      "iam:CreateServiceSpecificCredential",
      "iam:ResetServiceSpecificCredential",
    ]

    resources = ["*"]
  }

  # Tương tự: chặn CI tự sửa nội dung boundary. Cập nhật boundary phải do người
  # có MFA apply root này thủ công.
  statement {
    sid    = "DenyWeakeningThisBoundary"
    effect = "Deny"

    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:DeletePolicy",
    ]

    resources = [local.m12_ci_boundary_policy_arn]
  }
}

resource "aws_iam_policy" "ci_audit_boundary" {
  name        = var.ci_audit_boundary_name
  description = "Mandate 12: CI boundary allowing general IAM/Terraform work but denying audit kill switches."
  policy      = data.aws_iam_policy_document.ci_audit_boundary.json

  lifecycle {
    prevent_destroy = true
  }
}

output "ci_audit_boundary_policy_arn" {
  description = "Gắn vào terraform_plan/terraform_apply bằng enable_ci_audit_boundary sau khi simulation pass."
  value       = aws_iam_policy.ci_audit_boundary.arn
}

output "ci_audit_boundary_attached" {
  description = "false = policy đã tạo nhưng chưa attach; CI vẫn chạy như cũ."
  value       = var.enable_ci_audit_boundary
}

# Copy nguyên giá trị này vào audit_detection_bounded_principals trong
# production.auto.tfvars ở Phase 4b. Hai root dùng state khác nhau nên không
# tham chiếu trực tiếp được, nhưng sinh sẵn ở đây tránh gõ tay sai ARN.
output "ci_audit_boundary_expected_map" {
  description = "Map principal ARN -> boundary ARN cho heartbeat canh boundary còn attach."
  value = {
    for arn in local.m12_bounded_principal_arns :
    arn => aws_iam_policy.ci_audit_boundary.arn
  }
}

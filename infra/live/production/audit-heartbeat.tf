# Mandate 12 — phần alert plane còn lại sau khi gỡ heartbeat Lambda.
#
# Heartbeat Lambda đã được gỡ khỏi repo: function, code, zip, IAM role/policy,
# log group, EventBridge schedule + target + permission và 2 alarm canh nó.
#
# File giữ nguyên tên và giữ lại đúng phần KHÔNG thuộc heartbeat: policy cho
# topic alert primary của M11. Policy này là hạ tầng M11 — gỡ nó là trả topic về
# default policy của AWS và mất statement quản trị mức account, nên không đụng.

locals {
  # Vẫn được topic policy dưới đây dùng làm điều kiện aws:SourceArn. Giữ nguyên
  # phạm vi đã duyệt của statement thay vì nới rộng nhân lúc gỡ heartbeat.
  m12_heartbeat_alarm_source_arn_pattern = "arn:aws:cloudwatch:${var.region}:${data.aws_caller_identity.m12_current.account_id}:alarm:${var.cluster_name}-m12-audit-heartbeat-*"
}

data "aws_caller_identity" "m12_current" {}

# Topic primary của M11 chưa có policy cho service principal CloudWatch. Thiếu
# nó, alarm action sẽ fail âm thầm. Thêm ở production root vì đây là nơi sở hữu
# alarm; module M11 giữ nguyên.
data "aws_iam_policy_document" "m12_primary_alarm_topic" {
  # Liệt kê tường minh thay vì "sns:*". Topic policy của SNS chỉ nhận action
  # phạm vi topic; "sns:*" nở ra cả action mức account (CreateTopic, ListTopics,
  # Unsubscribe...) và SetTopicAttributes trả về
  # "InvalidParameter: Policy statement action out of service scope".
  # Đây đúng là danh sách trong default topic policy của AWS.
  statement {
    sid = "AllowAccountManagement"
    actions = [
      "sns:AddPermission",
      "sns:DeleteTopic",
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:Publish",
      "sns:RemovePermission",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
    ]
    resources = [module.audit_detection_ap_southeast_1.sns_topic_arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.m12_current.account_id}:root"]
    }
  }

  statement {
    sid       = "AllowCloudWatchAlarmPublish"
    actions   = ["sns:Publish"]
    resources = [module.audit_detection_ap_southeast_1.sns_topic_arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.m12_current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [local.m12_heartbeat_alarm_source_arn_pattern]
    }
  }
}

resource "aws_sns_topic_policy" "m12_primary_alarm_topic" {
  arn    = module.audit_detection_ap_southeast_1.sns_topic_arn
  policy = data.aws_iam_policy_document.m12_primary_alarm_topic.json
}

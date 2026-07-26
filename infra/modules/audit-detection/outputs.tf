output "trail_name" {
  value = try(aws_cloudtrail.audit[0].name, null)
}

output "trail_bucket_name" {
  value = try(aws_s3_bucket.trail_logs[0].bucket, null)
}

output "lambda_function_name" {
  value = aws_lambda_function.audit_alert_router.function_name
}

output "sns_topic_arn" {
  value = aws_sns_topic.audit_alerts.arn
}

# Topic alert mã hoá bằng key này, nên mọi publisher ngoài module (heartbeat M12)
# phải được cấp quyền KMS trên nó — không thì publish bị deny.
#
# CHỈ dùng cho mục đích cấp quyền publish. Muốn biết bucket archive đang mã hoá
# bằng key nào thì dùng trail_bucket_kms_key_arn — hôm nay hai giá trị bằng nhau,
# nhưng đó là chi tiết cài đặt, không phải hợp đồng.
output "kms_key_arn" {
  value = aws_kms_key.audit.arn
}

# Đọc thẳng từ cấu hình mã hoá đã áp lên bucket, không đọc từ aws_kms_key.audit.
# Nếu sau này ai tách key bucket khỏi key topic — một hướng siết chặt hợp lý —
# output này tự đi theo, còn heartbeat thì không FAIL vĩnh viễn trong im lặng.
# null ở instance không tạo trail (create_trail = false).
output "trail_bucket_kms_key_arn" {
  value = try(
    one([
      for rule in aws_s3_bucket_server_side_encryption_configuration.trail_logs[0].rule :
      one(rule.apply_server_side_encryption_by_default[*].kms_master_key_id)
    ]),
    null,
  )
}

output "event_rule_names" {
  value = keys(var.event_rules)
}

# Mandate 12: heartbeat so bốn giá trị này với trạng thái Lambda thật. Kiểm tra
# State=Active là chưa đủ — router có thể bị thay code thành no-op mà vẫn Active,
# khi đó alert bị nuốt trong im lặng. detector_config nằm trong danh sách vì đó
# là nơi chứa critical_group_numbers; sửa nó là cách gỡ bypass allowlist.
output "lambda_source_code_hash" {
  value = aws_lambda_function.audit_alert_router.source_code_hash
}

output "lambda_handler" {
  value = aws_lambda_function.audit_alert_router.handler
}

output "lambda_role_arn" {
  value = aws_lambda_function.audit_alert_router.role
}

output "lambda_detector_config" {
  value = local.detector_config
}

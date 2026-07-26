moved {
  from = module.vpc
  to   = module.network.module.vpc
}

moved {
  from = aws_security_group.vpc_endpoints
  to   = module.network.aws_security_group.vpc_endpoints
}

moved {
  from = aws_vpc_endpoint.s3
  to   = module.network.aws_vpc_endpoint.s3
}

moved {
  from = aws_vpc_endpoint.ssm
  to   = module.network.aws_vpc_endpoint.ssm
}

moved {
  from = aws_vpc_endpoint.ssmmessages
  to   = module.network.aws_vpc_endpoint.ssmmessages
}

moved {
  from = aws_vpc_endpoint.ec2messages
  to   = module.network.aws_vpc_endpoint.ec2messages
}

moved {
  from = aws_kms_key.eks
  to   = module.eks_platform.aws_kms_key.eks
}

moved {
  from = aws_kms_alias.eks
  to   = module.eks_platform.aws_kms_alias.eks
}

moved {
  from = module.eks
  to   = module.eks_platform.module.eks
}

moved {
  from = module.cluster_autoscaler_irsa
  to   = module.eks_platform.module.cluster_autoscaler_irsa
}

moved {
  from = module.lb_controller_irsa
  to   = module.eks_platform.module.lb_controller_irsa
}

moved {
  from = data.aws_ami.al2023
  to   = module.access.data.aws_ami.al2023
}

moved {
  from = aws_security_group.bastion
  to   = module.access.aws_security_group.bastion
}

moved {
  from = aws_iam_role.bastion
  to   = module.access.aws_iam_role.bastion
}

moved {
  from = aws_iam_role_policy_attachment.bastion_ssm
  to   = module.access.aws_iam_role_policy_attachment.bastion_ssm
}

moved {
  from = aws_iam_instance_profile.bastion
  to   = module.access.aws_iam_instance_profile.bastion
}

moved {
  from = aws_instance.bastion
  to   = module.access.aws_instance.bastion
}

moved {
  from = aws_security_group_rule.cluster_from_bastion
  to   = module.access.aws_security_group_rule.cluster_from_bastion
}

moved {
  from = data.aws_cloudfront_cache_policy.caching_disabled
  to   = module.edge.data.aws_cloudfront_cache_policy.caching_disabled
}

moved {
  from = data.aws_cloudfront_origin_request_policy.all_viewer_except_host
  to   = module.edge.data.aws_cloudfront_origin_request_policy.all_viewer_except_host
}

moved {
  from = aws_cloudfront_distribution.frontend
  to   = module.edge.aws_cloudfront_distribution.frontend
}

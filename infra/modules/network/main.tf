module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.azs
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway     = true
  single_nat_gateway     = true
  one_nat_gateway_per_az = false

  enable_dns_hostnames = true
  enable_dns_support   = true

  public_subnet_tags = {
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.cluster_name}-vpce-sg"
  description = "Allow HTTPS from inside the VPC to interface VPC endpoints"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "HTTPS from VPC CIDR"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "${var.cluster_name}-vpce-sg"
  }
}

# Gateway endpoint for S3 has no ENI and no hourly charge, so it stays. ECR layer
# blobs live in S3, meaning image-layer bytes keep flowing over this free endpoint
# even after the ECR interface endpoints below are removed.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}

locals {
  # Directive #18 (A1): collapse the SSM-family interface endpoints from all 3 AZs down
  # to the single subnet in azs[0] (ap-southeast-1a, the bastion AZ). This drops 12 of the
  # 15 endpoint ENIs. The removed ecr.api/ecr.dkr endpoints (6 ENIs) now resolve via public
  # DNS and egress through NAT: only the tiny ECR auth/API calls take that path, while layer
  # downloads stay on the free S3 gateway endpoint above.
  #   Trade-off: if AZ 1a is lost, SSM to the bastion is unavailable - but the bastion itself
  #   lives in 1a, and Cloudflare Zero Trust remains as the second control-plane access path.
  #   NAT data-processing measured at ~$7/mo vs the 15-ENI endpoint fleet at ~$142/mo; see
  #   docs/cost-breakdown-2026-07-22.md (sections 1.1, 5.3).
  # NOTE: this assumes azs[0] is the bastion AZ. If var.azs is ever reordered, revisit both
  # this selection and the stateful-node/bastion subnet wiring in infra/live/production.
  vpce_ssm_subnet_ids = [module.vpc.private_subnets[0]]
}

resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.region}.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.vpce_ssm_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
}

resource "aws_vpc_endpoint" "ssmmessages" {
  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.region}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.vpce_ssm_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
}

resource "aws_vpc_endpoint" "ec2messages" {
  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.region}.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.vpce_ssm_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
}

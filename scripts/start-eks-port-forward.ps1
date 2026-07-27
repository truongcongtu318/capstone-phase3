param(
    [string]$BastionId = "",
    [string]$EksHost = "",
    [string]$LocalPort = "8443",
    [string]$RemotePort = "443",
    [string]$Region = "ap-southeast-1"
)

# 1. Dynamically fetch Bastion ID if not provided
if (-not $BastionId) {
    Write-Host "Fetching latest Bastion ID from AWS..." -ForegroundColor Yellow
    $BastionId = aws ec2 describe-instances `
        --region $Region `
        --filters "Name=tag:Name,Values=techx-corp-tf3-bastion" "Name=instance-state-name,Values=running" `
        --query "Reservations[].Instances[].InstanceId" --output text
    
    if (-not $BastionId) {
        Write-Error "Could not find a running Bastion host."
        exit 1
    }
}

# 2. Dynamically fetch EKS Host if not provided
if (-not $EksHost) {
    Write-Host "Fetching EKS endpoint from AWS..." -ForegroundColor Yellow
    $EksHost = aws eks describe-cluster --name techx-corp-tf3 --region $Region `
        --query "cluster.endpoint" --output text
    
    if ($EksHost -match "^https://(.*)") {
        $EksHost = $Matches[1]
    } else {
        Write-Error "Could not find EKS cluster endpoint."
        exit 1
    }
}

Write-Host "bastion=$BastionId  eks_host=$EksHost" -ForegroundColor Green
Write-Host "Starting port forwarding session to $EksHost via bastion $BastionId..." -ForegroundColor Cyan

aws ssm start-session `
  --target $BastionId `
  --document-name AWS-StartPortForwardingSessionToRemoteHost `
  --parameters "host=$EksHost,portNumber=$RemotePort,localPortNumber=$LocalPort" `
  --region $Region

# forward_ports.ps1
# Script to start port forwarding for all TechX Corp microservices in the background.
# Ensure your AWS SSM tunnel on port 8443 is running before executing this script!

$Namespace = "techx-tf3"
$ErrorActionPreference = "Stop"

# 1. Verify SSM Tunnel on Port 8443 is active
$conn = Test-NetConnection -ComputerName 127.0.0.1 -Port 8443 -WarningAction SilentlyContinue
if (-not $conn.TcpTestSucceeded) {
    Write-Error "❌ Lỗi: SSM Tunnel kết nối tới EKS (port 8443) chưa chạy! Vui lòng khởi động lại SSM tunnel trước."
    exit 1
}

Write-Host "✅ Đã tìm thấy SSM Tunnel trên cổng 8443. Bắt đầu port-forward..." -ForegroundColor Green

# 2. Define deployments and their ports
$Services = @(
    @{ name = "product-catalog"; localPort = "3550"; targetPort = "8080" },
    @{ name = "cart";            localPort = "7070"; targetPort = "8080" },
    @{ name = "product-reviews"; localPort = "9090"; targetPort = "3551" },
    @{ name = "recommendation";  localPort = "8081"; targetPort = "8080" },
    @{ name = "currency";        localPort = "7001"; targetPort = "8080" },
    @{ name = "shipping";        localPort = "50051"; targetPort = "8080" }
)

# 3. Start port forwarding in background jobs
foreach ($svc in $Services) {
    $name = $svc.name
    $localPort  = $svc.localPort
    $targetPort = $svc.targetPort
    
    # Check if port is already in use locally
    $portCheck = Test-NetConnection -ComputerName 127.0.0.1 -Port $localPort -WarningAction SilentlyContinue
    if ($portCheck.TcpTestSucceeded) {
        Write-Host "⚠️  Cổng $localPort đã được sử dụng. Bỏ qua port-forward cho $name." -ForegroundColor Yellow
        continue
    }

    Write-Host "🚀 Đang chuyển tiếp cổng $localPort -> $targetPort cho deployment/$name..." -ForegroundColor Cyan
    
    # Run kubectl port-forward as a background job in PowerShell
    Start-Job -Name "pf-$name" -ScriptBlock {
        param($name, $localPort, $targetPort, $Namespace)
        $env:AWS_PROFILE = "techx-corp"
        kubectl port-forward deployment/$name "${localPort}:${targetPort}" -n $Namespace
    } -ArgumentList $name, $localPort, $targetPort, $Namespace | Out-Null
}

Write-Host "✅ Tất cả các cổng đã được chuyển tiếp chạy ngầm!" -ForegroundColor Green
Write-Host "💡 Để xem danh sách jobs đang chạy: Get-Job"
Write-Host "💡 Để tắt tất cả port-forward: Get-Job | Remove-Job -Force"

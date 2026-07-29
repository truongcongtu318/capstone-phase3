# aiops-engine

AIOps engine của AIO02: phát hiện bất thường (Isolation Forest), phân tích nguyên nhân
qua Bedrock, và khắc phục có người duyệt qua Slack.

## Nguồn gốc

Source được kéo về từ <https://github.com/DangThao195/AIO02_TF3_Phase3>, thư mục
`AIOps/aiops-engine/`, tại commit `d68dd9759491dc03e9a3d83c27393f52851dc8c9`
(2026-07-27 20:32:09 +0700).

Từ nay repo này là nguồn sự thật: image production build bằng
`.github/workflows/build-push-aiops.yml` (Trivy gate + Cosign keyless), và manifest deploy
nằm ở `gitops/aiops-engine/` do ArgoCD quản.

Lý do chuyển: trước đây ảnh `tf-2-ai-engine` được build tay và push thẳng ECR, không đi qua
supply-chain gate PM-101 — khác với mọi workload khác trên cụm.

## Những gì KHÔNG được kéo về

| Bỏ | Vì sao |
|---|---|
| `models/` (7 file `.joblib`, 14MB) | Kho model thật là S3 `tf3-aiops-models-197826770971/current/`. `.dockerignore` vốn đã loại chúng khỏi ảnh, nên chúng chỉ là dung lượng chết trong git và đổi mỗi lần retrain. |
| `scratch/` | Script debug chạy tay, cũng đã bị `.dockerignore` loại. |
| `audit_log.jsonl` | State runtime, không phải source. |
| `k8s/` | Manifest tay đã lạc hậu và **nguy hiểm**: `ingress.yaml` là bản `internet-facing` phơi `/remediation` ra Internet không xác thực (đã gỡ khỏi production 28/07); `rbac.yaml` bind vào ServiceAccount `default` với `pods/exec`+`pods:delete`. Nguồn sự thật là `gitops/aiops-engine/` do ArgoCD quản. |
| `main.tf` | Terraform root thứ hai, không backend, tạo OpenSearch Serverless + Bedrock KB + S3 `force_destroy`. Repo này có đúng một TF root `infra/live/production/`. Hạ tầng AI nếu cần thì đưa vào đó, không để root rời. |

## Điểm còn cần AIO02 xử lý trong `Dockerfile`

- **Không có chỉ thị `USER`.** Ảnh mặc định chạy root; chỉ nhờ `securityContext.runAsUser: 10001`
  của pod mới thành non-root. Chạy ảnh này ngoài cụm là root.

## Kubectl trong image

Image giữ command surface của `kubectl v1.36.3`, tương thích version skew với EKS 1.35.
Trong lúc chưa có stable release chứa bản vá, binary được build từ module
`k8s.io/kubectl v0.36.3` và ghim các dependency đã vá (`golang.org/x/net v0.57.0`,
`golang.org/x/text v0.40.0`, `go.opentelemetry.io/otel v1.42.0`). Builder image
được ghim bằng digest để phần build binary kubectl tái lập được.

Không nâng lên Kubernetes 1.37 beta: phiên bản đó chưa stable và vượt quá một minor so
với API server 1.35. Các CVE của binary kubectl không bị bỏ qua trong Trivy.

## Runtime base và Trivy gate

Runtime dùng `python:3.10.20-alpine3.23` ghim theo digest. `scikit-learn` được build
trong stage riêng có compiler; runtime chỉ giữ virtualenv cùng `libgomp` và
`libstdc++`. `pip`, `setuptools` và `wheel` bị gỡ khỏi cả runtime Python lẫn
virtualenv sau khi cài dependency.

`build-push-aiops.yml` áp cùng cổng với pipeline production chung: zero
HIGH/CRITICAL, không `--ignore-unfixed` và không ignorefile. Báo cáo JSON đầy đủ
vẫn được lưu làm evidence trước khi push.

## Chạy test

```bash
cd aiops-engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install pytest pytest-asyncio httpx
pytest tests/
```

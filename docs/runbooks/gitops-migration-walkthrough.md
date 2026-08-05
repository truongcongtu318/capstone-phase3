# Walkthrough: Account migration, GitOps, private access, autoscaling, and NetworkPolicy

**Ngay cap nhat:** 14/07/2026  
**Cluster:** `techx-corp-tf3` / `ap-southeast-1`  
**Namespace app:** `techx-tf3`  
**Nhanh test hien tai:** `deploy/account-migration-gitops`  
**Commit live da verify:** `7d4750a`

Tai lieu nay tom tat nhung viec da lam trong dot migrate sang AWS account moi va cac thay doi GitOps/Security/Performance lien quan. Muc tieu la de ca team biet hien cluster dang duoc quan ly nhu the nao, smoke test bang gi, va con viec nao chua nen coi la xong.

## Nguyen tac quan trong

- Khong merge vao `main` trong giai doan test account moi.
- Storefront public chi di qua CloudFront; cac cong van hanh di qua duong rieng/port-forward.
- Khong commit secret that vao Git, chat, PR, log.
- Khong vo hieu hoa `flagd` hoac co che sync token cua BTC.
- Khong bat default-deny NetworkPolicy toan namespace khi chua co allowlist va smoke test day du.
- Sau nay moi thay doi ha tang/GitOps/Security/Performance dang ke phai cap nhat them vao file nay:
  - ghi ro thay doi da lam;
  - ghi lenh/evidence smoke test;
  - ghi rollback neu thay doi co rui ro lam gian doan;
  - ghi nhung phan chua hoan tat de team khong hieu nham la da done.

## Tong quan trang thai hien tai

### EKS version / support mode

Live cluster:

```text
cluster version: 1.35
platformVersion: eks.18
cluster status: ACTIVE
createdAt: 2026-07-13T18:46:58+07:00
upgradePolicy.supportType: EXTENDED
```

Worker nodes:

```text
kubelet: v1.35.6-eks-8f14419
OS: Amazon Linux 2023.12.20260611
instance type: t3.large
```

Ket luan tai ngay 14/07/2026:

- Kubernetes `1.35` dang nam trong danh sach EKS versions o **standard support**.
- `upgradePolicy.supportType=EXTENDED` la chinh sach cho phep cluster tu dong vao extended support khi version het standard support; no khong co nghia cluster hien tai dang bi tinh la extended support.
- Can tiep tuc theo doi AWS Health/EKS release lifecycle truoc khi het standard support de tranh phi extended support khong can thiet.

### GitOps / ArgoCD

Tat ca ArgoCD apps dang `Synced / Healthy`:

```text
external-secrets           Synced   Healthy   0.20.4
flagd-secret-sync          Synced   Healthy   7d4750a...
karpenter                  Synced   Healthy   1.14.0
karpenter-nodepool         Synced   Healthy   7d4750a...
techx-corp                 Synced   Healthy   7d4750a...
techx-corp-bootstrap       Synced   Healthy   7d4750a...
techx-edge                 Synced   Healthy   7d4750a...
techx-infrastructure-app   Synced   Healthy   7d4750a...
```

ArgoCD dang quan ly:

- App Helm chinh `techx-corp`.
- Infrastructure manifests trong `gitops/infrastructure/`.
- Edge/internal ingress trong `gitops/edge/`.
- Karpenter controller va NodePool.
- External Secrets va secret sync cho `flagd-sync-token`.

### Public/private boundary

Storefront public dang di qua CloudFront:

```text
https://d2tn71186d7ilz.cloudfront.net
```

CloudFront distribution:

```text
Status: Deployed
Enabled: true
Origin Id: frontend-private-alb
Origin DomainName: internal-techx-tf3-frontend-internal-683117328.ap-southeast-1.elb.amazonaws.com
```

Internal ALB:

```text
Scheme: internal
State: active
DNSName: internal-techx-tf3-frontend-internal-683117328.ap-southeast-1.elb.amazonaws.com
```

Trong namespace `techx-tf3` hien chi con Ingress:

```text
frontend-proxy-internal   alb   *   internal-techx-tf3-frontend-internal-683117328.ap-southeast-1.elb.amazonaws.com   80
```

Khong con public ALB ingress trong namespace app.

## Cac thay doi da thuc hien

### 1. Refactor Terraform/GitOps cho account moi

- Chuyen production Terraform ve layout `infra/live/production` va module hoa cac lop:
  - `network`
  - `eks-platform`
  - `access`
  - `edge`
- Backend Terraform state dung S3 + DynamoDB lock.
- GitHub Actions infra da duoc dieu chinh de plan/apply tren nhanh test `deploy/account-migration-gitops` trong giai doan on dinh.
- Da apply theo nguyen tac targeted khi full plan bi chan boi precondition CloudFront staging selector khong lien quan.

### 2. Mandate #1 - storefront public, ops private

Da chuyen entrypoint khach hang sang:

```text
Internet -> CloudFront -> VPC Origin -> internal ALB -> frontend-proxy -> app services
```

Da clean public ALB cu, khong merge main.

Cong van hanh khong public truc tiep:

- ArgoCD
- Grafana
- Jaeger
- Prometheus
- Locust/load-generator

Truy cap ops UI qua private path/port-forward, xem runbook:

```text
docs/runbooks/private-access-to-ops-uis.md
```

Da tao IAM reviewer path cho mentor:

- IAM bootstrap user local profile: `mentor-mandate-bootstrap`
- Reviewer role: `techx-tf3-mandate-reviewer`
- EKS access entry/RBAC
- SSM document: `TechX-Mandate01-EKS-PortForward`

Khong in access key/secret key ra chat hay docs.

### 3. Mandate #2 - metrics, HPA, Karpenter Spot, resource tuning

Da bat cac thanh phan can cho flash-sale readiness:

- `metrics-server` EKS add-on.
- HPA cho hot path:
  - `frontend-proxy`
  - `frontend`
  - `checkout`
  - `cart`
  - `product-catalog`
  - `product-reviews`
  - `currency`
  - `recommendation`
  - `ad`
- Karpenter controller.
- Karpenter Spot NodePool:

```text
nodepool.karpenter.sh/flash-sale-spot   flash-sale-spot   NODES 0   READY True
```

HPA snapshot smoke:

```text
ad-hpa                cpu: 2%/65%    min 1   max 4   replicas 1
cart-hpa              cpu: 6%/65%    min 2   max 6   replicas 2
checkout-hpa          cpu: 3%/65%    min 2   max 8   replicas 2
currency-hpa          cpu: 2%/65%    min 2   max 6   replicas 2
frontend-hpa          cpu: 14%/65%   min 2   max 8   replicas 2
frontend-proxy-hpa    cpu: 6%/65%    min 2   max 8   replicas 2
product-catalog-hpa   cpu: 3%/65%    min 2   max 8   replicas 2
product-reviews-hpa   cpu: 7%/65%    min 2   max 6   replicas 2
recommendation-hpa    cpu: 9%/65%    min 1   max 4   replicas 1
```

Resource guardrails hien tai:

```text
ResourceQuota:
pods: 39/90
requests.memory: 6438Mi/16Gi
limits.memory: 11228Mi/24Gi

LimitRange:
techx-limits
```

PDB da co cho cac workload quan trong nhu `frontend`, `frontend-proxy`, `checkout`, `cart`, `product-catalog`, `product-reviews`, `payment`, `shipping`, `quote`, `currency`, `opensearch`.

Da right-size requests/limits cho nhieu service, tang headroom cho Grafana/Jaeger/Prometheus/OpenSearch de giam OOMKilled.

### 4. Secret management cho `flagd-sync-token`

Trang thai truoc do:

- K8s Secret `flagd-sync-token` ton tai thu cong.
- Khong co ownerReferences/annotations/labels GitOps.
- Token khong nam trong Git history.

Da chuyen sang flow:

```text
AWS Secrets Manager -> External Secrets Operator -> Kubernetes Secret flagd-sync-token
```

Terraform da tao:

- Secrets Manager secret: `techx-corp-tf3/flagd-sync-token`
- IAM role: `techx-corp-tf3-external-secrets`
- Least-privilege policy chi cho secret nay: `secretsmanager:DescribeSecret`, `secretsmanager:GetSecretValue`

GitOps da them:

- `gitops/apps/external-secrets-app.yaml`
- `gitops/apps/flagd-secret-sync-app.yaml`
- `gitops/secrets/flagd-sync-token.yaml`

Luu y ve zero downtime:

- Dung `creationPolicy: Merge` cho `flagd-sync-token` vi secret da ton tai thu cong.
- Khong recreate secret dot ngot, khong in raw token.

Smoke secret sync:

```text
ClusterSecretStore/aws-secrets-manager: Ready=True, reason=Valid
ExternalSecret/flagd-sync-token: Ready=True, reason=SecretSynced
secret_match=true
len=48
sha256=88f93a83088bbf4217e93c8b1535904af36490eeb3648c6af0071a2cae28119e
```

### 5. NetworkPolicy enforcement tren EKS

Van de truoc do:

- Co NetworkPolicy object nhung VPC CNI node agent chay voi `--enable-network-policy=false`.
- Smoke test cu cho thay `image-provider` van connect duoc `postgresql:5432`.

Da sua bang Terraform:

```hcl
configuration_values = jsonencode({
  enableNetworkPolicy = "true"
  nodeAgent = {
    healthProbeBindAddr = "8163"
    metricsBindAddr     = "8162"
  }
})
```

EKS add-on hien tai:

```text
addon: vpc-cni
status: ACTIVE
version: v1.22.3-eksbuild.1
configurationValues: {"enableNetworkPolicy":"true","nodeAgent":{"healthProbeBindAddr":"8163","metricsBindAddr":"8162"}}
health issues: []
```

`aws-eks-nodeagent` hien dang chay voi:

```text
--enable-network-policy=true
--metrics-bind-addr=:8162
--health-probe-bind-addr=:8163
```

### 6. NetworkPolicy phase 1 theo CDO01 backlog

Backlog yeu cau P0:

- Postgres chi cho `product-catalog`, `product-reviews`, `accounting`.
- Valkey chi cho `cart`.
- Kafka chi cho `checkout`, `accounting`, `fraud-detection`.
- Grafana khong de pod app thuong truy cap.
- Khong default-deny ca namespace ngay.

Da deploy 4 NetworkPolicy:

```text
postgres-network-policy      app.kubernetes.io/component=postgresql
valkey-cart-network-policy   app.kubernetes.io/component=valkey-cart
kafka-network-policy         app.kubernetes.io/component=kafka
grafana-network-policy       app.kubernetes.io/instance=techx-corp,app.kubernetes.io/name=grafana
```

AWS network policy controller da tao `PolicyEndpoint`:

```text
grafana-network-policy-s58f9
kafka-network-policy-qs5j7
postgres-network-policy-w8x5b
valkey-cart-network-policy-rd2xc
```

Smoke tu pod khong lien quan `image-provider`:

```text
postgresql:5432        BLOCKED_OR_TIMEOUT
valkey-cart:6379       BLOCKED_OR_TIMEOUT
kafka:9092             BLOCKED_OR_TIMEOUT
grafana:80             BLOCKED_OR_TIMEOUT
jaeger:16686           OPEN
prometheus:9090        OPEN
opensearch:9200        OPEN
load-generator:8089    OPEN
flagd:8013             OPEN
otel-collector:4317    OPEN
```

Smoke allowlist:

```text
product-catalog -> postgresql:5432   POSTGRES_ALLOWED
cart            -> valkey-cart:6379  VALKEY_ALLOWED
checkout        -> kafka:9092        KAFKA_ALLOWED
```

- P0 NetworkPolicy phase 1 da dat cho Postgres/Valkey/Kafka/Grafana.
- Observability surface con lai (`Jaeger`, `Prometheus`, `OpenSearch`, `load-generator`, `otel-collector`) van la phase sau theo backlog item #9.

### 7. Grafana memory resources tuning (Tránh lỗi OOMKilled)

- **Vấn đề**: Trong quá trình vận hành hệ thống và điều tra sự cố (truy vấn metrics/traces dung lượng lớn cùng lúc), container `grafana` bị hệ điều hành kết liễu (`OOMKilled`, exit code 137) do vượt quá giới hạn bộ nhớ cũ (`500Mi`), làm đứt kết nối port-forward.
- **Giải pháp**: Tăng tài nguyên RAM cho Grafana trong `phase3 - information/deploy/values-prod.yaml`:
  - `requests.memory`: `250Mi` $\rightarrow$ `512Mi`
  - `limits.memory`: `500Mi` $\rightarrow$ `1Gi`
- **Kết quả**: Pod Grafana tự động khởi động lại, chạy ổn định (`4/4 Ready`), không còn bị crash khi truy vấn tải cao.

## Smoke test ngay 14/07/2026

### Storefront public qua CloudFront

```text
GET /                                  code=200 time=0.428065
GET /api/data                          code=200 time=0.184800
GET /api/data?contextKeys=accessories  code=200 time=0.322042
GET /api/products                      code=200 time=0.153626
```

### Deployment readiness hot path

```text
frontend-proxy    READY 2   AVAILABLE 2   DESIRED 2
frontend          READY 2   AVAILABLE 2   DESIRED 2
cart              READY 2   AVAILABLE 2   DESIRED 2
checkout          READY 2   AVAILABLE 2   DESIRED 2
product-catalog   READY 2   AVAILABLE 2   DESIRED 2
payment           READY 2   AVAILABLE 2   DESIRED 2
```

### Pod health

Lenh:

```sh
kubectl -n techx-tf3 get pods --no-headers | awk '$3 != "Running" && $3 != "Completed" {print}'
```

Ket qua:

```text
<empty>
```

Khong co pod bat thuong tai thoi diem smoke.

### GitOps health

Lenh:

```sh
kubectl -n argocd get app -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision'
```

Ket qua: tat ca apps `Synced / Healthy`.

### NetworkPolicy block/allow

Block test tu pod `image-provider`:

```sh
kubectl -n techx-tf3 exec "$IMG_POD" -- nc -zvw2 postgresql 5432
kubectl -n techx-tf3 exec "$IMG_POD" -- nc -zvw2 valkey-cart 6379
kubectl -n techx-tf3 exec "$IMG_POD" -- nc -zvw2 kafka 9092
kubectl -n techx-tf3 exec "$IMG_POD" -- nc -zvw2 grafana 80
```

Ket qua: tat ca `BLOCKED_OR_TIMEOUT`.

Allow test bang ephemeral pods co label allowlist:

```sh
kubectl -n techx-tf3 run smoke-allow-product-catalog --rm -i --restart=Never \
  --image=public.ecr.aws/docker/library/busybox:1.36 \
  --labels='app.kubernetes.io/component=product-catalog' \
  --command -- sh -c 'nc -zvw3 postgresql 5432 && echo POSTGRES_ALLOWED'

kubectl -n techx-tf3 run smoke-allow-cart --rm -i --restart=Never \
  --image=public.ecr.aws/docker/library/busybox:1.36 \
  --labels='app.kubernetes.io/component=cart' \
  --command -- sh -c 'nc -zvw3 valkey-cart 6379 && echo VALKEY_ALLOWED'

kubectl -n techx-tf3 run smoke-allow-checkout --rm -i --restart=Never \
  --image=public.ecr.aws/docker/library/busybox:1.36 \
  --labels='app.kubernetes.io/component=checkout' \
  --command -- sh -c 'nc -zvw3 kafka 9092 && echo KAFKA_ALLOWED'
```

Ket qua:

```text
POSTGRES_ALLOWED
VALKEY_ALLOWED
KAFKA_ALLOWED
```

## Cac file GitOps/Terraform quan trong

### ArgoCD apps

```text
gitops/bootstrap/application.yaml
gitops/apps/techx-corp.yaml
gitops/apps/infrastructure-app.yaml
gitops/apps/techx-edge.yaml
gitops/apps/karpenter-app.yaml
gitops/apps/karpenter-nodepool-app.yaml
gitops/apps/external-secrets-app.yaml
gitops/apps/flagd-secret-sync-app.yaml
```

### Infrastructure manifests

```text
gitops/infrastructure/hpa-hotpath.yaml
gitops/infrastructure/limit-range.yaml
gitops/infrastructure/resource-quota.yaml
gitops/infrastructure/pdb-checkout.yaml
gitops/infrastructure/network-policy-postgres.yaml
gitops/infrastructure/network-policy-valkey.yaml
gitops/infrastructure/network-policy-kafka.yaml
gitops/infrastructure/network-policy-grafana.yaml
```

### Edge

```text
gitops/edge/frontend-proxy-internal-ingress.yaml
infra/modules/edge/
```

### EKS platform

```text
infra/modules/eks-platform/main.tf
infra/modules/eks-platform/karpenter.tf
infra/modules/eks-platform/external-secrets.tf
```

## Rollback nhanh

### NetworkPolicy

Neu mot policy lam gay app:

```sh
kubectl -n techx-tf3 delete networkpolicy <policy-name>
```

Traffic quay lai trang thai truoc trong vai giay. Sau do revert file GitOps va push lai nhanh hien tai de Argo khong tu recreate policy.

### VPC CNI NetworkPolicy enforcement

Chi rollback neu policy enforcement lam cluster network bat thuong. Doi config add-on ve:

```json
{"enableNetworkPolicy":"false"}
```

Uu tien rollback policy rieng truoc, khong tat enforcement ca cluster neu chi sai allowlist.

### External Secret `flagd-sync-token`

Khong xoa Kubernetes Secret that neu dang production. Neu External Secrets loi:

```sh
kubectl -n argocd get app external-secrets flagd-secret-sync
kubectl get clustersecretstore aws-secrets-manager
kubectl -n techx-tf3 get externalsecret flagd-sync-token
```

Vi target dang `creationPolicy: Merge`, secret hien co khong bi owner-delete boi External Secrets.

### Storefront edge

Neu CloudFront/private origin loi:

- Kiem tra CloudFront distribution status.
- Kiem tra internal ALB target health.
- Kiem tra `frontend-proxy-internal` ingress.
- Chi rollback edge phase theo Terraform/runbook, khong tao lai public ops endpoints.

## Con viec con lai

### NetworkPolicy phase sau

Chua dong cac surface sau tu pod app thuong:

```text
jaeger:16686
prometheus:9090
opensearch:9200
load-generator:8089
flagd:8013
otel-collector:4317
```

Can map allowlist ky truoc khi chuyen sang deny:

- `otel-collector` can gui logs/metrics/traces toi OpenSearch/Prometheus/Jaeger.
- Grafana co the can doc Prometheus/OpenSearch/Jaeger tuy dashboard/datasource.
- App services can day telemetry toi `otel-collector`.
- `flagd` la co che fault-injection cua BTC, khong duoc vo hieu hoa.

### Private access UX phase sau

Mentor feedback: SSM bastion + port-forward dat least-exposure nhanh cho Mandate #1 nhung chua tot ve van hanh dai han. Da dua vao backlog CDO01 muc #15 de spike solution khac nhu Cloudflare Zero Trust, Tailscale, NetBird hoac OpenVPN, kem private domain va onboarding/offboarding chuan. SSM hien giu lai nhu break-glass/private fallback cho toi khi solution moi duoc verify.

### Load test 200 users

Smoke test trong tai lieu nay chi la functional smoke nhe. Chua thay the cho bai load test 200 concurrent users / 15 phut cua Mandate #2.

Can nop rieng evidence:

- Success rate checkout >= 99%.
- Browse/cart >= 99.5%.
- Storefront p95 < 1s.
- Cost/capacity truoc-sau, scale up/scale down.

### Full Terraform plan

Da sua precondition CloudFront staging selector trong `infra/modules/edge/main.tf`:

- `edge_phase = "staging"` van bat buoc co `cloudfront_staging_selector`.
- `edge_phase = "private"`/`rollback` khong can selector chi de chay plan vi staging traffic dang disabled.
- Neu selector khong duoc truyen khi staging disabled, module dung placeholder `__disabled__` cho Continuous Deployment policy.

Verify sau sua:

```bash
terraform -chdir=infra/modules/edge test -no-color
# Success! 7 passed, 0 failed.

terraform -chdir=infra/live/production plan -no-color -input=false
# Plan: 0 to add, 6 to change, 0 to destroy.
```

Plan hien tai da het loi precondition. Cac change con lai khong destroy: update tag discovery cho Karpenter IAM/SQS/EKS access entry va update header value cua CloudFront Continuous Deployment policy dang disabled.

## Ghi chu cho team

- Hien cluster dang o trang thai tot cho smoke nhe va Security phase 1.
- Khong coi NetworkPolicy la hoan tat toan bo app; moi xong datastore/Grafana P0.
- Khong chay load test lon khi chua co nguoi monitor Grafana/Prometheus/Kubernetes events.
- Khong in secret that vao chat/docs. Khi can so sanh secret, dung length + sha256 fingerprint.

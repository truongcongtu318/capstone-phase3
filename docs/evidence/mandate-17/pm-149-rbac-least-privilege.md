# PM-149 — RBAC least privilege evidence

Status: implemented and reconciled in production on 2026-07-24. SEC-01 is
accepted as an operational pass with limited verifier provenance; SEC-02
passed.

## Scope

PM-149 closes only:

- SEC-01: Grafana cluster-wide Secret read access.
- SEC-02: unnecessary Kubernetes API token automount for workloads using the
  shared `techx-corp` ServiceAccount.

This evidence does not claim completion of the remaining Mandate 17 findings,
per-service ServiceAccount migration, NetworkPolicy work, Terraform changes, or
flagd changes.

## Environment metadata

| Field | Value |
|---|---|
| Cluster | `techx-corp-tf3` |
| Account | `197826770971` |
| Region | `ap-southeast-1` |
| Namespace | `techx-tf3` |
| Git branch | `feat/pm-149-mandate17-rbac-least-privilege` |
| PM-149 PR / merge | `#382` / `0d05aaf` |
| Hotfix PR / merge | `#383` / `4dbceba` |
| Argo revision | `4dbceba9c32d09ec4ea926fab860d3d62819f4c0` |
| Readonly verifier | `arn:aws:sts::197826770971:assumed-role/tf3-production-readonly/viet-readonly` |
| Privileged verifier | Not captured; the `no`/`yes` results were supplied separately and are retained as unattributed supporting evidence |
| Readonly capture | `2026-07-24 03:08:54 UTC`; independently captured live Role/RoleBinding and confirmed it cannot impersonate ServiceAccounts |

## Render evidence

Authoritative render must use a temporary chart copy and this values order:

```text
phase3 - information/techx-corp-chart/values.yaml
phase3 - information/deploy/values-flagd-sync.yaml
phase3 - information/deploy/values-prod.yaml
phase3 - information/deploy/values-aio-llm.yaml
```

Record:

- Helm version and command;
- rendered checksum;
- rendered Grafana `Role` and `RoleBinding`;
- absence of Grafana-owned `ClusterRole` and `ClusterRoleBinding`;
- dynamic list of workloads whose `serviceAccountName` is `techx-corp`;
- `automountServiceAccountToken: false` assertion for every shared-SA workload;
- `product-reviews-bedrock` ServiceAccount and IRSA annotation assertion.

Do not store rendered Secret values or ServiceAccount tokens.

## Live verification

The privileged verifier must record the command, timestamp, and result for:

```bash
kubectl auth can-i list secrets \
  --as=system:serviceaccount:techx-tf3:grafana \
  -n kube-system

kubectl auth can-i list secrets \
  --as=system:serviceaccount:techx-tf3:grafana \
  -n techx-tf3

kubectl -n techx-tf3 get role,rolebinding
kubectl get clusterrole,clusterrolebinding
kubectl -n techx-tf3 get serviceaccount techx-corp \
  -o jsonpath='{.automountServiceAccountToken}{"\n"}'
kubectl -n techx-tf3 get deploy -o json
kubectl -n techx-tf3 get pods -o json
```

Expected:

- Grafana cannot list Secrets in `kube-system`;
- Grafana can list required Secrets in `techx-tf3`;
- Grafana namespaced Role/RoleBinding exists;
- Grafana-owned cluster RBAC is absent after Argo prune;
- every current shared-SA workload has Pod-template automount `false`;
- newly created shared-SA Pods have no `kube-api-access-*` volume;
- `product-reviews` still uses `product-reviews-bedrock`.

If readonly access returns `Forbidden`, record the exact error and do not
interpret that error itself as a security pass. Separately supplied results must
retain an explicit provenance limitation.

## Production verification — 2026-07-24

Verification ran read-only through the existing SSM tunnel against EKS
`v1.35.6-eks-8f14419`. STS confirmed account `197826770971` before any
Kubernetes query. The documented local profile name `techx-new` was not present
on this workstation; profile `default` was used only after STS proved that it
resolved to the production read-only role above.

### Reconciliation and rollout

| Check | Result |
|---|---|
| Argo Application | `techx-corp` `Synced/Healthy` at `4dbceba9c32d09ec4ea926fab860d3d62819f4c0` |
| Deployments | All expected Deployments available; no non-ready application Pod at final gate |
| Checkout Rollout | `Healthy`, step `7`, stable/current hash `b5479c5d6`, `2/2` ready and updated |
| Checkout 20% analysis | `checkout-rollout-b5479c5d6-30-1` `Successful` |
| Checkout 50% analysis | `checkout-rollout-b5479c5d6-30-4` `Successful`, three measurements |
| Restarts | Newly rolled PM-149 application Pods had zero restarts |

Final checkout 50% measurements:

| Metric | Result |
|---|---:|
| Request rate | `2.4833333333333334` requests/second |
| Canary success rate | `1` |
| Success-rate regression | `0` |
| Canary p95 | `22.909090909090875` ms |
| p95 regression | `19.084090909090875` ms |

The first mass rollout briefly emitted CNI IP-assignment, readiness, and HPA
missing-metric warnings while replacement Pods started. All affected workloads
became Ready, no new warning persisted, and the checkout analyses passed, so the
rollback gate was not triggered.

### SEC-01 result

Argo's live resource tree reported namespaced `Role/grafana` and
`RoleBinding/grafana` as `Synced`. It reported cluster roles only for
`otel-gateway`, `otel-node-agent`, and `prometheus`; no Grafana-owned
`ClusterRole` or `ClusterRoleBinding` was managed by the Application.

The read-only identity cannot impersonate ServiceAccounts, so its `Forbidden`
responses are not treated as authorization results for Grafana. The expected
production results were supplied separately:

```text
kube-system list secrets: no
techx-tf3 list secrets: yes
Role/grafana: resources=configmaps,secrets; verbs=get,watch,list
RoleBinding/grafana: Role/grafana -> ServiceAccount/techx-tf3/grafana
Grafana ClusterRole/ClusterRoleBinding grep: no output
```

At `2026-07-24 03:08:54 UTC`, the read-only identity independently captured the
live `Role/grafana` and `RoleBinding/grafana`. Their content matches the
separately supplied authorization results: Grafana receives only namespaced
`get`, `list`, and `watch` access to ConfigMaps and Secrets through its
namespaced RoleBinding. Argo's resource tree independently corroborates that no
Grafana-owned cluster RBAC is managed by the release.

SEC-01 is therefore accepted as an operational pass for PM-149. The verifier
identity for the dynamic `no`/`yes` pair was not captured in the same command
session, so this evidence is not represented as a fully attributable privileged
audit transcript. That provenance limitation is retained rather than assigning
the results to `tf3-production-readonly/viet-readonly`. No extra production
RBAC was granted solely for verification.

### SEC-02 result

- The initial `#382` render placed the ServiceAccount automount field under
  `metadata`, which the API server dropped. Regression test `f74d88d` reproduced
  the missing top-level field.
- Hotfix `604b78c`, merged by `#383`, moved the field to the Kubernetes
  ServiceAccount top level.
- Live `ServiceAccount/techx-corp` returned
  `automountServiceAccountToken=false`.
- All 18 shared-SA Deployment templates returned Pod-level automount `false`:
  `accounting`, `ad`, `cart`, `checkout`, `currency`, `email`, `flagd`,
  `fraud-detection`, `frontend`, `frontend-proxy`, `image-provider`, `llm`,
  `load-generator`, `payment`, `product-catalog`, `quote`, `recommendation`,
  and `shipping`.
- After canary promotion both checkout Pods used hash `b5479c5d6`, returned
  Pod-level automount `false`, and had no `kube-api-access-*` volume.
- `product-reviews` continued to use `product-reviews-bedrock` with role
  `arn:aws:iam::197826770971:role/techx-corp-tf3-product-reviews-bedrock`.

The focused regression suite passed `11/11` after the hotfix.

## Availability and smoke tests

Final read-only smoke results:

| Endpoint / check | Result |
|---|---|
| CloudFront storefront `/` | `200` |
| CloudFront `/api/products` | `200` |
| CloudFront `/grafana/` | `403` |
| CloudFront `/jaeger/` | `403` |
| CloudFront `/loadgen/` | `403` |
| CloudFront `/feature/` | `403` |
| Cloudflare Grafana | `302` to the approved Access login flow |
| Grafana recent logs | No `Forbidden`, `AccessDenied`, or WebIdentity match |
| Product-reviews recent logs | No `Forbidden`, `AccessDenied`, `WebIdentity`, or invalid identity token match |

No flagd manifest, token, sync source, `/flagservice` route, or fault-injection
mechanism was changed.

## Rollback readiness

| Field | Value |
|---|---|
| PM-149 merge commit | `0d05aaf` |
| Corrective hotfix | PR `#383`, merge `4dbceba` |
| Revert branch/PR | Not created; rollback gate was not triggered |
| Rollback owner | TF3 production operator through normal reviewed GitOps PR |
| Argo expected behavior | reconcile reverted Git state; no manual live patch |

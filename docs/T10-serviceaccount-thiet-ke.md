# T10 — Workload identity hygiene

Status: **Wave 1 candidate**

## Scope confirmed from the live cluster

The production inventory was captured read-only on 2026-07-28. Eighteen
business services still use the shared `techx-corp` ServiceAccount:

| Service | Target ServiceAccount | Kubernetes API permission |
|---|---|---|
| image-provider | `techx-image-provider` | none |
| ad | `techx-ad` | none |
| recommendation | `techx-recommendation` | none |
| llm | `techx-llm` | none |
| product-catalog | `techx-product-catalog` | none |
| accounting | `techx-accounting` | none |
| fraud-detection | `techx-fraud-detection` | none |
| load-generator | `techx-load-generator` | none |
| frontend | `techx-frontend` | none |
| frontend-proxy | `techx-frontend-proxy` | none |
| currency | `techx-currency` | none |
| quote | `techx-quote` | none |
| shipping | `techx-shipping` | none |
| email | `techx-email` | none |
| payment | `techx-payment` | none |
| cart | `techx-cart` | none |
| checkout | `techx-checkout` | none |
| flagd | `techx-flagd` | none |

Per-service identities are intentionally stricter than the original six-group
proposal: granting a future permission to one workload cannot grant it to
another workload in the same business group.

No Role, RoleBinding, ClusterRole or ClusterRoleBinding is created for these
identities. All use `automountServiceAccountToken: false`.

## Existing identities that must be preserved

| Workload | Current identity | Decision |
|---|---|---|
| product-reviews | `product-reviews-bedrock` | Preserve name and IRSA role; do not migrate |
| aiops-engine | `aiops-engine` | Already dedicated; outside this migration |
| shopping-copilot | `shopping-copilot-sa` | Already dedicated; outside this migration |
| grafana | `grafana` | Already dedicated; keep existing namespaced RBAC |
| jaeger | `jaeger` | Already dedicated |
| otel-gateway | `otel-gateway` | Already dedicated; keep required telemetry RBAC |
| prometheus | `prometheus` | Already dedicated; keep required scrape RBAC |

`product-reviews-bedrock` is bound to:

```text
arn:aws:iam::197826770971:role/techx-corp-tf3-product-reviews-bedrock
```

Its IAM trust policy is tied to the ServiceAccount subject. Renaming it would
break Bedrock authentication.

## Retired in-cluster components

The following components are disabled in production and are not part of T10:

| Component | Replacement |
|---|---|
| kafka | Amazon MSK |
| postgresql | Amazon RDS |
| valkey-cart | Amazon ElastiCache |

They must not appear in `values-serviceaccounts.yaml`.

## Namespace default identity cleanup

- Cloudflared receives dedicated SA `cloudflared` with automount disabled.
- OpenSearch remains on `default` with Pod token automount explicitly disabled.
  OpenSearch chart 3.6.0 cannot select an existing SA unless `rbac.create=true`;
  enabling that would create an unnecessary Role/RoleBinding and violate T10.

Moving Cloudflared removes the previous identity sharing between the public
edge tunnel and the data/observability workload. A dedicated OpenSearch SA is a
separate chart-vendoring/upstream follow-up, not a reason to grant surplus RBAC.

## Rendering model

For a component with a `serviceAccount` override, the parent chart:

1. creates one component-scoped ServiceAccount;
2. sets the Deployment `serviceAccountName`;
3. sets SA token automount to false;
4. creates no RBAC.

The migration values file is loaded after production values. It is cumulative
but contains only waves already approved for production.

## Definition of done

- All 18 shared-SA services are promoted in separately reviewed waves.
- Every live Pod uses the mapped identity.
- `kubectl auth can-i --list` is captured before and after for every identity.
- No business identity has RoleBinding/ClusterRoleBinding.
- No business Pod contains a `kube-api-access-*` volume.
- Existing IRSA and observability identities remain unchanged.
- Browse, cart and checkout smoke tests pass after each wave.

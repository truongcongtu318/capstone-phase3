# Runbook — T10 ServiceAccount wave rollout

## Preflight

```bash
NS=techx-tf3

kubectl -n "$NS" get deploy,rollout
kubectl -n "$NS" get pods \
  -o custom-columns=NAME:.metadata.name,SA:.spec.serviceAccountName,READY:.status.containerStatuses[*].ready
kubectl -n "$NS" get events --sort-by=.lastTimestamp | tail -50
```

Record the current Argo revision and ensure no unrelated rollout is active.

## Before evidence

For every service in the incoming wave:

```bash
kubectl auth can-i --list \
  --as="system:serviceaccount:techx-tf3:techx-corp" \
  -n techx-tf3
```

Save Pod SA, Ready state, restart count and the browse/cart/checkout smoke
result.

## Promotion

Merge only one wave. Argo CD loads:

```text
phase3 - information/deploy/values-serviceaccounts.yaml
```

The file is cumulative. The rollout is complete through Wave 8.

Wait for Argo sync, then verify each newly migrated service:

```bash
./scripts/verify-sa-migration.sh <service>
```

For checkout, the workload object is named `checkout-rollout`; the verification
script resolves that name automatically.

## Required manual authorization evidence

```bash
SA=techx-<service>

kubectl auth can-i --list \
  --as="system:serviceaccount:techx-tf3:${SA}" \
  -n techx-tf3

kubectl -n techx-tf3 get rolebinding -o yaml
kubectl get clusterrolebinding -o yaml
```

Confirm the new SA is not a subject of any RoleBinding or
ClusterRoleBinding.

## Token and runtime checks

```bash
POD="$(kubectl -n techx-tf3 get pod \
  -l opentelemetry.io/name=<service> \
  -o jsonpath='{.items[0].metadata.name}')"

kubectl -n techx-tf3 get pod "$POD" \
  -o jsonpath='{.spec.serviceAccountName}{"\n"}'

kubectl -n techx-tf3 get pod "$POD" \
  -o jsonpath='{range .spec.volumes[*]}{.name}{"\n"}{end}' |
  grep kube-api-access && exit 1 || true

kubectl -n techx-tf3 logs "$POD" --tail=200 |
  grep -Ei '401|403|Forbidden|Unauthorized' && exit 1 || true
```

Hold for five minutes and confirm:

- Ready replicas equal desired replicas;
- restart/OOM/Pending deltas are zero;
- browse, cart and checkout smoke tests pass.

## Special identities

- Never rename `product-reviews-bedrock`.
- Do not add Kafka, PostgreSQL or Valkey to migration values.
- Do not replace existing Grafana, Jaeger, Prometheus, OTel, AIOps or
  shopping-copilot identities.

## Rollback

If any gate fails:

1. stop the wave;
2. revert the wave commit in Git;
3. merge and let Argo sync the previous desired state;
4. confirm the old SA is restored and repeat smoke tests.

Do not manually patch all Deployments or run an untracked Helm rollback while
Argo self-heal is active.

Final verified rollout state:

- all 18 business services use dedicated ServiceAccounts;
- `product-reviews` stays on `product-reviews-bedrock`;
- `cloudflared` uses its dedicated SA;
- `flagd` was the last promoted wave.

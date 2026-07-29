# T10 — Staged ServiceAccount migration plan

## Safety rule

`values-serviceaccounts.yaml` is consumed automatically by Argo CD. Add exactly
one wave per PR and retain already promoted waves. Never add all remaining
services in one PR.

Current state: **Waves 1-8 promoted and verified**.

## Promotion waves

| Wave | Services | Risk |
|---:|---|---|
| 1 | image-provider, ad, recommendation | Low; non-critical stateless |
| 2 | llm, product-catalog | Catalog/AI read path |
| 3 | accounting, fraud-detection | Async consumers |
| 4 | load-generator | Test tooling isolation |
| 5 | frontend, frontend-proxy | Public request path |
| 6 | currency, quote, shipping, email | Checkout dependencies |
| 7 | payment, cart, checkout | Revenue-critical |
| 8 | flagd | Feature configuration; migrate last |

`product-reviews` is excluded because it already uses
`product-reviews-bedrock`. Kafka, PostgreSQL and Valkey are excluded because
their in-cluster components are disabled.

## Gate for each wave

Before promotion:

- record the current Git SHA and Argo application revision;
- capture Pod-to-SA mapping and `kubectl auth can-i --list`;
- confirm all Pods are Ready and no rollout is already in progress;
- record restart counts and current browse/cart/checkout smoke result.

After Argo sync:

- only services in the new wave may receive a new ReplicaSet;
- Deployment/Rollout reaches Ready and Available;
- every new Pod uses the expected SA;
- no `kube-api-access-*` volume exists;
- no new 401/403, restart, OOM or Pending Pod;
- `kubectl auth can-i --list` shows no workload API permission;
- browse, cart and checkout smoke tests pass.

Hold each wave for at least five minutes after all replicas become Ready. Open
the next PR only after its evidence is attached.

The final rollout is complete through Wave 8.

## Rollback

Rollback is GitOps-owned:

1. revert the commit that added the failing wave;
2. merge the revert;
3. sync the `techx-corp` Argo application;
4. verify that Pods return to the previous SA and smoke tests recover.

Do not rely on a manual `helm rollback` while Argo self-heal is enabled because
Argo will restore the Git-declared state.

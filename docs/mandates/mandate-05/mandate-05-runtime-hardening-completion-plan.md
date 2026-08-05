# Mandate 5 — Runtime hardening completion plan

**Date:** 2026-07-17

**Deadline:** 2026-07-17

**Working branch:** `codex/mandate-05-runtime-hardening` / PR #194

**Scope:** PM-92 Pod Security, PM-95 image immutability/digest pinning,
PM-101 Trivy/Cosign, Kyverno admission enforcement, mentor acceptance evidence

**Constraints:** no additional fixed infrastructure cost, no storefront SLO
regression, operations endpoints remain private, and flagd/fault injection must
not be disabled or bypassed

## 1. Executive status

The Jira task split is directionally correct, but the combined work is not yet
sufficient to close Mandate 5. PM-92, PM-101 and the Kyverno audit task cover
the main implementation areas; the mandate additionally requires production
remediation, admission enforcement, a real rejection demonstration and a
signed end-to-end decision/evidence record.

Strict progress against the three Jira DoD lists was rechecked after the
one-policy-at-a-time Enforce cutover through PR #230:

| Work item | Passed DoD | Progress | Main remaining gap |
| --- | ---: | ---: | --- |
| PM-92 Pod Security | 3/4 | 75% | 2 time-bounded runtime exceptions remain: Kafka init ownership and out-of-tree aiops-engine. |
| Kyverno admission policies | 5/5 | 100% | All four policies are Enforce/Ready and live negative admission evidence is captured. |
| PM-101 Trivy/Cosign | 3/4 | 75% | 20/20 live first-party digests verify with Cosign; retained Trivy/Cosign evidence still needs final packaging. |
| **Combined Jira DoD** | **11/13** | **84.6%** | Enforce is complete; mentor acceptance and final supply-chain evidence packaging remain. |

This percentage is planning progress, not a completion claim. Mandate 5 remains
open until the remaining acceptance conditions are demonstrated:

1. the mentor repeats the rejection demonstration;
2. final PM-101 evidence is retained; and
3. the two time-bounded exceptions receive final disposition.

## 2. Verified live baseline

Snapshot updated after PR #230 on 2026-07-18. The checks render the production
chart, validate the runtime inventory, run Kyverno CLI tests and reconcile live
PolicyReports after Argo CD sync.

| Control | Current result | Target before closure |
| --- | ---: | ---: |
| PSA labels | `audit=baseline`, `warn=baseline`, no `enforce` | Preserve during remediation; enforce only after clean audit. |
| Kyverno controllers | 4/4 deployments available | 4/4 available throughout cutover. |
| Kyverno policies | All four required policies are `Enforce` and `Ready=True`. | Preserve one-policy rollback boundaries and clean reconciliation. |
| Baseline context: APE=false + drop ALL + seccomp | Branch render has zero unexplained findings after exception-register reconciliation. | 0 unexplained findings after live Argo CD sync. |
| `runAsNonRoot` | Live and render checks leave only Kafka init and aiops-engine as explained exceptions. | All first-party app containers; no unexplained root workload. |
| `readOnlyRootFilesystem` | 4/32 containers | Enable where write-path testing proves it safe; document stateful exceptions. |
| Explicit CPU/memory requests and limits | Branch render has zero unresolved resource findings. | Live current-resource report has zero unexplained failures. |
| Digest-pinned images | Branch render requires first-party ECR images to use exact digests. | Live workload inventory and PM-101 evidence map every required digest. |
| Floating, non-`latest` image refs | Branch render rejects `:latest`; tag-only external images remain outside first-party digest policy. | 0 unsupported mutable refs, or explicit external-image exceptions. |
| ECR Cosign signatures | 20/20 live first-party ECR digests verify with the GitHub OIDC workflow identity. | Retain the verification output in the final evidence pack. |
| PM-101 Actions runs/artifacts | Trivy evidence exists, but signed-release evidence remains incomplete. | Full green run plus retained Trivy/Cosign artifacts. |
| PolicyReport aggregate | Live reconciliation gate is clean: no active or unresolved failures. | Keep this clean after each Enforce PR. |
| Storefront smoke test | HTTP 200 after final Enforce cutover | HTTP 200 before, during and after enforce. |

The PolicyReport aggregate contains historical ReplicaSet results. It must not
be presented as a current workload count without reconciling the report scope,
UID and active controller revision.

## 3. Branch and merge safety

Cutover update: the sequence below records the original PR #194 safety model.
The current source revision is `677e74b`, with all four policies promoted by
separate reviewed PRs.

PR #194 is safe to merge when its required checks are green because all Kyverno
policies remain in `Audit`. It does not switch admission to `Enforce`, does not
mutate the live cluster imperatively and does not change flagd or fault-injection
paths.

After merge, use Argo CD to sync the Audit policies and capture fresh evidence.
Keep the Audit-to-Enforce promotion in a separate final PR so rollback can
change one policy action without reverting the runtime remediation and evidence
tooling.

## 4. Missing work beyond the existing Jira descriptions

### 4.1 Complete runtime remediation

- Apply the baseline context to every remaining first-party app:
  `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, and
  `seccompProfile.type: RuntimeDefault`.
- Make the remaining first-party images run as a numeric non-root user and set
  `runAsNonRoot: true` in the workload template.
- Test application write paths before enabling `readOnlyRootFilesystem`.
- For PostgreSQL, Kafka, Valkey, OpenSearch and observability workloads, record
  required writable paths and provide `emptyDir`/PVC mounts where appropriate.
- Track the 2 current exceptions in `docs/evidence/mandate-05/exception-register.yaml`
  until each owner either remediates the workload or signs a time-bounded
  acceptance.
- Verify every application, sidecar, init container and daemon container has
  CPU/memory requests and limits in Git, rather than relying only on LimitRange
  defaults.

### 4.2 Complete image immutability at runtime

- Keep the 20 first-party ECR images pinned by digest and reject any new
  first-party tag-only reference before promotion.
- External images remain fixed non-`latest` references and are covered by the
  external-image review workflow rather than TF3 Cosign signatures.
- Reconcile the external-image scan list with the images actually running. A
  scan of an inventory digest is not evidence for a different live tag.
- Keep the Audit image policies from PR #194 in place and promote them only
  after live PolicyReports show no unexplained mutable-image failures.

### 4.3 Complete PM-101 production evidence

- Merge PR #148 to `main`.
- Manually dispatch the full build workflow because the workflow path filter
  will not run solely from CI/docs changes.
- Remediate every HIGH/CRITICAL finding until the agreed full service set is
  green.
- Confirm and document whether the official DoD set is 18 application services
  or the 20 current `ALL_SERVICES` build targets. The workflow may cover the
  superset, but the evidence table must identify the official 18 explicitly.
- Verify that each pushed digest has a keyless GitHub OIDC Cosign signature and
  successful `cosign verify` result.
- Retain `trivy-app-images-<run-id>` and
  `signed-release-evidence-<run-id>` artifacts.
- Map every first-party digest running in the cluster to the Git SHA, Actions
  run, Trivy report and Cosign verification report.
- Run the external-image workflow at least once and retain its artifact.

Residual evidence risk: the current workflow scans a local `linux/amd64`
candidate and subsequently rebuilds the multi-platform image for push. The ADR
must record that limitation, or the release flow must produce stronger proof
that the signed pushed digest corresponds to the scanned build output.

### 4.4 Extend Kyverno coverage

The final policy set for namespace `techx-tf3` must cover:

1. explicit CPU/memory requests and limits;
2. `allowPrivilegeEscalation: false`;
3. `capabilities.drop` containing `ALL`;
4. `seccompProfile.type: RuntimeDefault`;
5. `runAsNonRoot: true` for first-party workloads;
6. no `latest` tag;
7. digest-pinned image references; and
8. optionally, Cosign `verifyImages` for first-party ECR digests after PM-101
   has produced the signed inventory.

Rules must evaluate `containers`, `initContainers` and `ephemeralContainers`.
They must be scoped deliberately so a TF3 mandate does not unexpectedly block
unrelated namespaces. Exceptions must identify an owner, reason, exact workload
and expiry/review date.

Cosign admission verification is not required to close the original PM-101
DoD, but it is the recommended final authenticity control. External images must
use exact digest exceptions; an unrestricted external-registry bypass is not
acceptable.

## 5. Controlled execution phases

### Phase 0 — Freeze and reconcile evidence

Actions:

- Record current `main`, PR #194 and PM-101 commit SHAs.
- Export the current workloads, image references, Kyverno policies and
  PolicyReports after PR #194 is synced.
- Separate current Pod/controller results from historical ReplicaSet reports.
- Confirm the 18-service PM-101 inventory with the team.

Exit gate:

- one authoritative inventory exists for workloads, containers, images,
  exceptions and owners;
- PR #194 has no unknown or unrelated diff; and
- the PR #194 merge, sync and evidence-capture sequence is accepted by reviewers.

### Phase 1 — Remediate without enforcement

Actions:

- merge and roll out runtime securityContext/Dockerfile fixes in small batches;
- add any remaining missing resources found by live PolicyReport reconciliation;
- pin every live image to a digest;
- leave Kyverno in Audit while each batch rolls out;
- smoke-test storefront, checkout flow and flagd after every batch.

Exit gate:

- zero current, unexplained Audit failures for resources, APE, capabilities,
  seccomp, non-root and digest pinning;
- no critical workload in CrashLoopBackOff;
- ArgoCD Synced/Healthy; and
- storefront returns HTTP 200.

### Phase 2 — Produce scan and signature evidence

Actions:

- merge PM-101;
- run the full first-party workflow;
- remediate vulnerabilities;
- verify ECR signatures and artifacts;
- run the external-image review; and
- prepare the live-digest evidence matrix.

Exit gate:

- every agreed first-party image has a clean Trivy report and successful Cosign
  verification;
- no required digest is missing evidence; and
- external exceptions are explicit and match the live digest inventory.

### Phase 3 — Audit the complete policy set

Actions:

- deploy the additional policies in Audit;
- exercise normal ArgoCD sync and at least one legitimate rollout;
- run server-side dry-run negative manifests to confirm each policy matches the
  intended field; and
- review every failure with the workload owner.

Exit gate:

- two normal deployment/sync cycles produce no false positive;
- current PolicyReport has zero unexplained failure;
- all exceptions are signed and time-bounded; and
- rollback commits are prepared.

### Phase 4 — Switch Audit to Enforce

Enable one control at a time in this order:

```text
resources
  -> baseline securityContext
  -> runAsNonRoot
  -> disallow latest / require digest
  -> Cosign verifyImages (optional final step)
```

For each step:

1. merge only that policy action change;
2. wait for ArgoCD Synced/Healthy;
3. perform a legitimate deployment dry-run;
4. apply the corresponding invalid test manifest and confirm rejection;
5. check workload readiness, storefront and flagd; and
6. continue only if there is no unintended rejection or SLO impact.

Exit gate:

- required policies show `Enforce` and `Ready=True`;
- valid GitOps sync remains successful; and
- invalid manifests are denied by the admission webhook.

### Phase 5 — Mentor acceptance and closeout

Prepare three minimal negative manifests:

- `bad-root.yaml`: root-capable container or missing required runtime context;
- `bad-latest-image.yaml`: mutable/latest image reference; and
- `bad-missing-resources.yaml`: missing requests/limits.

The mentor must run real `kubectl apply` commands and see all three rejected.
After the demo, show:

- Kyverno controllers Running;
- enforced policies Ready;
- current PolicyReport with no unexplained violation;
- live digest inventory and PM-101 scan/signature mapping;
- ArgoCD Synced/Healthy;
- storefront HTTP 200;
- private operations paths still private; and
- flagd/fault injection unchanged and operational.

## 6. Rollback plan

Rollback is policy-specific and does not disable Kyverno globally:

1. change only the failing policy from `Enforce` back to `Audit` through Git;
2. let ArgoCD self-heal to the reviewed Audit version;
3. revert the most recent workload batch if it caused readiness/SLO regression;
4. retain PolicyReport and rejection output for incident analysis;
5. do not disable admission webhooks, remove flagd, expose private operations
   endpoints or weaken unrelated controls; and
6. record any temporary exception with owner, reason and expiry before retrying
   enforcement.

PM-101 rollback reverts the workflow merge; it does not delete existing ECR
signatures or change deployed digests. Digest-pinning rollback selects a
previous known-good signed digest, never a mutable tag.

## 7. Required evidence pack

Create or update the following before closure:

- signed Mandate 5 ADR covering all Audit/Enforce decisions;
- before/after workload compliance matrix;
- current PolicyReport export and summarized violation table;
- PM-101 first-party digest/scan/signature matrix;
- external-image exception and scan table;
- terminal output for each admission denial;
- ArgoCD/Kyverno health snapshot;
- storefront and critical-flow smoke-test output; and
- rollback commands and the exact commits used for cutover.

The final ADR must state:

- which policies are enforced;
- which policy, if any, remains in Audit and why;
- every active exception, owner and expiry;
- the Audit-to-Enforce cutover criteria;
- known residual risk, including the pre-push amd64 versus multi-platform build
  relationship; and
- implementation owner and reviewer signatures.

## 8. Suggested Jira subtasks

- `M5-01 — Remediate remaining runtime security violations`
- `M5-02 — Promote digest and no-latest policies from Audit to Enforce`
- `M5-03 — Produce PM-101 CI/ECR scan and signature evidence`
- `M5-04 — Reconcile PolicyReports and remove stale/invalid exceptions`
- `M5-05 — Kyverno Audit-to-Enforce cutover`
- `M5-06 — Admission rejection demo and signed Mandate 5 ADR`

## 9. Definition of complete

- [x] No unexplained workload runs as root.
- [x] Every container type has explicit CPU/memory requests and limits.
- [ ] Every runtime image is pinned by digest; no `latest` or tag-only ref.
- [ ] Every agreed first-party app image has current Trivy and Cosign evidence.
- [ ] External images have exact-digest exceptions and current scan evidence.
- [x] Required Kyverno policies are Enforce and Ready.
- [x] Current PolicyReport has zero unexplained violation.
- [ ] Mentor applies root/latest/missing-resources manifests and sees admission
      rejection.
- [x] ArgoCD remains Synced/Healthy and no critical workload is CrashLooping.
- [x] Storefront remains HTTP 200 and SLO is not degraded.
- [x] Operations endpoints remain private.
- [x] Flagd and fault-injection paths are unchanged.
- [ ] Signed ADR, evidence pack and rollback plan are committed.

Until every item above is complete, the TF must report Mandate 5 as in progress,
not complete.

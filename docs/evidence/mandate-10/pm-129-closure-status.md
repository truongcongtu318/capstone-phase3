# PM-129 closure status — immutable provenance and release evidence

Date: 2026-07-23 (updated 2026-07-25, 2026-07-26)  
Scope: immutable CI dependencies, image provenance, and live traceability  
Status: **CLOSED — live trace returned `overallResult: PASS` on 2026-07-26 against
`checkout-rollout-6c986b459-cc5hw`, all five required links present. See §4.**

## 1. Before PM-129

Before PM-129, the repository had useful scan and release artifacts, but the
runtime chain was not enforceable end to end:

- GitHub Actions used version tags instead of immutable commit SHAs.
- Dockerfile base images were not uniformly digest-pinned.
- Build artifacts contained source SHA, image digest/tag and run metadata, but
  there was no single fail-closed command to trace a running pod through review,
  Trivy, Cosign and SBOM evidence.
- A live pod trace was not part of the release handoff.

## 2. Completed implementation and evidence

| Area | Completed change | Evidence |
|---|---|---|
| Action immutability | Pinned every workflow `uses:` reference to a full commit SHA with a version comment. | `python3 scripts/ci/verify-immutable-pins.py` → `PASS: immutable pins verified (9 workflows, 28 Dockerfiles)` |
| Container immutability | Pinned all discovered Dockerfile base images by digest. | `docs/evidence/mandate-10/pm-129/docker-pin-audit-after.txt` |
| Provenance tooling | Added fail-closed `scripts/ci/trace-provenance.sh` and the PM-129 runbook. | `docs/runbooks/pm-129-trace-provenance.md` |
| Release evidence | Build workflow retains Trivy, Cosign and CycloneDX SBOM evidence and opens a scoped promotion PR. | Build run [29978396050](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/29978396050) |
| Dependency remediation | Resolved all HIGH findings found in the post-merge matrix: `ad`, `fraud-detection`, `frontend`, `kafka`, `product-catalog` and `checkout`. | PRs #363 and #367; local service tests passed; post-push Trivy passed. |
| Promotion | Published and signed checkout digest, then merged the GitOps promotion PR. | PR #369, merge commit `ae8db7e1c3e3468ff760f646e94ee65daa98541e`; digest `sha256:ebea1f1d2ab51dac3a1de5493d4a8e97e6607601f966315eb1608a4d6f9aeeb8` |
| Required security checks | IaC, repository secret, SAST, immutable pins, gitleaks and aggregate Secure delivery gate passed on the promotion PR. | PR #369 check runs |

The PM-129 image change itself is scoped to the checkout image digest. It does
not run Terraform Apply and does not directly mutate Kubernetes. The Helm
configuration uses two replicas and an Argo Rollouts canary with
`maxUnavailable: 0` and `maxSurge: 1`.

## 3. Before/after impact

| Dimension | Before | After PM-129 |
|---|---|---|
| CI action supply chain | Tag-based action references could move. | Full SHA pins are verified in CI. |
| Image base supply chain | Base image tags/digests were inconsistent. | All 28 discovered Dockerfiles are digest-pinned. |
| Build security evidence | Evidence was distributed across artifacts. | Trivy, Cosign, SBOM and source/run metadata are linked by immutable digest. |
| Runtime traceability | No fail-closed pod-to-PR command. | `trace-provenance.sh` validates the five-link chain and writes JSON evidence. |
| Deployment impact | No PM-129 image promotion gate. | Checkout promotion is a reviewed GitOps PR and uses an existing canary rollout. |
| Downtime risk from PM-129 | Not measurable end to end. | The PM-129 rollout path has two replicas, readiness checks and `maxUnavailable: 0`; live no-downtime proof is still pending cluster access. |

## 4. What is not complete

The remaining DoD item is one successful trace against a real running pod.

**Update 2026-07-25:** the access blocker described below is resolved — dynamic
bastion lookup + SSM tunnel worked, `gh`/`cosign` were installed, and the trace ran
read-only end to end. It progressed further than any prior attempt (past preflight,
pod fetch, digest validation) but still returned `overallResult: FAIL`, now at the
`image-manifest` step: containerd `2.2.4` on this cluster reports a pod's `imageID` as
the release **index** digest itself rather than the platform-specific child manifest
digest the script expects, so the membership check fails even though the running
digest (`sha256:ebea1f1d...`) is confirmed correct against the promoted/reviewed
image. Independently verified: the pod's `imageID` equals the exact digest promoted
in PR #369, and the release index (fetched directly via
`docker buildx imagetools inspect`) is the expected 2-platform + 2-attestation index
from that promotion. Full evidence and root cause:
`docs/evidence/mandate-10/pm-129/trace-attempt-2026-07-25.md`.

This is a script-assumption gap (containerd behavior differs from what the script was
written against), not a supply-chain or signing failure. **Fixed in PR #445** (merged):
also found and fixed a second, independent defect in the same check — `jq -e` on a
boolean stream only evaluates the last emitted value, and the release index always
lists attestation manifests last, so the membership check had been fail-closed on
every possible run regardless of correctness. Both fixes verified against the real
release index before merge.

**Rerunning the trace after PR #445** progressed further than ever: it now passes
`image-manifest` and reaches the `trivy` step, failing with
`expected exactly one arm64 Trivy report`. Root cause: the currently-deployed checkout
digest (`sha256:ebea1f1d...`) was built by workflow run `29978396050` on 2026-07-23,
*before* PR #442 (the last-platform Trivy fix) merged — that run's own artifact
genuinely only contains an amd64 report, and this cannot be fixed retroactively
(GitHub re-runs a job against the workflow file pinned to that commit, not `main`).

**Attempted fix:** rebuilt + re-promoted checkout (PR #448, no source change) to get a
build with complete 2-platform evidence. The rebuild succeeded, but the resulting Argo
Rollouts canary could not schedule its surge pod — Karpenter's `elastic-ondemand-fallback`
NodePool is capped at `nodes: 0` and the two spot NodePools were already at their own
node cap. **Zero production impact**: the two existing checkout pods stayed
Running/Ready throughout (`maxUnavailable: 0` held as designed); only the Rollout
object's own progress status showed `Degraded`. Per repo convention (don't touch
NodePool/nodegroup config while another team's Karpenter work is in flight — this
turned out to be a leftover temporary cap from a Mandate 19 / PM-152 breakpoint test
that hadn't been restored yet), the promotion was reverted instead of touching NodePool
limits (PR #450, merged) — confirmed back to the clean pre-attempt state. Full account:
`docs/evidence/mandate-10/pm-129/checkout-promotion-attempt-2026-07-25.md`.

**Update 2026-07-26 — retry succeeded, `overallResult: PASS`:** with Karpenter capacity
improved (PR #451), retried the checkout re-promotion. It first hit an unrelated
blocker: `open-image-bump-pr` runs the full `scripts/ci` suite as its gate, and a newly
merged, unrelated PR (#457, `otel-logs-retention` CronJob) was missing `limits.cpu`,
which failed that suite and blocked **every** service's image-bump PR, not just
checkout's. Fixed and merged as PR #459
(`otel-logs-retention-cronjob.yaml`), which unblocked the pipeline for the whole repo.

Re-dispatched the checkout rebuild on `main` at PR #459's merge commit
(run [30187331856](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30187331856)).
It succeeded end to end and opened promotion PR #461 (digest
`sha256:8e22139cae1a6db0aa3dbabc83cba56a2608d78ee21c09541d7024959dac934e`), merged after
required checks passed. The canary surge scheduled successfully this time (on
`flash-sale-spot`'s slot freed by PR #451) and `checkout-rollout` reached `Healthy` with
zero downtime.

`trace-provenance.sh` against the new pod then surfaced **three further, independent**
script-assumption bugs — found only because the trace finally got far enough to reach
these steps — fixed in order and each re-verified against the real pod before moving on:

1. **cosign**: cosign v3 (unpinned installer version) only "partially populates" the
   `optional.Issuer`/`optional.Subject` fields the script re-derived from
   `cosign verify --output json` for the new bundle format
   (upstream `sigstore/cosign#4416`) — both come back empty on a real, correct
   signature. `cosign verify`'s own `--certificate-oidc-issuer`/`--certificate-identity`
   flags already enforce the identity match (fail closed on mismatch); replaced the
   redundant field re-check with a digest-binding check.
2. **sbom** (jq precedence): `EXPR and (...) as $p | BODY` parses as
   `(EXPR and (...)) as $p` in jq, so `$p` was bound to a boolean, not the properties
   map — same bug class as the boolean-stream defect PR #445 fixed elsewhere in this
   script. Fixed by parenthesizing the `as` binding.
3. **sbom** (digest mismatch): once bug 2 was fixed, the binding check still failed
   because it compared the SBOM's true per-platform `techx.subjectDigest` against
   `child_digest` — but this cluster's containerd (2.2.4) reports `child_digest` as the
   release **index** digest (the PR #445 finding), not the per-platform child digest.
   Fixed by resolving the real per-platform child digest from the already-fetched
   release index when that substitution is detected.
4. **argo**: five ArgoCD Applications from this repo now deploy into `techx-tf3`
   (`techx-corp`, `techx-edge`, `techx-infrastructure-app`, `flagd-secret-sync`,
   `native-admission-policies`), so repo+namespace matching no longer disambiguates to
   exactly one app. Fixed by resolving the pod's actual owning workload
   (`ReplicaSet` → its owner) and matching on that resource appearing in an
   Application's `status.resources` tree, with the old heuristic kept as a fallback.

All four (this update's three, plus the two PR #445 already fixed) are
script-assumption/environment-drift bugs — an upstream tool release, this cluster's
containerd version, and this repo's growing GitOps app count — not supply-chain or
signing failures. Verified: full `scripts/ci` suite (261 passed, 2 skipped) plus a live
rerun confirming `overallResult: PASS` reproduces. Full account and root-cause detail:
`docs/evidence/mandate-10/pm-129/trace-pass-2026-07-26.md`; raw result:
`docs/evidence/mandate-10/pm-129/trace-pass-2026-07-26.json`.

Historical blocker (resolved 2026-07-25, kept for record):

- `kubectl` previously timed out against `https://localhost:8443`.
- The original bastion was replaced by an independent Terraform Apply event;
  the old hardcoded tunnel target became invalid.
- A later access-only PR (#371) made bastion lookup dynamic; as of 2026-07-25 a
  live Kubernetes read succeeds via this path.

PM-129 is closed: the trace returned `overallResult: PASS` with all five required links:

`runtime digest → source commit/run → merged PR approval → exact Trivy pass → Cosign identity + PM-127 SBOM`.

## 5. External Terraform incident boundary

Terraform Apply run [29978951249](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/29978951249)
was manually triggered by `hailv1209` and is outside PM-129. Its log shows
partial production mutation before failure, including bastion replacement and
errors in SNS policy, Lambda ZIP handoff and an RDS version downgrade. PM-129
did not trigger this Apply and no further Apply is authorized for this task.

The infrastructure owner must first produce a fresh read-only Terraform plan
and confirm the bastion/SSM path and production health. No saved plan from the
failed run may be reused.

## 6. Closure gate

PM-129 is closed. All of the following are attached:

1. A working read-only EKS access path (SSM or approved equivalent). ✅
2. `kubectl` evidence of a healthy checkout rollout/pod using the promoted
   digest. ✅ (`checkout-rollout` revision 34, `Healthy`, 2/2 on
   `sha256:8e22139c...`)
3. The JSON output from `trace-provenance.sh` with `overallResult: PASS`. ✅
   `docs/evidence/mandate-10/pm-129/trace-pass-2026-07-26.json`
4. The trace JSON and redacted command transcript saved under this directory. ✅
   `docs/evidence/mandate-10/pm-129/trace-pass-2026-07-26.md`

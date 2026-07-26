# PM-129 closure status — immutable provenance and release evidence

Date: 2026-07-23 (updated 2026-07-25)  
Scope: immutable CI dependencies, image provenance, and live traceability  
Status: **CI/release evidence PASS; live trace ran read-only end-to-end on 2026-07-25
and FAILED at the `image-manifest` step (script assumption gap, not a supply-chain
failure) — see §4**

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
written against), not a supply-chain or signing failure — but per the fail-closed
policy it still must not be marked PASS until fixed and rerun. A fix is proposed
(accept `child_digest == release_digest` as well as membership in `.manifests[]`) but
not yet implemented; it needs its own reviewed PR like #441/#442.

Historical blocker (resolved 2026-07-25, kept for record):

- `kubectl` previously timed out against `https://localhost:8443`.
- The original bastion was replaced by an independent Terraform Apply event;
  the old hardcoded tunnel target became invalid.
- A later access-only PR (#371) made bastion lookup dynamic; as of 2026-07-25 a
  live Kubernetes read succeeds via this path.

PM-129 must not be marked 100% complete until the trace returns
`overallResult: PASS` with the five required links:

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

PM-129 can be closed after all of the following are attached:

1. A working read-only EKS access path (SSM or approved equivalent).
2. `kubectl` evidence of a healthy checkout rollout/pod using the promoted
   digest.
3. The JSON output from `trace-provenance.sh` with `overallResult: PASS`.
4. The trace JSON and redacted command transcript saved under this directory.

Until then, the accurate status is **implemented and release-gate verified,
live provenance validation blocked externally**.

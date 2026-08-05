# PM-101 evidence — Trivy scan gate and keyless Cosign signing

**Task:** `[MANDATE 5] Scan gate (Trivy) + ký xác thực image (Cosign) trước khi vào cluster`

**Backlog:** item #8 / PM-101, extending PM-95 digest pinning and ECR immutability

**Branch:** `fix/pm-101-production-completion`

**Date:** 2026-07-16

**Status:** all 20 first-party build targets pass the strict remote
HIGH/CRITICAL gate. Production push/sign and live-digest evidence remain
pending until the synchronized branch is merged and the `main` release flow
finishes.

## 1. Scope and isolation from PM-92

The original PM-101 workflow/ADR implementation is already on `main`. This
completion branch contains the Dockerfile/base-image changes and dependency
updates required to make the zero-HIGH/CRITICAL gate pass. A temporary
scan-only input was used on the branch to remediate without ECR mutation; after
syncing with the newer Mandate 8 workflow on `main`, that temporary input is not
part of the production workflow:

- `docs/evidence/pm-101-image-supply-chain.md`
- first-party image Dockerfiles and dependency lockfiles needed to clear the
  blocking gate

It deliberately does **not** contain PM-92 chart/securityContext or PSA changes.
The image remediation is in PM-101 scope because the release gate correctly
rejects the old dependencies and bases. Some final images now use patched
Alpine/distroless bases and explicit non-root users; those runtime changes were
smoke-tested locally. Merging the branch itself still does not change Kubernetes
pod templates, deployed image digests, replicas, public storefront routing,
private operations access, or flagd/fault-injection behavior. Runtime changes
occur only after a separately reviewed signed-digest promotion.

## 2. Before PM-101

The production baseline before this branch had these properties:

| Area | Before |
| --- | --- |
| Build order | Buildx pushed the selected multi-architecture images to ECR first. |
| Vulnerability gate | Trivy scanned the ECR image after push with `HIGH,CRITICAL`; a failed scan stopped the job but the candidate already existed in the registry. |
| Scan evidence | No per-service JSON artifact was uploaded by the release workflow. |
| Provenance | No Cosign signing or verification step existed. |
| External images | No dedicated scheduled, non-blocking Trivy evidence workflow existed on `main`. |
| ECR baseline | `imageTagMutability=IMMUTABLE` and `scanOnPush=true`; live audit on 2026-07-16 found zero Cosign signature tags/artifacts. |
| Existing evidence | `docs/scan-evidence.txt` covered one ECR digest, not every first-party image running in the cluster. |

This meant the pipeline could detect a vulnerable image, but could not prevent
that candidate from reaching ECR and could not prove that a deployed digest was
built and signed by the TF3 GitHub Actions identity.

## 3. What PM-101 changes

### First-party images

The workflow now performs this sequence for every selected build target:

```text
detect changed services
  -> build a local linux/amd64 candidate
  -> write a per-service Trivy JSON report
  -> fail on any HIGH or CRITICAL vulnerability
  -> upload Trivy evidence even when the gate fails
  -> build and push the multi-architecture ECR image only after a clean gate
  -> resolve the immutable ECR manifest-list digest
  -> keyless Cosign sign using GitHub Actions OIDC
  -> Cosign verify the pushed digest and certificate identity
  -> upload the digest/report/run mapping and raw verification output
```

The agreed threshold is zero `HIGH` and zero `CRITICAL`, including unfixed
findings. No static Cosign private key or password is stored in the repository
or GitHub Secrets.

The historical ticket says 18 app services. The current repository has 20
build targets in `ALL_SERVICES`; PM-101 gates and signs the superset so an
auxiliary target cannot bypass the control. The final Jira evidence must label
the agreed 18 app services and any additional auxiliary targets explicitly.

### External images

PostgreSQL, Grafana, Jaeger, OpenSearch, Prometheus, OTel Collector, Valkey, and
Flagd are upstream artifacts. TF3 must not sign them as if TF3 built them. A
weekly/manual workflow scans their pinned digests, uploads JSON reports, and
does not use `--exit-code 1`; missing TF3 signatures therefore do not block the
first-party application release.

## 4. Impact assessment

### Positive impact

- Vulnerable first-party candidates are blocked before the normal ECR push.
- Every pushed first-party digest receives a short-lived, auditable GitHub OIDC
  signature rather than a long-lived private signing key.
- Release evidence maps the Git commit and Actions run to the ECR digest,
  Trivy report, certificate identity, and raw Cosign verification output.
- External-image ownership and signature exceptions become explicit and
  reviewable instead of silently bypassing the first-party control.

### Operational trade-offs and risks

- CI builds the amd64 candidate before the later multi-architecture push, so
  release duration and GitHub Actions usage increase.
- The zero HIGH/CRITICAL threshold can block urgent releases until the base
  image or dependency is patched or Security records a reviewed exception.
- The pre-push gate scans the EKS runtime architecture (`linux/amd64`). The
  pushed manifest also contains `linux/arm64`; arm64 is not an EKS runtime in
  this environment and is not independently scanned by this implementation.
- The scheduled external scan consumes GitHub Actions minutes but creates no
  new cluster service and no fixed infrastructure cost.
- Merging the branch alone creates no signatures. Signatures and proof exist
  only after a successful workflow run on `main`.

Overall assessment: the security and auditability gain is positive. The main
negative effect is stricter, longer CI; that is intentional because a release
with an unreviewed HIGH/CRITICAL finding must stop.

## 5. Safe rollout flow

1. Review this branch and confirm its diff contains no PM-92 chart/PSA files.
2. Merge the PM-101 PR into `main`.
3. Run `Build & Push TechX Corp images to ECR` manually in full mode on `main`.
4. Remediate every HIGH/CRITICAL finding until the full run is green.
5. Download `trivy-app-images-<run-id>` and
   `signed-release-evidence-<run-id>`.
6. Confirm every required service has a Trivy JSON report, a digest entry, and
   a successful raw `cosign verify` report.
7. Record the exact signed digest and Actions run in `docs/../reports/release-notes-v1.md`.
8. Promote only those signed digests through a separate GitOps PR.
9. Verify the live pod image digests match the evidence table.
10. Run `Periodic Trivy review for external images` once manually and retain
    its first artifact before relying on the weekly schedule.

Steps 7-9 are deliberately separate from this CI-only branch so merging PM-101
cannot cause an unreviewed workload rollout.

## 6. Evidence state

| Evidence | Before | Branch/static result | Required after merge |
| --- | --- | --- | --- |
| PM-101 isolated from PM-92 | Mixed integration branch | Pass: only CI/docs/evidence files | Keep the PR diff isolated. |
| Pre-push HIGH/CRITICAL gate | No | Implemented | One green full run plus a controlled failing-gate demonstration or failed run artifact. |
| Per-service Trivy JSON | No release artifact | Implemented | Artifact must cover every required service. |
| Keyless Cosign signing | No | Implemented | ECR digest signatures must exist. |
| Immediate Cosign verification | No | Implemented | Raw verify report for every signed digest. |
| Digest/run/report mapping | No | Implemented as `signed-images.jsonl` | Attach artifact and summary table to Jira. |
| External-image exception list | Informal | Documented | Pass: run `29472103737`, artifact `trivy-external-images-29472103737`. |
| Live cluster runs signed digests | No proof | Out of this branch's mutation scope | Promote signed digests separately and compare live state. |

### Branch validation record — 2026-07-16

- Remediation code head `cfa38ab` was scanned on the branch, then synchronized
  with `origin/main@d8c2dd7` through merge commit `a712912`.
- The completion history is separated by control/remediation phase: scan-only
  diagnostics and report retention; Java/Node/Go/Python/Ruby/PHP/base-image
  remediation; then the final Flagd UI, proxy, payment and browser-load image
  work.
- The original PM-101 workflows and ADR were actionlint-validated before their
  merge to `main`; this completion branch does not change the external-image
  workflow.
- `git diff --check` passes for the completion branch.
- The branch contains no PM-92 chart, PSA, Kyverno, resource request/limit or
  securityContext mutation.
- No GitOps value or Kubernetes resource has been changed by this branch.
- Full remote scan-only run `29496811086` was dispatched from `cfa38ab` and
  completed successfully; because `scan_only=true`, it could not push or sign a
  candidate before acceptance. The
  final production workflow is the newer `main` implementation: it permits
  manual promotion only from `main`, uses run-unique immutable tags, scans the
  local candidate before push and every published platform after push, signs
  and verifies the digest, then opens a review-only GitOps image-bump PR.

## 7. Current execution record — 2026-07-16

The branch is not yet eligible for a 100% DoD claim. The following evidence is
real and reproducible:

| Check | Result | Evidence |
| --- | --- | --- |
| Trivy pre-push gate | Pass: strict remote batch accepted all 20 images before any AWS credentials/push | Actions run `29496811086` |
| Full candidate build | Pass: 20/20 linux/amd64 candidates built | Actions run `29496811086` |
| Per-image Trivy reports | Pass: 20 JSON files; every report has `HIGH=0`, `CRITICAL=0` | artifact `trivy-app-images-29496811086` (ID `8375271831`) |
| Local strict Trivy | All previously failing targets were remediated with zero HIGH/CRITICAL, including unfixed findings | local builds/scans and functional smoke tests from this branch |
| External-image scan | Passes as a non-blocking scheduled scan; findings remain upstream exceptions | run `29472103737`, artifact `trivy-external-images-29472103737` |
| Keyless Cosign implementation | Code path present, but skipped by failed full gate | Actions run `29479442966` shows push/sign skipped |
| ECR signatures | Not yet proven for the new release | no successful full production run yet |
| Live digest mapping | Not yet promoted | no GitOps digest promotion yet |

The remediation is fully committed and pushed. Important completion commits are
`fe6aed2` (frontend), `d24fa65` (cart/Kafka), `ecaa0d9`
(Python/Ruby/PHP), `f5d89b9` (Flagd UI), `1ff34f8` (proxy/image-provider/fraud
runtime), `51fce5d` (Go services), `3e6db41` (payment) and `cfa38ab`
(load-generator Playwright/Chromium).

Local functional evidence for the last risk-bearing images:

| Image | Functional result | Runtime identity | Strict Trivy result |
| --- | --- | --- | --- |
| `load-generator` | Playwright 1.61.0 opened Alpine Chromium 149 and loaded a test page | UID/GID `10001:10001` | 0 HIGH, 0 CRITICAL |
| `flagd-ui` | Phoenix root endpoint returned HTTP 200 with the real read-only flag data mount | UID/GID `65532:65532` | 0 HIGH, 0 CRITICAL |
| `frontend-proxy` | Envoy admin `/ready` returned `LIVE` / HTTP 200 | UID/GID `101:101` | 0 HIGH, 0 CRITICAL |
| `payment` | gRPC server started on `0.0.0.0:50051` | `node` user | 0 HIGH, 0 CRITICAL |
| `fraud-detection` | Java service process started on the patched Alpine JRE | UID/GID `10001:10001` | 0 HIGH, 0 CRITICAL |
| `image-provider` | `/status` returned HTTP 200 | UID `101` | 0 HIGH, 0 CRITICAL |

For `load-generator`, Playwright support was not removed to satisfy the gate.
The image retains the pinned Playwright Python/JavaScript driver, replaces its
glibc-only Node binary with patched Alpine Node, and points it at patched Alpine
Chromium. This removes the vulnerable Debian/Xvfb package surface while
preserving the browser-traffic behavior used by the demo.

Remote run `29496811086` is the accepted branch batch for all 20 current build
targets. It ran from `2026-07-16T12:05:12Z` to `12:27:42Z`, completed green,
and retained exactly 20 JSON reports. Every report was independently counted
from the downloaded artifact and contains zero HIGH and zero CRITICAL findings.
The production push/sign run is now allowed after review and merge.

The next acceptance gate is one green full run on `main`, followed by ECR
signature verification and live digest evidence. Until then the correct status
is **partial, not complete**.

## 8. Commands used for final verification

Verify branch isolation before merge:

```bash
git diff --name-status origin/main...HEAD
git diff --check origin/main...HEAD
```

Verify a first-party signature independently:

```bash
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/.github/workflows/build-push-ecr.yml@refs/heads/main \
  197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:<digest>
```

Compare the first-party digests actually running in the namespace:

```bash
kubectl get pods -n techx-tf3 -o json \
  | jq -r '.items[].spec.containers[].image' \
  | rg '197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:' \
  | sort -u
```

## 9. Rollback

If the new CI control causes an unintended release outage, revert the PM-101
merge commit on `main`. This restores the previous workflow and removes the
scheduled external review. Rollback does not restart pods, change deployed
digests, alter ECR immutability, expose private operations endpoints, or disable
flagd. A Security-approved temporary exception must be documented separately;
do not silently weaken `TRIVY_SEVERITIES` or remove Cosign verification.

## 10. Definition of Done

- [x] Blocking Trivy step is before the normal ECR push in branch code.
- [x] Threshold is explicitly zero HIGH/CRITICAL.
- [x] Keyless Cosign signing and immediate verification are implemented.
- [x] External-image exception and non-blocking periodic scan are documented.
- [x] PM-101 changes are isolated from PM-92 runtime hardening.
- [ ] Full workflow run on `main` is green.
- [x] Trivy artifact covers all 20 current first-party build targets with zero
  HIGH/CRITICAL findings (`trivy-app-images-29496811086`).
- [ ] Every pushed first-party digest has a successful Cosign verification.
- [ ] Jira/release evidence maps each running digest to its scan and signature.
- [x] External-image workflow produced retained artifact
  `trivy-external-images-29472103737` from successful run `29472103737`.

PM-101 must remain open until every unchecked runtime/evidence item above is
complete. A green branch diff is implementation evidence, not production proof.

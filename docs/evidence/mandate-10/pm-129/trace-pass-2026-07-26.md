# PM-129 live trace — PASS, 2026-07-26

Redacted command transcript and root-cause summary for the run that finally
returned `overallResult: PASS`. Raw JSON: `trace-pass-2026-07-26.json`.

## Context

Karpenter capacity had improved since the 2026-07-25 attempt (PR #451 raised
`flash-sale-spot` 2→3 nodes), so this session retried the checkout
re-promotion needed to backfill Trivy evidence with both platform reports
(see `checkout-promotion-attempt-2026-07-25.md` for why that was necessary).

## What blocked this attempt, in order, and how each was resolved

1. **`otel-logs-retention` CronJob missing `limits.cpu`** (introduced by PR
   #457, unrelated to checkout) failed the full `scripts/ci` suite that gates
   `open-image-bump-pr`, so it blocked *every* service's image-bump PR, not
   just checkout's. Reproduced locally against the exact `main` commit the
   CI run used; fixed and merged as PR #459
   (`phase3 - information/techx-corp-chart/templates/otel-logs-retention-cronjob.yaml`).

2. Re-dispatched `build-push-ecr.yml` (`services=checkout`, no source change)
   on `main` at PR #459's merge commit. Build succeeded end to end and opened
   promotion PR #461 (`chore(deploy): bump checkout image to b1ae5c1`, digest
   `sha256:8e22139c...`). Approved the two bot-authored CI runs
   (`gh api .../approve`), all required checks passed, merged with explicit
   user confirmation.

3. ArgoCD (`techx-corp`) synced the merge; Argo Rollouts canary surged
   `checkout-rollout`. The surge pod scheduled successfully this time (on
   `flash-sale-spot`'s newly freed slot from PR #451) and the rollout reached
   `Healthy` after both analysis steps (20%→50%→100%), zero downtime, old
   pods stayed `Running`/`Ready` throughout.

4. First `trace-provenance.sh` run against the new pod
   (`checkout-rollout-6c986b459-cc5hw`) still returned `FAIL`, but progressed
   further than ever — past `image-manifest` and `trivy` (both fixed by PR
   #445) to three **new** failures, found and fixed in order:

   - **`cosign`**: `signature identity/issuer does not match policy`. Root
     cause: cosign v3 (installed via `sigstore/cosign-installer`, unpinned to
     a specific cosign version, so it tracks upstream releases) only
     "partially populates" the `optional.Issuer`/`optional.Subject` fields in
     `cosign verify --output json` for the new bundle format
     (`sigstore/cosign#4416`) — both fields come back empty on a real,
     correct signature. `cosign verify` already enforces
     `--certificate-oidc-issuer`/`--certificate-identity` internally (fails
     closed with no output on a real mismatch), so the script's redundant
     re-derivation of those fields was replaced with a digest-binding check.

   - **`sbom`**: `Cannot index boolean with string "techx.sourceSha"`. Root
     cause: `EXPR and (...) as $p | BODY` parses in jq as
     `(EXPR and (...)) as $p`, i.e. `$p` was bound to a boolean, not the
     properties map — a jq operator-precedence bug, same class as the
     boolean-stream bug PR #445 fixed elsewhere in this script. Fixed by
     parenthesizing the `as` binding.

   - **`sbom`** (second, independent bug after the first was fixed): the
     binding check still failed because it compared the SBOM's true
     per-platform `techx.subjectDigest` against `child_digest` — but on this
     cluster's containerd (2.2.4), `child_digest` had already been observed
     to equal the *release index* digest, not the per-platform child
     manifest digest (the PR #445 finding). Fixed by resolving the real
     per-platform child digest from the already-fetched release index when
     that substitution is detected, and comparing against that instead.

   - **`argo`**: `expected exactly one matching Argo application`. Root
     cause: five ArgoCD Applications from this repo now deploy into
     `techx-tf3` (`techx-corp`, `techx-edge`, `techx-infrastructure-app`,
     `flagd-secret-sync`, `native-admission-policies`) — repo+namespace
     matching, which worked when the script was first written, no longer
     disambiguates to exactly one. Fixed by resolving the pod's actual owning
     workload (walk `ReplicaSet` → its owner) and matching on that resource
     appearing in an Application's `status.resources` tree, with the old
     heuristic kept as a fallback.

   All three are script-assumption/environment-drift bugs (cosign's own
   upstream release, this cluster's containerd version, and this repo's
   growing number of GitOps apps), not supply-chain or signing failures —
   same category as the two bugs PR #445 already fixed.

5. Reran `trace-provenance.sh` after each fix; the final run returned
   `overallResult: PASS` with all five required links: runtime digest → build
   source SHA/run → merged source PR (#459) with non-author approval →
   promotion PR (#461) → exact Trivy pass, Cosign identity, and PM-127 SBOM,
   plus GitOps ancestry (`Healthy`/`Synced`, promotion merge SHA is the exact
   Argo sync revision).

## Verification before merge

- `bash -n scripts/ci/trace-provenance.sh` — syntax OK.
- Full `python -m pytest -q scripts/ci` — 261 passed, 2 skipped (no
  regressions from the trace-provenance.sh changes).
- Reran the fixed script against the same live pod a final time to confirm
  `overallResult: PASS` reproduces (see `trace-pass-2026-07-26.json`).

## Closure

This satisfies the PM-129 closure gate (§6 of `pm-129-closure-status.md`):
a working read-only EKS access path, `kubectl` evidence of the healthy
checkout rollout on the promoted digest, a `trace-provenance.sh` PASS, and
this transcript are all attached under this directory.

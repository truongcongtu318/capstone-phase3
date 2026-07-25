# PM-129 checkout re-promotion attempt — 2026-07-25 (deferred, reverted cleanly)

## Why this was attempted

After fixing the two `trace-provenance.sh` defects (PR #445), the live trace against the
production checkout pod progressed further than ever before but still failed at the
`trivy` step: the currently-deployed checkout digest (`sha256:ebea1f1d...`) was built by
workflow run `29978396050` on **2026-07-23**, before PR #442 (last-platform Trivy fix)
merged, so that run's own evidence artifact genuinely only contains an amd64 report — no
amount of script fixing can add a missing arm64 scan to a historical, already-completed
GitHub Actions run. Closing PM-129's live-trace DoD requires evidence produced by a build
that ran with the fixed workflow, i.e. a fresh checkout build + promotion.

## What was done (with explicit user confirmation before each production-affecting step)

1. Triggered `build-push-ecr.yml` via `workflow_dispatch`, scoped to `services=checkout`
   (no source code change — rebuild of the same `main` HEAD, run to backfill evidence).
   - First 3 attempts (`30157592980` x2 reruns, `30157814829`) failed with GitHub Actions'
     own generic `"internal error when running your job"`, zero steps executed, no logs —
     confirmed via `githubstatus.com` that there was no broader GitHub incident
     (`"All Systems Operational"`), so this was a transient runner-provisioning blip
     scoped to this repo, not caused by our config.
   - 4th attempt (`30157905829`) succeeded fully: `prepare` → `build-scan (checkout)`
     (both-platform build, pre/post-push Trivy, Cosign sign, SBOM) → `aggregate` →
     `open-image-bump-pr`, all green. New digest: `sha256:5b16d444b6e5a4da91ffbe24a9fe0a9aace7ae434271ebc70e3844dcfa8f584d`.
2. This opened promotion PR **#448** (`chore(deploy): bump checkout image to 9915095`),
   authored by the `github-actions[bot]` app — its own CI runs needed manual approval
   (`gh api ... /approve`), which was granted; all 6 required checks passed twice (once
   before, once after a required branch update to catch up with unrelated commits
   #446/#447 that landed on `main` in the meantime). Reviewed and merged with explicit
   user confirmation (merge commit `6f67343a37a18dd88fd3975750b7b0593cbfde60`).
3. ArgoCD (`techx-corp` app) picked up the new commit and Argo Rollouts began a canary
   surge for `checkout-rollout`. The surge pod (`checkout-rollout-669df7ccf-dk2db`)
   **could not be scheduled**:
   ```
   FailedScheduling (karpenter): node limits have been exhausted for nodepool
   (NodePool=flash-sale-spot-arm64); (NodePool=flash-sale-spot); (NodePool=elastic-ondemand-fallback)
   ```
   Root cause, confirmed by reading the live `NodePool` CRs:
   - `elastic-ondemand-fallback`: `limits.nodes: 0` — a hard cap, not transient busy-ness.
   - `flash-sale-spot` and `flash-sale-spot-arm64`: both already at their own cap (2/2
     nodes each).
   - All three NodePools carry `techx.io/workload: elastic` (checkout's node selector),
     so any of them could in principle host the pod — none had headroom.
   - Separately discovered (via PR #451, merged independently by another workstream
     minutes later) that `flash-sale-spot`'s `nodes` limit had been **temporarily** dropped
     from 6 to 2 for a Mandate 19 / PM-152 breakpoint test, with a code comment saying it
     "PHẢI trả lại nodes: 6 sau khi test xong" (must be restored to 6 after the test) —
     that restoration had not happened yet, which is the real reason capacity was this
     tight. Not something this session caused or should fix unilaterally (a different
     team's in-flight Karpenter work, per repo convention).
4. **Zero production impact at any point.** `checkout-rollout`'s existing two pods
   (old digest) stayed `Running`/`Ready` for the entire episode — `maxUnavailable: 0`
   held exactly as designed. The only symptom was the Rollout object itself reporting
   `Degraded` (`ProgressDeadlineExceeded`) because the *new* pod never became Ready, not
   because live traffic was affected.
5. Rather than modify NodePool limits ourselves (explicitly against repo convention while
   another team's Karpenter work is mid-flight), reverted the promotion: PR **#450**
   (`git revert -m 1` of #448's merge commit), reviewed and merged by the user (I could
   not self-approve as the PR author). ArgoCD synced the revert and pruned the stuck
   `checkout-rollout-669df7ccf` ReplicaSet. Confirmed final state:
   ```
   checkout-rollout-6d97d4ff58-7fk5p   1/1 Running  (old digest, unchanged)
   checkout-rollout-6d97d4ff58-9rgcg   1/1 Running  (old digest, unchanged)
   Rollout: phase=Healthy replicas=2 updated=2 ready=2 available=2
   ```
   Back to exactly the pre-attempt state, cleanly.

## Status after this attempt

- PM-129 script defects: **fixed and merged** (#441, #442, #445).
- PM-129 live trace: **still not `PASS`** — blocked on evidence completeness for the
  currently-deployed digest (see `trace-attempt-2026-07-25.md`), and the one attempt to
  fix that by re-promoting checkout was blocked by unrelated Karpenter capacity
  exhaustion, then cleanly reverted with no production impact.
- Karpenter capacity has since improved independently (PR #451 raised `flash-sale-spot`
  from 2→3 nodes), which may make a future retry succeed, but this was not re-attempted
  in this session per explicit decision to stop here and finalize the report.

## Decision log (explicit user confirmations obtained, in order)

1. Confirmed before triggering the checkout rebuild + promotion in the first place
   (production-impacting; asked and reconfirmed downtime/coordination questions).
2. Confirmed before merging promotion PR #448.
3. When the rollout got stuck, presented 3 options (revert / wait / ask CDO01 first);
   user chose revert.
4. Confirmed to stop here (not retry immediately) and finalize the report with current
   evidence, rather than attempt a second promotion in this session.

# PM-129 live trace attempt — 2026-07-25

Date: 2026-07-25 (UTC)
Operator env: local workstation, `aws` profile `default` (assumed role
`arn:aws:iam::197826770971:role/tf3-production-readonly`, account `197826770971`).
`gh`/`cosign` installed ad hoc via `nix profile add nixpkgs#gh nixpkgs#cosign` for this
session. Access path: SSM port-forward through bastion `i-0f5959afa0eb31e7c` to the
private EKS API endpoint, `kubectl` pointed at `https://localhost:8443`. Read-only for
the entire session — no `apply`/`delete`/`scale`/`exec`, no Terraform Apply.

## What changed vs. the 2026-07-23 attempt

The prior attempt (`trace-attempt-2026-07-23.txt`) failed at `preflight` because `gh`
was not installed in the operator environment. This time `gh` (authenticated, account
`nvtank`, scopes `gist,read:org,repo,workflow`) and `cosign` were available, and both
#441 (Argo ancestry-match fix) and #442 (Trivy last-platform fix) were already merged
to `main`. The trace progressed past preflight, pod fetch, and the initial digest
validation this time, then failed at a new step.

## Command

```
bash scripts/ci/trace-provenance.sh \
  --pod checkout-rollout-6d97d4ff58-7fk5p \
  --namespace techx-tf3 \
  --output docs/evidence/mandate-10/pm-129/trace-provenance-2026-07-25.json
```

## Result — FAIL at `image-manifest`

```json
{
  "schemaVersion": 1,
  "overallResult": "FAIL",
  "pod": "checkout-rollout-6d97d4ff58-7fk5p",
  "namespace": "techx-tf3",
  "failedStep": "image-manifest",
  "error": "runtime child digest is not a member of the release index",
  "generatedAt": "2026-07-25T11:55:38Z"
}
```

Full output: `trace-provenance-2026-07-25.json` (this directory).

## Root cause (confirmed independently, not just script output)

Pod `checkout-rollout-6d97d4ff58-7fk5p` in `techx-tf3`, node
`ip-10-0-40-78.ap-southeast-1.compute.internal` (containerd `2.2.4+unknown`, kubelet
`v1.35.6-eks-8f14419`, `linux/amd64`):

- `.spec.containers[0].image` = `...techx-corp@sha256:ebea1f1d2ab51dac3a1de5493d4a8e97e6607601f966315eb1608a4d6f9aeeb8`
  — this **is** the promoted release digest from PR #369, confirmed correct.
- `.status.containerStatuses[0].imageID` = the **same** digest,
  `sha256:ebea1f1d2ab51...`. Full pod spec saved in `pod-checkout-2026-07-25.json`.

`trace-provenance.sh` treats `imageID` as the platform-specific *child* manifest
digest and asserts it must appear inside the release index's `.manifests[].digest`
list. Fetching that index directly:

```
docker buildx imagetools inspect --raw \
  197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:ebea1f1d2ab51dac3a1de5493d4a8e97e6607601f966315eb1608a4d6f9aeeb8
```

(full raw output: `release-index-manifest-2026-07-25.json`) lists 4 children:

| digest | platform |
|---|---|
| `sha256:98280f4556179f9991459e4169183c8d440cbe07c4a7ac5379287bc9c3a26175` | linux/amd64 |
| `sha256:13f555a7548d0f739032339af6ab3b1659ef17eed9ea7f98e64cbbcf38874f28` | linux/arm64 |
| `sha256:fab2e9f546400dc29a8ec2ca9f93c6265e23370d9e3b1637177851a1a5627066` | attestation (amd64) |
| `sha256:bd027efa01c0999bf3670d7730bd984eaea6a2c3ada3a4a3312f798a51158358` | attestation (arm64) |

`sha256:ebea1f1d...` (the pod's `imageID`) is none of these — it is the **index**
digest itself, not a member of it. This is not a supply-chain problem: the running
image is provably the exact digest that was reviewed, scanned, and promoted. It is a
**script assumption gap**: on containerd `2.2.4` (EKS `1.35`, AL2023), when a pod is
pinned to an image by digest reference pointing at a multi-arch index, the kubelet CRI
status reports `imageID` as that same index digest rather than resolving to the
platform-specific child manifest digest that `trace-provenance.sh` expects. Older
containerd/CRI versions this script was written against apparently returned the child
manifest digest instead — behavior changed under the script's feet.

## Impact on PM-129 closure

- **Confirms**: the promoted checkout digest is genuinely running in production
  (`imageID` == reviewed/scanned/signed release digest, index matches PR #369's
  approved manifest). This is real, independently-verified evidence of correct
  deployment — just not through the automated `overallResult: PASS` path.
- **Does not confirm**: the automated review→scan→signature→SBOM chain end-to-end,
  because the script exits before reaching the ECR/`gh`/cosign/SBOM/Argo steps for
  this pod. Those steps are untested in this run.
- **DoD still not met.** `overallResult` is `FAIL`, not `PASS`. Per the closure gate in
  `pm-129-closure-status.md`, PM-129 cannot be marked closed on this run.

## Recommended next step (not yet done — needs review before merge)

`trace-provenance.sh` line ~181 should also accept the case where the runtime digest
equals the release index digest itself (i.e. `child_digest == release_digest`), in
addition to being a member of `.manifests[].digest`, since containerd `2.2.4` reports
it that way when pods pin by digest. This is a change to a fail-closed security gate
script and should go through the same PR + CI review as #441/#442, not be patched
ad hoc during a live trace attempt.

## Artifacts in this directory

- `trace-provenance-2026-07-25.json` — raw script output (FAIL)
- `pod-checkout-2026-07-25.json` — full pod spec/status (read-only `kubectl get`)
- `node-2026-07-25.json` — full node spec/status (read-only `kubectl get`)
- `release-index-manifest-2026-07-25.json` — raw OCI index manifest for the promoted digest

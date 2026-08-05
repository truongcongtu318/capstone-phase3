# Image supply-chain controls

**Scope:** backlog #8, complementary to PM-95's ECR tag immutability and
digest pinning. This document owns the remaining release gate and provenance
controls; it does not replace the pinned digest in the GitOps values.
The signed decision and rollout trade-offs are recorded in
[`ADR 0008`](../adr/0008-pm-101-image-supply-chain-gate.md).

## First-party app images

`.github/workflows/build-push-ecr.yml` is the only release path for every
target in `ALL_SERVICES` (currently 20 build targets). Its order is deliberate:

1. Build each selected target locally for `linux/amd64`, the EKS node
   architecture.
2. Trivy scans the local candidate before it is pushed. The release threshold
   is **zero HIGH and zero CRITICAL vulnerabilities**, including unfixed CVEs:
   `--severity HIGH,CRITICAL --exit-code 1`. A failure stops the workflow, so
   the multi-architecture ECR push cannot run.
3. Only candidates that pass are pushed as the normal `linux/amd64,linux/arm64`
   manifest list. Each pushed ECR digest is then signed by `cosign sign --yes`.

Cosign is keyless: the GitHub Actions OIDC token supplied by
`permissions.id-token: write` obtains the short-lived signing identity. No
Cosign private key, password, or static signing secret is stored in this repo
or in GitHub Secrets. The identity expected for releases from `main` is:

```text
issuer:   https://token.actions.githubusercontent.com
identity: https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/.github/workflows/build-push-ecr.yml@refs/heads/main
```

For a pinned ECR digest, verify the provenance before a manual investigation or
future Kyverno policy rollout:

```sh
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/.github/workflows/build-push-ecr.yml@refs/heads/main \
  197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:<digest>
```

The Trivy JSON file for every selected app image is uploaded by the same run as
the `trivy-app-images-<run-id>` artifact and retained for 90 days. That artifact
is the current scan evidence to attach to the release/change record; a failed
gate uploads reports produced before the failure as well. The first successful
run after this PR must be recorded against the exact digest in
`docs/../reports/release-notes-v1.md` before that digest is promoted in GitOps.

After each successful signature, the workflow immediately verifies the ECR
digest against the certificate identity derived from `GITHUB_WORKFLOW_REF`.
The resulting `signed-release-evidence-<run-id>` artifact contains:

- `signed-images.jsonl`: service, tag, pushed digest, Git SHA, run URL, expected
  workflow identity, and the corresponding Trivy/Cosign report paths;
- `cosign/<service>.json`: the raw successful `cosign verify` output for that
  digest.

The two artifacts must be reviewed together. A digest is eligible for GitOps
promotion only when it has both a clean Trivy report and a successful Cosign
verification from the same workflow run. The branch implementation itself is
not runtime evidence; the first green full run on `main` supplies that proof.

## External-image exceptions

The following production dependencies are third-party artifacts. TF3 did not
build them, therefore it cannot truthfully sign them with the TF3 GitHub OIDC
identity. They remain digest-pinned by PM-95, are excluded from the first-party
signature requirement, and are reviewed by the non-blocking weekly workflow
`.github/workflows/scan-external-images.yml`. A HIGH/CRITICAL result opens a
review/remediation decision; it never fails application-build CI merely because
an upstream image lacks a TF3 signature.

| Component | Pinned image | Signature exception | Scan cadence |
| --- | --- | --- | --- |
| PostgreSQL | `docker.io/library/postgres@sha256:00bc866...` | Upstream image; no TF3 signing authority | Weekly Trivy + quarterly review |
| Grafana | `docker.io/grafana/grafana@sha256:0f86bada...` | Upstream image; no TF3 signing authority | Weekly Trivy + quarterly review |
| Jaeger | `docker.io/jaegertracing/jaeger@sha256:626657...` | Upstream image; no TF3 signing authority | Weekly Trivy + quarterly review |
| OpenSearch | `docker.io/opensearchproject/opensearch@sha256:b5dd15...` | Upstream image; no TF3 signing authority | Weekly Trivy + quarterly review |
| Prometheus | `quay.io/prometheus/prometheus@sha256:c0b857...` | Upstream image; no TF3 signing authority | Weekly Trivy + quarterly review |
| OTel Collector | `docker.io/otel/opentelemetry-collector-contrib@sha256:d57bfe...` | Upstream image; no TF3 signing authority | Weekly Trivy + quarterly review |
| Valkey | `docker.io/valkey/valkey@sha256:c106a0...` | Upstream image; no TF3 signing authority | Weekly Trivy + monthly review |
| Flagd | `ghcr.io/open-feature/flagd@sha256:e6cca8...` | Upstream image; no TF3 signing authority | Weekly Trivy + quarterly review |

The full digests and release inventory are authoritative in
[`../reports/release-notes-v1.md`](../reports/release-notes-v1.md). Any new external runtime image
must be added to both that inventory and the periodic workflow in the same PR.

## Boundary with admission control

This change creates signatures and a stable verifier identity, but it does not
yet enforce signature verification in the API server. The follow-up Kyverno
task should use the verifier identity above for first-party ECR images and
exclude only the documented external-image list. Until then, digest pinning and
the CI gate remain preventive controls rather than an admission-time guarantee.

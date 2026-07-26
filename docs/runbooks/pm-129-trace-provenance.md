# PM-129 immutable provenance trace runbook

This runbook traces one already-running workload without changing cluster or
Terraform state. It is a read-only, pre-merge/release-evidence check. The
ECR scan-on-push setting is not sufficient evidence for this gate: the trace
requires the exact Trivy artifact produced by the trusted `build-push-ecr.yml`
run, the merged review PRs, keyless Cosign verification, and the PM-127
CycloneDX SBOM attestation.

## Preconditions

1. Authenticate the two read paths:

   ```bash
   gh auth login
   aws sso login --profile <profile>
   export AWS_PROFILE=<profile>
   ```

2. Establish the existing read-only private-cluster tunnel (if the cluster is
   private), then verify context. Do not run `terraform apply`, `kubectl apply`,
   `helm upgrade`, or any imperative rollout command for this procedure.

   ```bash
   kubectl config current-context
   kubectl auth can-i get pods -n techx-tf3
   kubectl auth can-i get applications.argoproj.io -A
   aws sts get-caller-identity
   ```

3. Install/read-only tooling: `jq`, `docker buildx`, `cosign`, `python3`,
   `aws`, `gh`, and `kubectl`. Log in to ECR only when required by the SBOM
   helper; this does not push or mutate an image:

   ```bash
   aws ecr get-login-password --region ap-southeast-1 |
     docker login 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com \
       --username AWS --password-stdin
   ```

## Canary release validation (optional, stateless only)

The normal `push` workflow still builds the full production matrix. For a
read-only rehearsal of one stateless service, an administrator may dispatch
`Build and push images to ECR` on `main` with `services=image-provider` (or
another stateless service) and the normal `linux/amd64,linux/arm64` platforms.
The workflow publishes immutable evidence and opens the normal image-bump PR;
it does not deploy directly. Merge that PR only after the required checks and
review pass. Do not use this flow for Kafka, databases, or a Recreate workload
while demonstrating the gate.

## Trace a live pod

Use the pod's actual namespace and name. If it has more than one release
container, provide `--container` so the selection is unambiguous:

```bash
scripts/ci/trace-provenance.sh \
  --pod image-provider-<suffix> \
  --namespace techx-tf3 \
  --output /tmp/pm-129-trace.json
jq . /tmp/pm-129-trace.json
```

The script fails closed and writes an atomic JSON result. A successful result
contains these five links in one record:

`runtime index/child digest -> build source SHA/run -> merged source PR with a
non-author approval -> exact post-push Trivy reports with no HIGH/CRITICAL ->
merged promotion PR/Argo revision plus Cosign identity and PM-127 SBOM`.

Useful disambiguation options are `--source-pr NUMBER` and
`--promotion-pr NUMBER`; they do not bypass any validation. The script still
checks the base branch, merge state, reviewer state, artifact name, digest,
and signature identity/issuer/SBOM properties exactly. For GitOps, it checks
that the single matching Argo Application is Healthy/Synced and that the
promotion PR's merge commit is an ancestor of (or equal to) Argo's current
sync revision — not that the two are byte-equal. ArgoCD tracks `main` HEAD
with auto-sync + selfHeal, so unrelated commits keep landing after a
promotion merges; requiring exact equality would fail every trace as soon as
anything else ships. Ancestry proves the promoted change is included in what
is currently live without demanding a frozen `main`.

## Troubleshooting

- `preflight` or `workflow-run`: refresh `gh auth login`; check that the run is
  on `main` and that the token can read Actions artifacts.
- `pod`/`argo`: refresh the private-cluster tunnel and verify the two
  `kubectl auth can-i` commands. No write permission is needed. If `argo`
  fails specifically on ancestry ("promotion merge SHA is not an ancestor"),
  the Argo Application has not yet synced past the promotion commit, or is
  tracking a different branch/fork entirely — wait for the next auto-sync
  and rerun; do not treat this as a script bug.
- `approved-artifact`, `promotion-artifact`, or `trivy`: do not substitute a
  newer run or a local scan. The exact run/attempt artifact is part of the
  provenance chain; rerun the trusted workflow if it has expired.
- `cosign`/`sbom`: ensure Rekor/network access and ECR read access. A missing,
  ambiguous, stale, or differently-bound attestation is a failure.

Save the resulting JSON and command transcript under
`docs/evidence/mandate-10/pm-129/` only after redacting credentials and pod
secrets. A blocked/authentication result is evidence of an incomplete live
validation, not a PASS.

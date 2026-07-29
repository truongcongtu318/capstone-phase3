# AIOps `techx-corp` Pipeline Migration Design

## Goal

Build `aiops-engine` through the existing first-party image workflow so the
result is pushed to `techx-corp`, scanned before and after push, signed with
Cosign, and receives the same CycloneDX SBOM attestations as the other
production services.

## Scope

This change is phase A of a two-phase migration.

- Add an `aiops-engine` Buildx Bake target whose context is the repository-root
  `aiops-engine/` directory.
- Register `aiops-engine` in the common workflow trigger, service allowlist,
  and changed-path detection.
- Keep the common Trivy, Cosign, SBOM, and promotion gates unchanged.
- Exclude `aiops-engine` from the Helm image-bump step because its Deployment
  and CronJob are standalone GitOps manifests, not chart components.
- Remove the obsolete dedicated AIOps workflow.

The current Deployment, CronJob, and external-image allowlist remain unchanged.
Phase B will update those files only after phase A produces a verified
multi-platform digest with valid signatures and attestations.

## Build Context Contract

`docker-compose.yml` lives under
`phase3 - information/techx-corp-platform/`, so the AIOps Bake target uses
`../../aiops-engine` as its context and `Dockerfile` relative to that context.
Docker therefore applies `aiops-engine/.dockerignore`; `models/`, `scratch/`,
virtual environments, and generated data stay outside the build context. The
service is under the `aiops-build` profile so normal local `docker compose up`
does not start a production-oriented AIOps process without its GitOps runtime
configuration.

## Safety and Rollback

The strict zero HIGH/CRITICAL Trivy gate is not relaxed. Existing services keep
their current 60-minute timeout and build/promotion behavior. The AIOps matrix
child receives 90 minutes because its Alpine arm64 scientific stack compiles
under QEMU; local validation took about 49 minutes for the build alone. If that
matrix child fails, the aggregate manifest and image-bump job do not proceed.

Rollback is removal of the AIOps target and workflow registration. No running
workload changes in this phase.

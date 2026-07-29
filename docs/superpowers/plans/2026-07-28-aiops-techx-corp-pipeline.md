# AIOps `techx-corp` Pipeline Migration Plan

1. Add failing contracts for the common-workflow registration, root build
   context, `.dockerignore`, and no-auto-promotion rule.
2. Add the `aiops-engine` Compose Bake target and common workflow routing.
3. Teach the existing image-manifest validator that `aiops-engine` is a valid
   built service, while explicitly excluding it from Helm update/render checks.
4. Delete the dedicated AIOps workflow.
5. Run focused CI contracts, resolve the Bake definition, inspect the build
   context, and build/scan both supported architectures without pushing.
6. Review the diff, commit atomically, push a task branch, and open a draft PR.

Phase B is deliberately separate: consume the verified digest in the AIOps
Deployment/CronJob and then remove the old `tf-2-ai-engine` allowlist entries.

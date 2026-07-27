# PM-176 pre-NetworkPolicy runtime dependency evidence

Captured: 2026-07-26 UTC, immediately after the PR #471 Grafana image rollout.

## Context

- PR #471 (`chore(deploy): bump grafana image to f5ba80a`) merged at
  `74ce2f3ccac5e1426e4cb972e30ce1edfb81bfd2`.
- PR #472 fixed the native admission-policy spelling mismatch and merged at
  `e0d822ac2071a6bd943bad0d8425116213205f4d`.
- Grafana Pod `grafana-8f757b88f-vnmz7` became `4/4 Ready`, with zero restarts.
- Image reference was:
  `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:f5ba80a-30210176908-grafana@sha256:fe9bdb6513fafc2fbf15b1ec27f408fe94e58bd00c3a0ac8d4848860758623f0`.
- ArgoCD `techx-corp` was `Synced/Healthy` at `e0d822a`.

## Observed failure

The Grafana startup log contained:

```text
Installing plugin pluginId=grafana-opensearch-datasource
Downloaded and extracted grafana-opensearch-datasource v2.34.0
Plugin registered pluginId=grafana-opensearch-datasource
Plugin successfully installed pluginId=grafana-opensearch-datasource
```

This proves that the image rollout alone did not satisfy PM-176. The plugin
was still declared through the Helm `grafana.plugins` value and installed at
runtime.

## NetworkPolicy state

At capture time PR #426 was still open. The live
`grafana-network-policy` had `policyTypes: [Ingress]` only. Therefore public
egress was not yet blocked, and this evidence is intentionally a
pre-NetworkPolicy baseline rather than a success claim.

## Required follow-up

The PM-176 PR 2 must remove the runtime plugin declaration, render
`GF_PATHS_PLUGINS=/opt/grafana/plugins`, and repeat the destructive Pod
recreation gate after the NetworkPolicy PR is promoted. This failure evidence
must remain attached to the task.

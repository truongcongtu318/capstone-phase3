# PM-176 post-PR #474 plugin signature failure

Captured: 2026-07-26 UTC, after PR #474 reconciled in production.

## Deployment state

- `origin/main` contained merge commit `31df196`.
- ArgoCD `techx-corp` reconciled that revision and became `Synced/Healthy`.
- Replacement Pod `grafana-7687bf6f89-ztkb8` became `4/4 Ready` with zero
  restarts.
- `GF_PATHS_PLUGINS` was `/opt/grafana/plugins`.
- No `GF_PLUGINS_PREINSTALL*` environment variable was rendered.
- No runtime install/download lines were present in the replacement Pod.

## Observed failure

Grafana rejected the baked OpenSearch datasource plugin:

```text
Plugin file checksum does not match signature checksum
Skipping loading plugin due to problem with signature
Plugin validation failed pluginId=grafana-opensearch-datasource
```

This is a functional PM-176 failure. A Ready Pod is not sufficient when the
required datasource plugin is skipped.

## Root cause

The image Dockerfile installed the signed Grafana catalog archive and then
overwrote its `gpx_opensearch-datasource_linux_${TARGETARCH}` file with a
locally compiled binary from the plugin source repository. That changed a file
covered by the archive's `MANIFEST.txt`, so Grafana correctly detected a
modified signature. The official 2.34.0 archive already contains signed
`linux_amd64` and `linux_arm64` backend binaries.

## Corrective action

The follow-up image change removes the source-built plugin stage and the
overwrite `COPY`. The Docker build now verifies that the catalog archive's
`MANIFEST.txt` and target-architecture signed backend remain present, then
locks the plugin directory read-only.

The smoke test also fails on modified/invalid signature messages, not only
runtime installer activity.

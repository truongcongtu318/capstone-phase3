# PM-176 post-PR #473 automatic preinstall failure

Captured: 2026-07-26 UTC, after PR #473 reconciled in production.

## Context

- PR #473 merged at
  `f7ef66b1290a03c2c9f5fb45f64b9a9aa540a686`.
- ArgoCD `techx-corp` became `Synced/Healthy` at that revision.
- Grafana Pod `grafana-5877d84f78-6dlgs` became `4/4 Ready`, with zero
  restarts.
- The Deployment no longer contained `GF_PLUGINS_PREINSTALL*`.
- `GF_PATHS_PLUGINS` was `/opt/grafana/plugins`.
- The live ConfigMap disabled analytics update checks and reporting.

## Observed failure

The OpenSearch plugin was no longer downloaded at startup. However, Grafana 13
still started its independent automatic preinstall catalogue and tried to
install bundled/default plugins into the immutable path. Startup logs included:

```text
Plugins installed plugins=[]
Installing plugin pluginId=grafana-exploretraces-app
Failed to install plugin ... permission denied
Installing plugin pluginId=grafana-metricsdrilldown-app
Failed to install plugin ... permission denied
```

The same sequence covered other default catalogue entries such as Tempo,
Jaeger, Zipkin, Elasticsearch, PostgreSQL, MSSQL, Pyroscope, Loki Explore, and
Stackdriver. This is a PM-176 failure even though the Pod is Ready: startup
still depends on a runtime plugin installer and produces permission errors.

## Root cause

The Grafana 13 image's `/usr/share/grafana/conf/defaults.ini` defines:

```ini
[plugins]
preinstall =
preinstall_sync =
preinstall_disabled = false
preinstall_auto_update = true
```

Removing the Helm chart's `grafana.plugins` declaration only removed the
OpenSearch-specific installer environment variable. It did not disable
Grafana's own automatic preinstall feature.

## Corrective action and rollback boundary

The follow-up change sets these official Grafana options through
`grafana.grafana.ini.plugins`:

```ini
preinstall_disabled = true
preinstall_auto_update = false
plugin_admin_enabled = false
plugin_admin_external_manage_enabled = false
```

The smoke gate now fails on any plugin install/download attempt, not only an
OpenSearch attempt. Do not promote PR #426 until the replacement Pod has no
installer/download/failure lines and the baked OpenSearch datasource passes
the functional checks. Revert the follow-up merge through Git if Grafana fails
readiness, plugin loading, datasource health, or sidecar provisioning.

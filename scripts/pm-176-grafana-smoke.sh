#!/usr/bin/env bash

# PM-176 immutable Grafana smoke test.
# Read-only apart from a short-lived kubectl port-forward. It never applies,
# patches, deletes, restarts, or syncs Kubernetes resources.

set -euo pipefail

NS="${NAMESPACE:-techx-tf3}"
ARGO_NS="${ARGO_NAMESPACE:-argocd}"
SELECTOR="${GRAFANA_SELECTOR:-app.kubernetes.io/name=grafana}"
EXPECTED_PLUGIN_VERSION="${EXPECTED_PLUGIN_VERSION:-2.34.0}"
EXPECTED_PLUGIN_PATH="${EXPECTED_PLUGIN_PATH:-/opt/grafana/plugins}"
EXPECTED_IMAGE_RE="${EXPECTED_IMAGE_RE:-197826770971\\.dkr\\.ecr\\.ap-southeast-1\\.amazonaws\\.com/techx-corp:[A-Za-z0-9_.-]+-grafana@sha256:[0-9a-f]{64}}"
API_TIMEOUT="${API_TIMEOUT_SECONDS:-5}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT_SECONDS:-120}"
EXPECT_EGRESS_BLOCK="${EXPECT_EGRESS_BLOCK:-0}"
GRAFANA_BASE_URL="${GRAFANA_BASE_URL:-}"
GRAFANA_TOKEN="${GRAFANA_TOKEN:-}"
PORT_FORWARD_PID=""
PORT_FORWARD_LOG=""
failures=0
blocked=0

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_dir="${PM176_OUTPUT_DIR:-outputs/pm-176/$timestamp}"
mkdir -p "$output_dir"
exec > >(tee "$output_dir/run.log") 2>&1

cleanup() {
  if [[ -n "$PORT_FORWARD_PID" ]]; then
    kill "$PORT_FORWARD_PID" 2>/dev/null || true
    wait "$PORT_FORWARD_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

pass() {
  printf 'PASS %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1"
  failures=$((failures + 1))
}

blocked_check() {
  printf 'BLOCKED %s\n' "$1"
  blocked=$((blocked + 1))
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$1" >&2
    exit 69
  }
}

json_assert() {
  local payload="$1"
  local expression="$2"
  python3 -c "import json, sys; value=json.load(sys.stdin); assert $expression" <<<"$payload"
}

api_get() {
  local path="$1"
  local url="${GRAFANA_BASE_URL%/}${path}"
  if [[ -n "$GRAFANA_TOKEN" ]]; then
    curl -fsS --max-time "$API_TIMEOUT" \
      -H "Authorization: Bearer ${GRAFANA_TOKEN}" "$url"
  else
    curl -fsS --max-time "$API_TIMEOUT" "$url"
  fi
}

need_command kubectl
need_command curl
need_command python3

pod="$(kubectl get pods -n "$NS" -l "$SELECTOR" \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')"
if [[ -z "$pod" ]]; then
  fail "running Grafana pod"
  exit 1
fi

pod_json="$(kubectl get pod -n "$NS" "$pod" -o json)"
pod_uid="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])' <<<"$pod_json")"
node="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["spec"].get("nodeName",""))' <<<"$pod_json")"
image="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(c["image"] for c in d["spec"]["containers"] if c["name"]=="grafana"))' <<<"$pod_json")"
image_id="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(c["imageID"] for c in d["status"]["containerStatuses"] if c["name"]=="grafana"))' <<<"$pod_json")"
printf 'pod=%s\npod_uid=%s\nnode=%s\nimage=%s\nimage_id=%s\n' \
  "$pod" "$pod_uid" "$node" "$image" "$image_id"

if [[ "$image" =~ $EXPECTED_IMAGE_RE ]] && [[ "$image_id" == *"@sha256:"* ]]; then
  pass "Grafana image is first-party and digest-pinned"
else
  fail "Grafana image is first-party and digest-pinned"
fi

if kubectl -n "$ARGO_NS" get application techx-corp \
  -o jsonpath='{.status.sync.status} {.status.health.status}' \
  | grep -qx 'Synced Healthy'; then
  pass "ArgoCD techx-corp is Synced/Healthy"
else
  fail "ArgoCD techx-corp is Synced/Healthy"
fi

if kubectl wait --for=condition=Ready -n "$NS" "pod/$pod" \
  --timeout="${STARTUP_TIMEOUT}s" >/dev/null; then
  pass "Grafana pod is Ready"
else
  fail "Grafana pod is Ready"
fi

plugin_path="$(python3 -c 'import json,sys; d=json.load(sys.stdin); c=next(c for c in d["spec"]["containers"] if c["name"]=="grafana"); print(next((e.get("value","") for e in c.get("env",[]) if e.get("name")=="GF_PATHS_PLUGINS"),""))' <<<"$pod_json")"
if [[ "$plugin_path" == "$EXPECTED_PLUGIN_PATH" ]]; then
  pass "GF_PATHS_PLUGINS points to the immutable image path"
else
  fail "GF_PATHS_PLUGINS points to the immutable image path"
fi

grafana_ini="$(kubectl get configmap -n "$NS" grafana -o jsonpath='{.data.grafana\.ini}')"
required_plugin_settings=(
  "preinstall_disabled = true"
  "preinstall_auto_update = false"
  "plugin_admin_enabled = false"
  "plugin_admin_external_manage_enabled = false"
)
for setting in "${required_plugin_settings[@]}"; do
  if grep -Fqx "$setting" <<<"$grafana_ini"; then
    pass "Grafana config contains: $setting"
  else
    fail "Grafana config contains: $setting"
  fi
done

manifest="$(
  kubectl exec -n "$NS" "$pod" -c grafana -- sh -ceu \
    "test -f '$EXPECTED_PLUGIN_PATH/grafana-opensearch-datasource/plugin.json' && \
     cat '$EXPECTED_PLUGIN_PATH/grafana-opensearch-datasource/plugin.json'"
)"
if json_assert "$manifest" \
  "value.get('id') == 'grafana-opensearch-datasource' and value.get('version') == '$EXPECTED_PLUGIN_VERSION'"; then
  pass "baked OpenSearch plugin manifest and version"
else
  fail "baked OpenSearch plugin manifest and version"
fi

startup_log="$(kubectl logs -n "$NS" "$pod" -c grafana)"
if grep -Eqi \
  'plugin\.(backgroundinstaller|installer).*installing plugin|download(ed)? and extracted|plugin successfully installed|failed to install plugin|modified signature|skipping loading plugin due to problem with signature|plugin validation failed' \
  <<<"$startup_log"; then
  fail "Grafana made no runtime plugin install/download attempt or signature validation failure"
else
  pass "Grafana made no runtime plugin install/download attempt or signature validation failure"
fi

if [[ -z "$GRAFANA_BASE_URL" ]]; then
  local_port="${GRAFANA_LOCAL_PORT:-13000}"
  PORT_FORWARD_LOG="$output_dir/port-forward.log"
  kubectl -n "$NS" port-forward "service/grafana" \
    "${local_port}:80" >"$PORT_FORWARD_LOG" 2>&1 &
  PORT_FORWARD_PID=$!
  GRAFANA_BASE_URL="http://127.0.0.1:${local_port}"
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "${GRAFANA_BASE_URL}/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

health="$(api_get /api/health)"
if json_assert "$health" "value.get('database') == 'ok'"; then
  pass "Grafana API health"
else
  fail "Grafana API health"
fi

plugin_settings="$(api_get /api/plugins/grafana-opensearch-datasource/settings)"
if json_assert "$plugin_settings" \
  "value.get('id') == 'grafana-opensearch-datasource' and value.get('enabled') is True"; then
  pass "Grafana API reports the OpenSearch plugin loaded"
else
  fail "Grafana API reports the OpenSearch plugin loaded"
fi

datasource="$(api_get /api/datasources/uid/webstore-logs)"
if json_assert "$datasource" \
  "value.get('uid') == 'webstore-logs' and value.get('type') == 'grafana-opensearch-datasource'"; then
  pass "webstore-logs datasource is provisioned"
else
  fail "webstore-logs datasource is provisioned"
fi

if datasource_health="$(api_get /api/datasources/uid/webstore-logs/health 2>/dev/null)"; then
  if json_assert "$datasource_health" "value.get('status') == 'success'"; then
    pass "webstore-logs datasource health"
  else
    fail "webstore-logs datasource health"
  fi
else
  blocked_check "webstore-logs datasource health endpoint unavailable"
fi

if [[ "$EXPECT_EGRESS_BLOCK" == "1" ]]; then
  external_result="$(kubectl exec -n "$NS" "$pod" -c grafana -- sh -ceu \
    'command -v curl >/dev/null && curl -sS --connect-timeout 5 --max-time 8 https://example.com' \
    2>&1 || true)"
  if grep -Eqi 'timed out|timeout|could not resolve|network is unreachable|connection refused' <<<"$external_result"; then
    pass "public egress is blocked"
  else
    fail "public egress is blocked"
  fi
else
  blocked_check "public egress check skipped (set EXPECT_EGRESS_BLOCK=1 after PR #426)"
fi

printf 'failures=%s blocked=%s output=%s\n' "$failures" "$blocked" "$output_dir"
if (( failures > 0 )); then
  exit 1
fi
if (( blocked > 0 )); then
  exit 2
fi

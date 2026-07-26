#!/usr/bin/env bash
# Trace one running workload back to the immutable build, review, scan,
# signature, and SBOM evidence that produced it.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
POLICY_FILE="${REPO_ROOT}/scripts/ci/provenance-policy.json"
INVENTORY_FILE="${REPO_ROOT}/scripts/ci/dockerfile-scope.json"
POD=""
NAMESPACE=""
CONTAINER=""
SOURCE_PR=""
PROMOTION_PR=""
OUTPUT="trace-provenance.json"
WORK=""
FAILED_STEP=""
FAILED_MESSAGE=""

usage() {
  cat <<'EOF'
Usage: scripts/ci/trace-provenance.sh --pod POD --namespace NAMESPACE [options]

Required:
  --pod POD                  Running pod to inspect
  --namespace NAMESPACE      Kubernetes namespace containing the pod

Optional:
  --container NAME           Container when the pod has more than one release image
  --source-pr NUMBER         Disambiguate the merged source PR
  --promotion-pr NUMBER      Disambiguate the merged image-promotion PR
  --output FILE              Atomic JSON output (default: trace-provenance.json)
  -h, --help                 Show this help
EOF
}

fail_step() {
  FAILED_STEP="$1"
  FAILED_MESSAGE="$2"
  return 1
}

cleanup() {
  if [[ -n "$WORK" && -d "$WORK" ]]; then
    rm -rf -- "$WORK"
  fi
}
trap cleanup EXIT

write_failure() {
  local tmp="$1"
  mkdir -p -- "$(dirname -- "$OUTPUT")"
  jq -n \
    --arg pod "$POD" --arg namespace "$NAMESPACE" \
    --arg step "$FAILED_STEP" --arg message "$FAILED_MESSAGE" \
    '{schemaVersion:1, overallResult:"FAIL", pod:$pod, namespace:$namespace,
      failedStep:$step, error:$message, generatedAt:(now|todateiso8601)}' > "${tmp}.new"
  mv -f -- "${tmp}.new" "$OUTPUT"
}

run_json() {
  local step="$1"; shift
  local output="$1"; shift
  if ! "$@" >"$output" 2>"${output}.err"; then
    local detail
    detail="$(tail -1 "${output}.err" 2>/dev/null || true)"
    fail_step "$step" "${detail:-command failed: $*}"
    return 1
  fi
  if ! jq empty "$output" >/dev/null 2>&1; then
    fail_step "$step" "command returned invalid JSON"
    return 1
  fi
}

require_tools() {
  local tool
  for tool in aws gh kubectl jq cosign docker python3; do
    command -v "$tool" >/dev/null 2>&1 || {
      fail_step preflight "required command is unavailable: $tool"
      return 1
    }
  done
  jq -e '(.repository and .workflowPath and .registry and .imageRepository and .awsRegion and .oidcIssuer and .oidcIdentity and .sbomPredicateType)' "$POLICY_FILE" >/dev/null \
    || { fail_step preflight "invalid provenance policy: $POLICY_FILE"; return 1; }
}

validate_hex_digest() {
  [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]]
}

latest_review_approvers() {
  local reviews="$1" author="$2"
  jq -c --arg author "$author" '
    map(select(.state != "COMMENTED" and .state != "PENDING" and .state != "DISMISSED"))
    | group_by(.user.login)
    | map(max_by(.submitted_at // ""))
    | map(select(.state == "APPROVED" and .user.login != $author))
    | map({login:.user.login, submittedAt:.submitted_at})' <<<"$reviews"
}

review_pr() {
  local number="$1" author="$2" expected_base="$3" out="$4"
  local pr reviews approvers
  run_json "review-pr-${number}" "$out.pr" gh api "repos/${REPOSITORY}/pulls/${number}" || return 1
  pr="$(cat "$out.pr")"
  author="$(jq -r '.user.login' <<<"$pr")"
  [[ "$(jq -r '.state' <<<"$pr")" == "closed" && "$(jq -r '.merged' <<<"$pr")" == true ]] \
    || { fail_step "review-pr-${number}" "PR is not merged"; return 1; }
  [[ "$(jq -r '.base.ref' <<<"$pr")" == "$expected_base" ]] \
    || { fail_step "review-pr-${number}" "PR base is not ${expected_base}"; return 1; }
  run_json "reviews-${number}" "$out.reviews" gh api "repos/${REPOSITORY}/pulls/${number}/reviews" || return 1
  reviews="$(cat "$out.reviews")"
  approvers="$(latest_review_approvers "$reviews" "$author")"
  [[ "$(jq 'length' <<<"$approvers")" -ge 1 ]] \
    || { fail_step "reviews-${number}" "no latest non-author APPROVED review"; return 1; }
  jq -n --argjson pr "$pr" --argjson approvers "$approvers" \
    '{number:$pr.number,url:$pr.html_url,author:$pr.user.login,mergedAt:$pr.merged_at,
      mergeCommit:$pr.merge_commit_sha,headCommit:$pr.head.sha,base:$pr.base.ref,approvers:$approvers}' > "$out"
}

parse_args() {
  while (($#)); do
    case "$1" in
      --pod) POD="${2:?missing pod}"; shift 2;;
      --namespace) NAMESPACE="${2:?missing namespace}"; shift 2;;
      --container) CONTAINER="${2:?missing container}"; shift 2;;
      --source-pr) SOURCE_PR="${2:?missing source PR}"; shift 2;;
      --promotion-pr) PROMOTION_PR="${2:?missing promotion PR}"; shift 2;;
      --output) OUTPUT="${2:?missing output path}"; shift 2;;
      -h|--help) usage; exit 0;;
      *) echo "unknown option: $1" >&2; usage >&2; exit 2;;
    esac
  done
  [[ -n "$POD" && -n "$NAMESPACE" ]] || { usage >&2; exit 2; }
}

main() {
  parse_args "$@"
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/pm129-trace.XXXXXX")"
  local result_tmp="$WORK/result.json"
  local policy pod_json release_image release_digest child_digest service container_name
  local workflow_run workflow_attempt source_sha promotion_number promotion_merge_sha
  local source_pr_json promotion_pr_json manifest_json ecr_json trivy_dir cosign_json sbom_json apps_json

  if ! require_tools; then write_failure "$result_tmp"; return 1; fi
  policy="$(cat "$POLICY_FILE")"
  REPOSITORY="$(jq -r '.repository' <<<"$policy")"
  REGISTRY="$(jq -r '.registry' <<<"$policy")"
  IMAGE_REPOSITORY="$(jq -r '.imageRepository' <<<"$policy")"
  REGION="$(jq -r '.awsRegion' <<<"$policy")"
  WORKFLOW_PATH="$(jq -r '.workflowPath' <<<"$policy")"
  OIDC_ISSUER="$(jq -r '.oidcIssuer' <<<"$policy")"
  OIDC_IDENTITY="$(jq -r '.oidcIdentity' <<<"$policy")"

  if ! run_json pod "$WORK/pod.json" kubectl get pod "$POD" -n "$NAMESPACE" -o json; then write_failure "$result_tmp"; return 1; fi
  pod_json="$(cat "$WORK/pod.json")"
  local image_count
  image_count="$(jq '[.spec.containers[] | select(.image | contains("@sha256:"))] | length' <<<"$pod_json")"
  [[ "$image_count" -ge 1 ]] || { fail_step pod "pod has no immutable release image"; write_failure "$result_tmp"; return 1; }
  if [[ -n "$CONTAINER" ]]; then
    container_name="$CONTAINER"
    release_image="$(jq -r --arg c "$CONTAINER" '.spec.containers[] | select(.name==$c) | .image' <<<"$pod_json" | head -1)"
    child_digest="$(jq -r --arg c "$CONTAINER" '.status.containerStatuses[] | select(.name==$c) | .imageID' <<<"$pod_json" | head -1 | sed -E 's#^.*@##')"
  else
    [[ "$image_count" -eq 1 ]] || { fail_step pod "multiple immutable release images; pass --container"; write_failure "$result_tmp"; return 1; }
    container_name="$(jq -r '[.spec.containers[] | select(.image | contains("@sha256:"))][0].name' <<<"$pod_json")"
    release_image="$(jq -r '[.spec.containers[] | select(.image | contains("@sha256:"))][0].image' <<<"$pod_json")"
    child_digest="$(jq -r --arg c "$container_name" '.status.containerStatuses[] | select(.name==$c) | .imageID' <<<"$pod_json" | head -1 | sed -E 's#^.*@##')"
  fi
  release_image="${release_image//$'\n'/}"
  [[ "$release_image" == "${REGISTRY}/${IMAGE_REPOSITORY}@sha256:"* ]] \
    || { fail_step pod "release image is outside the trusted ECR repository"; write_failure "$result_tmp"; return 1; }
  release_digest="${release_image##*@}"
  validate_hex_digest "$release_digest" || { fail_step pod "release image digest is invalid"; write_failure "$result_tmp"; return 1; }
  validate_hex_digest "$child_digest" || { fail_step pod "runtime imageID has no valid child digest"; write_failure "$result_tmp"; return 1; }
  service="$(jq -r '.metadata.labels["opentelemetry.io/name"] // .metadata.labels["app.kubernetes.io/name"] // .metadata.labels.app // empty' <<<"$pod_json")"
  [[ -n "$service" ]] || service="$container_name"
  if ! run_json image-manifest "$WORK/manifest.json" docker buildx imagetools inspect --raw "$release_image"; then write_failure "$result_tmp"; return 1; fi
  manifest_json="$(cat "$WORK/manifest.json")"
  # `any()` is required, not a bare `.manifests[]?.digest == $child` stream: `jq -e`
  # only checks the LAST emitted value of a stream, and the index always lists
  # attestation manifests (architecture "unknown") after the real platform
  # manifests, so the bare form failed closed on every run regardless of whether
  # an earlier entry matched. Some container runtimes (confirmed: containerd
  # 2.2.4 on EKS 1.35/AL2023) also report a digest-pinned pod's imageID as the
  # release index digest itself rather than resolving to the child platform
  # manifest, so accept that as equivalent proof of provenance too.
  jq -e --arg child "$child_digest" '[.manifests[]?.digest] | any(. == $child)' <<<"$manifest_json" >/dev/null \
    || [[ "$child_digest" == "$release_digest" ]] \
    || { fail_step image-manifest "runtime child digest is neither a member of the release index nor equal to the index digest"; write_failure "$result_tmp"; return 1; }

  if ! run_json ecr "$WORK/ecr.json" aws ecr describe-images --repository-name "$IMAGE_REPOSITORY" --image-ids "imageDigest=$release_digest" --region "$REGION" --output json; then write_failure "$result_tmp"; return 1; fi
  ecr_json="$(cat "$WORK/ecr.json")"
  local tag_json
  tag_json="$(jq -c --arg service "$service" '[.imageDetails[0].imageTags[]? | select(test("-[0-9]+-" + $service + "$"))]' <<<"$ecr_json")"
  [[ "$(jq length <<<"$tag_json")" -ge 1 ]] || { fail_step ecr "no immutable run tag maps to service ${service}"; write_failure "$result_tmp"; return 1; }
  local run_ids
  run_ids="$(jq -c --arg service "$service" 'map(capture("-(?<run>[0-9]+)-" + $service + "$").run) | unique' <<<"$tag_json")"
  [[ "$(jq length <<<"$run_ids")" -eq 1 ]] || { fail_step ecr "release digest maps to multiple workflow runs"; write_failure "$result_tmp"; return 1; }
  workflow_run="$(jq -r '.[0] | capture("-(?<run>[0-9]+)-" + $service + "$").run' --arg service "$service" <<<"$tag_json")"
  workflow_attempt="$(jq -r '.[0] | capture("-(?<run>[0-9]+)-" + $service + "$").run' --arg service "$service" <<<"$tag_json")"
  if ! run_json workflow-run "$WORK/run.json" gh api "repos/${REPOSITORY}/actions/runs/${workflow_run}"; then write_failure "$result_tmp"; return 1; fi
  local run_json_data
  run_json_data="$(cat "$WORK/run.json")"
  [[ "$(jq -r '.path' <<<"$run_json_data")" == "$WORKFLOW_PATH" && "$(jq -r '.head_branch' <<<"$run_json_data")" == "main" && "$(jq -r '.conclusion' <<<"$run_json_data")" == "success" ]] \
    || { fail_step workflow-run "workflow run is not the trusted successful main build"; write_failure "$result_tmp"; return 1; }
  workflow_attempt="$(jq -r '.run_attempt' <<<"$run_json_data")"
  source_sha="$(jq -r '.head_sha' <<<"$run_json_data")"
  [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || { fail_step workflow-run "workflow source SHA is invalid"; write_failure "$result_tmp"; return 1; }

  rm -rf "$WORK/approved" "$WORK/promotion" "$WORK/trivy"
  mkdir -p "$WORK/approved" "$WORK/promotion" "$WORK/trivy"
  gh run download "$workflow_run" -R "$REPOSITORY" -n "approved-images-${workflow_run}-${workflow_attempt}" -D "$WORK/approved" >/dev/null 2>"$WORK/approved.err" \
    || { fail_step approved-artifact "cannot download exact approved-images artifact: $(tail -1 "$WORK/approved.err")"; write_failure "$result_tmp"; return 1; }
  local approved_file
  approved_file="$(find "$WORK/approved" -type f -name approved-images.json -print -quit)"
  [[ -n "$approved_file" && "$(find "$WORK/approved" -type f -name approved-images.json | wc -l)" -eq 1 ]] || { fail_step approved-artifact "artifact must contain exactly one approved-images.json"; write_failure "$result_tmp"; return 1; }
  run_json approved-manifest "$WORK/approved.json" cat "$approved_file" || { write_failure "$result_tmp"; return 1; }
  jq -e --arg sha "$source_sha" --arg digest "$release_digest" --arg service "$service" --arg run "$workflow_run" --arg attempt "$workflow_attempt" '.sourceSha==$sha and (.workflowRunId|tostring)==$run and (.workflowRunAttempt|tostring)==$attempt and any(.services[]; .name==$service and .digest==$digest)' "$WORK/approved.json" >/dev/null \
    || { fail_step approved-manifest "source SHA, service, or release digest mismatch"; write_failure "$result_tmp"; return 1; }

  local source_candidates
  source_candidates="$(gh pr list -R "$REPOSITORY" --state merged --search "$source_sha" --json number,url,author,mergedAt,mergeCommit,headRefOid,baseRefName)" \
    || { fail_step source-pr "gh pr list failed"; write_failure "$result_tmp"; return 1; }
  local source_number
  source_number="$SOURCE_PR"
  if [[ -z "$source_number" ]]; then
    source_number="$(jq -r --arg sha "$source_sha" '[.[] | select(.baseRefName=="main" and (.mergeCommit.oid==$sha or .headRefOid==$sha))] | if length==1 then .[0].number else empty end' <<<"$source_candidates")"
  fi
  [[ "$source_number" =~ ^[0-9]+$ ]] || { fail_step source-pr "source SHA does not resolve to exactly one merged main PR; pass --source-pr"; write_failure "$result_tmp"; return 1; }
  review_pr "$source_number" "$(jq -r --arg n "$source_number" '.[] | select((.number|tostring)==$n) | .author.login' <<<"$source_candidates" | head -1)" main "$WORK/source-pr.json" \
    || { write_failure "$result_tmp"; return 1; }
  jq -e --arg sha "$source_sha" '.mergeCommit==$sha or .headCommit==$sha' "$WORK/source-pr.json" >/dev/null \
    || { fail_step source-pr "source PR does not contain the trusted source SHA"; write_failure "$result_tmp"; return 1; }

  gh run download "$workflow_run" -R "$REPOSITORY" -n "promotion-evidence-${workflow_run}-${workflow_attempt}" -D "$WORK/promotion" >/dev/null 2>"$WORK/promotion.err" \
    || { fail_step promotion-artifact "cannot download exact promotion evidence: $(tail -1 "$WORK/promotion.err")"; write_failure "$result_tmp"; return 1; }
  local promotion_file
  promotion_file="$(find "$WORK/promotion" -type f -name promotion-evidence.json -print -quit)"
  [[ -n "$promotion_file" && "$(find "$WORK/promotion" -type f -name promotion-evidence.json | wc -l)" -eq 1 ]] || { fail_step promotion-artifact "artifact must contain exactly one promotion-evidence.json"; write_failure "$result_tmp"; return 1; }
  run_json promotion-manifest "$WORK/promotion.json" cat "$promotion_file" || { write_failure "$result_tmp"; return 1; }
  promotion_number="$(jq -r '.promotionPr.number' "$WORK/promotion.json")"
  [[ -z "$PROMOTION_PR" || "$PROMOTION_PR" == "$promotion_number" ]] || { fail_step promotion-manifest "--promotion-pr does not match artifact"; write_failure "$result_tmp"; return 1; }
  jq -e --arg sha "$source_sha" --arg digest "$release_digest" --arg service "$service" --arg run "$workflow_run" --arg attempt "$workflow_attempt" '.sourceSha==$sha and (.workflowRunId|tostring)==$run and (.workflowRunAttempt|tostring)==$attempt and any(.services[]; .name==$service and .digest==$digest) and .promotionPr.base=="main" and .promotionPr.state=="OPEN"' "$WORK/promotion.json" >/dev/null \
    || { fail_step promotion-manifest "promotion evidence does not match source/release"; write_failure "$result_tmp"; return 1; }
  promotion_number="${PROMOTION_PR:-$promotion_number}"
  run_json promotion-pr "$WORK/promotion-pr.json" gh api "repos/${REPOSITORY}/pulls/${promotion_number}" || { write_failure "$result_tmp"; return 1; }
  promotion_pr_json="$(cat "$WORK/promotion-pr.json")"
  [[ "$(jq -r '.merged' <<<"$promotion_pr_json")" == true && "$(jq -r '.base.ref' <<<"$promotion_pr_json")" == main ]] || { fail_step promotion-pr "promotion PR is not merged into main"; write_failure "$result_tmp"; return 1; }
  jq -e --arg head "$(jq -r '.promotionPr.headSha' "$WORK/promotion.json")" '.head.sha==$head' <<<"$promotion_pr_json" >/dev/null \
    || { fail_step promotion-pr "promotion PR head does not match promotion evidence"; write_failure "$result_tmp"; return 1; }
  promotion_merge_sha="$(jq -r '.merge_commit_sha' <<<"$promotion_pr_json")"
  review_pr "$promotion_number" "$(jq -r '.user.login' <<<"$promotion_pr_json")" main "$WORK/promotion-reviewed.json" || { write_failure "$result_tmp"; return 1; }

  gh run download "$workflow_run" -R "$REPOSITORY" -n "trivy-post-push-${workflow_run}-${service}" -D "$WORK/trivy" >/dev/null 2>"$WORK/trivy.err" \
    || { fail_step trivy "cannot download exact post-push Trivy artifact: $(tail -1 "$WORK/trivy.err")"; write_failure "$result_tmp"; return 1; }
  local trivy_file trivy_count
  for platform in amd64 arm64; do
    trivy_count="$(find "$WORK/trivy" -type f -name "${service}-linux-${platform}.json" | wc -l)"
    [[ "$trivy_count" -eq 1 ]] || { fail_step trivy "expected exactly one ${platform} Trivy report"; write_failure "$result_tmp"; return 1; }
  done
  local trivy_files
  trivy_files="$(find "$WORK/trivy" -type f -name "${service}-linux-*.json" | sort)"
  while IFS= read -r trivy_file; do
    jq -e --arg digest "$release_digest" '([.ArtifactName // "", .ArtifactDigest // ""] + [.Metadata.RepoDigests[]? // ""]) | any(contains($digest))' "$trivy_file" >/dev/null \
      || { fail_step trivy "report does not identify the approved release digest: $trivy_file"; write_failure "$result_tmp"; return 1; }
    jq -e '[.Results[]?.Vulnerabilities[]?.Severity] | any(. == "HIGH" or . == "CRITICAL") | not' "$trivy_file" >/dev/null \
      || { fail_step trivy "HIGH/CRITICAL vulnerability in $trivy_file"; write_failure "$result_tmp"; return 1; }
  done < <(find "$WORK/trivy" -type f -name "${service}-linux-*.json" | sort)

  local release_ref="$REGISTRY/$IMAGE_REPOSITORY@$release_digest"
  cosign verify --output json --certificate-oidc-issuer "$OIDC_ISSUER" --certificate-identity "$OIDC_IDENTITY" "$release_ref" > "$WORK/cosign.json" 2>"$WORK/cosign.err" \
    || { fail_step cosign "cosign verify failed: $(tail -1 "$WORK/cosign.err")"; write_failure "$result_tmp"; return 1; }
  cosign_json="$(cat "$WORK/cosign.json")"
  jq -e --arg issuer "$OIDC_ISSUER" --arg identity "$OIDC_IDENTITY" '((if type=="array" then . else [.] end)[] | .optional // {}) | select(.Issuer==$issuer and .Subject==$identity)' <<<"$cosign_json" >/dev/null \
    || { fail_step cosign "signature identity/issuer does not match policy"; write_failure "$result_tmp"; return 1; }

  local node_name node_arch platform child_ref
  node_name="$(jq -r '.spec.nodeName // empty' <<<"$pod_json")"
  [[ -n "$node_name" ]] || { fail_step pod "pod is not scheduled on a node"; write_failure "$result_tmp"; return 1; }
  if ! run_json node "$WORK/node.json" kubectl get node "$node_name" -o json; then write_failure "$result_tmp"; return 1; fi
  node_arch="$(jq -r '.status.nodeInfo.architecture // empty' "$WORK/node.json")"
  [[ "$node_arch" == amd64 || "$node_arch" == arm64 ]] || { fail_step pod "unsupported node architecture: ${node_arch:-unknown}"; write_failure "$result_tmp"; return 1; }
  platform="linux/$node_arch"
  child_ref="$REGISTRY/$IMAGE_REPOSITORY@$child_digest"
  python3 "$SCRIPT_DIR/get-sbom.py" --no-login --metadata --platform "$platform" "$child_ref" > "$WORK/sbom.json" 2>"$WORK/sbom.err" \
    || { fail_step sbom "trusted SBOM lookup failed: $(tail -1 "$WORK/sbom.err")"; write_failure "$result_tmp"; return 1; }
  sbom_json="$(cat "$WORK/sbom.json")"
  jq -e --arg sha "$source_sha" --arg child "$child_digest" '.predicateType=="https://cyclonedx.org/bom" and (.predicate.metadata.properties | from_entries) as $p | ($p["techx.sourceSha"]==$sha and $p["techx.subjectDigest"]==$child)' <<<"$sbom_json" >/dev/null \
    || { fail_step sbom "SBOM is not bound to source SHA and runtime child digest"; write_failure "$result_tmp"; return 1; }

  if ! run_json argo "$WORK/apps.json" kubectl get applications.argoproj.io -A -o json; then write_failure "$result_tmp"; return 1; fi
  apps_json="$(cat "$WORK/apps.json")"
  local matching_apps app_count argo_revision
  matching_apps="$(jq -c --arg repo "$REPOSITORY" --arg ns "$NAMESPACE" '[.items[] | ((.spec.source.repoURL // "") as $url | (.spec.sources[]?.repoURL // $url)) as $source | select(($source==("https://github.com/"+$repo) or $source==("https://github.com/"+$repo+".git") or $source==("git@github.com:"+$repo+".git")) and (.spec.destination.namespace==$ns or .spec.destination.namespace=="techx-tf3"))]' <<<"$apps_json")"
  app_count="$(jq 'length' <<<"$matching_apps")"
  [[ "$app_count" -eq 1 ]] || { fail_step argo "expected exactly one matching Argo application"; write_failure "$result_tmp"; return 1; }
  jq -e '.[0] | .status.sync.status=="Synced" and .status.health.status=="Healthy"' <<<"$matching_apps" >/dev/null \
    || { fail_step argo "Argo application is not Healthy/Synced"; write_failure "$result_tmp"; return 1; }
  argo_revision="$(jq -r '.[0].status.sync.revision // empty' <<<"$matching_apps")"
  [[ "$argo_revision" =~ ^[0-9a-f]{40}$ ]] \
    || { fail_step argo "Argo sync revision is not a valid commit SHA"; write_failure "$result_tmp"; return 1; }
  # ArgoCD tracks main HEAD with auto-sync + selfHeal, so unrelated commits keep
  # landing on main after this promotion merges. The live revision will almost
  # never equal the promotion SHA exactly — what must hold is that the promoted
  # commit is included in (an ancestor of, or equal to) what is currently synced.
  run_json argo-ancestry "$WORK/argo-compare.json" gh api "repos/${REPOSITORY}/compare/${promotion_merge_sha}...${argo_revision}" \
    || { write_failure "$result_tmp"; return 1; }
  jq -e '.status=="ahead" or .status=="identical"' "$WORK/argo-compare.json" >/dev/null \
    || { fail_step argo "promotion merge SHA is not an ancestor of the current Argo revision"; write_failure "$result_tmp"; return 1; }

  jq -n --arg pod "$POD" --arg namespace "$NAMESPACE" --arg container "$container_name" \
    --arg service "$service" --arg release "$release_ref" --arg index "$release_digest" --arg child "$child_digest" \
    --arg source_sha "$source_sha" --arg source_pr "$source_number" --arg promotion_pr "$promotion_number" \
    --arg promotion_sha "$promotion_merge_sha" --arg argo_revision "$argo_revision" --arg run "$workflow_run" --arg attempt "$workflow_attempt" \
    --arg issuer "$OIDC_ISSUER" --arg identity "$OIDC_IDENTITY" \
    '{schemaVersion:1,overallResult:"PASS",generatedAt:(now|todateiso8601),pod:$pod,namespace:$namespace,container:$container,service:$service,
      runtime:{releaseImage:$release,indexDigest:$index,childDigest:$child},
      build:{workflowRunId:$run,workflowRunAttempt:$attempt,sourceSha:$source_sha},
      review:{sourcePr:$source_pr,promotionPr:$promotion_pr,promotionMergeSha:$promotion_sha},
      scans:{trivy:"PASS",cosign:"PASS",sbom:"PASS"},signature:{issuer:$issuer,identity:$identity},
      gitops:{promotionRevision:$promotion_sha,argoRevision:$argo_revision,promotionIsAncestor:true,status:"Healthy/Synced"}}' > "$result_tmp"
  mkdir -p -- "$(dirname -- "$OUTPUT")"
  mv -f -- "$result_tmp" "$OUTPUT"
  cat "$OUTPUT"
}

if ! main "$@"; then
  [[ -n "$WORK" ]] || WORK="$(mktemp -d "${TMPDIR:-/tmp}/pm129-trace-fail.XXXXXX")"
  write_failure "$WORK/result.json"
  cat "$OUTPUT" >&2
  exit 1
fi

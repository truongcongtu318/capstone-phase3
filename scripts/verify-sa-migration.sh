#!/usr/bin/env bash
# verify-sa-migration.sh
# Dùng sau mỗi helm upgrade khi migrate ServiceAccount cho 1 service.
#
# Usage:
#   ./scripts/verify-sa-migration.sh <service-name>
#
# Ví dụ:
#   ./scripts/verify-sa-migration.sh image-provider
#   ./scripts/verify-sa-migration.sh checkout
#   ./scripts/verify-sa-migration.sh kafka
#
# Special cases handled:
#   checkout → dùng Argo Rollouts (replicasManagedExternally), script
#              kiểm tra Rollout object thay vì Deployment.
#   kafka    → strategy: Recreate, có thể mất kết nối ngắn trong rollout.
#              Script warn thay vì fail nếu có producer error.
#
# Exit code:
#   0 = tất cả kiểm tra pass → an toàn migrate service tiếp theo
#   1 = có kiểm tra fail → dừng, xem log, cân nhắc rollback

set -euo pipefail

SERVICE="${1:-}"
NS="techx-tf3"
EXPECTED_SA="techx-${SERVICE}"
ROLLOUT_NAME="${SERVICE}-rollout"

# Services dùng Argo Rollouts (replicasManagedExternally)
ARGO_ROLLOUT_SERVICES=("checkout")
# Services dùng strategy: Recreate (stateful, cần downtime ngắn)
RECREATE_SERVICES=("kafka")

# ── màu sắc ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass()  { echo -e "${GREEN}[PASS]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
info()  { echo -e "       $*"; }

is_argo_rollout() {
  local svc="$1"
  for s in "${ARGO_ROLLOUT_SERVICES[@]}"; do
    [[ "$s" == "$svc" ]] && return 0
  done
  return 1
}

is_recreate() {
  local svc="$1"
  for s in "${RECREATE_SERVICES[@]}"; do
    [[ "$s" == "$svc" ]] && return 0
  done
  return 1
}

if [[ -z "$SERVICE" ]]; then
  echo "Usage: $0 <service-name>"
  echo "Example: $0 image-provider"
  exit 1
fi

echo ""
echo "════════════════════════════════════════════"
echo " SA Migration Verify: ${SERVICE}"
echo " Namespace: ${NS}"
echo " Expected SA: ${EXPECTED_SA}"
if is_argo_rollout "$SERVICE"; then
  echo " Mode: Argo Rollouts (replicasManagedExternally)"
fi
if is_recreate "$SERVICE"; then
  echo " Mode: Recreate strategy (stateful pod)"
fi
echo "════════════════════════════════════════════"
echo ""

ERRORS=0

# ── CHECK 1: SA đã được tạo ───────────────────────────────────────────────
echo "▶ CHECK 1: ServiceAccount '${EXPECTED_SA}' tồn tại"
if kubectl get sa "${EXPECTED_SA}" -n "${NS}" &>/dev/null; then
  pass "SA '${EXPECTED_SA}' tồn tại"
  AUTOMOUNT=$(kubectl get sa "${EXPECTED_SA}" -n "${NS}" \
    -o jsonpath='{.automountServiceAccountToken}' 2>/dev/null || echo "null")
  if [[ "$AUTOMOUNT" == "false" ]]; then
    pass "automountServiceAccountToken = false"
  else
    warn "automountServiceAccountToken = ${AUTOMOUNT} (mong đợi: false)"
  fi
else
  fail "SA '${EXPECTED_SA}' KHÔNG tồn tại — helm upgrade có thể chưa apply"
  ERRORS=$((ERRORS+1))
fi
echo ""

# ── CHECK 2: Rollout hoàn thành ───────────────────────────────────────────
echo "▶ CHECK 2: Rollout status"
if is_argo_rollout "$SERVICE"; then
  warn "checkout dùng Argo Rollouts — kiểm tra Rollout object thay vì Deployment"

  # Kiểm tra SA trong Rollout spec
  ROLLOUT_SA=$(kubectl get rollout "${ROLLOUT_NAME}" -n "${NS}" \
    -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || echo "NOTFOUND")

  if [[ "$ROLLOUT_SA" == "$EXPECTED_SA" ]]; then
    pass "Rollout spec đã dùng SA: ${ROLLOUT_SA}"
  else
    fail "Rollout spec vẫn dùng SA: '${ROLLOUT_SA}' (mong đợi: '${EXPECTED_SA}')"
    info "Cần patch Rollout thủ công:"
    info "  kubectl -n ${NS} patch rollout ${ROLLOUT_NAME} \\"
    info "    --type=merge -p '{\"spec\":{\"template\":{\"spec\":{\"serviceAccountName\":\"${EXPECTED_SA}\"}}}}'"
    ERRORS=$((ERRORS+1))
  fi

  # Kiểm tra rollout phase
  ROLLOUT_PHASE=$(kubectl get rollout "${ROLLOUT_NAME}" -n "${NS}" \
    -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
  if [[ "$ROLLOUT_PHASE" == "Healthy" || "$ROLLOUT_PHASE" == "Paused" ]]; then
    pass "Rollout phase: ${ROLLOUT_PHASE}"
  else
    warn "Rollout phase: ${ROLLOUT_PHASE} (mong đợi: Healthy)"
  fi
else
  if kubectl rollout status deploy/"${SERVICE}" -n "${NS}" --timeout=120s 2>&1; then
    pass "Deploy '${SERVICE}' rolled out thành công"
  else
    fail "Deploy '${SERVICE}' rollout TIMEOUT hoặc FAILED"
    ERRORS=$((ERRORS+1))
  fi
fi
echo ""

# ── CHECK 3: Pod đang dùng đúng SA ────────────────────────────────────────
echo "▶ CHECK 3: Pod đang dùng ServiceAccount đúng"
ACTUAL_SA=$(kubectl get pod -n "${NS}" \
  -l "opentelemetry.io/name=${SERVICE}" \
  -o jsonpath='{.items[0].spec.serviceAccountName}' 2>/dev/null || echo "NOTFOUND")

if [[ "$ACTUAL_SA" == "$EXPECTED_SA" ]]; then
  pass "Pod dùng SA: ${ACTUAL_SA}"
else
  fail "Pod dùng SA: '${ACTUAL_SA}' (mong đợi: '${EXPECTED_SA}')"
  ERRORS=$((ERRORS+1))
fi
echo ""

# ── CHECK 4: Token KHÔNG được mount ──────────────────────────────────────
echo "▶ CHECK 4: SA token KHÔNG mount trong pod"
TOKEN_CHECK=$(kubectl exec -n "${NS}" \
  "$(kubectl get pod -n "${NS}" -l "opentelemetry.io/name=${SERVICE}" \
     -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)" -- \
  ls /var/run/secrets/kubernetes.io/serviceaccount/ 2>&1 || true)

if echo "$TOKEN_CHECK" | grep -qiE "No such file|cannot access|not found"; then
  pass "Token không mount — đúng hành vi mong muốn"
else
  warn "Token có thể vẫn đang mount. Output: ${TOKEN_CHECK}"
  warn "Kiểm tra: automountServiceAccountToken phải là false trong SA object"
fi
echo ""

# ── CHECK 5: Không có lỗi 403/401 trong log ──────────────────────────────
echo "▶ CHECK 5: Không có lỗi 403/401 trong log gần nhất"
# Capture the effective authorization list required by T10, then fail closed
# on representative workload API permissions. Kubernetes discovery entries in
# `--list` are expected and are not workload privileges.
echo "▶ AUTHORIZATION: kubectl auth can-i --list"
SA_SUBJECT="system:serviceaccount:${NS}:${EXPECTED_SA}"
kubectl auth can-i --list --as="${SA_SUBJECT}" -n "${NS}"

for check in \
  "get pods" \
  "get secrets" \
  "list secrets" \
  "patch deployments.apps" \
  "create pods/exec"; do
  read -r verb resource <<<"${check}"
  if [[ "$(kubectl auth can-i "${verb}" "${resource}" --as="${SA_SUBJECT}" -n "${NS}")" == "yes" ]]; then
    fail "${SA_SUBJECT} can ${verb} ${resource}; expected no workload API permission"
    ERRORS=$((ERRORS+1))
  else
    pass "${SA_SUBJECT} cannot ${verb} ${resource}"
  fi
done
echo ""

LOG_ERRORS=$(kubectl logs -n "${NS}" \
  "$(kubectl get pod -n "${NS}" -l "opentelemetry.io/name=${SERVICE}" \
     -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)" \
  --tail=100 2>/dev/null | \
  grep -iE "403|401|Forbidden|Unauthorized|permission denied" || true)

if [[ -z "$LOG_ERRORS" ]]; then
  pass "Không tìm thấy 403/401/Forbidden/Unauthorized trong 100 dòng log gần nhất"
else
  if is_recreate "$SERVICE"; then
    warn "Phát hiện errors trong log (có thể do gap Recreate, kiểm tra thêm):"
  else
    fail "Phát hiện lỗi trong log:"
    ERRORS=$((ERRORS+1))
  fi
  echo "$LOG_ERRORS" | while IFS= read -r line; do
    info "  $line"
  done
fi
echo ""

# ── CHECK 6: Pod restart count ───────────────────────────────────────────
echo "▶ CHECK 6: Pod restart count"
RESTART_COUNT=$(kubectl get pod -n "${NS}" \
  -l "opentelemetry.io/name=${SERVICE}" \
  -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo "0")

if [[ "$RESTART_COUNT" -eq 0 ]]; then
  pass "Restart count = 0"
elif [[ "$RESTART_COUNT" -le 2 ]]; then
  warn "Restart count = ${RESTART_COUNT} (có thể là restart từ trước khi migrate)"
  warn "Chi tiết: kubectl describe pod -n ${NS} -l opentelemetry.io/name=${SERVICE}"
else
  fail "Restart count = ${RESTART_COUNT} — có thể pod đang crash sau migrate"
  ERRORS=$((ERRORS+1))
fi
echo ""

# ── CHECK 7: Đặc biệt cho kafka ──────────────────────────────────────────
if is_recreate "$SERVICE"; then
  echo "▶ CHECK 7 (kafka): Broker đã available trở lại"
  # Kiểm tra consumer group lag
  KAFKA_POD=$(kubectl get pod -n "${NS}" -l "opentelemetry.io/name=kafka" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
  if [[ -n "$KAFKA_POD" ]]; then
    KAFKA_LAG=$(kubectl exec -n "${NS}" "${KAFKA_POD}" -- \
      sh -c "KAFKA_OPTS='' /opt/kafka/bin/kafka-consumer-groups.sh \
        --bootstrap-server localhost:9092 \
        --describe --group accounting 2>/dev/null | grep orders" || true)
    if [[ -n "$KAFKA_LAG" ]]; then
      pass "Kafka consumer group accounting respond được"
      info "Consumer lag: ${KAFKA_LAG}"
    else
      warn "Kafka consumer group chưa respond — có thể đang warm up, kiểm tra lại sau 30s"
    fi
  fi
  echo ""
fi

# ── CHECK 8: Đặc biệt cho flagd ──────────────────────────────────────────
if [[ "$SERVICE" == "flagd" ]]; then
  echo "▶ CHECK 8 (flagd): BTC sync token vẫn hoạt động"
  FLAGD_LOG=$(kubectl logs -n "${NS}" deploy/flagd --tail=30 2>/dev/null || true)
  if echo "$FLAGD_LOG" | grep -qi "sync"; then
    pass "flagd log có sync activity — BTC endpoint vẫn kết nối được"
  else
    warn "Không thấy sync log — kiểm tra thêm: kubectl logs deploy/flagd -n ${NS} --tail=50"
  fi
  if echo "$FLAGD_LOG" | grep -qiE "auth.*error|connection refused|bearer.*fail"; then
    fail "flagd có dấu hiệu lỗi sync với BTC endpoint"
    ERRORS=$((ERRORS+1))
  else
    pass "Không có lỗi sync BTC trong log"
  fi
  echo ""
fi

# ── CHECK 9: Smoke test storefront ───────────────────────────────────────
# Chỉ chạy sau khi migrate frontend, frontend-proxy, checkout, cart, product-catalog
CRITICAL_SERVICES=("frontend" "frontend-proxy" "checkout" "cart" "product-catalog" "payment")
for cs in "${CRITICAL_SERVICES[@]}"; do
  if [[ "$SERVICE" == "$cs" ]]; then
    echo "▶ CHECK 9: Smoke test storefront (service '${SERVICE}' là critical path)"
    # Kiểm tra port-forward đang chạy không
    if curl -s -o /dev/null -w "%{http_code}" \
        http://localhost:8080/api/products --max-time 5 2>/dev/null | grep -q "200"; then
      pass "GET /api/products → 200 OK"
    else
      warn "GET /api/products không trả 200 — đảm bảo port-forward đang chạy:"
      info "  kubectl -n ${NS} port-forward svc/frontend-proxy 8080:8080"
      info "  Sau đó re-run script này để verify"
    fi
    echo ""
    break
  fi
done

# ── KẾT QUẢ ──────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════"
if [[ "$ERRORS" -eq 0 ]]; then
  echo -e "${GREEN}✅ TẤT CẢ KIỂM TRA PASS — An toàn migrate service tiếp theo${NC}"
  echo ""
  echo "Next steps:"
  echo "  1. Uncomment service tiếp theo trong deploy/values-serviceaccounts.yaml"
  echo "  2. helm upgrade ... -f deploy/values-prod.yaml -f deploy/values-serviceaccounts.yaml"
  echo "  3. ./scripts/verify-sa-migration.sh <service-tiep-theo>"
  exit 0
else
  echo -e "${RED}❌ CÓ ${ERRORS} KIỂM TRA FAIL — DỪNG migration, xem log${NC}"
  echo ""
  echo "Rollback options:"
  echo "  # Option A: Rollback toàn bộ helm release"
  echo "  helm rollback techx-corp -n ${NS}"
  echo ""
  echo "  # Option B: Rollback chỉ service này"
  echo "  # Xóa serviceAccount block của '${SERVICE}' khỏi values-serviceaccounts.yaml"
  echo "  # helm upgrade ... -f deploy/values-prod.yaml -f deploy/values-serviceaccounts.yaml"
  exit 1
fi

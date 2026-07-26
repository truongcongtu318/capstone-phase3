# Kế hoạch triển khai [MANDATE-19]: Biết trần & Nâng trần bằng hiệu suất

## Phạm vi PR và thứ tự

| PR | Branch | Nội dung | Phụ thuộc |
|---|---|---|---|
| **PM-153** | `feat/pm-153` | HPA tuning (65%→75%) + Envoy circuit_breakers + breakpoint test evidence | Không |
| **PM-154** | `feat/mandate-19` | Route classification + `local_ratelimit` shadow mode | PM-153 evidence cần cho token bucket |
| **PM-154b** | (PR riêng sau shadow pass) | Flip `filter_enforced` 0%→100% + điền `max_tokens` từ PM-153 | PM-154 shadow ≥ 5 phút pass |

---

## PM-153 — HPA Tuning + Breakpoint Discovery

### Thay đổi (branch `feat/pm-153`)

**`gitops/infrastructure/hpa-hotpath.yaml`:**

| HPA | CPU target | maxReplicas |
|---|---|---|
| `frontend-proxy-hpa` | 65% → **75%** | 8 (giữ) |
| `frontend-hpa` | 65% → **75%** | 8 → **12** |
| `product-catalog-hpa` | 65% → **75%** | 8 → **10** |
| `cart-hpa`, `checkout-hpa` | Giữ 65% | Giữ nguyên |

Lý do: mỗi pod gánh nhiều request hơn trước khi scale → requests-per-node density tăng mà không thêm node. Checkout/cart giữ 65% vì revenue-critical.

**`envoy.tmpl.yaml` — cluster `frontend`:**
```yaml
circuit_breakers:
  thresholds:
    - priority: DEFAULT
      max_connections: 1024
      max_pending_requests: 1024
      max_requests: 4096   # default 1024 → 4096
      max_retries: 3
```
Loại bỏ Envoy-level bottleneck trước khi backend thực sự cạn.

### Breakpoint Test Procedure (PM-153)

```bash
# Ramp up dần: 200 → 300 → 400 → 500 → 700 → 1000 user
# Giữ mỗi bậc 3-5 phút, quan sát signal gãy: p99 > 1000ms HOẶC error rate > 1%
kubectl -n techx-tf3 set env deploy/load-generator \
  LOCUST_USERS=300 LOCUST_SPAWN_RATE=30
kubectl -n techx-tf3 rollout restart deploy/load-generator

# Theo dõi
watch kubectl -n techx-tf3 get hpa
kubectl -n techx-tf3 top pod --sort-by=cpu
```

**Ghi lại (bắt buộc cho PM-154 token bucket):**

| Metric | Giá trị |
|---|---|
| Breakpoint user count | _(điền)_ |
| Browse breakpoint RPS | _(điền)_ |
| frontend-proxy Ready count tại breakpoint | _(điền)_ |
| `max_tokens` tính được = floor(0.70 × RPS / Ready) | _(tính)_ |
| Service bão hoà sớm nhất | _(điền)_ |
| p99 tại breakpoint | _(điền)_ |

---

## PM-154 — Route Classification + Load Shedding (Shadow Mode)

### Thay đổi (branch `feat/mandate-19`, PR hiện tại)

**`phase3 - information/techx-corp-platform/src/frontend-proxy/envoy.tmpl.yaml`:**

#### Route priority table

| Route | Name | Xử lý |
|---|---|---|
| `/api/checkout` | `checkout_protected` | Luôn forward — không shed |
| `/api/cart` | `cart_protected` | Luôn forward — không shed |
| `/api/products/<id>` | `product_detail_protected` | Luôn forward — không shed (checkout journey step 1) |
| `/` (catch-all) | `browse_shedable` | Token bucket — shed khi vượt ngưỡng |

Tại sao `/api/cart` protected: cart write là bước ngay trước checkout trong funnel. Shed cart = vô hiệu checkout protection gián tiếp.

#### local_ratelimit — shadow mode

```yaml
filter_enabled:  numerator: 100   # Đếm — stat tích lũy
filter_enforced: numerator: 0     # SHADOW: không reject, pass-through
token_bucket:
  max_tokens: 100           # Calibrated: 200users×2.5RPS/2pods=250/pod×0.70=~175
  tokens_per_fill: 100      # Counter tick ở 1.5× overload test (~112 RPS/pod)
                            # THAY bằng PM-153 evidence trước PM-154b enforce PR
```

- Mục đích shadow: quan sát `browse_rate_limiter.rate_limited` tăng tự nhiên trước khi flip enforce
- Response header `x-techx-load-shed: browse` chỉ active ở PM-154b (enforce mode)

#### Công thức token bucket (cho PM-154b)

```
max_tokens = floor(0.70 × browse_breakpoint_RPS / frontend-proxy-Ready-count)
```

Lấy `browse_breakpoint_RPS` và `frontend-proxy-Ready-count` từ PM-153 evidence.

### Pre-deploy Validation

> [!IMPORTANT]
> **Bắt buộc trước khi deploy PM-154 lên production:**

```bash
# 0. Envoy config validation (CI tự động qua .github/workflows/validate-envoy.yml)
# PR không thể merge nếu validate-envoy job fail. Kiểm tra status check trước merge.

# 1. Validate Envoy config (chạy local để debug nếu CI fail)
docker run --rm \
  -e ENVOY_ADDR=0.0.0.0 -e ENVOY_PORT=8080 -e ENVOY_ADMIN_PORT=9901 \
  -e OTEL_SERVICE_NAME=frontend-proxy \
  -e OTEL_COLLECTOR_HOST=otel -e OTEL_COLLECTOR_PORT_GRPC=4317 -e OTEL_COLLECTOR_PORT_HTTP=4318 \
  -e FRONTEND_HOST=frontend -e FRONTEND_PORT=8080 \
  -e IMAGE_PROVIDER_HOST=image-provider -e IMAGE_PROVIDER_PORT=8081 \
  -e FLAGD_HOST=flagd -e FLAGD_PORT=8013 -e FLAGD_UI_HOST=flagd-ui -e FLAGD_UI_PORT=4000 \
  -e LOCUST_WEB_HOST=loadgen -e LOCUST_WEB_PORT=8089 \
  -e GRAFANA_HOST=grafana -e GRAFANA_PORT=3000 \
  -e JAEGER_HOST=jaeger -e JAEGER_UI_PORT=16686 \
  --entrypoint /bin/sh envoyproxy/envoy:v1.34.10@sha256:3343a698c1bdfdbb174f1bd907dea789d728692f4f99a943e3e6f0bc5ef6513f \
  -c 'envsubst < /etc/envoy/envoy.yaml > /tmp/envoy-rendered.yaml && envoy --mode validate -c /tmp/envoy-rendered.yaml'
# → phải thấy "configuration ... OK"

# 2. Build + push frontend-proxy image (CI)
# Trigger workflow build-push-ecr.yml cho frontend-proxy sau khi merge PR
# Cập nhật values-prod.yaml imageOverride với tag mới

# 3. Verify filter đã load sau deploy
kubectl -n techx-tf3 exec deploy/frontend-proxy -c frontend-proxy -- \
  wget -qO- localhost:${ENVOY_ADMIN_PORT}/stats | grep -E "rate_limit|browse_rate"
# → phải thấy: local_rate_limiter.* và browse_rate_limiter.*
```

### Shadow Mode Validation (≥ 5 phút sustained overload)

```bash
# Đẩy tải vượt trần (dùng breakpoint × 1.5 từ PM-153)
kubectl -n techx-tf3 set env deploy/load-generator \
  LOCUST_USERS=<breakpoint_users * 1.5> LOCUST_SPAWN_RATE=30
kubectl -n techx-tf3 rollout restart deploy/load-generator

# Quan sát shadow counter (phải tăng nếu tải vượt max_tokens)
kubectl -n techx-tf3 exec deploy/frontend-proxy -c frontend-proxy -- \
  wget -qO- localhost:${ENVOY_ADMIN_PORT}/stats | grep browse_rate_limiter.rate_limited

# Xác nhận checkout KHÔNG bị ảnh hưởng trong shadow
# (không có 429, p99 checkout vẫn ổn)
```

Điều kiện pass shadow:
- `browse_rate_limiter.rate_limited` > 0 (counter tích lũy)
- Checkout success rate ≥ 99% trong shadow period
- Không có pod crash / OOM / restart

---

## PM-154b — Enforce Mode (PR riêng, sau shadow pass)

> [!CAUTION]
> Chỉ tạo PR này sau khi shadow đã pass ≥ 5 phút liên tục. Không merge cùng PM-154.

### Thay đổi

**`envoy.tmpl.yaml`** — 2 thay đổi:

```yaml
# 1. Flip enforced
filter_enforced:
  default_value:
    numerator: 100   # ← đổi từ 0 → 100

# 2. Điền token bucket từ PM-153 evidence
token_bucket:
  max_tokens: <floor(0.70 × browse_breakpoint_RPS / proxy_ready)>
  tokens_per_fill: <same>
```

### Demo xuống mềm (nộp mentor)

```bash
# Đẩy tải vượt trần
kubectl -n techx-tf3 set env deploy/load-generator \
  LOCUST_USERS=<breakpoint_users * 1.5> LOCUST_SPAWN_RATE=30

# Quan sát song song:
# 1. Browse: phải thấy 429 + header x-techx-load-shed: browse
curl -I https://<storefront>/
# → HTTP/1.1 429
# → x-techx-load-shed: browse

# 2. Checkout: phải vẫn 200
curl -X POST https://<storefront>/api/checkout -d '{...}'
# → HTTP/1.1 200

# 3. Hệ không sập (vẫn có request được phục vụ)
# Grafana: checkout success rate ≥ 99%, browse error rate > 0%
```

---

## Evidence Checklist (bắt buộc trước khi nộp mentor)

Lưu vào `docs/evidence/mandate-19/`:

- [ ] **Locust stats:** screenshot/CSV — RPS, error rate, breakpoint (PM-153)
- [ ] **Prometheus:** p99 trước/sau tuning, checkout rate, `browse_rate_limiter.rate_limited` (PM-154)
- [ ] **Envoy counter:** output của `wget /stats | grep rate_limit` trong shadow period
- [ ] **Jaeger trace:** 1 checkout trace (protected, 200) + 1 browse trace (429) khi enforce
- [ ] **Node timeline:** `kubectl get nodes` trước/sau — node count không đổi
- [ ] **Rollback evidence:** output của `kubectl rollout undo deploy/frontend-proxy` (nếu cần)

---

## Rollback

```bash
# Frontend-proxy (PM-154 revert)
kubectl -n techx-tf3 rollout undo deployment/frontend-proxy

# Hoặc đổi imageOverride về tag cũ và ArgoCD sync
# Tag cũ: xem values-prod.yaml components.frontend-proxy.imageOverride trước PR
```

---

## Tham chiếu

- [ADR 0011](adr/0011-mandate-19-throughput-ceiling-load-shedding.md)
- [envoy.tmpl.yaml](../phase3%20-%20information/techx-corp-platform/src/frontend-proxy/envoy.tmpl.yaml)
- [hpa-hotpath.yaml](../gitops/infrastructure/hpa-hotpath.yaml)
- [validate-envoy.yml](../.github/workflows/validate-envoy.yml)
- [Mandate-02 load test report](mandate-02-load-test-report.md)

# ADR 0011 — Mandate-19: Route Classification & Graduated Load Shedding

**Status:** Proposed
**Date:** 2026-07-23
**Author:** CDO-01 (TF3)
**Mandate:** Directive #19 — Biết trần của mình và nâng trần bằng hiệu suất
**Depends on:** PM-153 (HPA tuning + circuit_breakers + breakpoint evidence)

---

## Bối cảnh

Directive #19 yêu cầu xác định trần thông lượng thật của hệ, nâng trần bằng hiệu suất (không bằng node), xử nút thắt, và đảm bảo hệ **xuống mềm** (graceful degradation) khi vượt trần — ưu tiên checkout, shed load browse, không sập toàn bộ.

Hiện trạng:
- Mandate-02: 200 user pass (p95 ~46ms, checkout 99.98%), **breakpoint thật chưa được đo**
- Mandate-16: Checkout critical path song song hoá, latency 185ms → ~45ms
- Envoy hiện tại: một catch-all route `/` không phân loại traffic; không có cơ chế shed

---

## Phạm vi ADR này (PM-154)

ADR này chỉ ghi nhận quyết định **route classification** và **local_ratelimit** (Envoy-level load shedding). Các quyết định về:
- HPA CPU target tuning (65%→75%)
- Envoy circuit_breakers max_requests tăng
- Kết quả breakpoint test

→ ghi nhận trong **PM-153** (đã tách sang PR riêng).

---

## Quyết định

### 1. Route classification

Tách catch-all `/` thành 3 class ưu tiên rõ ràng:

| Route | Name | Ưu tiên | Rate limit |
|---|---|---|---|
| `/api/checkout` | `checkout_protected` | Tối cao | Không (global bucket 10 000/s — không bao giờ trigger) |
| `/api/cart` | `cart_protected` | Cao | Không (cùng global bucket) |
| `/api/products/<id>` | `product_detail_protected` | Cao | Không (cùng global bucket) |
| `/` (catch-all) | `browse_shedable` | Thấp | Token bucket per-pod (xem § 2) |

**Tại sao `/api/products/<id>` được bảo vệ:**
Locustfile `add_to_cart()` gọi `GET /api/products/<id>` trước `POST /api/cart`. Nếu product detail bị shed (429) → Locust cart add fail → checkout journey gãy. Prefix `/api/products/` (có trailing slash) chỉ match detail pages; `GET /api/products` (list, không có slash) vẫn rơi vào `browse_shedable`.

**Tại sao `/api/cart` được bảo vệ:**
Cart write operations (add/update/delete item) là bước ngay trước checkout trong user journey. Nếu cart bị shed trong khi checkout được phép, người dùng không thể hoàn thành đơn hàng → checkout protection bị vô nghĩa. Bảo vệ cả hai tạo ra "checkout funnel shield".

**Tại sao browse bị shed trước:**
Browse (homepage, product listing, search) là traffic khối lượng lớn, không phát sinh doanh thu trực tiếp. Đây là traffic đúng đắn để sacrifice khi hệ thống tiếp cận trần.

### 2. Cơ chế load shedding — Envoy `local_ratelimit`

**Lựa chọn:** `envoy.filters.http.local_ratelimit` (in-process token bucket)

**Lý do:**
- In-process trong Envoy → không cần Redis external, không thêm network hop, latency overhead ~0.01ms
- Per-route `typed_per_filter_config` → phân loại độc lập cho từng route class
- Stats counter `browse_rate_limiter.rate_limited` → có thể quan sát shadow mode trước khi enforce
- HTTP 429 + custom header → client và monitoring phân biệt được rate-limit response vs backend error

**Token bucket formula (per-pod, local_ratelimit là in-process):**
```
max_tokens = floor(0.70 × browse_breakpoint_RPS / frontend-proxy-Ready-count)
```

- `browse_breakpoint_RPS`: RPS browse tại điểm SLO gãy — **lấy từ PM-153 evidence**
- `frontend-proxy-Ready-count`: số pod frontend-proxy Ready tại thời điểm test (xem `kubectl get hpa frontend-proxy-hpa`)
- `0.70`: buffer 30% — shed bắt đầu trước khi đạt breakpoint 100% để có margin

Ví dụ (placeholder — điền sau PM-153):
```
breakpoint 400 RPS, 3 Ready pods:
max_tokens = floor(0.70 × 400 / 3) = 93 token/s/pod
```

**Hiện tại trong config: `max_tokens: 100`** — shadow threshold calibrated từ Mandate-02
baseline (200 users → ~150 browse RPS tổng / 2 proxy pod min ≈ 75 RPS/pod; counter tick
ở 1.5× overload test). filter_enforced=0% → không reject thực tế.

### 3. Deploy theo 2 giai đoạn — Shadow → Enforce

**Giai đoạn 1 (PR này — PM-154):** Shadow mode
```yaml
filter_enabled:  numerator: 100   # Đếm — stat tăng khi token bucket bị exceed
filter_enforced: numerator: 0     # KHÔNG reject — traffic pass-through 100%
```
Quan sát: `browse_rate_limiter.rate_limited` trên Envoy stats hoặc `envoy_local_rate_limiter_rate_limited` trên Prometheus.

**Giai đoạn 2 (PR riêng — PM-154b):** Enforce mode
```yaml
filter_enforced: numerator: 100   # Reject 429 khi vượt token bucket
token_bucket:
  max_tokens: <từ PM-153 evidence>
```
Điều kiện enforce: shadow đã chạy sustained ≥ 5 phút dưới overload, counter đã tích lũy, không có side effect.

### 4. Response header

Header `x-techx-load-shed: browse` được thêm vào response khi request bị shed.
- Không dùng `x-local-rate-limit` (tên Envoy-internal, không mang semantic của hệ)
- `x-techx-load-shed: browse` → client và load balancer biết đây là shed decision, không phải lỗi backend
- Header chỉ visible khi `filter_enforced > 0%` — sẽ active ở giai đoạn 2

---

## Pre-conditions (phải có trước khi enforce)

> [!IMPORTANT]
> PM-154 chỉ chuyển sang enforce sau khi tất cả điều kiện sau được thoả:

1. **PM-153 merged và evidence có sẵn:**
   - Breakpoint RPS đã đo (Locust + Prometheus)
   - `frontend-proxy-Ready-count` tại thời điểm test đã ghi lại
   - `max_tokens` đã tính theo công thức trên

2. **PM-154 shadow đã chạy live ≥ 5 phút sustained overload:**
   - `browse_rate_limiter.rate_limited` counter tăng > 0
   - Checkout/cart traffic không bị ảnh hưởng trong shadow period

3. **Frontend-proxy image đã được build và validate:**
   - `envoy --validate-config` pass
   - CI build-push-ecr.yml cho `frontend-proxy` thành công
   - `imageOverride` trong `values-prod.yaml` cập nhật tag mới

---

## Evidence cần lưu (mandatory)

| Evidence | Công cụ | Lưu tại |
|---|---|---|
| Locust stats (RPS, error rate, breakpoint) | Locust UI screenshot / CSV | `docs/evidence/mandate-19/` |
| Prometheus metrics (p99, checkout rate, browse rate_limited counter) | Grafana screenshot / promql export | `docs/evidence/mandate-19/` |
| Envoy counter (`browse_rate_limiter.rate_limited`) | `wget -qO- /stats \| grep rate_limit` | `docs/evidence/mandate-19/` |
| Jaeger trace (checkout protected, browse 429 path) | Jaeger screenshot | `docs/evidence/mandate-19/` |
| Node timeline (node count không đổi) | `kubectl get nodes` before/after | `docs/evidence/mandate-19/` |
| Rollback evidence | `kubectl rollout undo deploy/frontend-proxy` output | `docs/evidence/mandate-19/` |

---

## Trade-offs đã chấp nhận

| Trade-off | Lý do |
|---|---|
| Browse user bị 429 khi vượt trần | Mandate yêu cầu shed, không phải sập; checkout được bảo vệ |
| Token bucket per-pod (không global) | local_ratelimit in-process; tổng throughput = max_tokens × pod_count |
| Shadow mode trước → enforce sau | Giảm rủi ro production; có thể quan sát impact trước khi reject thật |
| max_tokens chưa có số thật | Phụ thuộc PM-153 evidence; shadow mode an toàn để deploy trước |
| `/api/cart` protected (rộng hơn chỉ checkout) | Cart writes là phần của checkout funnel — shed cart = shed checkout gián tiếp |

---

## Không thay đổi

- HPA targets / maxReplicas → PM-153
- Envoy circuit_breakers → PM-153
- flagd, `/flagservice/`, `/otlp-http/` routes
- Stateful services, Karpenter NodePool
- Topology prod (PDB, topologySpreadConstraints)

---

## Tham chiếu

- PM-153 (HPA + circuit_breakers): `feat/pm-153` branch
- [Mandate-02 load test report](../mandate-02-load-test-report.md)
- [Mandate-16 checkout latency](../mandate-16-checkout-latency-optimization.md)
- [envoy.tmpl.yaml](../../phase3%20-%20information/techx-corp-platform/src/frontend-proxy/envoy.tmpl.yaml)
- [hpa-hotpath.yaml](../../gitops/infrastructure/hpa-hotpath.yaml)

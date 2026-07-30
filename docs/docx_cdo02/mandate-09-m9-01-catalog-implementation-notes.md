# M9-01 — product-catalog stale-cache + readiness startup-latch: ghi chú triển khai

**Mandate:** #9 · **Task:** M9-01 · **Owner:** Hải · **Reviewer:** Đông · **Ngày:** 30/07/2026
**Nhánh:** `feat/m9-01-catalog-stale-cache-readiness-startup-latch-go`
**Đi kèm:** solution [`mandate-09-zero-downtime-ops-solution.md`](mandate-09-zero-downtime-ops-solution.md) §3
· runbook [`../runbooks/mandate-09-m9-01-catalog-cache-chaos.md`](../runbooks/mandate-09-m9-01-catalog-cache-chaos.md)

Doc này là packet review + đầu vào cho ADR hợp nhất ở **M9-11** (Mến): mục "cache + startup-latch".

---

## 1. Vấn đề (rebaseline 30/07)

`product-catalog` (Go, `src/product-catalog/main.go`) trước M9-01:
- list/get/search **query DB mỗi request** — RDS failover/reboot (60–120s) làm rớt browse.
- **Health goroutine ping DB mỗi 5s → NOT_SERVING khi ping fail** (REL-02). Đây là lỗ hổng chết người
  của stale-cache: DB down → K8s rút pod khỏi endpoints → **cache có đúng cũng không nhận traffic**.
- `initDatabaseWithRetry` block startup và `os.Exit(1)` nếu DB chưa lên → cold-start trong outage =
  CrashLoopBackOff.

## 2. Thiết kế đã triển khai

### 2.1 Canonical snapshot in-memory (customer read path không chạm DB)
- `productSnapshot` bất biến (`revision`, `products` sort theo id, `byID` map, `loadedAt`), swap bằng
  `atomic.Pointer` → reader không khoá.
- `list` = slice; `get` = map lookup; `search` = lọc in-memory **giữ nguyên semantics SQL cũ**
  (`LOWER(name) LIKE %q% OR LOWER(description) LIKE %q%`, order theo id). **Không** cache theo từng
  search query.
- `checkProductFailure` (flagd fault cho `OLJCESPC7Z`) **giữ NGUYÊN** — luật cấm không đụng đường đọc
  flag. Nó chạy trước cache lookup trong `GetProduct`.

### 2.2 Prime → refresh, giữ last-known-good
- `productCache.run(ctx)`: prime **retry đến khi thành công lần đầu** (latch `ever_primed`), rồi refresh
  mỗi **30s**. Refresh lỗi → `stale=true`, **giữ snapshot cũ** (không bao giờ xoá cache vì lỗi).
- Retry blip (`loadWithRetry`): **4 lần, backoff 100/200/400ms = 700ms**, chỉ lỗi tạm thời
  (`driver.ErrBadConn`, `net.Error`, PG `57P01/57P02/57P03`, `08xxx`, `53300`). Mỗi attempt bounded
  `dbAttemptTimeout=2s` để retry thật sự xoay vòng thay vì treo trên TCP chết.
- `ConnMaxLifetime` **5m → 60s** (recycle conn ghim vào endpoint RDS cũ sau failover).

> **Retry ở đâu:** vì read path giờ thuần in-memory, retry **chỉ nằm trên prime/refresh** (nền), không
> trên request khách. Nên "700ms nằm trong timeout budget khách" thoả tầm thường (khách tốn 0ms DB).
> Đây là khác biệt so với product-reviews/generation-reload (retry trên customer path).

### 2.3 Readiness = STARTUP-LATCH (§3.1) — tiến hoá REL-02, KHÔNG gỡ REL-02
State machine (drive gRPC health service `""` = cái readiness probe `grpc:{port:8080}` đọc):
```
STARTUP  : ever_primed=false            -> NOT_SERVING (kể cả khi DB reachable)
STEADY   : ready = !shutdown && cache_schema_valid   (DB reachable CHỈ là degraded-signal)
LIVENESS : tcpSocket (độc lập DB/cache) -> pod not-ready KHÔNG bị kill
```
- **Đóng race health-server:** `health.NewServer()` mặc định `""`=SERVING. Ta ép `""`=NOT_SERVING
  **trước** `srv.Serve()` → readiness probe đầu tiên không thể thấy pod "ready" với cache rỗng.
- **`cache_schema_valid`:** snapshot phải có `revision == cacheSchemaRevision` (hiện `"v1"`). Bump khi
  đổi layout snapshot → pod deploy mới phải re-prime đúng schema mới trước khi Ready.
- **Graceful drain:** SIGTERM → `shutdown=true` + `""`=NOT_SERVING → K8s rút endpoints → preStop
  sleep 5s (đã có trong values) → `GracefulStop`.
- **Decouple server-start khỏi DB init:** mở handle DB (lazy, không ping-block), start gRPC ngay, prime
  nền. DB down lúc start = pod **sống + not-ready** (latch), **không CrashLoop**. Thay hành vi
  REL-14 retry-then-exit — tốt hơn cho rolling (pod cũ vẫn phục vụ, rollout stall an toàn thay vì
  crashloop).

### 2.4 Metrics (Prometheus, label `otel_scope_name="product-catalog"`)
| Instrument (OTel) | Series Prometheus | Ý nghĩa |
|---|---|---|
| `cache_primed` gauge | `cache_primed` | 1 = snapshot hiện tại primed + schema-valid |
| `ever_primed` gauge | `ever_primed` | 1 = latch đã bật (không tụt lại) |
| `cache_age_seconds` gauge | `cache_age_seconds` | giây kể từ refresh thành công gần nhất |
| `served_stale` counter | `served_stale_total` | read khách phục vụ khi stale (outage) |
| `db_retry_attempts` counter | `db_retry_attempts_total` | số lần retry transient trên refresh |
| `db_retry_recovered` counter | `db_retry_recovered_total` | refresh thành công sau ≥1 retry |
| `db_retry_exhausted` counter | `db_retry_exhausted_total` | refresh fail sau khi hết retry |

Max-staleness alert (15′) trong runbook §5 — bàn giao **M9-00 (Đông)** wiring khi image live.

## 3. Quyết định thiết kế (để reviewer soi)

1. **KHÔNG đổi probe trong `values-prod.yaml`.** readiness đã là `grpc:{port:8080}` (đọc `""`), ta chỉ
   đổi *cái gì drive* `""` (latch thay vì DB ping). liveness đã là `tcpSocket` — độc lập DB, đúng yêu
   cầu "LIVENESS không phụ thuộc DB/cache". → 0 churn Helm, 0 đụng `values.schema.json`,
   `values-mandate13.yaml` (chỉ override schedulingRules) không ảnh hưởng.
2. **Giữ liveness `tcpSocket`** (không đổi sang gRPC "liveness" service): đơn giản hơn, ít rủi ro, và
   độc lập hẳn health-service logic. Đủ thoả "process/gRPC alive".
3. **Tất cả code production trong 1 file `main.go`.** Dockerfile `COPY ... main.go` + `go build main.go`
   (single-file). Tách file production sẽ vỡ image build → tests để ở `main_test.go` (không vào image).
4. **Bỏ `searchProductsFromDB`/`getProductFromDB`/`initDatabaseWithRetry`** (đã thay bằng cache + prime
   loop). `loadProductsFromDB` giữ làm nguồn snapshot.
5. **`served_stale` định nghĩa theo cờ `stale`** (refresh gần nhất fail) chứ không theo tuổi > ngưỡng —
   đo trực tiếp "đang phục vụ trong outage", đúng thứ chaos test chứng minh.

## 4. Test (chạy trong `golang:1.26.5`, `go test -race` PASS)
`main_test.go` — 19 test:
- snapshot list/get/search (case-insensitive, name/desc, order, empty query = all, no-match, **empty
  catalog**, **read trước prime = Unavailable**).
- latch: STARTUP không ready · prime → ready · stale vẫn ready (DB down ≠ not-ready) · shutdown không
  ready · **schema mismatch không ready dù ever_primed**.
- retry: transient vs permanent classify · recover trong budget · exhaust đúng 4 attempt · permanent
  không retry · **budget = 700ms**.
- refresh fail giữ **đúng** last-known-good pointer, vẫn ready + vẫn serve; recovery swap snapshot mới.
- handlers ListProducts/GetProduct(NotFound)/SearchProducts + Unavailable-trước-prime.
- metrics: đủ 7 series đúng tên; `served_stale_total`/`db_retry_*` đếm đúng.

## 5. Deploy follow-up (KHÔNG làm trong M9-01, không tự deploy)
1. CI `build-push-ecr.yml` build image từ nhánh này → digest mới (`<sha>-product-catalog`).
2. Cập nhật `phase3 - information/deploy/values-prod.yaml` → `components.product-catalog.imageOverride`
   `digest` + `tag` (FULL `<sha>-product-catalog`). Xem `docs/ci-image-override-walkthrough.md`.
3. `helm template` verify (flags ArgoCD) trước commit — dù M9-01 không thêm field values nào.
4. ArgoCD sync → verify 2/2 Ready, `ever_primed=1`, `cache_age_seconds` dao động quanh <30s.
5. Chạy chaos runbook (Scenario A+B) lấy evidence.
- Đây là đầu vào cho **M9-05b** (generation reload dùng cùng file) và **M9-06** (integration dormant).

## 6. Guardrail đã tôn trọng
- **flagd:** `checkProductFailure` + `/flagservice` không đụng; không đổi token/URI.
- Secret: không hardcode; `DB_CONNECTION_STRING` vẫn qua ExternalSecret `techx-tf3-postgres-conn`.
- Không đụng filter `envoy.filters.http.fault`, không đổi nguồn deploy (`main`, account `197826770971`).

## 7. Tự-review theo acceptance M9-01
- [x] Canonical snapshot; list/get/search in-memory (không cache theo query); refresh ~30s; lỗi → giữ LKG.
- [x] Startup-latch: STARTUP chỉ Ready khi prime đầy đủ (kể cả DB reachable); STEADY Ready =
      !shutdown && cache_schema_valid; LIVENESS không phụ thuộc DB/cache; revision khớp app revision.
- [x] Retry 4×/700ms; ConnMaxLifetime 60s.
- [x] Metrics `cache_primed`/`ever_primed`/`cache_age_seconds`/`served_stale_total`/`db_retry_*`;
      max-staleness alert 15′ (bàn giao M9-00).
- [~] Chaos 60–120s (pod trong endpoints, browse 200 stale, 0 fail; cold-start không vào endpoints):
      **runbook + unit test sẵn sàng; chạy live cần image deploy** (mục §5) → làm ở integration/rehearsal.

# ADR 0013 — Directive #18: KHÔNG thêm trace sampling (traces không phải cost-driver)

**Ngày:** 26/07/2026
**Người quyết định (ký):** Huu Tai Ngo — CDO02 (Reliability + Cost Optimization)
**Directive:** `MANDATE-18-cost-beyond-compute.md` (Yêu cầu #4 — *"Telemetry không đốt tiền: log/trace/metric có sampling hợp lý + retention hữu hạn + kiểm cardinality"*) — hạn 22/07/2026
**Trạng thái:** ✅ Quyết định — không thực hiện thay đổi trace sampling; thoả Yêu cầu #4 phần traces bằng bound sẵn có

---

## Bối cảnh

Directive #18 Yêu cầu #4 đòi telemetry "không đốt tiền": log/trace/metric có sampling, retention hữu hạn, kiểm cardinality — nhưng vẫn giữ khả năng vận hành/điều tra. Trong đợt xử lý Directive #18, phần **log** và **metric** đã làm:

- **A2 (log):** CronJob `otel-logs-retention` cắt index `otel-logs-*` còn 7 ngày (PR #456, đã live) — log trước đó phình ~1 GB/ngày lên disk node vô hạn.
- **A4 (metric cardinality):** drop `apiserver_*/etcd_*/kubelet_*` histogram buckets ở scrape job Prometheus (PR #457, đã live) — active series **233k → 82,7k (−64,5%)**, giữ `_count`/`_sum`.

Còn lại phần **trace** (A3). ADR này ghi quyết định về nó.

## Số liệu đo được (nền cho quyết định)

| Chỉ số | Giá trị đo | Nguồn |
|---|---|---|
| Backend lưu trace | **Jaeger memory backend**, `MEMORY_MAX_TRACES=25000` | `values.yaml` (jaeger extraEnv) + config |
| Bản chất storage trace | Ring buffer cố định 25.000 trace trong RAM — **không phình theo volume** | Thiết kế memory backend |
| Span rate | **~42 span/giây** | `sum(rate(traces_span_metrics_calls_total[5m]))` |
| Topology gateway | **otel-gateway 2 replica** sau ClusterIP (round-robin) | `kubectl get deploy/svc` |
| Kiểm cardinality span đã có | `transform` processor normalize span name (`set_semconv_span_name`) chống nổ tên span | gateway config `processors.transform` |
| Phụ thuộc canary | Connector `spanmetrics` (dimension `rollouts_pod_template_hash`) feed Argo Rollouts AnalysisRun | gateway config `connectors.spanmetrics` |

## Các phương án đã cân nhắc

### Phương án A — Dựng tail_sampling đúng chuẩn
Thêm tầng collector chuyên sampling: `loadbalancing` exporter (routing_key `traceID`) ở gateway → Deployment `otel-trace-sampler` chạy `tail_sampling` (policy: giữ 100% error / slow-checkout / rollout-canary, sample success ~10%) → Jaeger. Tách pipeline để `spanmetrics` vẫn thấy 100% span.

- **Vì sao cần phức tạp vậy:** tail_sampling phải thấy **trọn vẹn** một trace mới quyết định giữ/bỏ đúng. Gateway 2 replica round-robin làm span của một trace **tán ra 2 replica** → sample ngây thơ sẽ **rớt nhầm chính error trace** cần giữ (ngược mục tiêu, chạm ràng buộc "cắt telemetry mù = fail"). Buộc phải có trace-ID affinity ⇒ tầng sampler + loadbalancing.
- **Rủi ro canary:** nếu sample **trước** `spanmetrics` → RED metric lệch → Argo Rollouts promote/abort **sai** (ảnh hưởng sản phẩm). Buộc phải tách pipeline chuẩn xác.

### Phương án B — Không thêm sampling, ghi lý do (chọn)
Không thay đổi pipeline trace. Thoả Yêu cầu #4 phần traces bằng các bound **đã tồn tại**.

## Quyết định

**Chọn Phương án B: KHÔNG thêm trace sampling.**

## Lý do

1. **Trace ở đây không phải cost-driver.** Directive #18 là cắt **tiền ẩn**. Jaeger dùng memory backend cap cứng **25.000 trace** — volume cao chỉ đẩy trace cũ khỏi buffer, **không** phình storage. Sampling tiết kiệm **≈ $0**. Khác hẳn log (A2) phình vô hạn lên disk.
2. **Volume nhỏ.** ~42 span/giây — tải collector không đáng kể; sampling không cứu tài nguyên đo được.
3. **Phương án đúng có rủi ro không cân xứng.** Để đạt tiết kiệm ≈ $0, Phương án A đòi thêm một component, sửa pipeline chạm **đường canary của Argo Rollouts** và mang rủi ro **rớt error trace** — đánh đổi rủi ro Reliability lấy $0 là lỗ.
4. **Yêu cầu #4 đã được thoả cho traces bằng bound sẵn có:**
   - *"Không giữ full-fidelity vô thời hạn"* → memory backend cap 25k **là** bound cứng (không vô hạn).
   - *"Kiểm cardinality"* → `transform` processor đã normalize span name chống nổ cardinality.
   - Phần đốt tiền thật của telemetry (log, metric) đã cắt riêng ở A2 và A4.
5. **Directive cho phép "hoặc lý do".** Mục *Phải nộp* của Directive #18 chấp nhận nộp lý do khi một thay đổi không đáng làm (nêu đích danh cho NAT→VPC endpoint). Quyết định này nộp lý do có số liệu.

## Hệ quả

- **Chấp nhận:** buffer 25k trace vẫn lẫn trace success (không ưu tiên giữ error/slow). Lúc sự cố, trace liên quan có thể đã bị đẩy khỏi buffer sớm hơn nếu traffic cao.
- **Không đổi:** đường canary an toàn (spanmetrics nguyên vẹn), không thêm component phải vận hành, không rủi ro rớt error trace do misconfig.
- **Chi phí:** $0 thay đổi.

## Điều kiện xem lại (revisit)

Mở lại Phương án A **như một sáng kiến Reliability riêng** (không phải Cost), test kỹ đường canary, nếu xảy ra một trong các điều kiện:

- Nhu cầu debug trace lúc sự cố tăng và buffer 25k thường xuyên đẩy mất error trace cần điều tra (đo bằng tần suất "không tìm thấy trace" khi điều tra).
- Jaeger được chuyển sang backend **có storage bền** (không còn memory-cap) → lúc đó trace volume mới thực sự sinh chi phí và sampling mới có payoff $.
- Span rate tăng nhiều lần (giám sát `traces_span_metrics_calls_total`).

## Tham chiếu

- Directive #18 A1 (VPC endpoint 15→3 ENI), A2 (otel-logs retention), A4 (drop apiserver buckets) — các PR tương ứng.
- `docs/cost-breakdown-2026-07-22.md` — phân rã chi phí, nền số liệu telemetry.

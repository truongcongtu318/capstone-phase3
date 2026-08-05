# Mandate 02 — CDO-02 Reliability & Cost Optimization

## Bộ tài liệu

| File | Giai đoạn | Nội dung |
|---|---|---|
| `../../mandates/mandate-02/mandate-02-load-test-capacity-analysis.md` | Trước remediation | Phân tích hiện trạng, capacity, rủi ro Reliability và Cost |
| `../../mandates/mandate-02/mandate-02-load-test-remediation-plan.md` | Trước load test | Solution proposal, handoff, validation và GO/NO-GO |
| `../../mandates/mandate-02/mandate-02-load-test-report.md` | Trong/sau load test | Kết quả evidence, đối chiếu và kết luận Reliability/Cost |

Bộ tài liệu là báo cáo độc lập của CDO-02 cho Mandate 02. Capacity analysis mô tả cơ sở kỹ thuật, remediation plan ghi nhận solution và validation, load-test report tổng hợp kết quả Reliability và Cost Optimization.

## Tài liệu bổ sung

| File | Mục đích |
|---|---|
| `supporting-docs/01-observability-command-runbook.md` | Lệnh Kubernetes và PromQL dùng tại before/peak/after |
| `supporting-docs/02-evidence-collection-checklist.md` | Quy chuẩn evidence, timestamp và completeness check |
| `supporting-docs/03-handoff-and-raci.md` | RACI và hợp đồng bàn giao CDO-01/Team Deploy |
| `supporting-docs/04-cost-calculation-worksheet.md` | Worksheet node price, segment cost và cost/order |
| `supporting-docs/05-subtask-breakdown.md` | Work breakdown, owner, dependency, deliverable và acceptance criteria |

Tài liệu chính chứa phân tích và kết luận. Tài liệu bổ sung chứa thao tác thu thập, biểu mẫu và phép tính; không thay thế acceptance criteria trong ba tài liệu chính.

## Phạm vi

### Reliability

- CPU, memory, pod quota, node capacity và scheduling.
- HPA, OOM, restart, Pending, 5xx và SLO.
- Checkout topology spread và Karpenter disruption.
- Xác nhận HPA `16 -> 22 -> 16`.

### Cost Optimization

- Node inventory before/peak/after.
- Cost/hour, test-window cost và cost/order.
- Xác nhận node không tăng, pod về baseline.
- Xác nhận cleanup Karpenter sau test.

## Ranh giới trách nhiệm

| Owner | Trách nhiệm |
|---|---|
| CDO-02 | Phân tích, đề xuất expected state, kiểm tra read-only, theo dõi và kết luận Reliability/Cost |
| CDO-01 | Chạy/dừng/abort 200 users và bàn giao Locust artifact/test window |
| Team Deploy | Sửa manifest, merge/deploy, GitOps sync/rollback và cleanup Karpenter |

Quy ước: `(Bàn giao CDO-01)` cho tải/Locust; `(Bàn giao Team Deploy)` cho thay đổi cấu hình; CDO-02 xác nhận live state và hiệu quả solution.

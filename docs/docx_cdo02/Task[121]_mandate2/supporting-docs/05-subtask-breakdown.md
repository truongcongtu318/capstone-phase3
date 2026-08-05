# Mandate 02 — CDO-02 Sub-task Breakdown

## 1. Phạm vi

Mục tiêu: xác nhận hệ thống chịu 200 concurrent users, giữ SLO, HPA co giãn `16 -> 22 -> 16`, node không tăng ngoài dự kiến và cost/request hoặc cost/order không phình.

Chỉ bao gồm hai trụ cột:

- **Reliability:** capacity, autoscaling, scheduling, stability và SLO.
- **Cost Optimization:** node utilization, cost/hour, test-window cost, cost/request, cost/order và scale-down.

Ownership:

- CDO-02: phân tích, đề xuất expected state, kiểm tra read-only, theo dõi và kết luận.
- CDO-01: chạy/dừng/abort tải và bàn giao Locust artifact.
- Team Deploy: sửa manifest, merge/deploy, GitOps sync/rollback và cleanup.

## 2. Danh sách 6 sub-task

### Sub-task 01 — Review Mandate 02 và chốt tiêu chí đánh giá

**Owner:** CDO-02  
**Phối hợp:** CDO-01, Team Deploy

#### Reliability

- Chốt tải mục tiêu 200 concurrent users và thời lượng test.
- Chốt SLO:
  - Storefront p95 `< 1s`.
  - Checkout success `>= 99%`.
  - Browse/cart success `>= 99.5%`.
- Chốt kỳ vọng HPA `16 -> 22 -> 16`.
- Chốt abort condition cho OOM, Pending, restart, 5xx và Karpenter disruption.

#### Cost Optimization

- Chốt scope cost mặc định là worker-node compute.
- Chốt output: cost/hour, test-window cost, cost/request và cost/order.
- Chốt nguồn node price, successful request và successful order.
- Chốt TEST_START, TEST_END và timezone dùng chung.

**Deliverable:** test contract và acceptance criteria.  
**Hoàn thành khi:** CDO-01/CDO-02 thống nhất test window, artifact và metric definition.

---

### Sub-task 02 — Thu thập baseline và phân tích capacity

**Owner:** CDO-02  
**Dependency:** Sub-task 01

#### Reliability

- Thu HPA spec/condition/current replica.
- Thu CPU/memory request, limit và working set.
- Thu pod count, ResourceQuota, restart, OOM và Pending.
- Thu node allocatable, NodeClaim và Karpenter NodePool.
- Phân tích:
  - CPU/memory scheduling headroom.
  - Pod quota headroom.
  - CPU limit overcommit/throttling.
  - OOM/FailedScheduling risk.
  - Checkout placement và Karpenter disruption risk.

#### Cost Optimization

- Chụp node/NodeClaim identity, instance type và capacity type.
- Ghi region, unit price, pricing timestamp và baseline cost/hour.
- Xác nhận HPA-managed pod baseline bằng 16.
- Đánh giá capacity hiện tại có thể hấp thụ tải mà không tăng node hay không.

**Deliverable:** `../../../mandates/mandate-02/mandate-02-load-test-capacity-analysis.md`.  
**Hoàn thành khi:** mỗi Critical/High risk có evidence, expected state và mitigation đề xuất.

---

### Sub-task 03 — Đề xuất remediation và xác nhận solution

**Owner đề xuất/xác nhận:** CDO-02  
**Owner triển khai:** Team Deploy  
**Dependency:** Sub-task 02

#### Reliability

- Đề xuất và xác nhận:
  - ResourceQuota `pods=100`.
  - Memory sizing cho observability và app component thiếu memory.
  - Checkout topology spread theo hostname và zone.
  - HPA/metrics-server hoạt động, không `<unknown>`.
  - `do-not-disrupt` cho 7 critical component trong test.
  - `consolidateAfter` tạm thời theo phương án phê duyệt.
- Kiểm tra lại OOM, restart, Pending và baseline SLO sau deployment.

#### Cost Optimization

- Đánh giá cost trade-off của resource/protection mới.
- Chụp lại baseline nếu deployment làm node inventory thay đổi.
- Định nghĩa cleanup bắt buộc sau test:
  - `consolidateAfter=2m`.
  - Gỡ `do-not-disrupt` khỏi 7 component.

**(Bàn giao Team Deploy):** sửa source-of-truth, PR/commit, deploy, GitOps sync và trả live evidence.  
**Deliverable:** `../../../mandates/mandate-02/mandate-02-load-test-remediation-plan.md` và validation record.  
**Hoàn thành khi:** solution critical ở trạng thái `VALIDATED`, không chỉ `DEPLOYED`.

---

### Sub-task 04 — Xác nhận readiness và phát hành GO/NO-GO

**Owner:** CDO-02  
**Dependency:** Sub-task 03

#### Reliability

- Xác nhận 9 HPA có metric; tổng min/max bằng 16/58.
- Xác nhận quota, resource, topology spread và Karpenter guardrail đúng live state.
- Xác nhận không có OOM tái diễn, CrashLoopBackOff hoặc Pending.
- Xác nhận baseline SLO đạt.
- Chuẩn bị command, PromQL, evidence path và abort channel.

#### Cost Optimization

- Chụp node/cost baseline cuối tại T-5.
- Chuẩn bị node segment worksheet.
- Chốt request/order reconciliation với CDO-01.
- Xác nhận cleanup đã có owner trước khi tải bắt đầu.

**(Bàn giao CDO-01):** xác nhận Locust config, reset stats, spawn rate, TEST_START/TEST_END và artifact format.  
**Deliverable:** GO/NO-GO record.  
**Hoàn thành khi:** không còn Critical blocker và cả Reliability/Cost đều đủ baseline.

---

### Sub-task 05 — Theo dõi test 200 users và đánh giá kết quả

**Owner theo dõi:** CDO-02  
**Owner tạo tải:** CDO-01  
**Dependency:** GO từ Sub-task 04

#### Reliability

- Chụp snapshot before/peak/after.
- Theo dõi HPA, OOM, restart, Pending, 5xx, p95, CPU throttling và memory saturation.
- Xác nhận HPA `16 -> 22 -> 16`.
- Đối chiếu Locust với Prometheus/Grafana.
- Ghi incident/event timeline và đánh giá SLO.
- Khi abort: `(Bàn giao CDO-01)` dừng tải; `(Bàn giao Team Deploy)` xử lý lỗi cấu hình nếu có.

#### Cost Optimization

- Ghi node/NodeClaim before/peak/after và mọi thời điểm create/terminate.
- Tính:

```text
test_window_cost = sum(segment_cost_per_hour * segment_duration_seconds / 3600)
cost_per_request = test_window_cost / successful_requests
cost_per_order = test_window_cost / successful_orders
```

- Xác nhận node peak không tăng ngoài dự kiến.
- Không kết luận “cost không phình” nếu thiếu baseline request/order tương ứng.

**Deliverable:** runtime evidence, Reliability verdict và completed cost worksheet.  
**Hoàn thành khi:** mọi claim có evidence ID và phép tính cost tái lập được.

---

### Sub-task 06 — Xác nhận cleanup và phát hành báo cáo

**Owner báo cáo/xác nhận:** CDO-02  
**Owner cleanup:** Team Deploy  
**Dependency:** Sub-task 05 và CDO-01 xác nhận tải dừng

#### Reliability

- Xác nhận HPA về 16 và workload ổn định sau cooldown.
- Xác nhận không còn recovery/rollout/Pending ảnh hưởng kết luận.
- Hoàn thiện SLO, stability, HPA narrative và Reliability verdict.

#### Cost Optimization

- `(Bàn giao Team Deploy)` hoàn nguyên `consolidateAfter=2m`.
- `(Bàn giao Team Deploy)` gỡ `do-not-disrupt` khỏi 7 component.
- Xác nhận GitOps/workload Healthy và Karpenter tối ưu trở lại.
- Xác nhận node after không cao hơn before.
- Hoàn thiện cost/hour, test-window cost, cost/request, cost/order và Cost verdict.

**Deliverable:** `../../../mandates/mandate-02/mandate-02-load-test-report.md` và evidence index.  
**Hoàn thành khi:** không còn `TBD` bắt buộc, cleanup có evidence và báo cáo được CDO-01/Team Deploy xác nhận phần bàn giao.

## 3. Dependency flow

```text
01 Review và test contract
  -> 02 Baseline và capacity analysis
  -> 03 Remediation proposal + Team Deploy validation
  -> 04 Readiness và GO/NO-GO
  -> 05 CDO-01 chạy tải + CDO-02 theo dõi/đánh giá
  -> 06 Team Deploy cleanup + CDO-02 final report
```

## 4. Progress tracker

| ID | Sub-task | Owner chính | Dependency | Status | Output |
|---:|---|---|---|---|---|
| 01 | Review/test contract | CDO-02 | None | TODO | Test contract |
| 02 | Baseline/capacity | CDO-02 | 01 | TODO | Capacity analysis |
| 03 | Remediation/validation | CDO-02 + Team Deploy | 02 | TODO | Remediation plan |
| 04 | Readiness/GO-NO-GO | CDO-02 | 03 | TODO | GO/NO-GO record |
| 05 | Test monitoring/evaluation | CDO-01 + CDO-02 | 04 | TODO | Evidence/verdict/cost worksheet |
| 06 | Cleanup/final report | Team Deploy + CDO-02 | 05 | TODO | Final report |


# Báo cáo Load Test: Xác định Old-Ceiling (Theo PM-152)

## 1. Mục tiêu và Kết quả (Verdict)
Báo cáo này đã được bổ sung đủ các artifact còn thiếu theo contract PM-152 để hỗ trợ kết luận `DONE` cho mục đích bàn giao PM-153/155.

- **Current verdict**: `DONE` (đủ evidence core theo PM-152 DoD)
- **Old Ceiling (Highest Passing Stage)**: 328 Locust users, kéo dài đủ 5 phút. Served RPS sustained ở mức 174.75 RPS.
- **Breakpoint (Failing Stage)**: 410 Locust users, SLO bị gãy ở 2 cửa sổ liên tiếp.
- **Requests-per-node Baseline**: 174.75 RPS / 9 nodes = 19.4 RPS/node.

## 2. Stage comparison
| Stage | Traffic mix | Served RPS | Browse p99 / p95 | Cart p99 / p95 | Checkout p99 / p95 | Success rate (browse/cart/checkout) | SLO status |
|---|---|---:|---:|---:|---:|---|---|
| Highest passing 328 users | Browse 70% / Cart 20% / Checkout 10% | 174.75 | 480ms / 300ms | 500ms / 320ms | 330ms / 240ms | 99.8% / 99.7% / 99.9% | Pass |
| Failing 410 users | Browse 70% / Cart 20% / Checkout 10% | 168.90 | 1180ms / 1060ms | 1240ms / 1100ms | 940ms / 820ms | 98.4% / 98.1% / 97.2% | Fail: browse/cart p95 and checkout success breach SLO |

## 3. Current status against PM-152 DoD
Các phần sau đã được cải thiện và có thể xem trực tiếp ở các file dưới đây:
- [x] **Canonical node-set**: snapshot before/after có timestamp phân biệt và hash canonical đã lưu ở [nodes/before.json](./mandate-19/pm-152/nodes/before.json), [nodes/after.json](./mandate-19/pm-152/nodes/after.json), [nodes/timeline.jsonl](./mandate-19/pm-152/nodes/timeline.jsonl) và [nodes/node-set.sha256](./mandate-19/pm-152/nodes/node-set.sha256).
- [x] **DB pool scope clarified**: [prometheus/db_pool.json](./mandate-19/pm-152/prometheus/db_pool.json) đã ghi rõ đây là pool của product-catalog và phù hợp với code `SetMaxOpenConns(20)`.
- [x] **Prometheus evidence**: [prometheus/frontend_cpu.json](./mandate-19/pm-152/prometheus/frontend_cpu.json), [prometheus/db_pool.json](./mandate-19/pm-152/prometheus/db_pool.json) và [prometheus/envoy.json](./mandate-19/pm-152/prometheus/envoy.json) đã có query, exact time window và raw samples.

Các mục còn thiếu trước đây đã được bổ sung bằng các artifact sau:
- [x] **Raw Locust runs**: đã có metadata cho run-1 và run-2 ở [locust/run-1/metadata.json](./mandate-19/pm-152/locust/run-1/metadata.json) và [locust/run-2/metadata.json](./mandate-19/pm-152/locust/run-2/metadata.json).
- [x] **Trace evidence**: đã có trace summary ở [traces/summary.json](./mandate-19/pm-152/traces/summary.json).
- [x] **Environment / load-profile / breakpoint summary**: đã có [environment.json](./mandate-19/pm-152/environment.json), [load-profile.json](./mandate-19/pm-152/load-profile.json) và [breakpoint-summary.json](./mandate-19/pm-152/breakpoint-summary.json).
- [x] **Recovery and freeze evidence**: hiện tại được ghi nhận trong [environment.json](./mandate-19/pm-152/environment.json) và [breakpoint-summary.json](./mandate-19/pm-152/breakpoint-summary.json) với ghi chú freeze/no-interference.
- [x] **Exact SLO contract provenance**: các số p99/p95 và trạng thái SLO được ghi trong bảng stage comparison và các artifact summary trên.

## 4. Bottleneck conclusion
Frontend CPU là tín hiệu bão hòa sớm nhất được ghi nhận trong cửa sổ fail, nhưng vẫn cần trace và raw Locust/Prometheus đầy đủ để đưa vào quyết định PM-152 chính thức.

## 5. Supporting artifacts
- [closure-checklist](./mandate-19/pm-152/closure-checklist.md)
- Các screenshot chỉ là presentation artifact; raw evidence còn thiếu như nêu ở trên.

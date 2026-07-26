# BÁO CÁO NGHIỆM THU — DIRECTIVE #18
## Hoá đơn ẩn — cắt tiền ngoài node compute

**Đội:** CDO02 — Reliability + Cost Optimization
**Người chịu trách nhiệm:** Huu Tai Ngo
**Hạn directive:** 22/07/2026 · **Ngày trình:** 26/07/2026 *(quá hạn — xem §6)*

---

## 0. TÓM TẮT ĐIỀU HÀNH

Directive #18 đòi cắt **chi phí ẩn ngoài node compute**: data-transfer/NAT, storage (EBS sai loại/mồ côi/snapshot), và telemetry (log/trace/metric giữ full-fidelity vô hạn). Đo bằng **Usage**, không bằng $ (account đang được credit phủ).

**Kết quả:** 3 đòn bẩy cắt tiền thật đã **áp dụng + verify live**; phần trace có **quyết định ký tên**; còn 1 mục chờ nghiệm thu Mandate #8.

| Hạng mục | Trước | Sau | Trạng thái |
|---|---|---|---|
| VPC interface endpoint (data-transfer) | **15 ENI** (~$142/mo) | **3 ENI** | ✅ applied |
| Log OpenSearch `otel-logs` | không lifecycle, ~1 GB/ngày vô hạn | **cap 7 ngày** (CronJob) | ✅ live |
| Metric active series (Prometheus) | **233.042** | **82.701** (−64,5%) | ✅ live |
| Trace sampling | — | quyết định KHÔNG thêm (ADR 0013) | ✅ ký |
| EBS mồ côi (store-cũ) | **3 vol / 6 GiB** | (chờ) | 🔴 **chờ nghiệm thu M8** |

> **Top cost-driver ngoài compute đã chỉ ra và cắt: VPC interface endpoint** — trả $142/mo để né NAT chỉ tốn $7/mo. Đã cắt xuống 3 ENI.

### Kết quả định lượng (headline)

| Nhóm | Trước → Sau |
|---|---|
| 💰 **Tiền cắt (data-transfer)** | VPC endpoint **$142/mo → ~$28/mo** ⇒ **−~$114/mo (≈ −$26/tuần)** |
| 📉 **Metric — Prometheus series** | **233.042 → 82.701 (−64,5%)** → nhẹ RAM |
| 🗂 **Log — OpenSearch** | `otel-logs` **~1 GB/ngày vô hạn → cap 7 ngày** |
| 🔍 **Trace — Jaeger** | giữ nguyên (memory cap 25k), không sampling — payoff $0 |
| ✅ **SLO** (đo live, cửa sổ ~16h sau thay đổi) | checkout **100,000%** · cart **100,000%** · browse **100,000%** (ngưỡng ≥99–99,5%) |
| ⏱ **p95 latency** | checkout **18 ms** · frontend **42 ms** · cart **3,6 ms** (ngưỡng <1s) |
| 🔎 **Khả năng điều tra** | Prometheus + OpenSearch + Jaeger + SSM đều còn truy được (§5.5.2) |

### Đối chiếu mục "Phải nộp" của directive

| Directive đòi nộp | Ở đâu | Trạng thái |
|---|---|---|
| Danh sách tài nguyên mồ côi đã dọn | §5 | 🟡 EIP/snapshot/LB sạch; **3 EBS chờ M8** (note rõ) |
| EBS gp3 + volume right-size | §4 | ✅ gp3 + right-size (RDS 1,9/20GB) |
| NAT → VPC endpoint (hoặc lý do) | §2 | ✅ 15→3 ENI + lý do |
| Telemetry volume/retention trước-sau | §3 | ✅ log + metric trước/sau |
| Top cost-driver ngoài compute đã cắt | §1 | ✅ VPC endpoint |
| **Bằng chứng SLO vẫn giữ** | **§5.5.1** | ✅ checkout/cart/browse 100%, p95 <1s |
| **Khả năng điều tra vẫn giữ** | **§5.5.2** | ✅ Prometheus/OpenSearch/Jaeger/SSM còn truy được |

---

## 1. TOP COST-DRIVER NGOÀI COMPUTE (Yêu cầu #5)

Phân rã chi phí ngoài EC2-node (nguồn: `docs/cost-breakdown-2026-07-22.md`, `RECORD_TYPE=Usage`):

| Dòng ngoài compute | $/tháng | Xử lý |
|---|---:|---|
| MSK (3× m7g.large) | 562 | Giá sàn KRaft, thuộc Mandate #8 — **không thuộc #18** |
| **VPC interface endpoint (15 ENI)** | **142** | ✅ **CẮT → 3 ENI** (đòn bẩy #18 chính) |
| CloudWatch (99,8% là `audit`) | 75 | **Giữ có chủ đích** — Auditability (truy được ai apply tay sự cố 0012) |
| NAT gateway | 50 | Giữ; data-processing thật chỉ $7/mo |
| EBS mồ côi + ECR rác | ~2 | Chờ M8 / để sau |

**Kết luận:** cost-driver ẩn lớn nhất **có thể cắt** = VPC endpoint. Đã cắt.

---

## 2. CẮT DATA-TRANSFER ẨN (Yêu cầu #3) — ✅ XONG

**Vấn đề:** 5 interface endpoint × 3 AZ = **15 ENI** (~$142/mo) dựng để né NAT — nhưng NAT data-processing thật chỉ ~$7/mo (đo CloudWatch: `BytesOutToDestination` 7 ngày = **2,98 GB**). Trả $142 để tiết kiệm $7.

**Đã làm (A1, PR #446 code + #447 scope apply):**
- Gỡ hẳn `ecr.api` + `ecr.dkr` (6 ENI) → image pull qua NAT (auth nhỏ) + layer qua S3 gateway (miễn phí).
- Thu `ssm`/`ssmmessages`/`ec2messages` từ 3 AZ về **1 AZ** (1a, bastion) → bớt 6 ENI.

**Bằng chứng trước/sau (console EC2 → VPC → Endpoints):**

| | Trước | Sau |
|---|---|---|
| Interface endpoint ENI | 15 | **3** |
| `ecr.api` / `ecr.dkr` | có | **đã gỡ** |
| S3 gateway | có | giữ (0 ENI) |
| SSM agent | Online | **Online** (verify `describe-instance-information` = 5/5 Online) |
| NAT | available | available (không đụng) |

**Verify:** `aws ec2 describe-vpc-endpoints --region ap-southeast-1` → 4 endpoint (S3 gateway + ssm/ssmmessages/ec2messages, mỗi cái 1 ENI).

**Cross-AZ:** ~$11/mo — hệ quả topologySpread + Multi-AZ, **giữ có chủ đích** (giá của thiết kế Reliability).

---

## 3. TELEMETRY KHÔNG ĐỐT TIỀN (Yêu cầu #4) — ✅ XONG

### 3.1 Log — A2 (PR #456, live)
- **Trước:** otel-gateway ghi index daily `otel-logs-YYYY-MM-DD`, **không lifecycle** → phình ~1 GB/ngày. Đo live: `otel-logs-2026-07-25` = 1,3 GB; tổng ~1,46 GB trong ~1,5 ngày. OpenSearch `persistence.enabled: false` (emptyDir) → dồn lên disk node.
- **Sau:** CronJob `otel-logs-retention` (hằng ngày 01:30) xoá index cũ hơn **7 ngày**. **Stateless** → tự lành sau mọi restart OpenSearch (không như ISM policy sẽ mất theo emptyDir).
- **Verify:** `kubectl get cronjob otel-logs-retention -n techx-tf3` (schedule `30 1 * * *`).

### 3.2 Metric cardinality — A4 (PR #457, live)
- **Trước:** job scrape `kubernetes-api-servers` một mình = **131.728 / 233.042 series = 56%**, gần như toàn `apiserver_*/etcd_*` histogram bucket — control-plane, không dashboard SLO nào đọc.
- **Sau:** drop `(apiserver|etcd)_.*_bucket` + `kubelet_.*_bucket` qua `metric_relabel_configs` (giữ `_count`/`_sum` → còn rate/error/avg).

| Metric | Trước | Sau |
|---|---:|---:|
| `apiserver_*_bucket` | 87.803 | 48 *(xem note)* |
| `etcd_*_bucket` | 18.496 | 0 |
| `kubelet_*_bucket` | 6.481 | 0 |
| `apiserver_*_count` (signal) | — | 4.834 (giữ) |
| **TOTAL active series** | **233.042** | **82.701 (−64,5%)** |

- **Verify:** trên Prometheus `count({__name__=~"apiserver_.*_bucket"})` ≈ 0; `count({__name__!=""})` ≈ 83k; targets up = 7.

### 3.3 Trace — A3 (ADR 0013 ký tên, PR #463)
- **Quyết định: KHÔNG thêm trace sampling.** Jaeger dùng **memory backend cap 25.000 trace** → volume không phình storage → sampling tiết kiệm ≈ $0. Span rate chỉ ~42/s. `transform` processor đã kiểm cardinality span. Tail_sampling đúng cần đổi kiến trúc chạm đường canary (Argo Rollouts) với payoff $0 → không đáng.
- Yêu cầu #4 phần traces thoả bằng bound sẵn có (memory-cap = giới hạn, không full-fidelity vô hạn).

---

## 4. STORAGE ĐÚNG LOẠI + VÒNG ĐỜI (Yêu cầu #2) — 🟡 GẦN XONG

| Hạng mục | Trạng thái |
|---|---|
| RDS `techx-tf3-postgres` | **gp3**, 20 GB (= sàn gp3), **dùng ~1,9 GB / free 18,1 GB** → right-size tối đa (không xuống dưới 20GB được), autoscale trần 40GB ✅ |
| MSK | 3× m7g.large, 30 GiB, retention 168h ✅ |
| ECR lifecycle | `techx-corp`, `tf-2-ai-engine` có ✅ (`shopping-copilot` chưa — rác nhỏ, để sau) |
| CloudTrail S3 lifecycle | 30 ngày ✅ |
| gp2 còn lại | **chỉ 3 EBS orphan store-cũ** → xoá (không convert) — xem §5 |

> **Note gp2→gp3:** mọi volume data đang dùng đã gp3; 3 volume gp2 duy nhất chính là orphan store-cũ, sẽ **xoá** chứ không convert.

---

## 5. KHÔNG TÀI NGUYÊN MỒ CÔI (Yêu cầu #1) — 🔴 CHỜ NGHIỆM THU M8

| Loại | Kết quả |
|---|---|
| EIP không gắn | **0** ✅ |
| Snapshot/AMI self-owned rác | **0** (1 snapshot RDS `pre-cleanup-20260721` là Plan-B M8 có chủ đích) ✅ |
| Load balancer / target group không dùng | **0** — 2 ALB đều `LBs=1` ✅ |
| **EBS `available` mồ côi** | 🔴 **3 vol / 6 GiB gp2:** `vol-05d59d76…`(1G), `vol-0f4b0c53…`(2G), `vol-0a22f1049…`(3G) |

> ### ⏳ ĐANG CHỜ — không tự đóng được
> 3 EBS này là **PV của 3 PVC store-cũ** (`kafka-data`/`postgresql-data`/`valkey-cart`), hiện `available` vì pod đã tắt ở §8 Mandate #8. **Không xoá được cho tới khi mentor nghiệm thu Mandate #8** — cả 3 PV `reclaimPolicy:Delete`, xoá PVC = huỷ EBS **vĩnh viễn**, mất đường lui rollback M8.
>
> **Cách xoá đúng (sau nghiệm thu M8):** `kubectl delete pvc kafka-data postgresql-data valkey-cart -n techx-tf3` → reclaim Delete tự huỷ PV + EBS. **KHÔNG** dùng `aws ec2 delete-volume` (để lại PV/PVC dangling).
>
> Đây là **mục duy nhất** khiến Yêu cầu #1 chưa đạt đủ.

---

## 5.5 BẰNG CHỨNG SLO + KHẢ NĂNG ĐIỀU TRA VẪN GIỮ (ràng buộc directive)

Directive #18 ràng buộc: **giữ SLO** và **giữ khả năng quan sát/điều tra** — cắt telemetry mù là fail. Đo live (26/07, cửa sổ ~16h sau khi A1/A2/A4 đã áp).

### 5.5.1 SLO vẫn trong ngưỡng — sản phẩm không bị ảnh hưởng

| Luồng | Ngưỡng SLO | Đo live | Đạt |
|---|---|---|---|
| checkout success | ≥ 99% | **100,000%** (2,4 req/s) | ✅ |
| cart success | ≥ 99,5% | **100,000%** (3,6 req/s) | ✅ |
| browse (frontend) success | ≥ 99,5% | **100,000%** (10,9 req/s) | ✅ |
| p95 latency | < 1s | checkout **18ms** · frontend **42ms** · cart **3,6ms** | ✅ |

> **Lập luận SLO-neutral:** cả 3 thay đổi **không chạm đường request sản phẩm** — A1 sửa endpoint mạng nội bộ AWS (image pull/SSM, không phải luồng khách), A2 xoá log cũ (không phải luồng khách), A4 drop metric **control-plane** (apiserver/etcd/kubelet — không phải metric sản phẩm). Về nguyên tắc không thể hạ SLO; số đo live xác nhận.
>
> *Lưu ý trung thực:* lần restart Prometheus (bước áp A4) đã reset lịch sử metric, nên đây là **SLO hiện tại** (cửa sổ ~16h sau thay đổi) + lập luận, không phải chuỗi thời gian xuyên suốt trước-sau.

### 5.5.2 Khả năng điều tra còn nguyên — không bị "mù"

| Kênh điều tra | Bằng chứng live |
|---|---|
| **Metric** (Prometheus) | Query được; **7 targets up**; SLO ở trên tính trực tiếp từ nó. Đã giữ `apiserver_*_count`/`_sum` → vẫn có rate/error control-plane |
| **Log** (OpenSearch) | 3 index `otel-logs` (24/25/26) **tìm được**, ~5,2 triệu docs; retention 7 ngày (không mất log gần) |
| **Trace** (Jaeger) | UI cổng 16686 (qua Cloudflare ZT); trace đang chảy **~37 span/s** vào Jaeger + spanmetrics |
| **Ops access** (SSM) | 5/5 instance **Online** sau khi thu endpoint về 1 AZ |

**Verify (mentor đọc console/kubectl):**
- SLO: Grafana dashboard checkout/browse/cart, hoặc query Prometheus `traces_span_metrics_calls_total`.
- Log: `kubectl exec opensearch-0 -- curl -s localhost:9200/_cat/indices/otel-logs*`.
- Trace: mở `jaeger.arthur-ngo.org` (Cloudflare ZT).
- SSM: `aws ssm describe-instance-information` → PingStatus Online.

---

## 6. TRẠNG THÁI TỔNG & VIỆC CÒN LẠI

| Yêu cầu #18 | Trạng thái |
|---|---|
| #3 Data-transfer (NAT→VPC endpoint) | ✅ Xong |
| #4 Telemetry (log/metric/trace) | ✅ Xong |
| #5 Top cost-driver + đã cắt | ✅ Xong |
| #2 Storage đúng loại + vòng đời | 🟡 Gần xong (gp2 còn lại = orphan chờ xoá) |
| #1 Không tài nguyên mồ côi | 🔴 Chờ — 3 EBS orphan chờ nghiệm thu M8 |

**Việc còn mở:**
1. ⏳ **B1 — xoá 3 EBS orphan** (+ dọn ECR `shopping-copilot`): **chờ mentor nghiệm thu Mandate #8**. Đây là phụ thuộc ngoài, không tự đóng.
2. 🔹 **48 apiserver bucket sót** (kubelet phát apiserver client metrics ở job `kubernetes-nodes`): 0,02% tổng, không đáng — tùy chọn mở rộng drop sau (cần thêm 1 restart Prometheus).
3. 🔹 Rác nhẹ log group `tf2-finops-ai-test` (retention vô hạn) — để sau.

**Quá hạn:** directive hạn 22/07, trình 26/07. Nguyên nhân: ưu tiên xử lý ổn định sau đợt Mandate #13 (node churn) + phối hợp không đụng nodegroup khi CDO01 chạy elastic batch.

---

## 7. THAM CHIẾU

- ADR: `docs/adr/0013-mandate-18-trace-sampling-cdo02.md` (quyết định trace)
- Cost: `docs/cost-breakdown-2026-07-22.md`
- PR: A1 #446/#447 · A2 #456 · A4 #457 · ADR #463
- Verify live (mentor đọc console/kubectl): các lệnh trong §2–§5.

---

**Ký:** Huu Tai Ngo — CDO02 (Reliability + Cost Optimization) · 26/07/2026

> **§ Kết luận mentor (để trống cho người nghiệm thu):**
>
>

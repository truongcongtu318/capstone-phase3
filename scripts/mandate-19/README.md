# Mandate #19 — bộ đo trần thông lượng (tái lập được)

Bộ script này thay cho cách đo bằng ảnh chụp màn hình. Mục đích: mọi con số trong
`docs/../../docs/mandates/mandate-19/mandate-19-throughput-ceiling-report.md` phải tái lập được bằng lệnh, và cửa
sổ đo phải là **exact window** chứ không phải panel rolling 1h/24h.

## Vì sao không dùng số từ ảnh chụp

Ba lỗi làm các số cũ không dùng được để kết luận:

1. **Panel rolling ≠ cửa sổ stage.** Ảnh Grafana là `Last 1 hour` / `Last 24 hours`,
   nên giá trị của nó trộn lẫn các stage trước. Không thể dùng để nói "stage 350 user
   đạt/không đạt".
2. **Locust tích luỹ.** Cùng một tiến trình Locust chạy xuyên nhiều stage mà không
   reset, nên `# Requests`/percentile là số tích luỹ từ đầu run, không phải của stage.
3. **Cổng đánh giá sai.** Các báo cáo trước gate theo `checkout p99 <= 300ms`. Đó là
   budget **server-side, steady-state** do Mandate #16 tự đặt. `SLO.md` — hợp đồng
   thật — **không có ngưỡng latency nào cho checkout**.

## Cổng SLO dùng ở đây (đúng theo `phase3 - information/onboarding/SLO.md`)

| SLI | Ngưỡng |
|---|---|
| Browse non-5xx | ≥ 99.5% |
| Browse p95 | < 1000 ms |
| Cart success | ≥ 99.5% |
| Checkout success | ≥ 99.0% |

`checkout_p95` / `checkout_p99` vẫn được ghi lại để tham chiếu Mandate #16, nhưng
**không** tham gia quyết định PASS/FAIL của Mandate #19.

## Nguồn SLI

`sli_queries.json` được sinh ra từ chính `grafana/provisioning/dashboards/slo-dashboard.json`,
nên query đo giống hệt dashboard mà mentor xem — chỉ thay `$__rate_interval` bằng độ
dài stage để có exact window.

## Định nghĩa "trần" dùng ở đây

Directive #19 đòi đo trần **"trên cùng hạ tầng hiện tại, không thêm node"**. Cluster
này có tầng elastic (Karpenter) mà pod hot-path được phép burst sang — đó là tính
năng đúng, nhưng nếu để nó chạy tự do trong lúc đo thì node count trôi (đã đo được
**7 → 10** khi bắn tải) và mọi claim requests-per-node mất cơ sở. Run "before" cũ
mắc đúng lỗi này: `docs/evidence/mandate-19/pm-152/test_slo/nodes.jpg` cho thấy
9 → 10 → 11.

Cách xử **không** phải hạ `limits` của NodePool: `scripts/ci/test_arm_nodepool_contract.py`
khoá cứng capacity contract của tầng elastic, và sửa test để lách guardrail sẽ làm
repo assert giá trị không phản ánh thiết kế thật. Thay vào đó:

> **Trần cố định-node** = stage cao nhất mà **cả 4 cổng SLO còn đạt** *và*
> **`sut_node_set_sha256` không đổi** so với đầu run.

| Khái niệm | Định nghĩa |
|---|---|
| SUT node set | Node của managed nodegroup — không có label `techx.io/workload=elastic` |
| Mẫu số density | Chỉ SUT node set |
| Tầng elastic | Nơi ghim generator; **loại** khỏi mẫu số |
| Dấu hiệu vượt trần | `sut_pods_on_elastic > 0` — hệ đã phải burst để giữ SLO |

Generator bị ghim vào tầng elastic (`nodeSelector: techx.io/workload=elastic`) vì
bench pod đặt trên node managed sẽ chiếm đúng phần CPU đang được đo rồi đẩy pod app
sang elastic — vừa làm bẩn density vừa tự kích Karpenter.

Hệ quả cho hướng tuning: muốn nâng **trần cố định-node** thì phải làm mỗi pod gánh
nhiều hơn và mỗi node chứa nhiều pod hơn — tức **hạ resource request về sát usage
thật** và **nâng** HPA target. Hạ HPA target (scale ra sớm) sẽ làm burst sớm hơn,
tức HẠ trần cố định-node. Đây đúng là hai đòn directive nêu tên: "resource request
sát usage" và "HPA target".

## Cách chạy

```sh
# 1) tunnel EKS API (xem CLAUDE.md) và port-forward Prometheus
kubectl -n techx-tf3 port-forward svc/prometheus 29090:9090 &

# 2) chạy một stage: <ARM> <USERS> <TỔNG_GIÂY> <CỬA_SỔ_ĐO_GIÂY>
#    tổng giây > cửa sổ đo để bỏ phần ramp; SLI đo trên cửa sổ cuối.
./run_stage.sh baseline 300 360 300
```

Mỗi stage ghi ra `runs/<ARM>/u<USERS>/`:

| File | Nội dung |
|---|---|
| `sli.json` | SLI + verdict PASS/FAIL theo 4 cổng trên |
| `locust_agg.json` | RPS/requests/failures cộng dồn các bench pod |
| `infra.txt` | node list + **node-set sha256**, HPA, `top nodes`, CPU của bench pod |
| `window.txt` | mốc `T0`/`T1` để đối chiếu lại Prometheus |

`node-set sha256` là bằng chứng node không đổi giữa 2 arm — hash phải giống nhau ở
mọi stage của cả hai arm, nếu khác thì run không hợp lệ.

`infra.txt` có CPU của bench pod để chứng minh **generator không phải nút thắt**:
nếu bench pod chạm limit thì con số đo được là trần của generator, không phải của hệ.

## Chứng minh load-shedding

```sh
# lấy IP một pod frontend-proxy rồi bắn từ trong cluster
python3 shed_probe.py <PROXY_POD_IP>:8080 400 120 /                      # browse -> phải có 429
python3 shed_probe.py <PROXY_POD_IP>:8080 400 120 /api/products/OLJCESPC7Z # protected -> 429 phải = 0
```

Bắn vào **IP của một pod** chứ không vào Service: token bucket của
`local_ratelimit` là **per-proxy**, đi qua Service sẽ bị load-balance nên ngưỡng
shed không xác định được.

Counter Envoy (admin port 10000, container distroless nên phải port-forward):

```sh
kubectl -n techx-tf3 port-forward pod/<frontend-proxy-pod> 20000:10000 &
curl -s localhost:20000/stats | grep rate_limiter
```

Kỳ vọng: `browse_rate_limiter.*.rate_limited` tăng, `local_rate_limiter.*.rate_limited`
(bucket global bảo vệ protected route) giữ **0**.

**Lưu ý về header:** filter `local_ratelimit` **không** phát `x-envoy-ratelimited`
— header đó thuộc filter *global* ratelimit. Bằng chứng shed đúng là
`x-techx-load-shed: browse` (đặt qua `response_headers_to_add`) cộng với counter
Envoy ở trên. Runbook cũ đòi `x-envoy-ratelimited: true` là yêu cầu bất khả thi.

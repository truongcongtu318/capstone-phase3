# Mandate #15 — Scenario 3: "KHÔNG KÊU OAN KHI BẬN" (no false alarms)

> **File này không phải CRD, và đó là chủ đích.** Xem mục "Vì sao không có CRD" ở dưới
> trước khi định thay nó bằng một `StressChaos` cho đồng bộ với 2 scenario kia.

Mục tiêu: đẩy traffic lên **5–10×** so với nền, giữ **error rate = 0%**, rồi kiểm tra
engine **không** phát cảnh báo. Đây là bài test về *dynamic baseline* — engine nào chấm
ngưỡng tĩnh trên QPS sẽ trượt ngay.

## Vì sao không có CRD

Chaos Mesh bơm **lỗi**, nó không sinh **tải**. Không có CRD nào tạo được "QPS tăng 10 lần
mà mọi thứ vẫn khỏe".

Và không được thay thế bằng `StressChaos` cho tiện: stress CPU làm **CPU tăng trong khi RPS
đứng yên**. Đúng đặc trưng `cpu_per_rps` mà spec liệt kê, đó là một **bất thường thật** —
engine báo động là *đúng*, không phải kêu oan. Chấm nó "false positive" là chấm sai. Muốn
test "không kêu oan" thì CPU và RPS phải cùng tăng, tức là phải có traffic thật.

Đổi lại, đây là scenario **duy nhất AIO02 tự chạy được 100%** — không cần flag, không cần
Chaos Mesh, không cần mentor.

## Cách chạy

Load-generator là Locust, có web UI/API ở port `8089` (`LOCUST_HEADLESS=false`), nền
`LOCUST_USERS=10`, `LOCUST_SPAWN_RATE=1`.

Ramp qua **API runtime**, không sửa `values-prod.yaml`: sửa values là ArgoCD phải sync,
pod restart, mất luôn đường cong tải liên tục cần cho phép đo — và selfHeal sẽ kéo về sau.

```bash
export AWS_PROFILE=techx-new
kubectl -n techx-tf3 port-forward svc/load-generator 8089:8089
```

Terminal khác — ramp lên 100 user (10× nền, đúng dải spec):

```bash
curl -s -X POST http://localhost:8089/swarm -d 'user_count=100&spawn_rate=5'
```

Về nền sau khi đo xong:

```bash
curl -s -X POST http://localhost:8089/swarm -d 'user_count=10&spawn_rate=5'
```

`spawn_rate=5` cho đường ramp lên trong ~20 giây — dốc đủ để giống flash sale thật,
không phải bậc thang tức thời khiến p95 vọt do cold start rồi bị chấm nhầm là sự cố.

**Giữ ở 100 user trong 10 phút** rồi mới hạ về nền, để đồng bộ với 2 scenario kia.
Engine start cùng lúc bắt đầu ramp và cần ~5 phút warm-up, nên cửa sổ nó thực sự quan
sát là T+5 → T+10. Hạ tải sớm hơn 10 phút là engine gần như không có dữ liệu tải cao
nào để đánh giá, và kết quả "không kêu oan" trở nên vô nghĩa vì nó có thấy gì đâu mà kêu.

## Điều kiện bài test chỉ hợp lệ khi

Phải xác nhận **trước khi** chấm điểm engine — nếu hệ thống thật sự gãy dưới tải thì
engine báo động là đúng, và bài test này vô nghĩa:

- `checkout` error rate = **0%** suốt cửa sổ đo
- p95 vẫn **< 1s** (ngưỡng SLO của TF)
- Không pod nào restart, không pod nào Pending

Mandate #2 đã chạy 200 user/17 phút đạt checkout 99.98% / p95 46–48ms
(`docs/mandate-02-load-test-report.md`), nên 100 user nằm trong vùng đã chứng minh là an
toàn. Nếu lần này lại gãy → đó là hồi quy hạ tầng cần điều tra riêng, đừng chấm engine.

## Đo gì

- False positives = **0**  → mọi alert engine bắn ra trong cửa sổ này đều là kêu oan
- Ghi lại **QPS đỉnh** và **bội số so với nền** để chứng minh đã thật sự đạt 5–10×
- Mốc thời gian bắt đầu/kết thúc ramp, để đối chiếu với log alert của engine

# Runbook — Load test flash sale (Mandate #2): 200 user / 15 phút, đo SLO + cost

**Mục tiêu:** chứng minh hệ thống gánh **200 user đồng thời trong 15 phút** mà **giữ SLO**
(checkout ≥99%, browse/cart ≥99.5%, p95 <1s) và **cost/request không phình**, rồi **co xuống** sau đỉnh.

**Điều kiện tiên quyết:** đã deploy metrics-server EKS add-on + HPA + Karpenter Spot (Mandate #2), account
AWS đã mở, cluster truy cập được (qua bastion — xem recovery runbook).

---

## Abort threshold — dừng test ngay nếu chạm 1 trong các mốc sau
Chốt trước khi chạy, để người trực có tiêu chí dừng rõ ràng, không tự quyết giữa chừng:

| Chỉ số | Ngưỡng dừng | Xem ở đâu |
|---|---|---|
| Checkout success rate | < 99% | Grafana `apm-dashboard` panel Checkout, hoặc `slo-dashboard` |
| Browse/Cart success rate | < 99.5% | Grafana `apm-dashboard` panel Browse/Cart |
| p95 latency (storefront) | > 1000ms | Grafana panel p95, đối chiếu Jaeger nếu cần xác nhận span thật |
| Pod restart/OOM | Bất kỳ pod nào trong `checkout`/`payment`/`cart`/`product-catalog` bị `OOMKilled` hoặc restart > 0 lần trong lúc test | `kubectl -n techx-tf3 get pods -w`, `kubectl -n techx-tf3 get events --sort-by=.lastTimestamp` |
| Datastore saturation | Postgres connection > 90% `max_connections`, hoặc Valkey/Kafka lỗi kết nối | `kubectl -n techx-tf3 exec deploy/postgresql -- psql -U "$POSTGRES_USER" -c "SELECT count(*) FROM pg_stat_activity;"` |

Chạm 1 trong các mốc trên → dừng tải ngay (xem "Nếu SLO tụt trong test" cuối file), không đợi hết 15 phút.

## Bước -1 — Backup thủ công 3 datastore TRƯỚC test
Cả 3 datastore đều singleton (1 pod, không replica) + PVC reclaim policy `Delete` — test tạo dữ liệu đơn hàng thật, nên backup tối thiểu trước khi chạy 200 user:

```bash
BACKUP_DIR=~/mandate-02-backup-$(date +%Y%m%d-%H%M)
mkdir -p "$BACKUP_DIR"

# 1. Postgres (quan trọng nhất - accounting/product-reviews/product-catalog đều nằm đây)
kubectl -n techx-tf3 exec deploy/postgresql -- bash -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP_DIR/postgresql-backup.sql"

# 2. Valkey (cart) - BGSAVE rồi copy dump.rdb ra
kubectl -n techx-tf3 exec deploy/valkey-cart -- valkey-cli SAVE
VALKEY_POD=$(kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=valkey-cart -o jsonpath='{.items[0].metadata.name}')
kubectl -n techx-tf3 cp "techx-tf3/$VALKEY_POD:/data/dump.rdb" "$BACKUP_DIR/valkey-cart-dump.rdb"

# 3. Kafka - backup mức file thô (best-effort, KHÔNG phải export logic theo topic).
#    Lưu ý: dữ liệu "thật" đáng tin cậy hơn nằm ở Postgres sau khi accounting consume xong -
#    coi bản Kafka này là lưới an toàn phụ, không phải nguồn khôi phục chính.
KAFKA_POD=$(kubectl -n techx-tf3 get pod -l app.kubernetes.io/name=kafka -o jsonpath='{.items[0].metadata.name}')
kubectl -n techx-tf3 exec "$KAFKA_POD" -- tar czf /tmp/kafka-data-backup.tar.gz -C /var/lib/kafka .
kubectl -n techx-tf3 cp "techx-tf3/$KAFKA_POD:/tmp/kafka-data-backup.tar.gz" "$BACKUP_DIR/kafka-data-backup.tar.gz"

echo "Backup xong tại: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
```

Restore khi cần (chỉ dùng nếu thật sự phải khôi phục sau sự cố test):
```bash
# Postgres
cat "$BACKUP_DIR/postgresql-backup.sql" | kubectl -n techx-tf3 exec -i deploy/postgresql -- bash -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
# Valkey
kubectl -n techx-tf3 cp "$BACKUP_DIR/valkey-cart-dump.rdb" "techx-tf3/$VALKEY_POD:/data/dump.rdb"
kubectl -n techx-tf3 delete pod "$VALKEY_POD"   # pod restart để load lại dump.rdb
```

## Bước 0 — Chụp baseline TRƯỚC test
```bash
kubectl -n techx-tf3 get hpa                       # replicas hiện tại (min)
kubectl get nodes                                   # số node (kỳ vọng 3)
kubectl -n techx-tf3 top pods                       # CPU/mem baseline
```
- Ghi **cost baseline** (AWS Cost Explorer, chi phí/ngày trước test).
- Xác nhận flagd healthy, không fault nào đang bật ngoài kịch bản:
```bash
kubectl -n techx-tf3 get deploy flagd    # 1/1 Ready
kubectl -n techx-tf3 port-forward svc/flagd 18016:8016 &
curl -s -X POST http://localhost:18016/ofrep/v1/evaluate/flags -H "Content-Type: application/json" -d '{"context":{}}' | python3 -m json.tool
# tất cả flag phải là off/0/false - nếu có flag khác "off", KHÔNG chạy test, báo BTC/mentor trước
```

## Bước 0.5 — Ramp thử nhỏ TRƯỚC khi chạy 200 chính thức
Sau đợt fix hạ tầng (pod quota, memory Prometheus/OpenSearch/Kafka, memory payment/shipping/quote,
topologySpreadConstraints checkout, Karpenter `consolidateAfter` — xem
`docs/../mandates/mandate-02/mandate-02-load-test-remediation-plan.md`), chạy thử 1 đợt nhỏ để xác nhận mọi thứ ổn định
trước khi tính vào kết quả chính thức:
```bash
kubectl -n techx-tf3 set env deploy/load-generator LOCUST_USERS=50 LOCUST_SPAWN_RATE=5
kubectl -n techx-tf3 rollout restart deploy/load-generator
# chạy ~5 phút, quan sát HPA/observability memory/checkout-rollout như Bước 2
```
Nếu ổn (không chạm abort threshold, observability không gần chạm limit mới) → **dừng loadgen, reset
stats** (Locust UI → Stop → Reset Stats, hoặc `LOCUST_USERS=0`) rồi mới sang Bước 1. Không để traffic
của lần ramp thử này lẫn vào số liệu 200 user chính thức.

## Bước 1 — Chạy load-generator ở 200 user / 15 phút
`load-generator` là Locust. Điều khiển qua env hoặc UI (truy cập UI qua đường **riêng tư**, không public):
```bash
# Cách A - set cấu hình rồi restart loadgen:
kubectl -n techx-tf3 set env deploy/load-generator LOCUST_USERS=200 LOCUST_SPAWN_RATE=20
kubectl -n techx-tf3 rollout restart deploy/load-generator
# đợi ~15 phút

# Cách B - qua Locust UI (private): port-forward rồi điều khiển
kubectl -n techx-tf3 port-forward svc/load-generator 8089:8089
#   -> http://localhost:8089  đặt Users=200, Spawn rate=20, Run 15m
```
> Cùng cấu hình tải (200 user, 15 phút) cho cả 4 TF để so công bằng — theo mandate.

## Bước 2 — Quan sát trong lúc test (SLO + co giãn)
Grafana (private, qua bastion + port-forward — xem `private-access-to-ops-uis.md`):
- `apm-dashboard`: checkout success ≥99%, browse/cart ≥99.5%, p95 <1s.
- `postgresql-dashboard`: connection count không cạn (REL-05 giữ pool).
```bash
watch kubectl -n techx-tf3 get hpa      # thấy replicas CO LÊN theo tải
watch kubectl get nodes                  # Karpenter thêm Spot node nếu pod Pending
kubectl get nodepool,nodeclaim           # NodePool/NodeClaim trạng thái Spot burst
```

## Bước 3 — Sau đỉnh: xác nhận CO XUỐNG (không neo tài nguyên/tiền)
Tắt tải (Locust stop / LOCUST_USERS về mức thường), rồi đợi ~5-10 phút:
```bash
kubectl -n techx-tf3 get hpa      # replicas co về min (2)
kubectl get nodes                  # node co về baseline on-demand
kubectl get nodeclaim              # Spot NodeClaim được consolidate/xóa khi rảnh
```
- Đây là bằng chứng **co lên → co xuống**: pod & node trở về baseline.
- **Đổi lại `consolidateAfter: 3m → 2m`** trong `gitops/karpenter/spot-nodepool.yaml` sau khi Mandate 2
  xong hẳn (giá trị gốc trước Mandate 2 là `2m`) — không gấp bằng việc gỡ `do-not-disrupt` (mục dưới),
  nhưng vẫn nên làm để về đúng baseline.
- **Gỡ `podAnnotations.karpenter.sh/do-not-disrupt`** khỏi `cart`/`checkout`/`payment`/`shipping`/`quote`/
  `postgresql`/`valkey-cart` (7 component — 2 cái sau do PR #112 Mandate #3 thêm khi merge) trong
  `values-prod.yaml` ngay sau khi xác nhận co xuống xong — đây mới là cái đang thật sự chặn
  Karpenter tối ưu chi phí node (PDB không thay thế được, xem `../mandates/mandate-02/mandate-02-load-test-remediation-plan.md`
  mục 0). Không quên bước này.

## Bước 4 — Nộp evidence (theo README mandate)
1. **SLO giữ:** screenshot/dexport Grafana 15 phút @200 user — 3 ngưỡng SLO đều đạt.
2. **Cost trong trần:** cost trước/sau (Cost Explorer); tính **cost/đơn** = cost cửa sổ test / số đơn
   thành công → so baseline, chứng minh **không phình**.
3. **Co giãn:** bảng replicas + node theo mốc (trước / đỉnh / sau) cho thấy về lại mức thường.
4. Cho mentor lệnh chạy lại (Bước 1) để tự chứng kiến.

## Nếu SLO tụt trong test (rollback)
- Dừng tải ngay (Locust stop).
- Nếu do HPA/Karpenter bất ổn → `git revert` manifest Mandate #2 → ArgoCD prune → về baseline replicas cố định.
- Điều tra bottleneck (thường: CPU request quá thấp làm HPA scale sai, hoặc datastore bão hòa) → tinh
  chỉnh target/request → test lại. Bottleneck tầng latency/perf: phối hợp CDO01.

## Ràng buộc suốt test
- Storefront public, ops private (Mandate #1) — không mở public cổng ops để tiện xem.
- **KHÔNG đụng flagd.** Không tăng cứng tài nguyên cố định để "chắc gánh nổi" (mandate cấm).

# Mandate #2 — Phân tích capacity trước khi chạy load test 200 user/15 phút

**Cập nhật:** 14/07/2026 — sau khi `values-prod.yaml` được set resource request/limit tường minh cho toàn bộ component (trước đó nhiều service chỉ có `limits.memory`, request suy ra qua LimitRange/chart mirror).
**Nguồn dữ liệu:** live cluster (`kubectl` qua SSM tunnel, snapshot mới nhất) + `phase3 - information/deploy/values-prod.yaml`, `gitops/infrastructure/hpa-hotpath.yaml`, `gitops/infrastructure/resource-quota.yaml`, `gitops/karpenter/spot-nodepool.yaml`, `infra/modules/eks-platform/main.tf`.

---

## 1. HPA hot-path — request/limit mới từ `values-prod.yaml` (không còn mirror request=limit)

Khác với bản trước: giờ mỗi service có **request và limit tách riêng** (`components.<service>.resources`), không còn do chart tự mirror memory request=limit nữa. min/max HPA **không đổi**.

| Service | min | max | CPU req/pod | CPU limit/pod | Mem req/pod | Mem limit/pod |
|---|---|---|---|---|---|---|
| frontend-proxy | 2 | 8 | 100m | 500m | 32Mi | 65Mi |
| frontend | 2 | 8 | 100m | 500m | 100Mi | 250Mi |
| product-catalog | 2 | 8 | 100m | 500m | 16Mi | 20Mi |
| cart | 2 | 6 | 100m | 500m | 64Mi | 160Mi |
| checkout | 2 | 8 | 100m | 500m | 16Mi | 20Mi |
| currency | 2 | 6 | 100m | 300m | 8Mi | 20Mi |
| recommendation | 1 | 4 | 100m | 500m | 64Mi | 500Mi |
| product-reviews | 2 | 6 | 100m | 500m | 80Mi | 150Mi |
| ad | 1 | 4 | 100m | 500m | 200Mi | 300Mi |
| **Tổng (min → max)** | **16** | **58** | | | | |

CPU request vẫn đồng loạt 100m (không đổi) → HPA target 65%/request vẫn đúng ý đồ cũ. **Live xác nhận** (`kubectl get hpa -n techx-tf3`): 9/9 vẫn đọc metric OK, replicas đang ở min (2-2-2-2-2-2-1-2-1 = 16), CPU 1-7% (idle).

**Quan trọng — request và limit trả lời 2 câu hỏi khác nhau, đừng gộp chung:**
- **CPU/mem request** → scheduler dùng để quyết định pod đặt lên node nào (tổng request phải ≤ allocatable của node). Đây là con số "chắc chắn có".
- **CPU/mem limit** → trần cứng kernel throttle (CPU) / OOMKill (memory) nếu container cố vượt. Đây là con số "tối đa CÓ THỂ dùng nếu traffic dồn cùng lúc" — **không được scheduler kiểm khi đặt pod**, nên tổng limit của mọi pod trên 1 node hoàn toàn có thể vượt capacity thật của node (gọi là overcommit) mà K8s vẫn cho chạy bình thường — chỉ khi tất cả cùng lúc cố dùng tới limit thì mới lộ ra vấn đề (CPU bị throttle, không phải bị kill).
- **Không ai "scale" CPU của 1 pod từ request lên limit** — CPU pod dùng bao nhiêu là do traffic thật đánh vào (Locust), dao động tự nhiên trong khoảng [0, limit]. HPA **không** đụng vào limit của pod nào — việc HPA làm là khi CPU **trung bình** các pod hiện có > 65% **request** (tức > 65m/pod), nó **thêm pod mới** (tăng replica) để chia bớt tải ra, chứ không nâng trần của pod đang chạy.

## 2. ResourceQuota `techx-tf3` — KHÔNG ĐỔI (vẫn là gap chính)

`gitops/infrastructure/resource-quota.yaml` **chưa được cập nhật** cùng đợt với `values-prod.yaml`:

```yaml
hard:
  requests.memory: 16Gi
  limits.memory: 20Gi
  pods: "50"
```

**Snapshot live mới nhất:**

```
pods: 39/50                       (không đổi)
requests.memory: 6438Mi/16Gi      (~39%, giảm so với 8443Mi trước — sizing mới nhẹ hơn)
limits.memory: 11228Mi/20Gi       (~56%, tăng so với 9693Mi — limit nhiều service được nới thực tế hơn)
```

Vẫn không có trần CPU nào trong quota đang áp dụng (khác seed BTC `deploy/quota.yaml` có `requests.cpu: 4`) — same lưu ý như bản trước, chưa thấy sửa.

## 3. Node capacity + Karpenter — không đổi

3 node `t3.large` tĩnh (2 vCPU/~7.8Gi capacity mỗi node, ~1.93 vCPU/~7.08Gi allocatable), chưa node nào do Karpenter tạo (chưa có tải). `cluster-autoscaler` vẫn không có trong `gitops/apps/` — node tĩnh không tự scale. Karpenter NodePool `flash-sale-spot` vẫn trần `cpu: 12, memory: 48Gi`.

## 4. Tính lại tổng resource — số liệu live thật (kubectl, đã đối soát pod-by-pod), tách rõ HIỆN TẠI vs CHIẾU TẠI MAX

Bảng dưới lấy từ `kubectl get pods -n techx-tf3 -o json`, cộng dồn request/limit thật của từng container trong từng pod (kể cả sidecar) — không suy từ values.yaml nữa, nên khớp gần khít số quota live (lệch ~1-3% do sai số thời điểm/làm tròn).

| | Pods | CPU req | CPU limit | Mem req | Mem limit |
|---|---|---|---|---|---|
| **9 service HPA — ở MIN (live, hiện tại)** | 16 | 1.6 vCPU | 7.6 vCPU | 896Mi | 2 170Mi |
| **9 service HPA — ở MAX (chiếu, chưa xảy ra)** | 58 | 5.8 vCPU | **27.8 vCPU** | 3 280Mi | 8 020Mi |
| Baseline 23 pod (cố định, không HPA) | 23 | 1.55 vCPU | 7.0 vCPU | 5 456Mi | 8 723Mi |
| **TỔNG HIỆN TẠI (39 pod, khớp live)** | **39** | 3.15 vCPU | 14.6 vCPU | **~6 350Mi** (live quota báo 6438Mi) | **~10 900Mi** (live quota báo 11228Mi) |
| **TỔNG NẾU HPA SCALE HẾT (81 pod, chiếu)** | **81** | **7.35 vCPU** | **34.8 vCPU** | **8 736Mi (~8.53Gi)** | **16 743Mi (~16.35Gi)** |

*(Baseline dùng số live thật — trước đó tôi ước tính grafana chỉ 1 sidecar, thực tế grafana có **3 sidecar container** (alerts/dashboards/datasources), mỗi cái ăn resource riêng → grafana pod thật request 538Mi/limit 1268Mi, không phải 346Mi/756Mi như bản trước. `flagd-ui` không còn tồn tại (đã gỡ khỏi chart), không tính.)*

### Đọc bảng này thế nào

- **Memory (request lẫn limit):** dư nhiều ở cả 2 kịch bản — hiện tại mới ~40-56% trần, chiếu tại max cũng chỉ ~53%/16Gi request và ~82%/20Gi limit. **Không phải điểm nghẽn.**
- **CPU request:** 7.35 vCPU cần (max) vs ~17.8 vCPU capacity (3 node tĩnh ~5.79 vCPU + Karpenter burst 12 vCPU) → **đủ để schedule**, không phải điểm nghẽn cho việc *đặt pod lên node*.
- **CPU limit: 34.8 vCPU nếu tất cả 81 pod cùng lúc cố dùng hết trần của nó — vượt gần gấp đôi tổng capacity thật (~17.8 vCPU).** Đây là rủi ro **khác** với chuyện pod bị `Pending` — pod vẫn chạy được (vì scheduler chỉ xét request), nhưng khi traffic dồn thật, nhiều pod cùng lúc bị cgroup throttle vì tổng nhu cầu CPU vượt phần cứng có — biểu hiện là **latency tăng đột biến** đúng lúc tải đỉnh, đe doạ SLO `storefront p95 < 1s`, không phải pod chết hay Pending.
- **`pods: "50"` vẫn là điểm nghẽn CỨNG nhất và đến SỚM nhất** — chỉ còn 11 pod dư từ baseline 39/50, trong khi cần thêm 42 pod (16→58) chỉ riêng 9 service HPA. Quota này chặn HPA tạo pod mới **trước khi** kịp chạm tới rủi ro CPU-limit throttle ở trên (vì sẽ không đủ pod để tổng limit thật sự lên tới 34.8vCPU) — nhưng **sau khi nâng `pods` quota**, CPU-limit-throttle ở trên trở thành rủi ro **thật, cần theo dõi** trong lúc chạy test (xem CPU throttling qua `kubectl top pod` / Grafana, không chỉ xem HPA có scale được hay không).

### Khuyến nghị
1. **Bắt buộc:** nâng `pods` trong `gitops/infrastructure/resource-quota.yaml` lên **90-100** trước khi chạy load test — không cần đụng `requests.memory`/`limits.memory`, dư nhiều.
2. **Nên làm thêm:** sau khi nâng pods quota, theo dõi CPU throttling (`kubectl top pod -n techx-tf3` hoặc panel CPU throttle trong Grafana nếu có) trong lúc chạy 200 user — nếu p95 latency tăng bất thường dù pod chưa Pending, khả năng cao là CPU-limit overcommit (mục trên), không phải thiếu pod hay thiếu memory. Cân nhắc nâng CPU limit của vài service hot nhất (`checkout`, `frontend-proxy`, `product-catalog`) nếu quan sát thấy throttle rõ.

## 5. metrics-server — không đổi, vẫn ổn

Vẫn là EKS-managed addon (`infra/modules/eks-platform/main.tf`), live xác nhận HPA đọc metric bình thường.

## 6. Load-generator — ĐÃ SỬA theo đúng khuyến nghị trước

`values-prod.yaml` giờ có:

```yaml
load-generator:
  envOverrides:
    - name: LOCUST_AUTOSTART
      value: "false"
    - name: LOCUST_BROWSER_TRAFFIC_ENABLED
      value: "false"
  resources:
    requests: { cpu: 200m, memory: 1Gi }
    limits: { cpu: "1", memory: 1500Mi }
```

- `LOCUST_BROWSER_TRAFFIC_ENABLED: "false"` — **đã tắt đúng như khuyến nghị**, loại bỏ rủi ro OOM do Chromium + nhiễu traffic pattern. ✅ Xong.
- `LOCUST_AUTOSTART: "false"` (trước đây `"true"`) — thay đổi thêm so với bản trước: giờ bài test **không tự chạy khi pod khởi động** nữa, phải chủ động bấm Start trên UI Locust (`kubectl -n techx-tf3 port-forward svc/load-generator 8089:8089` → mở `http://localhost:8089`, nhập **200 users / spawn rate** tại đó, bấm Start, canh **15 phút** rồi Stop). Cách này thực ra **hợp lý hơn** cho mandate: khớp đúng yêu cầu "cho mentor cách chạy lại hoặc chứng kiến bài test" — mentor tự bấm Start/Stop qua UI, không cần biết trước `LOCUST_USERS` đã set sẵn trong env là bao nhiêu.
- Do `LOCUST_AUTOSTART=false`, biến `LOCUST_USERS`/`LOCUST_SPAWN_RATE` trong values.yaml (`"10"`/`"1"`) **không còn ý nghĩa** cho lần chạy thật — số 200 user nhập trực tiếp trên UI lúc bấm Start, không cần sửa giá trị mặc định trong chart nữa.
- CPU request 200m cho load-generator: cần cộng thêm vào bảng baseline phía trên (đã tính) — không ảnh hưởng kết luận.

## 7. Kết luận — đã đủ điều kiện chạy 200 user / 15 phút và pass mandate-02 chưa?

**Vẫn chưa — đúng 1 gap duy nhất còn lại, mọi thứ khác đã sẵn sàng hoặc đã được sửa từ bản trước:**

| Hạng mục | Trạng thái |
|---|---|
| HPA 9 service hot-path (min/max, target CPU 65%) | ✅ Đúng, live xác nhận đọc metric OK |
| metrics-server | ✅ EKS-managed addon, hoạt động |
| Karpenter (burst 12 vCPU/48Gi) | ✅ Đã cấu hình |
| CPU **request** capacity ở max HPA | ✅ Dư — 7.35 vCPU cần vs ~17.8 vCPU sẵn có (đủ để schedule) |
| Memory quota ở max HPA (request lẫn limit) | ✅ Dư — request ~53%, limit ~82% trần, kể cả đã tính đủ 81 pod |
| Resource request/limit từng service | ✅ Đã set tường minh, hợp lý (trước đây thiếu) |
| `LOCUST_BROWSER_TRAFFIC_ENABLED` | ✅ Đã tắt — xong, không cần làm gì thêm |
| `LOCUST_USERS`/`AUTOSTART` | ✅ Đã chuyển sang chạy tay qua UI (hợp lý hơn cho việc mentor verify) — nhập 200 lúc bấm Start |
| **`pods: "50"` ResourceQuota** | ❌ **Blocker cứng, đến sớm nhất** — 81 pod cần ở kịch bản max, chỉ còn 11 pod dư từ baseline 39/50. **Chưa thấy sửa trong đợt update này.** |
| CPU **limit** overcommit ở max HPA | ⚠️ **Rủi ro mềm, chỉ lộ ra SAU khi hết blocker trên** — tổng limit lý thuyết 34.8 vCPU vượt ~2x capacity thật (~17.8 vCPU); không chặn pod chạy nhưng có thể gây CPU throttle/latency spike đúng lúc đỉnh tải nếu nhiều service cùng lúc cày gần trần. Không phải điều kiện chặn cứng để bắt đầu test, nhưng nên theo dõi khi chạy. |

**Việc bắt buộc trước khi chạy thật:** nâng `pods` trong `gitops/infrastructure/resource-quota.yaml` (đề xuất 90-100). **Việc nên làm thêm:** theo dõi CPU throttling trong lúc chạy 200 user, vì đây là rủi ro thật (dù không chặn test bắt đầu) mà quota/HPA hiện tại không tự bảo vệ được.

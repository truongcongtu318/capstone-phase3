# ARM NodePool Foundation — Thiết kế

## Trạng thái

- Thiết kế được duyệt trong hội thoại ngày 2026-07-29.
- Tài liệu này chỉ phê duyệt **capacity foundation**. Chưa chuyển thêm service
  nào sang ARM trong cùng PR.
- Mọi thay đổi production đi qua PR, Argo CD reconcile và live verification.
  Không apply, patch hoặc sync tay.

## Mục tiêu

Chuẩn hóa capacity ARM để các service multi-arch có thể được chuyển dần sang
Graviton mà vẫn giữ:

- ARM Spot là lựa chọn chính để tối ưu chi phí;
- ARM On-Demand là pool fallback có preference thấp hơn Spot; weight giảm xác
  suất chọn fallback nhưng không phải cơ chế failover tuyệt đối;
- giới hạn node rõ ràng để không scale ngoài kiểm soát;
- rollback độc lập với từng đợt chuyển service;
- SLO hiện tại: browse/cart `>= 99.5%`, checkout `>= 99%`, storefront p95
  `< 1s`;
- ngân sách toàn hệ thống khoảng `$300/tuần`.

## Hiện trạng đã kiểm chứng

Snapshot live read-only ngày 2026-07-29, Argo CD revision
`ee9177d6a7d90d1f18b2e806e9e43823aecaeec9`:

- `flash-sale-spot-arm64` đang Ready với 2 node `c6g.large`, đúng cap 2;
- chỉ `product-catalog` được hard-pin sang ARM bằng
  `techx.io/arch: arm64`;
- `flash-sale-spot` AMD đang ở cap 2;
- trong rollout `frontend-proxy`, một pod mới không đặt được trên hai node AMD
  Spot hiện có, nên Karpenter đã tạo một node
  `elastic-ondemand-fallback` AMD;
- NodePool ARM hiện cho phép category `c`, `m`, `r`, `t`, chưa có ARM
  On-Demand fallback.

Karpenter provision theo pod `Unschedulable`, resource requests và scheduling
constraints. `spec.limits` là giới hạn vận hành, không phải desired count; tăng
cap không tự tạo node. Việc kiểm tra limits có eventual consistency nên rapid
scale-out vẫn cần theo dõi NodeClaim thay vì coi cap là hard billing boundary.

Tài liệu tham chiếu:

- <https://karpenter.sh/preview/concepts/nodepools/>
- <https://docs.aws.amazon.com/eks/latest/best-practices/karpenter.html>
- <https://docs.aws.amazon.com/eks/latest/best-practices/cost-opt-compute.html>

## Phạm vi

### Trong phạm vi

1. Chuẩn hóa ARM Spot cho workload CPU/memory thông thường.
2. Tăng cap ARM Spot từ 2 lên 4 node.
3. Thêm ARM On-Demand cold fallback tối đa 2 node.
4. Thêm contract test cho scheduling/capacity contract.
5. Ghi rõ verification và rollback.

### Ngoài phạm vi

- chuyển service sang ARM;
- thay HPA, resource requests/limits hoặc topology spread;
- thay AMD Spot và AMD On-Demand fallback;
- giảm managed On-Demand nodegroup từ 4 xuống 3;
- sửa application code hoặc build lại image;
- thay đổi `flagd`, OpenFeature, `/flagservice` hoặc
  `envoy.filters.http.fault`;
- chạy interruption exercise hoặc load test trong PR foundation.

## Các phương án

### A. Tách ARM Spot và ARM On-Demand fallback — chọn

Hai NodePool dùng cùng workload/architecture contract nhưng khác capacity type,
weight, limits và EC2 tags.

Ưu điểm:

- theo dõi và cap Spot/On-Demand độc lập;
- cost attribution rõ;
- fallback có thể scale về 0;
- rollback không ảnh hưởng AMD;
- phù hợp rollout từng service.

Đánh đổi:

- thêm một NodePool và một EC2NodeClass;
- cần giữ selector/taint contract đồng bộ giữa hai pool.

### B. Một ARM NodePool cho cả Spot và On-Demand

Ít YAML hơn và Karpenter có thể ưu tiên Spot trước On-Demand, nhưng không tách
được cap, weight và cost attribution theo capacity type rõ như phương án A.

### C. Chỉ tăng ARM Spot

Rẻ nhất ở steady state nhưng không có đường cấp capacity tương thích khi ARM
Spot tạm thời thiếu. Pod hard-pin ARM có thể Pending lâu hơn và critical-path
migration sau này có rủi ro cao hơn.

## Thiết kế được chọn

### ARM Spot

Sửa `NodePool/flash-sale-spot-arm64`:

| Thuộc tính | Giá trị |
|---|---|
| Architecture | `arm64` |
| Capacity type | `spot` |
| Weight | `100` |
| Instance category | `c`, `m` |
| Instance generation | `> 2` |
| Instance CPU | `2`, `4` |
| Instance memory | `> 3072 MiB` |
| Max nodes | `4` |
| Max CPU | `16` |
| Max memory | `64Gi` |
| Consolidation | `WhenEmptyOrUnderutilized`, sau `10m` |

Giữ nguyên hai taint:

```yaml
techx.io/workload=elastic:NoSchedule
techx.io/arch=arm64:NoSchedule
```

Lý do chọn `c/m`:

- `c` phù hợp service CPU-oriented;
- `m` cung cấp lựa chọn cân bằng khi service cần thêm memory;
- loại `t` để tránh CPU credit trở thành biến số khi tải kéo dài;
- loại `r` vì workload dự kiến chưa có nhu cầu memory-optimized;
- vẫn giữ diversity qua nhiều generation, hai kích thước CPU và nhiều AZ.

### ARM On-Demand cold fallback

Thêm:

- `NodePool/elastic-ondemand-fallback-arm64`;
- `EC2NodeClass/elastic-ondemand-fallback-arm64`.

NodePool dùng cùng architecture, category, size và taint contract với ARM Spot,
nhưng:

| Thuộc tính | Giá trị |
|---|---|
| Capacity type | `on-demand` |
| Weight | `10` |
| Max nodes | `2` |
| Max CPU | `8` |
| Max memory | `32Gi` |
| Consolidation | `WhenEmptyOrUnderutilized`, sau `10m` |

EC2NodeClass:

- giữ AMI ARM AL2023 đã được production chứng minh trên hai node hiện tại;
- giữ subnet/security-group discovery hiện có;
- có tag `techx.io/capacity: on-demand-fallback` và
  `techx.io/arch: arm64`;
- dùng NodeClass riêng để EC2 cost attribution không bị gắn nhầm là Spot.

Fallback không có min/desired node. Operational target sau khi tải ổn định và
qua cửa sổ consolidation là 0 node, nhưng đây không phải invariant được
Karpenter hoặc kube-scheduler đảm bảo.

### Workload contract cho các PR sau

Một service chỉ vào ARM khi pod có đủ:

```yaml
nodeSelector:
  techx.io/workload: elastic
  techx.io/arch: arm64
tolerations:
  - key: techx.io/workload
    operator: Equal
    value: elastic
    effect: NoSchedule
  - key: techx.io/arch
    operator: Equal
    value: arm64
    effect: NoSchedule
```

Không hard-pin service vào Spot hay On-Demand. Weight chỉ bias lựa chọn NodePool
khi Karpenter provision capacity mới; kube-scheduler không đọc weight và có thể
đặt pod lên fallback node đang tồn tại. Vì vậy fallback node count phải được
theo dõi như một operational target, không được dùng weight để claim Spot-first
tuyệt đối.

## Thứ tự delivery

1. PR foundation: NodePool + EC2NodeClass + contract test.
2. Merge và chờ Argo CD reconcile.
3. Xác minh NodePool Ready, không có unexpected churn/Pending.
4. Chuyển từng service bằng PR riêng, bắt đầu từ nhóm rủi ro thấp.
5. Mỗi service phải có canary/runtime proof trên ARM trước khi chuyển service
   tiếp theo.

Không gộp migration service vào PR foundation vì sẽ làm khó phân biệt lỗi
capacity với lỗi runtime architecture.

## Verification

### Trước merge

- contract test phải fail với manifest cũ và pass sau thay đổi;
- YAML parse thành công;
- kiểm tra toàn bộ YAML trong Argo directory `gitops/karpenter` thấy đúng 4
  NodePool và các EC2NodeClass tương ứng;
- Kubernetes server-side dry-run cho directory này thành công;
- diff không đụng workload, HPA, application code hoặc protected flag/fault
  paths.

### Sau merge

- Argo applications liên quan `Synced/Healthy` tại đúng revision merge;
- `flash-sale-spot-arm64` Ready với cap 4;
- `elastic-ondemand-fallback-arm64` Ready;
- sau ít nhất một cửa sổ consolidation với tải ổn định, ARM fallback đạt target
  0 node; nếu không, phải ghi nhận nguyên nhân và chưa chuyển critical service;
- hai node ARM Spot `c6g.large` hiện tại vẫn Ready; chúng còn thỏa requirement
  `c/m`, nên thay đổi này không được kỳ vọng tạo Drift;
- `product-catalog` vẫn 2/2 Ready;
- không có critical pod Pending, OOMKilled hoặc restart bất thường;
- SLO/customer path không xấu đi.

## Rủi ro và kiểm soát

| Rủi ro | Kiểm soát |
|---|---|
| Unexpected Drift hoặc NodeClaim churn | Hai node `c6g.large` vẫn thỏa `c/m`; monitor và coi Drift/churn do PR là no-go để điều tra |
| ARM Spot thiếu capacity | ARM On-Demand có weight thấp hơn và capacity cap riêng |
| Fallback được chọn dù Spot còn khả dụng | Weight là preference, không guarantee; theo dõi NodeClaim/capacity type và chặn critical migration nếu fallback không về target |
| Fallback tồn tại sau khi hết tải | Consolidation `WhenEmptyOrUnderutilized` sau `10m`; xác minh live thay vì suy ra từ YAML |
| Hard topology spread tạo thêm node | Giữ cap rõ ràng; đánh giá per-service trong PR migration |
| Pool quá hẹp làm giảm Spot diversity | Cho cả `c/m`, nhiều generation, 2/4 CPU và nhiều AZ |
| Chi phí vượt kiểm soát | ARM Spot cap 4, ARM fallback cap 2; fallback 0 là target cần đo |
| Rapid provisioning tạm vượt limits | Theo dõi NodeClaim/capacity type và AWS budget; không coi `spec.limits` là hard billing boundary |

## Rollback

Nếu foundation gây churn hoặc scheduling xấu:

1. revert PR qua Git;
2. Argo CD tự reconcile;
3. trả ARM Spot về cap 2 và category `c/m/r/t`;
4. prune ARM On-Demand fallback NodePool/EC2NodeClass;
5. xác minh `product-catalog` vẫn 2/2 Ready trên ARM Spot.

Không rollback bằng patch/delete trực tiếp trên production.

## Tiêu chí hoàn thành

- manifest và contract test pass;
- chỉ hai manifest Karpenter, contract test, workflow trigger và tài liệu liên
  quan nằm trong diff;
- ARM Spot có cap 4 và chỉ dùng `c/m`;
- ARM On-Demand fallback có cap 2, weight thấp và có evidence live cho target
  scale-down về 0 trước khi migrate critical service;
- AMD capacity giữ nguyên;
- không service nào bị chuyển architecture trong PR;
- live verification sau merge không có regression.

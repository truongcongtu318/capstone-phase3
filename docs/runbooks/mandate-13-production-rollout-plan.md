# Mandate 13 - Ke hoach rollout production an toan

Tai lieu nay giai thich ro thay doi du kien cho Mandate 13, tai sao can thay doi, rui ro nao da duoc kiem soat, va can verify gi sau khi merge.

## 1. Muc tieu

Thay doi nay nham day production toi trang thai co the dat cac dieu kien con thieu cua Mandate 13:

1. spot share vuot 50% theo huong evidence cua mandate
2. co arm64/Graviton live tren production
3. khong tao SPOF moi truoc khi quay video

## 2. Hien trang truoc thay doi

Snapshot read-only ngay 24/07/2026:

- Tong node: `8`
- Spot node: `3`
- On-demand node: `5`
- Ty le spot: `37.5%`
- Toan bo node dang la `amd64`

Nhan dinh:

- Production da co spot that
- Critical path da chay tren spot
- Nhung chua dat `>= 50% spot`
- Chua co `arm64` live, nen chua claim duoc Graviton

## 3. Thay doi duoc dua vao PR

### 3.1. Tat stateful nodegroup dang rong

Phan Terraform duoc them de cho phep tat han `stateful_1a` bang bien `enable_stateful_node_group = false`.

Ly do:

- Nodegroup nay duoc tao cho PostgreSQL/Valkey in-cluster
- Hai datastore nay da retire o production
- Kiem tra thuc te khong con pod `techx-tf3` nao nam tren node do
- Giu node on-demand rong se lam ty le spot xau di ma khong tang an toan he thong

Tac dung mong doi:

- Giam 1 on-demand node rong
- Khong giam headroom cua 4 node on-demand dang ganh observability va workload nen

### 3.2. Them arm64 spot NodePool rieng va bo freeze consolidation

Them `flash-sale-spot-arm64` trong Karpenter voi:

- `kubernetes.io/arch = arm64`
- `karpenter.sh/capacity-type = spot`
- taint rieng `techx.io/arch = arm64:NoSchedule`
- `limits.nodes = 2`

Dong thoi:

- bo `budgets.nodes: "0"` tren pool Spot hien co
- ha `consolidateAfter` ve `3m` de con co the chung minh co xuong

Ly do:

- NodePool spot hien tai hardcode `amd64`
- Du image da multi-arch thi production van khong len duoc arm64 neu khong mo nodepool rieng
- Freeze consolidation se auto-fail yeu cau co xuong
- Tach nodepool arm64 rieng giup rollout theo cach co kiem soat, khong day toan bo workload sang arm64 ngay

### 3.3. Chi opt-in `product-catalog` sang arm64

Them file override rieng `values-mandate13.yaml` va moc vao Argo Application.

Workload duoc chon:

- `product-catalog`

Ly do chon:

- la workload stateless
- da co `2 replicas`
- da co PDB
- da co topology spread hard theo zone/hostname
- image dang deploy la OCI image index, co the hien la multi-arch
- failure cua no khong tao SPOF moi nhu phuong an `recommendation`

### 3.4. Right-size request truoc khi cat sau node

PR dong thoi dieu chinh request cho mot so workload de tranh tinh trang node "khong vua tren giay" du tai that con thap, hoac nguoc lai scheduler xep duoc nhung runtime lai bi memory pressure:

- `load-generator`: ha memory request tu `1Gi -> 256Mi`
- `prometheus`: nang memory request tu `450Mi -> 900Mi`
- `opensearch`: nang memory request tu `750Mi -> 1280Mi`

Ly do:

- `load-generator` dang giu request cao hon usage rat nhieu, lam ton headroom scheduler khong can thiet
- `prometheus` va `opensearch` la nhom observability de nhay cam, request thieu de tao false-fit va memory pressure khi hạ baseline node
- right-size truoc giup bai test Mandate 13 sat hon voi yeu cau `request vua du`, khong chi don thuan cat node

## 4. Tai sao khong sua manh tay hon

Khong chon cac huong sau:

- khong giam node on-demand observability dang ganh Grafana/Prometheus/Jaeger/OpenSearch
- khong dua `checkout` len arm64 ngay
- khong doi nodepool spot hien co tu `amd64` sang `amd64+arm64` cho tat ca workload

Ly do:

- cac huong do kho predict hon
- de lam xau he thong that truoc khi co evidence
- kho khoanh vung neu rollout loi

Phuong an trong PR nay uu tien:

- thay doi it nhat
- de rollback
- de chung minh yeu cau mandate truoc

## 5. Kiem tra an toan da lam truoc PR

Da kiem tra:

1. `kubectl top nodes`
   - node `ip-10-0-4-166` dung rat thap
2. `kubectl -n techx-tf3 get pods -o wide --field-selector spec.nodeName=ip-10-0-4-166...`
   - khong co pod `techx-tf3` nao tren node stateful
3. `kubectl get nodeclaims`
   - hien co 3 spot nodeclaim
4. `aws ecr describe-images` cho tag product-catalog dang deploy
   - `imageManifestMediaType = application/vnd.oci.image.index.v1+json`
   - xac nhan la manifest list, khong phai single-arch image
5. `terraform validate`
   - pass
6. `kubectl apply --dry-run=client -f gitops/karpenter/spot-nodepool.yaml`
   - pass
7. `kubectl apply --dry-run=client -f gitops/apps/techx-corp.yaml`
   - pass
8. `terraform plan -refresh=false "-target=module.eks_platform"`
   - cho thay y do chinh la destroy nodegroup `stateful_1a`

## 6. Anh huong du kien sau merge

Neu rollout thanh cong:

- `stateful_1a` bi go bo
- baseline default on-demand giam tu `4 -> 3`
- Karpenter co the tao toi da `2` arm64 spot node cho `product-catalog`
- production co arm64 live de claim Graviton
- co cua so thuc te de do lai spot share va node-hours thay vi chi dem node

## 7. Rui ro con lai

Van con 4 nhom rui ro can theo doi sau merge:

1. `product-catalog` co the image multi-arch nhung runtime van gap issue rieng tren arm64
2. Karpenter co the chua tao du `2` arm64 spot node neu scheduler chua canh tranh du de dat pod moi
3. Ha baseline on-demand tu `4 -> 3` van la thay doi ha tang that, can theo doi sat observability headroom
4. Go `stateful_1a` can xac nhan lai khong con phu thuoc an danh nao ngoai `techx-tf3`

## 8. Cach verify sau merge

Chay cac lenh sau:

```powershell
kubectl --kubeconfig C:\Users\Admin\.kube\config --server=https://localhost:8443 --insecure-skip-tls-verify=true get nodes -L karpenter.sh/capacity-type,node.kubernetes.io/instance-type,kubernetes.io/arch,topology.kubernetes.io/zone
```

```powershell
kubectl --kubeconfig C:\Users\Admin\.kube\config --server=https://localhost:8443 --insecure-skip-tls-verify=true -n techx-tf3 get pods -o wide
```

```powershell
kubectl --kubeconfig C:\Users\Admin\.kube\config --server=https://localhost:8443 --insecure-skip-tls-verify=true get nodeclaims
```

```powershell
$nodes = kubectl --kubeconfig C:\Users\Admin\.kube\config --server=https://localhost:8443 --insecure-skip-tls-verify=true get nodes -L karpenter.sh/capacity-type --no-headers
$spot = ($nodes | Select-String "spot").Count
$total = ($nodes | Measure-Object).Count
"total=$total spot=$spot ratio=$([math]::Round(($spot*100.0)/$total,2))%"
```

Dieu can thay:

- co node `arm64`
- `product-catalog` nam tren node `arm64`
- scale-down con hoat dong, khong bi freeze
- he thong van xanh, khong co pod critical bi Pending

## 9. Binh luan cho buoi review

Noi gon:

- thay doi nay khong co tinh chat "toi uu dep"
- day la rollout co chu dich de sua dung 3 gap that cua Mandate 13: `arm64 live`, `khong tao SPOF`, `co xuong that`
- chon workload 2 replica + PDB thay vi workload 1 replica

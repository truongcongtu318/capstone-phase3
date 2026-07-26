# ADR 0012 - Mandate 13: Spot + Graviton rollout khong tao SPOF

**Ngay:** 24/07/2026
**Nguoi quyet dinh (ky):** Ha Tay Nguyen
**Trang thai:** De xuat rollout production
**Pham vi:** Reliability + Cost + Operational Excellence cho Mandate 13

## Boi canh

Production hien da co Spot that va nhieu workload critical path da chay tren Spot, nhung van con 3 gap:

1. Spot chua vuot 50% ro rang theo huong evidence cua mandate
2. Chua co arm64/Graviton live
3. NodePool Spot dang bi freeze consolidation, nen khong the chung minh co xuong that

Mot phuong an truoc do dua `recommendation` len arm64 tren pool Spot rieng da bi loai bo vi:

- `recommendation` chi co 1 replica
- khong co PDB
- neu mat 1 Spot node se tao SPOF moi
- freeze consolidation lam hong yeu cau scale-down

## Quyet dinh

Chon phuong an moi:

1. tat nodegroup `stateful_1a` da rong o production
2. ha baseline managed on-demand nodegroup tu `4 -> 3`
3. bo freeze consolidation tren NodePool Spot hien co
4. them NodePool `flash-sale-spot-arm64` cho Spot arm64
5. chi opt-in `product-catalog` sang arm64
6. right-size `load-generator` va nang memory request cho `prometheus`/`opensearch`

## Tai sao chon `product-catalog`

`product-catalog` duoc chon thay vi `recommendation` vi:

- da co `2 replicas`
- da co PDB
- da co topology spread hard theo zone/hostname
- image dang deploy la OCI image index multi-arch
- khong phai frontend ingress point duy nhat
- khong tao SPOF moi khi mat 1 Spot node

## Tai sao khong them on-demand arm64 fallback

Trong vong rollout nay, uu tien dau tien la:

- khong tao SPOF
- dat Graviton live
- de Spot share vuot 50%

Neu them on-demand arm64 fallback ngay lap tuc, spot share co nguy co bi keo xuong va cost floor tang len.
Voi `product-catalog` co 2 replica + PDB + spread theo node/zone, mat 1 Spot node van con replica con lai song, phu hop hon phuong an 1-replica truoc day.

## Danh doi duoc chap nhan

- Khi mat 1 Spot node, `product-catalog` van song nho replica con lai, nhung replacement pod co the cho arm64 Spot moi len roi moi dat lai 2/2.
- Giam baseline on-demand tu 4 xuong 3 van tao ap luc cho Spot/Karpenter, nhung an toan hon muc 4 xuong 2 trong rollout dau tien.
- Viec nang request cho `prometheus` va `opensearch` co the lam scheduler chat hon tren giay, nhung doi lai giam rui ro memory pressure/evict khi test that.
- Muc tieu cua thay doi nay la dat dung huong mandate va tao cua so quay evidence, khong claim san la da pass toan bo.

## Bat buoc evidence sau rollout

Sau khi merge va sync production, phai thu duoc cac bang chung sau:

1. `kubectl get nodes` cho thay co `arm64` live
2. `kubectl get pods -o wide` cho thay `product-catalog` len node arm64
3. Spot share > 50% trong evidence runtime/history phu hop
4. Node count co xu huong co xuong that sau khi giam tai
5. Dien tap mat 1 Spot node khong lam rot request khach hang

## Rollback

Neu rollout xau di:

1. bo file override `values-mandate13.yaml`
2. bo NodePool `flash-sale-spot-arm64`
3. tra `node_desired_size/node_min_size` ve 4
4. bat lai `enable_stateful_node_group` neu can

Rollback phai qua GitOps/Terraform, khong sua tay production.

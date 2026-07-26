# Chaos experiments — Mandate #15 (bơm lỗi thật cho AIOps engine)

Bộ kịch bản để AIO02 chấm điểm AIOps engine bằng **lỗi thật trên cụm thật**, thay vì
dữ liệu giả. Hạ tầng do CDO02 dựng; việc chạy và chấm là của AIO02.

> 📘 **Bản hướng dẫn đầy đủ để gửi AIO02:**
> [`docs/runbooks/mandate-15-aiops-chaos-runbook.md`](../docs/runbooks/mandate-15-aiops-chaos-runbook.md)
> — gồm 4 kịch bản, lệnh khắc phục đã kiểm chứng, tiêu chí đạt, số đo từ chạy nháp,
> query Grafana và lệnh dừng khẩn cấp. File này chỉ là ghi chú kỹ thuật của CDO02.

| Scenario | File | Cơ chế | Thời lượng |
|---|---|---|---|
| 1. Bắt đúng | [`scenario-1-payment-latency.yaml`](experiments/scenario-1-payment-latency.yaml) | NetworkChaos (tc netem) | 10m |
| 2A. Không bị che — sự cố thật | [`scenario-2a-payment-real-issue.yaml`](experiments/scenario-2a-payment-real-issue.yaml) | NetworkChaos | 10m |
| 2B. Không bị che — nhiễu | [`scenario-2b-recommendation-noise.yaml`](experiments/scenario-2b-recommendation-noise.yaml) | StressChaos | 5m |
| 3. Không kêu oan | [`scenario-3-flash-sale-load.md`](experiments/scenario-3-flash-sale-load.md) | Locust ramp (không phải CRD) | giữ tải 10m |
| 4. Tự khắc phục thành công | [`scenario-4-capacity-shortage.yaml`](experiments/scenario-4-capacity-shortage.yaml) | NetworkChaos, chậm 1 pod | 10m |

> **Scenario 2: apply CẢ HAI file cùng lúc ở T+0.** Nhiễu sống T+0→T+5 (chấm tách
> cluster khi cả hai cùng anomaly), rồi T+5→T+10 chỉ còn payment (chấm không bỏ sót sau
> khi nhiễu tắt). Engine chạy liên tục nên luôn warm — không cần canh lệch giờ.

## Vì sao không dùng flagd

Flag `paymentFailure` / `recommendationCacheFailure` mô tả đúng hiện tượng, nhưng giá trị
**đang chạy thật** đồng bộ từ nguồn trung tâm của BTC (`values-flagd-sync.yaml`) — TF chỉ
đọc được, không set được. Sửa `src/flagd/demo.flagd.json` không inject gì cả, đó chỉ là bản
seed tham khảo. Đổi TOKEN/URI sang nguồn khác là **disqualify cả TF**.

Chaos Mesh bơm ở tầng k8s/network/cgroup nên **không chạm gì tới đường đọc flag**, và
AIO02 không phải chờ mentor bật flag mới chạy được bài test.

## Cài Chaos Mesh

Manifest ArgoCD: [`gitops/apps/chaos-mesh-app.yaml`](../gitops/apps/chaos-mesh-app.yaml),
namespace: [`gitops/infrastructure/namespace-chaos-mesh.yaml`](../gitops/infrastructure/namespace-chaos-mesh.yaml).

**Auto-sync tắt có chủ đích** — sau khi merge phải vào ArgoCD bấm Sync app `chaos-mesh`
một lần. Công cụ có khả năng gây sự cố thì việc cài phải là hành động người bấm.

Kiểm tra sau khi sync:

```bash
export AWS_PROFILE=techx-new
kubectl -n chaos-mesh get pod -o wide
```

Phải thấy `chaos-controller-manager` ×2 Running và `chaos-daemon` chạy trên **mọi node**
(DaemonSet). Thiếu node nào thì pod chạy trên node đó không bơm lỗi được.

## Vì sao experiment KHÔNG nằm trong ArgoCD

Cố ý. Nếu để chúng trong một Application có `selfHeal: true`:

- Muốn bơm lỗi phải mở PR và chờ merge — không dùng được trong một buổi demo.
- **Kill switch chết**: `kubectl delete` để dừng sự cố sẽ bị ArgoCD tạo lại ngay, vì file
  vẫn còn trong git. Đúng lúc cần dừng gấp thì không dừng được.

Nên: operator do GitOps quản (luôn có, ổn định), còn experiment thì `kubectl apply` thủ
công. Đây cũng là lý do file scenario để ở `chaos/` chứ không phải `gitops/`.

## Dừng khẩn cấp

```bash
kubectl -n techx-tf3 delete networkchaos,stresschaos,podchaos --all
```

Chaos Mesh gỡ netem/stress khỏi pod đích, không cần restart pod. Ngoài ra mỗi scenario đều
có `duration` — hết giờ tự gỡ kể cả khi không ai nhớ delete. **Đừng bỏ field `duration`.**

Xem trạng thái đang bơm gì:

```bash
kubectl -n techx-tf3 get networkchaos,stresschaos -o wide
kubectl -n techx-tf3 describe networkchaos m15-s1-payment-latency
```

## Giới hạn blast radius

Hai lớp, đã verify bằng `helm template`:

1. `clusterScoped: false` + `targetNamespace: techx-tf3` — RoleBinding **chỉ** sinh ở
   `techx-tf3`. Chaos Mesh không có quyền đụng `argocd`, `kube-system`, `external-secrets`,
   `argo-rollouts`. Kể cả gõ nhầm namespace trong CR cũng không inject được.
2. Không có datastore nào còn nằm trong cụm sau Mandate #8 (RDS/ElastiCache/MSK đều là
   managed, ngoài VPC-nội-cụm) → không có đường nào để một experiment lỡ tay phá dữ liệu.

## ⚠️ Điều PHẢI biết trước khi chấm điểm "tự khắc phục"

Scenario 1 trong spec kỳ vọng engine tự Scale/Restart rồi **giải phóng được nghẽn**. Có một
vấn đề về bản chất cần thống nhất với AIO02 trước, nếu không sẽ chấm sai:

**Chaos Mesh giữ lỗi cho tới khi hết `duration` hoặc bị delete.** Nó không phải lỗi tự khỏi
khi restart pod. Restart hay scale trong lúc experiment còn sống thì controller vẫn giữ
netem trên các pod đã bị chọn. Nghĩa là:

- Đo được: engine **quyết định đúng** hành động gì, và **thực thi được** (qua màng lọc C6).
- **Không** đo được bằng cách này: "sau khi engine hành động thì sự cố hết". Sự cố hết là
  do `duration` chạy hết giờ, không phải do engine.

Đây không phải lỗi của Chaos Mesh — flagd cũng y hệt (flag còn bật thì restart vô ích).
Muốn đo *hiệu quả* của remediation thì lỗi phải thuộc loại **thiếu năng lực phục vụ**
(pod ít, CPU cạn) mà thêm replica là đỡ thật. Chưa có trong 3 file này; cần AIO02 chốt có
muốn bổ sung scenario 4 dạng đó không.

Riêng Scenario 2 và 3 **không dính vấn đề này** — chúng chỉ chấm phát hiện/phân cụm, chạy
được nguyên trạng.

## Trước buổi diễn thật

- [ ] Chạy nháp **từng scenario một** ngoài giờ cao điểm, chưa chấm điểm, để chỉnh cường độ
      (đặc biệt `load` của StressChaos ở Scenario 2 — xem ghi chú trong file đó).
- [ ] Xác nhận `chaos-daemon` có mặt trên mọi node, gồm cả node Karpenter mới nổi lên.
- [ ] **Báo trước cho CDO01 + AIO02** khung giờ chạy. Scenario 1 và 2 phá SLO thật; không
      báo thì sẽ có người mở postmortem cho một sự cố do chính mình tạo ra.
- [ ] Kiểm tra không trùng lịch với batch Karpenter elastic của CDO01 (PR #316→#330) —
      node đang bị xáo trộn thì phép đo lead-time nhiễu.
- [ ] Ghi lại mốc `AllInjected` của mỗi experiment làm t0 cho lead-time.

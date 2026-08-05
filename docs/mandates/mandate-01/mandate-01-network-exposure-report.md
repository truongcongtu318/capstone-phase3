# Mandate #1 — Báo cáo tách storefront công khai và cổng vận hành riêng tư

**Directive:** `MANDATE-01-network-exposure.md` (bản directive do Ban Hạ tầng & Bảo mật cung cấp)<br>
**Ngày hoàn tất least-exposure ban đầu:** 13/07/2026<br>
**Ngày chuyển đường truy cập vận hành sang Cloudflare Zero Trust:** 15/07/2026<br>
**Ngày kiểm chứng lại:** 16/07/2026 (UTC+7)<br>
**Nhóm thực hiện:** TF3 (CDO01 phối hợp CDO02)<br>
**Người xác nhận/chứng kiến (mentor):** _(điền sau khi mentor kiểm tra)_<br>
**Kết quả:** **PASS — storefront vẫn công khai; Grafana, Jaeger và ArgoCD được bảo vệ bởi Cloudflare Access; các route vận hành cũ không còn đi qua cổng public.**

---

## 1. Tóm tắt thay đổi

TF3 đã tách riêng các luồng truy cập theo mục đích sử dụng:

- **Luồng truy cập của khách hàng:** storefront tiếp tục được cung cấp công khai qua CloudFront và internal ALB đến `frontend-proxy`.
- **Luồng truy cập vận hành:** Grafana, Jaeger và ArgoCD chỉ được truy cập qua Cloudflare Tunnel và Cloudflare Access. Người dùng chưa có phiên SSO hợp lệ sẽ không thể truy cập các ứng dụng này.
- **Luồng quản trị cluster:** EKS API sử dụng hostname tunnel riêng cho `kubectl`; sau khi vượt qua lớp Cloudflare Access, người dùng vẫn phải được xác thực và phân quyền bằng AWS IAM/EKS access entry.

Phương án đầu tiên của nhóm cho Mandate #1 là **SSM bastion + `kubectl port-forward`**. Sau đó nhóm đã chuyển đường truy cập thường ngày của các UI vận hành sang **Cloudflare Zero Trust** để mentor/người được cấp quyền có thể đăng nhập trực tiếp bằng trình duyệt, không phải có quyền `kubectl` hoặc vận hành bastion. SSM hiện chỉ được giữ làm **đường fallback**, không phải đường truy cập chính của báo cáo này.

```text
Khách hàng ── Internet ── CloudFront ── internal ALB ── frontend-proxy ── storefront

Người vận hành ── Cloudflare Access (SSO) ── Cloudflare Tunnel (outbound-only)
                                             ├── Grafana Service
                                             ├── Jaeger Service
                                             ├── ArgoCD Service
                                             └── EKS private API (kubectl + IAM)
```

`cloudflared` chủ động kết nối **outbound** từ trong cluster tới Cloudflare; hệ thống không mở thêm inbound port hoặc public LoadBalancer cho các UI vận hành.

## 2. Phạm vi exposure sau thay đổi

| Thành phần | Trạng thái internet | Đường truy cập được phép | Kết quả |
|---|---|---|---|
| Storefront | Công khai | CloudFront | ✅ Giữ public |
| Grafana | Không cho truy cập ứng dụng khi chưa xác thực | Cloudflare Access + SSO | ✅ Private sau identity-aware proxy |
| Jaeger | Không cho truy cập ứng dụng khi chưa xác thực | Cloudflare Access + SSO | ✅ Private sau identity-aware proxy |
| ArgoCD | Không cho truy cập ứng dụng khi chưa xác thực | Cloudflare Access + SSO, sau đó đăng nhập ArgoCD | ✅ Private sau identity-aware proxy |
| EKS API / kubectl | EKS endpoint private-only | Cloudflare Access TCP tunnel + AWS IAM/EKS access entry | ✅ Hai lớp kiểm soát |
| `/feature` (flagd UI) | Bị chặn trên public edge | Không công khai | ✅ Gỡ UI quản trị khỏi storefront |
| `/loadgen` | Bị chặn trên public edge | Chỉ vận hành nội bộ khi cần | ✅ Không công khai |
| `/flagservice/` | Giữ nguyên | Kênh runtime của flagd | ✅ Không vô hiệu hóa cơ chế bơm sự cố |

Các route `/grafana`, `/jaeger`, `/feature` và `/loadgen` đã được gỡ khỏi cấu hình Envoy. ArgoCD vốn là `ClusterIP` và không có route public. `/flagservice/` và fault-injection filter được giữ nguyên theo Luật chơi.

## 3. Bằng chứng kiểm chứng ngày 16/07/2026

Kiểm tra được chạy từ một máy trên internet, **không có Cloudflare Access session**:

| URL kiểm tra | HTTP | Diễn giải | Đạt? |
|---|---:|---|---|
| `https://d2tn71186d7ilz.cloudfront.net/` | `200` | Storefront truy cập công khai | ✅ |
| `https://d2tn71186d7ilz.cloudfront.net/grafana` | `403` | Route Grafana cũ bị chặn ở public edge | ✅ |
| `https://d2tn71186d7ilz.cloudfront.net/jaeger` | `403` | Route Jaeger cũ bị chặn ở public edge | ✅ |
| `https://d2tn71186d7ilz.cloudfront.net/feature` | `403` | flagd UI không còn public | ✅ |
| `https://d2tn71186d7ilz.cloudfront.net/loadgen` | `403` | Load-generator UI không còn public | ✅ |
| `https://grafana.arthur-ngo.org/` | `302` → Cloudflare Access login | Chưa xác thực không vào được Grafana | ✅ |
| `https://jaeger.arthur-ngo.org/jaeger/ui/` | `302` → Cloudflare Access login | Chưa xác thực không vào được Jaeger | ✅ |
| `https://argocd.arthur-ngo.org/` | `302` → Cloudflare Access login | Chưa xác thực không vào được ArgoCD | ✅ |

Lệnh để mentor tự kiểm tra lớp public/unauthenticated:

```sh
curl -sS -o /dev/null -w '%{http_code}\n' https://d2tn71186d7ilz.cloudfront.net/
curl -sS -o /dev/null -w '%{http_code}\n' https://d2tn71186d7ilz.cloudfront.net/grafana
curl -sS -o /dev/null -w '%{http_code}\n' https://d2tn71186d7ilz.cloudfront.net/jaeger
curl -sS -o /dev/null -w '%{http_code}\n' https://d2tn71186d7ilz.cloudfront.net/feature
curl -sS -o /dev/null -w '%{http_code}\n' https://d2tn71186d7ilz.cloudfront.net/loadgen
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://grafana.arthur-ngo.org/
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://jaeger.arthur-ngo.org/jaeger/ui/
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://argocd.arthur-ngo.org/
```

Kỳ vọng: storefront `200`; bốn path ops cũ `403` hoặc `404`; các hostname ops trả `302` về domain đăng nhập `cloudflareaccess.com` nếu chưa có session hợp lệ.

## 4. Cách mentor truy cập để đánh giá

### 4.1 Điều kiện trước khi kiểm tra

1. Mentor gửi email sẽ dùng để đăng nhập cho đầu mối TF3.
2. TF3 thêm đúng email đó vào allowlist của Cloudflare Access. Không commit email, token hoặc thông tin xác thực vào repo.
3. Mentor mở cửa sổ trình duyệt riêng tư để kiểm tra cả trường hợp chưa đăng nhập và đã đăng nhập.

### 4.2 Kiểm tra UI vận hành

1. Mở một trong các URL:
   - Grafana: `https://grafana.arthur-ngo.org`
   - Jaeger: `https://jaeger.arthur-ngo.org/jaeger/ui/`
   - ArgoCD: `https://argocd.arthur-ngo.org`
2. Cloudflare Access yêu cầu xác thực email/SSO.
3. Đăng nhập bằng email đã được TF3 allowlist.
4. Xác nhận Grafana và Jaeger mở được. Với ArgoCD, sau khi qua Cloudflare Access vẫn phải đăng nhập vào chính ArgoCD.
5. Mở lại URL bằng cửa sổ ẩn danh hoặc email không nằm trong allowlist; xác nhận không truy cập được ứng dụng.

### 4.3 Kiểm tra storefront

Mở `https://d2tn71186d7ilz.cloudfront.net/` mà không dùng VPN/tunnel và thực hiện browse → cart → checkout. Storefront phải tiếp tục hoạt động công khai.

Hướng dẫn vận hành đầy đủ và cách dùng tunnel cho `kubectl` nằm tại [cloudflare-zero-trust-access.md](runbooks/cloudflare-zero-trust-access.md).

## 5. Reliability, Security, Auditability và chi phí

### Security

- Chỉ storefront đi qua public delivery path.
- Mỗi UI có một Cloudflare Access application và allow policy riêng.
- Tunnel kết nối outbound-only; không tạo public inbound port cho cluster.
- EKS API vẫn private-only và yêu cầu thêm AWS IAM/EKS authorization.
- Tunnel credential nằm trong Kubernetes Secret tạo ngoài Git; repo không lưu token thật.

### Reliability

- Việc gỡ route ops khỏi Envoy không thay đổi route storefront.
- `cloudflared` chạy 2 replica và có PodDisruptionBudget `minAvailable: 1`.
- Storefront hiện trả `200` sau thay đổi; các bài kiểm tra Mandate #2/#3 sau thời điểm least-exposure cũng xác nhận storefront vẫn giữ các ngưỡng SLO trong các cửa sổ test tương ứng. Xem [Mandate #2 load-test report](../../mandates/mandate-02/mandate-02-load-test-report.md) và [Mandate #3 drain-node report](../../mandates/mandate-03/mandate-03-drain-node-report.md).

### Auditability

- Cloudflare Access là điểm xác thực tập trung trước các UI và cung cấp sự kiện truy cập theo identity/session trong Zero Trust dashboard.
- Thay đổi được quản lý bằng Terraform, manifest GitOps và lịch sử PR/commit.
- Mentor có thể kiểm tra cả luồng bị từ chối và luồng được phép bằng chính identity được cấp.

### Chi phí

- Dùng Cloudflare Zero Trust free tier phù hợp quy mô nhóm hiện tại và domain có sẵn.
- Không phát sinh public ALB/LoadBalancer riêng cho Grafana, Jaeger hoặc ArgoCD.
- Chi phí cluster chỉ tăng phần tài nguyên nhỏ của 2 pod `cloudflared` (`50m CPU/32Mi` request mỗi pod; `200m CPU/128Mi` limit mỗi pod), nằm trong hạ tầng hiện hữu.

## 6. Timeline và quyết định chuyển từ SSM sang Cloudflare

| Mốc | Thay đổi |
|---|---|
| 13/07/2026 | Gỡ các route observability/admin khỏi Envoy; storefront và `/flagservice/` được giữ nguyên. Mandate đạt least-exposure bằng đường private SSM bastion + port-forward. |
| 15/07/2026 | Bổ sung Cloudflare Tunnel/Access trực tiếp tới Grafana, Jaeger và ArgoCD; sửa health/metrics để `cloudflared` chạy ổn định. |
| 16/07/2026 | Kiểm chứng lại public storefront, các path bị chặn và Cloudflare Access redirect từ internet. |

Lý do chuyển:

- Mentor/người vận hành dùng trình duyệt + SSO, không cần cài AWS CLI, Session Manager plugin và `kubectl` chỉ để xem dashboard.
- Policy được gắn theo từng application và identity, hẹp hơn việc cấp quyền cluster.
- Hai replica tunnel tránh phụ thuộc vào một bastion instance cho luồng UI thường ngày.
- SSM vẫn là break-glass/fallback trong giai đoạn hiện tại; việc gỡ hẳn chỉ thực hiện sau một quyết định riêng và bằng chứng vận hành đủ dài.

## 7. Rollback và giới hạn còn lại

### Rollback

- Nếu Cloudflare route gặp sự cố, người vận hành có quyền dùng SSM bastion + `kubectl port-forward` theo [private-access-to-ops-uis.md](runbooks/private-access-to-ops-uis.md).
- Không rollback bằng cách mở lại `/grafana`, `/jaeger`, `/feature` hoặc `/loadgen` trên storefront public.
- Không sửa hoặc vô hiệu hóa `/flagservice/` và cơ chế fault injection.

### Giới hạn được công khai

- Domain `arthur-ngo.org` là domain cá nhân đang dùng tạm; nên chuyển sang domain do tổ chức sở hữu trước khi vận hành dài hạn.
- Kiểm chứng ngày 16/07 xác nhận lớp truy cập từ internet. Phiên này không thực hiện kiểm tra live pod/EKS vì máy kiểm chứng không có AWS profile `techx-new`; trạng thái runtime trong cluster được dẫn từ manifest GitOps và runbook đã merge.
- SSM bastion vẫn còn trong Terraform làm fallback. Vì vậy, kiến trúc hiện tại là **Cloudflare Zero Trust primary + SSM fallback**, chưa phải “đã xoá toàn bộ SSM”.

## 8. Đối chiếu Directive #1

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| Storefront công khai, không gián đoạn | ✅ Đạt | HTTP `200` ngày 16/07; route storefront không đổi; report Mandate #2/#3 có SLO sau thay đổi. |
| Grafana, Jaeger, ArgoCD không truy cập công khai | ✅ Đạt | Public path cũ `403`; hostname ops chuyển tới Cloudflare Access login khi chưa xác thực. |
| Người có quyền vẫn truy cập được qua đường riêng | ✅ Đạt về thiết kế và runbook | Cloudflare Access allowlist + SSO; mục 4 cung cấp quy trình mentor tự kiểm tra. Chờ mentor ký xác nhận phiên đăng nhập. |
| Mentor có hướng dẫn tự đánh giá | ✅ Đạt | Mục 3 và mục 4. |
| Không phá storefront SLO | ✅ Đạt | Kiến trúc tách đường ops; report Mandate #2/#3 chứng minh các SLO trong các cửa sổ test sau thay đổi. |
| Không vượt ngân sách | ✅ Đạt | Không thêm public load balancer; dùng free tier và tài nguyên pod nhỏ trong cluster hiện hữu. |
| Không vô hiệu hóa flagd | ✅ Đạt | Chỉ gỡ `/feature` UI; `/flagservice/` được giữ nguyên. |
| Có khả năng audit truy cập | ✅ Đạt về control | Cloudflare Access là điểm identity/policy/log tập trung; lịch sử thay đổi nằm trong Git/Terraform/GitOps. |

## 9. Kết luận

**Mandate #1 đạt yêu cầu kỹ thuật.** Storefront vẫn là bề mặt công khai duy nhất dành cho khách hàng; các UI vận hành không còn route qua storefront và được đặt sau Cloudflare Access. Phương án hiện tại cải thiện trải nghiệm truy cập so với SSM bastion nhưng vẫn giữ SSM làm fallback có kiểm soát.

Việc còn lại để đóng hồ sơ: mentor đăng nhập bằng email được allowlist, kiểm tra ba UI, thử lại bằng cửa sổ ẩn danh và điền tên/xác nhận ở đầu báo cáo.

## 10. Tài liệu và artifact liên quan

- [ADR Mandate #1 — least-exposure Envoy](adr/0004-mandate-01-cdo01-envoy-least-exposure.md)
- [Runbook Cloudflare Zero Trust](runbooks/cloudflare-zero-trust-access.md)
- [Runbook private ops UI / SSM fallback](runbooks/private-access-to-ops-uis.md)
- [Terraform Cloudflare Access root](../infra/live/production/cloudflare-access.tf)
- [Terraform module Cloudflare Access](../infra/modules/cloudflare-access/main.tf)
- [GitOps deployment cloudflared](../gitops/infrastructure/cloudflared.yaml)

---

_TF3 xác nhận các thông tin nhạy cảm như Cloudflare API token, tunnel token và danh sách email thật không được đưa vào báo cáo hoặc commit vào repository._

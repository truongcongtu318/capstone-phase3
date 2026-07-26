# Báo cáo triển khai Mandate-19 (PM-154)

## 1. Mục tiêu
Thực thi Mandate-19 (Throughput Ceiling & Load Shedding) qua PR **PM-154**, tập trung cấu hình giới hạn luồng yêu cầu ở mức Application Gateway (Envoy proxy) và tách biệt hoàn toàn với **PM-153** (cấu hình HPA & Circuit Breaker).

## 2. Các hạng mục đã hoàn thành trên nhánh `feat/mandate-19`

### 2.1. Phân loại Route (Route Classification)
Sửa đổi file cấu hình `phase3 - information/techx-corp-platform/src/frontend-proxy/envoy.tmpl.yaml`:
- **Protected Routes (`protected_routes`)**: Được bảo vệ tuyệt đối, không bị rate-limit bởi policy load-shedding thông thường. 
  - Các route quan trọng của hệ thống Checkout: `/api/cart`, `/api/checkout`, `/api/products/<id>`.
- **Browse / Shedable Routes (`browse_shedable`)**: Áp dụng load-shedding để giảm tải hệ thống khi có traffic spike.
  - Các route duyệt web hoặc gọi API không trọng yếu.

### 2.2. Triển khai Shadow Mode cho Token Bucket
Áp dụng Token Bucket với cấu hình "Shadow Mode" ban đầu để theo dõi, đánh giá (chưa block traffic thật):
- Bật filter `envoy.filters.http.local_ratelimit`
- Đặt `stat_prefix: browse_rate_limiter`
- Cấu hình tạm thời: `max_tokens: 100`, `tokens_per_fill: 100` để quan sát (do `filter_enforced: 0` nên hệ thống không thực sự drop request).
*(Sau khi thu thập metrics từ PM-153 overload test, con số này sẽ được tính toán lại = floor(0.70 × breakpoint_RPS / proxy_ready) và apply vào chế độ Enforce ở PM-154b).*

### 2.3. Xác thực cấu hình Envoy bằng CI
Do các chính sách bảo vệ chặt chẽ của hệ thống (Contract Test PM-149) ngăn cấm việc sửa đổi thư mục `.github/workflows/` kết hợp với các thay đổi ngoài luồng, tôi đã không tạo thêm workflow mới.
Thay vào đó, tôi đã chèn trực tiếp tiến trình validate Envoy vào `Dockerfile` của frontend-proxy:
- Bổ sung lệnh: `envsubst < envoy.tmpl.yaml > /tmp/envoy-rendered.yaml && envoy --mode validate -c /tmp/envoy-rendered.yaml`
- Truyền đầy đủ giả lập cho 21 biến môi trường (ví dụ: `ENVOY_PORT=8080`, `FLAGD_HOST=localhost`, v.v.) để bảo đảm file sinh ra là hợp lệ về cấu trúc YAML lẫn logic Envoy.
- Việc này giúp CI hiện tại (`build-push-ecr.yml`) **tự động xác thực** cấu hình khi build image mà không vi phạm các luật Contract.

### 2.4. Giải quyết các Blocker của CI & Test Pipeline
Đảm bảo toàn bộ quy định "Immutable" và "Contract Testing" của nền tảng được nguyên vẹn:
- **Revert `test-image-bump.yml`**: Trả lại nguyên trạng để không thay đổi các thông số `fetch-depth` ngoài phạm vi.
- **Revert `test_pm149_rbac_least_privilege.py`**: Trả lại nguyên trạng 100% so với nhánh `main`. Không sử dụng `@pytest.mark.skip`, không phá bỏ giới hạn check 6 files của PM-149. PM-154 tuân thủ bằng cách không chạm vào `.github/workflows/` hay `scripts/ci/` để không vô tình trigger các strict validation pipeline nằm ngoài phạm vi.

## 3. Các bước tiếp theo
1. Thực hiện review và merge PR **PM-154**.
2. Branch out riêng nhánh `feat/pm-153` để cấu hình HPA target 75% cho các dịch vụ `browse` và giới hạn Circuit Breaker Envoy.
3. Thu thập Metrics cho Envoy Rate-limit từ "Shadow Mode", tính toán con số giới hạn chính thức, và mở PR bổ sung để kích hoạt chế độ "Enforce Mode".

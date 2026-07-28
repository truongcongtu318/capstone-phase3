# Yêu Cầu Triển Khai Hệ Thống (CDO Deploy Request) - CẬP NHẬT BIGUPDATE SPRINT 3

Chào anh em CDO,

Bên AIO/AIE1 đã hoàn thành nâng cấp dịch vụ `product-reviews` kết nối trực tiếp với AWS Bedrock, đồng thời hoàn thiện hệ thống Caching 2 tầng, bộ điều khiển sự cố (Actuator) phục vụ kịch bản Closed-Loop Mitigation.

> [!WARNING]
> **LƯU Ý QUAN TRỌNG KHI MERGE CODE (TRÁNH XOÁ MẤT CODE CÁC DỊCH VỤ KHÁC):**
> 
> Nhánh `feature/product-review` đã được tối giản hóa bằng việc xóa các thư mục của 16 dịch vụ khác để thuận tiện phát triển dịch vụ `product-reviews`. Do đó, **KHÔNG MERGE TRỰC TIẾP** nhánh này vào `main` vì sẽ gây xung đột và xóa mất code các dịch vụ khác trên `main`.
> 
> **Cách merge an toàn (chỉ lấy thay đổi của product-reviews & hạ tầng):**
> ```bash
> git checkout main
> git pull origin main
> git checkout feature/product-review -- "phase3 - information/techx-corp-platform/src/product-reviews/"
> git checkout feature/product-review -- "phase3 - information/deploy/values-aio-llm.yaml"
> git checkout feature/product-review -- "infra/iam.tf" "infra/outputs.tf"
> git checkout feature/product-review -- "CDO_DEPLOYMENT_MESSAGE.md"
> git add .
> git commit -m "feat: deploy bigupdate product-reviews from AIE1 (caching, actuator, IRSA)"
> git push origin main
> ```

Dưới đây là các đầu việc chi tiết nhờ anh em CDO hỗ trợ triển khai khi deploy phiên bản mới này lên EKS:


### 1. Database Migration (Quan trọng - thực hiện trước khi deploy app):
* **Yêu cầu quyền:** Nhờ anh em dùng tài khoản Postgres Admin / Superuser để thực hiện chạy tệp migration.
* **Chạy migration SQL:**
  * [migration.sql](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/techx-corp-platform/src/product-reviews/migration.sql):
    1. Thêm cột `is_safe` (mặc định `TRUE`) và index `productreviews_prod_safe_idx` vào bảng `reviews.productreviews`.
    2. Tạo bảng audit `reviews.fidelity_audit` lưu vết đánh giá AI và phân quyền cho user `otelu`.
    3. **Tạo bảng mới `reviews.product_summaries`** (lưu trữ bản tóm tắt tĩnh phục vụ Caching Tầng 2 - Fallback) và cấp quyền `GRANT SELECT, INSERT, UPDATE, DELETE ON reviews.product_summaries TO otelu`.
* **Chạy worker đồng bộ dữ liệu cũ:**
  * Export biến môi trường `DB_CONNECTION_STRING` và chạy tệp [db_migration_worker.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/techx-corp-platform/src/product-reviews/db_migration_worker.py) để tự động quét toàn bộ review cũ và đánh dấu `is_safe = FALSE` nếu vi phạm bộ lọc Regex Guardrail. Chạy độc lập ngoài request path để tránh ảnh hưởng hệ thống.

### 2. Cấu hình Redis Caching:
* Hệ thống đã tích hợp Caching 2 tầng (Redis Real-time Cache + Postgres Static Summary Fallback).
* Nhờ anh em kiểm tra kết nối gRPC/HTTP tới Valkey/Redis của cluster, đảm bảo dịch vụ nhận được các biến môi trường kết nối Redis (đã cấu hình mặc định tự động nhận diện, hỗ trợ TLS `rediss://`).

### 3. Cổng điều khiển Sự cố (Actuator), Circuit Breaker & Telemetry (MANDATE #22):
* **Actuator:** Dịch vụ tự động lắng nghe Redis key `product_reviews:fallback_override`. Khi AIOps Detector set key này bằng `true` hoặc `1`, dịch vụ sẽ lập tức bypass hoàn toàn Bedrock và chuyển sang chế độ fallback (kết hợp Caching Tầng 2 từ Postgres).
* **Circuit Breaker:** Tự động ngắt mạch (`guardrails/circuit_breaker.py`) khi cuộc gọi Bedrock thất bại liên tục nhằm bảo vệ tài nguyên hệ thống và kích hoạt Fallback Tầng 2.
* **Error Injection Mode:** Bộ mô phỏng bơm lỗi (`guardrails/error_injection.py`) phục vụ các kịch bản diễn tập sự cố (Replay Sim `aiops_replay_sim.py`) cùng đội AIOps.
* **LLM Tracing & Tool Validator:** Tích hợp kiểm vết các lệnh LLM (`guardrails/llm_trace.py`) và xác thực tính hợp lệ của các tool call (`guardrails/tool_validator.py`).
* **Telemetry Metrics:** Xuất Prometheus metric `app_ai_fallback_total` để monitor lỗi kết nối LLM.


### 4. Build lại Docker Image:
* Đã cập nhật file `requirements.txt` (bổ sung `redis` bên cạnh `boto3` và `tenacity`) và toàn bộ mã nguồn liên quan.
* Nhờ anh em chạy script [build-push-images.sh](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/deploy/build-push-images.sh) để build multi-arch image mới (`1.0-product-reviews`) và push lên registry.

### 5. Helm Upgrade & Phân quyền AWS Bedrock (IRSA):
* **IAM Policy:** Đảm bảo ServiceAccount `techx-corp` trong namespace `techx-corp` được gắn IAM Role có quyền gọi Bedrock:
  * `bedrock:InvokeModel`
  * `bedrock:InvokeModelWithResponseStream`
  * `bedrock:ApplyGuardrail`
* **Helm Values:** Sử dụng cấu hình cập nhật tại [values-aio-llm.yaml](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/deploy/values-aio-llm.yaml) (đã tích hợp ServiceAccount role-arn annotation).
* **Lưu ý Helm Upgrade:** Nhớ áp dụng đồng thời cả file `values-aio-llm.yaml` lẫn `values-flagd-sync.yaml` để duy trì cơ chế sự cố flagd:
  ```bash
  helm upgrade techx-corp ./phase3\ -\ information/techx-corp-chart \
    -f ./phase3\ -\ information/deploy/values-aio-llm.yaml \
    -f ./phase3\ -\ information/deploy/values-flagd-sync.yaml \
    -n techx-corp
  ```

Cảm ơn anh em!

# 🌟 Thông Báo & Nhờ Hỗ Trợ Triển Khai Hệ Thống (CDO Deployment Request) - BigUpdate Sprint 3

**Thân gửi anh em Đội ngũ CDO (Cloud & DevOps),**

Lời đầu tiên, đội ngũ AIO/AIE1 xin gửi lời cảm ơn chân thành đến anh em CDO đã luôn đồng hành và hỗ trợ hệ thống nhiệt tình trong suốt thời gian qua!

Hiện tại, tụi mình đã hoàn tất nâng cấp bản **BigUpdate Sprint 3** cho dịch vụ `product-reviews` — chính thức kết nối trực tiếp với AWS Bedrock LLM, hoàn thiện hệ thống **Caching 2 tầng chịu lỗi**, bổ sung **Thread Pool Isolation** bảo vệ hiệu năng Read API và tích hợp cổng điều khiển sự cố tự động (**Actuator / Closed-Loop Mitigation**).

Dưới đây là một số lưu ý và các bước nhờ anh em CDO hỗ trợ triển khai giúp AIO/AIE1 khi deploy phiên bản mới này lên EKS nhé:

---

> [!TIP]
> **💡 Lưu ý nhỏ giúp tụi mình về quy trình Merge Code (Để giữ an toàn cho các dịch vụ khác trên `main`):**
> 
> Do nhánh `feature/product-review` đã được tối giản hóa (chỉ giữ mã nguồn dịch vụ `product-reviews` để tiện phát triển), anh em vui lòng **không merge trực tiếp** nhánh này vào `main` để tránh vô tình làm ảnh hưởng đến code của 16 dịch vụ khác nhé.
> 
> **Cách sync code an toàn và nhanh chóng:**
> ```bash
> git checkout main
> git pull origin main
> git checkout feature/product-review -- "phase3 - information/techx-corp-platform/src/product-reviews/"
> git checkout feature/product-review -- "phase3 - information/deploy/values-aio-llm.yaml"
> git checkout feature/product-review -- "infra/iam.tf" "infra/outputs.tf"
> git checkout feature/product-review -- "CDO_DEPLOYMENT_MESSAGE.md"
> git add .
> git commit -m "feat: deploy bigupdate product-reviews from AIE1 (caching, actuator, IRSA, thread-isolation)"
> git push origin main
> ```

---

## 🛠️ Danh Sách Các Đầu Việc Nhờ Anh Em CDO Hỗ Trợ

### 1. Database Migration (Thực hiện trước khi rollout App giúp tụi mình nhé):
* **Phân quyền:** Nhờ anh em sử dụng tài khoản **Postgres Admin / Superuser** để chạy script migration.
* **Chạy migration SQL:**
  * Thực thi file [migration.sql](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/techx-corp-platform/src/product-reviews/migration.sql) & [init.sql](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/techx-corp-chart/postgresql/init.sql):
    1. Bổ sung cột `is_safe` (mặc định `TRUE`) và index `productreviews_prod_safe_idx` cho bảng `reviews.productreviews`.
    2. Tạo bảng audit `reviews.fidelity_audit` để lưu vết đánh giá AI và phân quyền cho user `otelu`.
    3. **Tạo bảng mới `reviews.product_summaries`** (lưu bản tóm tắt tĩnh cho Caching Tầng 2 - Fallback) và cấp đủ quyền `GRANT SELECT, INSERT, UPDATE, DELETE ON reviews.product_summaries TO otelu`.
* **Chạy Worker đồng bộ dữ liệu lịch sử:**
  * Export biến môi trường `DB_CONNECTION_STRING` và hỗ trợ chạy tệp [db_migration_worker.py](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/techx-corp-platform/src/product-reviews/db_migration_worker.py) để quét toàn bộ review cũ và gắn cờ `is_safe = FALSE` nếu vi phạm bộ lọc Regex Guardrail. Tệp này chạy độc lập nên hoàn toàn không ảnh hưởng tới traffic thực tế.

---

### 2. Cấu Hình & Kiểm Tra Redis Caching:
* Hệ thống mới đã nâng cấp Caching 2 tầng (Redis Real-time Cache + Postgres Static Summary Fallback).
* Nhờ anh em kiểm tra giúp kết nối gRPC/HTTP tới Valkey/Redis Cluster, đảm bảo Pod nhận đủ biến môi trường kết nối Redis (hỗ trợ kết nối bảo mật `rediss://`).

---

### 3. Cổng Điều Khiển Sự Cố (Actuator), Circuit Breaker, Thread Isolation & Telemetry:
* **Actuator:** Tự động lắng nghe Redis key `product_reviews:fallback_override`. Khi AIOps Detector set key này bằng `true` / `1`, ứng dụng sẽ chuyển ngay sang chế độ fallback an toàn mà không cần restart Pod.
* **Circuit Breaker:** Tự động ngắt mạch (`guardrails/circuit_breaker.py`) khi Bedrock gặp sự cố liên tục để bảo vệ tài nguyên hạ tầng.
* **Thread Pool Isolation (Ticket S6):** Đã tách riêng luồng AI vào Thread Pool độc lập (`AI_EXECUTOR_MAX_WORKERS=15`), giúp các request AI nặng không làm ảnh hưởng tới 35+ luồng gRPC Read API của người dùng.
* **Error Injection & Telemetry:** Sẵn sàng bộ bơm lỗi diễn tập (`guardrails/error_injection.py`), bộ kiểm vết LLM (`guardrails/llm_trace.py`), Tool Validator (`guardrails/tool_validator.py`) và xuất Prometheus metric `app_ai_fallback_total`.

---

### 4. Build & Push Multi-Arch Docker Image:
* Đã cập nhật file `requirements.txt` (bổ sung `redis`) và toàn bộ mã nguồn liên quan.
* Nhờ anh em chạy script [build-push-images.sh](file:///C:/Users/ASUS/OneDrive/Obsidian%20Vault/XBrain-Phase3/Phase3-TF3-Infra-Sentinel/phase3%20-%20information/deploy/build-push-images.sh) để build multi-arch image mới (`1.0-product-reviews`) và push lên Docker Registry giúp tụi mình nha.

---

### 5. Helm Upgrade, Bảo Mật ServiceAccount & Phân Quyền AWS Bedrock (IRSA):
* **Bảo mật ServiceAccount (`automountServiceAccountToken: false`):** Helm Chart đã cập nhật `automountServiceAccountToken: false` cho ServiceAccount và Pod template nhằm tuân thủ tiêu chuẩn bảo mật K8s.
* **IAM Policy (IRSA):** Nhờ anh em kiểm tra ServiceAccount `techx-corp` trong namespace `techx-corp` được gắn IAM Role có đủ quyền gọi Bedrock: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`, `bedrock:ApplyGuardrail`.
* **Cú pháp Helm Upgrade:** Anh em áp dụng đồng thời file `values-aio-llm.yaml` và `values-flagd-sync.yaml` giúp tụi mình nhé:
  ```bash
  helm upgrade techx-corp ./phase3\ -\ information/techx-corp-chart \
    -f ./phase3\ -\ information/deploy/values-aio-llm.yaml \
    -f ./phase3\ -\ information/deploy/values-flagd-sync.yaml \
    -n techx-corp
  ```

---

Cảm ơn anh em CDO rất nhiều vì sự phối hợp tuyệt vời này! Chúc anh em một buổi deploy thật suôn sẻ và mượt mà! 

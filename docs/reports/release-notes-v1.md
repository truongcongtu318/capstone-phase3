# Release Notes & Image Inventory - V1

## Giới thiệu
Tài liệu này lưu trữ danh sách cố định (Digest Pinning) của toàn bộ các Container Images hiện đang chạy trên hệ thống EKS cho bản Release V1.
Nhờ việc cấu hình Tag Immutability trên Amazon ECR và việc sử dụng Digest (SHA256) trong Helm Chart, chúng ta đảm bảo 100% tính nguyên vẹn (Integrity) và bất biến của phần mềm khi deploy.

## 1. Internal Services (TechX Corp)
Các dịch vụ nội bộ được host trên ECR `techx-corp`.

| Service | Phiên bản (Tag) | Digest (SHA256) |
| --- | --- | --- |
| **accounting** | 6a3fe95-accounting | `sha256:8fc8a91f98ae40d6be284ff9009b32dd0e1e1c3152532362ed363f8bc71c4ed6` |
| **ad** | 58b13f2-ad | `sha256:a45fdb96972c11c4b75261ef1205f96c92f5c23fb5edbc47f3b6bb95eb3f27bb` |
| **cart** | 6a3fe95-cart | `sha256:1cc20ba4d7f195245429e084e5aa495a305ed0b14539261953f8595ab50c05b6` |
| **checkout** | 7527509-checkout | `sha256:a774cb69f27795406f768881a7c575ba882f024f8e99ca928413047f3b3eb532` |
| **currency** | 58b13f2-currency | `sha256:e4e4c76b27fea4d82bbc25aa2f2d6c2163450a223f89c71e7ae4985fb6c0203a` |
| **email** | 58b13f2-email | `sha256:ca14e55cc0855e3a8a2de19098d75f69772408d2bef6f9b52663e864ae1a545f` |
| **fraud-detection** | 58b13f2-fraud-detection | `sha256:b4797d6b16bf6a3b88ec8ddb9dbcd6c29c208e6be221f4f018af4b5f624fbc13` |
| **frontend** | 58b13f2-frontend | `sha256:047faed92fe4ecf8b2bb7d3d99c191a2d495f41024abc44c204fe94a9ae019a3` |
| **frontend-proxy** | 6a3fe95-frontend-proxy | `sha256:7cf4dd2e0c5cdf097ee8c56600ca94b31d4bd1fc04965dac13f6c26262287630` |
| **image-provider** | 58b13f2-image-provider | `sha256:00b73a3efd2caab3e69fce24b40b4e176da5c5f89b7b2c8ae2f37c25400cf44a` |
| **kafka** | 58b13f2-kafka | `sha256:afc05edcd00b7f56c8331d5e4a83c7ff6bf46182fd0667033529c964bccc2e68` |
| **llm** | 58b13f2-llm | `sha256:85a7578ef9b826196632fdd219eaa131f0caed024753499d036fc5baabf374b8` |
| **load-generator** | 58b13f2-load-generator | `sha256:db7016dbed1d6b24c5aa6beb1102fd11148aa791a6b61b745ef8fdebc6146641` |
| **payment** | 58b13f2-payment | `sha256:839b9cb5e5c50ba9a03acea8a4b15e29be724089e30cf18904530a1bc07bede5` |
| **product-catalog** | 6a3fe95-product-catalog | `sha256:412f75faac8b02fc48676c1fe2d3bc695e39b9cf6c0fbd6bb941c1fbea80f83f` |
| **product-reviews** | 6a3fe95-product-reviews | `sha256:4d5403f3b7beda840dad76b406e1a25f4d1dd90248638930ed4327bdb1517439` |
| **quote** | 58b13f2-quote | `sha256:97fbf36ede49bb20218b75bfe0f2c9e90ed976114813091abb11ca789f567df3` |
| **recommendation** | 6a3fe95-recommendation | `sha256:7b1246d011356a0e6d2b0b94b854b2bc3eb0ee06a502d02d9a79a3163b447b78` |
| **shipping** | 58b13f2-shipping | `sha256:4952c73703cca38ec8afe934a3571f5f0a5f5e8e2adeb4af3eafc5cfa5ddb3ec` |

> *Tất cả images trên được kiểm tra lỗ hổng tự động qua Amazon Inspector (Continuous Enhanced Scanning) và chặn ở bước CI/CD nếu vi phạm chính sách CRITICAL/HIGH (Trivy Scan Gate).*

## 2. External Dependencies (Third-Party Images)
Đây là các dịch vụ phụ trợ tải từ registry bên ngoài (Docker Hub, Quay, GHCR).

| Thành phần | Registry & Image | Digest (SHA256) | Lịch Review |
| --- | --- | --- | --- |
| **PostgreSQL** | docker.io/library/postgres | `sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929` | Hàng quý (Mỗi 3 tháng) |
| **Grafana** | docker.io/grafana/grafana | `sha256:0f86bada30d65ef9d0183b90c1e2682ac92d53d95da8bed322b984ea78a4a73a` | Hàng quý |
| **Jaeger** | docker.io/jaegertracing/jaeger | `sha256:6266573208d665ce5c17483bce0a75d0806480d92c84766d288d0aee885ce708` | Hàng quý |
| **OpenSearch** | docker.io/opensearchproject/opensearch | `sha256:b5dd1512af2a99748c942cfbbd7f32162623336b210667d0fc6333c6321f171d` | Hàng quý |
| **Prometheus** | quay.io/prometheus/prometheus | `sha256:c0b857aead0d5793aa566adb8f49a9983d6f6031652098759d521a330cfa050f` | Hàng quý |
| **OTel Collector** | docker.io/otel/opentelemetry-collector-contrib | `sha256:d57bfe8eee2378f31cb1193239fbcac521d54a5a071fca2bfc106916a32b892d` | Hàng quý |
| **Valkey** | docker.io/valkey/valkey | `sha256:c106a0c03bcb23cbdf9febe693114cb7800646b11ca8b303aee7409de005faa8` | Hàng tháng (Mới thay thế) |
| **Flagd** | ghcr.io/open-feature/flagd | `sha256:e6cca86b29629a06806aa7954b4a9b5f291c30839c6ae4f815dc4ddcee4a0746` | Hàng quý |

## 3. Quá trình kiểm soát rủi ro
1. ECR Tag Immutability ngăn chặn hoàn toàn khả năng một kẻ tấn công ghi đè image tag hợp lệ bằng một image độc hại.
2. Việc sử dụng SHA256 digest trong cấu hình ArgoCD/Helm đảm bảo rằng Kubernetes luôn luôn triển khai cùng một bit-for-bit container cho tất cả các nút và mỗi lần Rolling Update, kể cả khi Registry có sự thay đổi.
3. Nếu Argo Rollout tiến hành Rollback, quá trình Rollback không phụ thuộc vào tên tag (thứ có thể đã bị ghi đè), mà luôn tìm đúng digest cố định.

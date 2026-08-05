# Hướng dẫn chụp ảnh cho biên bản nghiệm thu Mandate #8

Đi kèm [biên bản nghiệm thu](../../mandates/mandate-08/mandate-08-nghiem-thu.md). Chụp xong dán vào đúng chỗ `[ẢNH-xx]`.

**Chuẩn bị:**
```bash
export AWS_PROFILE=techx-new     # account 197826770971
```
- AWS Console: đúng account `197826770971`, region **ap-southeast-1 (Singapore)**
- Chụp **nguyên cửa sổ trình duyệt** (thấy được URL + tên resource) — đừng crop quá sát, mentor cần thấy ngữ cảnh

---

# 🔴 NHÓM 1 — GẤP: 3 ảnh Grafana (làm trước tiên)

**Vì sao gấp:** Prometheus dùng `emptyDir`, **pod restart là mất sạch dữ liệu**. Số liệu mình đã lưu bền ở
`docs/evidence/mandate-08/slo-01-checkout-success-rate.md`, nhưng **ảnh thì chỉ chụp được lúc data còn**.

### Chuẩn bị Grafana (làm 1 lần)
1. Mở **https://grafana.arthur-ngo.org** (đăng nhập SSO qua Cloudflare Access)
2. Góc trên bên phải → chọn **múi giờ UTC** (⚙️ hoặc time-picker → *Change time settings* → **UTC**)
   → **Bắt buộc**, để khớp với mọi mốc giờ trong biên bản
3. Mở dashboard có panel **checkout success rate**. Nếu không tìm thấy panel sẵn, dùng **Explore**:
   - Menu trái → **Explore** → chọn datasource **Prometheus**
   - Dán query này:
   ```promql
   1 - ((sum(rate(traces_span_metrics_calls_total{service_name="checkout",status_code="STATUS_CODE_ERROR"}[5m])) or vector(0)) / clamp_min((sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[5m]))),0.001))
   ```
   - Đổi sang chế độ **Graph**, trục Y đặt **Min 0.9 / Max 1.0** cho dễ nhìn

---

## 📸 ẢNH-05 — SLO cutover **Valkey** (phải phẳng ≥99%)
- **Time range:** `2026-07-18 00:00:00` → `2026-07-18 23:59:59` **UTC**
- **Phải thấy:** đường success rate **phẳng ~100%**, không có hố sụt
- **Ý nghĩa:** chứng minh cutover Valkey **0 downtime**

## 📸 ẢNH-06 — SLO cutover **Postgres** (phải phẳng ≥99%)
- **Time range:** `2026-07-19 00:00:00` → `2026-07-19 15:00:00` **UTC**
  *(dừng ở 15:00 để KHÔNG dính sự cố 0010 lúc 15:26 — cửa sổ này là của Postgres)*
- **Phải thấy:** phẳng ~100%
- **Ý nghĩa:** cutover Postgres **0 downtime**

## 📸 ẢNH-07 — SLO cutover **Kafka + 2 sự cố** (cố ý cho thấy hố sụt)
- **Time range:** `2026-07-19 14:00:00` → `2026-07-20 17:00:00` **UTC**
- **Phải thấy:** **2 hố sụt** rồi hồi phục hoàn toàn:
  - `19/07 ~15:26–15:40` → sự cố **0010** (lỗi của CDO02)
  - `20/07 ~15:00–15:45` → sự cố **0012** (NetworkPolicy CDO01), đáy **68,65%**
- ⚠️ **Đây là ảnh trung thực, cố ý đưa vào** — không phải điểm trừ. Trình bày kèm 2 postmortem.

## 📸 ẢNH-07b *(nên có)* — Lưu lượng checkout, cùng khung giờ
- Đổi query thành: `sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[5m]))`
- Cùng time range ẢNH-07
- **Phải thấy:** lưu lượng bình thường ~**16,9 req/s**, tụt còn **~0,3–2,4 req/s** đúng 2 cửa sổ sự cố
- **Ý nghĩa quan trọng:** sự cố **0010 không hiện ở đồ thị SLO** (điểm mù của công thức) nhưng **hiện rõ ở lưu lượng**. Ảnh này chứng minh đội hiểu hệ thống sâu, không chỉ đọc số bề mặt.

---

# NHÓM 2 — AWS Console (5 ảnh)

## 📸 ẢNH-01 — RDS
1. AWS Console → **RDS** → **Databases** → click **`techx-tf3-postgres`**
2. Ở tab **Configuration** (hoặc Summary)
3. **Phải thấy trong khung:** `Status: Available` · `Multi-AZ: Yes` (hoặc *Secondary Region/AZ*) · `Engine version: 17.6` · `Publicly accessible: No`

## 📸 ẢNH-09 — RDS bảo mật *(cùng trang, tab khác)*
1. Vẫn ở `techx-tf3-postgres` → tab **Connectivity & security**
2. **Phải thấy:** `Publicly accessible: No` · `Encryption: Enabled` (+ tên KMS key) · VPC + Subnet group (private)

## 📸 ẢNH-15 — RDS backup/PITR *(cùng trang, tab khác)*
1. Vẫn ở `techx-tf3-postgres` → tab **Maintenance & backups**
2. **Phải thấy:** `Automated backups: Enabled` · `Backup retention period: 7 days` · **`Latest restorable time`** (mốc gần hiện tại)
3. **Ý nghĩa:** chứng minh **Plan B** (đường lui sau khi xoá store cũ) là thật

## 📸 ẢNH-14 — Snapshot (điểm lui)
1. RDS → menu trái **Snapshots** → tab **Manual**
2. **Phải thấy:** `techx-tf3-postgres-pre-cleanup-20260721-2242`, `Status: Available`
3. Rồi sang **ElastiCache** → **Backups** → thấy `techx-tf3-valkey-pre-cleanup-20260721-2243`
   *(có thể chụp 2 ảnh riêng, đánh số 14a/14b)*

## 📸 ẢNH-02 — ElastiCache
1. AWS Console → **ElastiCache** → **Redis OSS / Valkey caches** → click **`techx-tf3-valkey`**
2. **Phải thấy:** `Status: Available` · `Multi-AZ: Enabled` · `Encryption in-transit: Enabled` · `Encryption at-rest: Enabled` · **2 node** (1 primary + 1 replica)

## 📸 ẢNH-03 — MSK
1. AWS Console → **Amazon MSK** → **Clusters** → click **`techx-tf3-kafka`**
2. **Phải thấy:** `Status: Active` · `Total number of brokers: 3` · `Apache Kafka version: 3.9.x` · 3 AZ khác nhau

## 📸 ẢNH-08 — Secrets Manager
1. AWS Console → **Secrets Manager** → **Secrets**
2. Chụp **danh sách** — thấy các secret của mandate (tên chứa `techx-tf3`)
3. 🚨 **TUYỆT ĐỐI KHÔNG** click *Retrieve secret value* / mở tab **Secret value** khi chụp

## 📸 ẢNH-12 — Cost Explorer
1. AWS Console → **Billing and Cost Management** → **Cost Explorer**
2. Time range: **7 ngày gần nhất** · Group by: **Service** · Filter: `RDS`, `ElastiCache`, `MSK`
3. ⚠️ **Lưu ý quan trọng:** mình đã query — account này trả về **~$0 cho mọi service** (credit/sandbox). Ảnh sẽ **không thể hiện chi phí thật**.
   → Chụp vẫn được, nhưng **ghi chú thẳng dưới ảnh**: *"Account dùng credit nên Cost Explorer không phản ánh giá thật; con số $202/tháng là dự toán theo bảng giá AWS, xem mục B tiêu chí 5."*
   Đừng để mentor tưởng chi phí bằng 0.

---

# NHÓM 3 — Ứng dụng (1 ảnh + 1 tuỳ chọn)

## 📸 ẢNH-10 — Đặt hàng thành công trên storefront
1. Mở **https://d2tn71186d7ilz.cloudfront.net**
2. Chọn 1 sản phẩm → **Add to Cart** → **Go to Cart** → **Place Order**
3. **Chụp màn hình xác nhận đơn**, phải thấy **Order Confirmation ID**
4. **Ý nghĩa:** chứng minh luồng end-to-end chạy thật: browse → giỏ (**ElastiCache**) → đặt hàng (checkout → **MSK**) → `accounting` ghi **RDS**

## 📸 ẢNH-11 *(tuỳ chọn, rất thuyết phục)* — Jaeger trace đi vào MSK
1. Mở **https://jaeger.arthur-ngo.org/jaeger/ui/**
2. Service: **`checkout`** → **Find Traces** → mở 1 trace vừa tạo ở ẢNH-10
3. Tìm span tên **`orders publish`** → mở phần **Tags**
4. **Phải thấy:** thuộc tính trỏ tới broker **MSK** (`...kafka.ap-southeast-1.amazonaws.com:9096`), **không phải** `kafka:9092`
5. **Ý nghĩa:** bằng chứng trực quan nhất rằng đơn hàng thật sự đi qua MSK

---

# NHÓM 4 — Chờ §8 (sau khi xoá store cũ)

## 📸 ẢNH-04 — Không còn pod store tự host
Chỉ chụp **SAU** khi hoàn tất §8:
```bash
export AWS_PROFILE=techx-new
kubectl -n techx-tf3 get pods
```
- **Phải thấy:** **không còn** dòng nào tên `postgresql`, `valkey-cart`, `kafka`; mọi pod còn lại `Running`/`Ready`
- Nếu mentor hỏi về `opensearch`: đó là **kho log telemetry**, không thuộc 3 datastore của Mandate #8

## 📸 ẢNH-13 *(tuỳ chọn)* — Log pod cô lập nối MSK
Nội dung log đã lưu trong postmortem 0010 + evidence. Pod đã xoá nên **không chụp lại được** —
nếu cần, trích đoạn text trong `docs/postmortem/0010-...md` thay cho ảnh.

---

# ✅ Thứ tự đề xuất

| Ưu tiên | Ảnh | Lý do |
|---|---|---|
| 🔴 **1. Ngay** | 05, 06, 07, 07b | Prometheus `emptyDir` — restart là mất |
| 2 | 01, 09, 15, 14 | Cùng một trang RDS, chụp liền tay |
| 3 | 02, 03, 08, 12 | AWS Console còn lại |
| 4 | 10, 11 | Cần thao tác trên storefront |
| 5 | **04** | **Chỉ sau khi xong §8** |

**Tổng: 13 ảnh bắt buộc + 2 tuỳ chọn (11, 13).**

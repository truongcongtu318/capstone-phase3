# Evidence — Mandate #8 (migrate 3 datastore lên managed)

Bằng chứng thô, thu thập **21/07/2026**, dùng cho [biên bản nghiệm thu](../../mandates/mandate-08/mandate-08-nghiem-thu.md).

| File | Nội dung | Dùng cho |
|---|---|---|
| `parity-01-postgres-cu.txt` | Đếm + checksum 5 bảng trên **Postgres CŨ** | OUTPUT-06 |
| `parity-02-rds.txt` | Đếm + checksum 5 bảng trên **RDS** (cùng câu lệnh) | OUTPUT-06 |
| `parity-03-kafka-cu.txt` | Trạng thái **Kafka CŨ** + ghi chú mất state | OUTPUT-08 |
| `parity-04-msk.txt` | Consumer group + LAG trên **MSK** | OUTPUT-08 |
| `rollback-01-snapshot-pitr.txt` | Snapshot RDS/ElastiCache + PITR retention | OUTPUT-10 |
| `rollback-02-msk-retention.txt` | Retention topic MSK + config cluster | OUTPUT-10 |

---

## ⭐ KẾT QUẢ CHÍNH — Data parity Postgres → RDS

Checksum = `md5` toàn dòng, tổng hợp **độc lập thứ tự** (không phụ thuộc tên cột, không phụ thuộc thứ tự đọc).
Chạy **cùng một câu lệnh** trên cả hai nguồn.

| Bảng | Postgres CŨ (đếm / checksum) | RDS (đếm / checksum) | Khớp? |
|---|---|---|---|
| `catalog.products` | **10** / `bd6d7f7301cd136f0c4dbf4112243dca` | **10** / `bd6d7f7301cd136f0c4dbf4112243dca` | ✅ **KHỚP TUYỆT ĐỐI** |
| `reviews.productreviews` | **50** / `bc4d8d6832ba47f191fb16bae49c8647` | **50** / `bc4d8d6832ba47f191fb16bae49c8647` | ✅ **KHỚP TUYỆT ĐỐI** |
| `accounting.order` | 70.478 / `3d4badcc…befe7` | 215.033 / `b3b832a9…cc3d` | ⬆️ lệch — **đúng như thiết kế** |
| `accounting.orderitem` | 129.131 / `b21e5a21…d98a` | 395.205 / `30ea128f…2422` | ⬆️ lệch — **đúng như thiết kế** |
| `accounting.shipping` | 70.478 / `937df803…9891` | 215.033 / `0e220db7…db1b` | ⬆️ lệch — **đúng như thiết kế** |

### Đọc bảng này thế nào (giải thích cho mentor)

**Hai bảng seed tĩnh khớp checksum tuyệt đối** → chứng minh bước `pg_dump`/restore đã sao chép
**trung thực từng byte**. Đây là phép thử sạch nhất, vì hai bảng này **không đổi** sau cutover nên
mọi sai lệch dù nhỏ đều lộ ra ở checksum.

**Ba bảng `accounting.*` lệch là ĐÚNG, không phải mất dữ liệu:**
- Postgres cũ **đóng băng** từ lúc cutover (không còn ai ghi vào) → giữ nguyên **70.478 đơn**.
- RDS **tiếp tục nhận đơn mới** → đã lên **215.033 đơn**.
- Chênh lệch ~144.500 đơn chính là **đơn phát sinh sau cutover, chỉ tồn tại ở RDS** → bằng chứng
  migrate đang sống thật.

**Parity thật sự của bước cutover** được kiểm tại thời điểm đó, **trên nguồn đã đứng yên**
(đóng băng người ghi duy nhất là `accounting`), kết quả: **70.478 → 70.556 đơn** — 78 đơn phát sinh
trong cửa sổ đóng băng đều được replay đủ từ Kafka, **không mất đơn nào**.

---

## Kafka → MSK

- **MSK:** `accounting` LAG=0 cả 3 partition (7703/7610/7566) · `fraud-detection` LAG=0 · consumer đang active.
- **Kafka cũ:** đã mất topic `orders` + consumer group do pod bị tạo lại (~5h trước lúc đo).
  **Không ảnh hưởng production** (kho này đã nghỉ hưu từ cutover). Bằng chứng LAG=0 của kho cũ đã đo
  **trước đó** (offset đóng băng 141.242, *"has no active members"*) — xem `parity-03-kafka-cu.txt`.

## Điểm lui Plan B (thay cho việc giữ pod cũ)

| Hạng mục | Giá trị |
|---|---|
| RDS backup tự động | **7 ngày**, cửa sổ 19:53–20:23 |
| RDS PITR | `LatestRestorableTime` = 2026-07-21T15:40:49Z (**sống, cập nhật liên tục**) |
| RDS snapshot thủ công | `techx-tf3-postgres-pre-cleanup-20260721-2242` (20 GB) |
| ElastiCache snapshot thủ công | `techx-tf3-valkey-pre-cleanup-20260721-2243` (chụp từ **replica**, không tải lên primary) |
| MSK retention | `log.retention.hours=168` (**7 ngày**) · RF=3 · min.insync=2 · ISR đầy đủ |

⇒ Đủ điều kiện chuyển từ **Plan A (đường lui nóng)** sang **Plan B (đường lui lạnh)**, tức **xoá được
3 store cũ** ở §8 mà không giảm khả năng phục hồi.

---

## Cách tự tái tạo bằng chứng

Toàn bộ lệnh nằm trong [biên bản nghiệm thu](../../mandates/mandate-08/mandate-08-nghiem-thu.md) mục **C** (parity) và
mục **E.3** (snapshot/PITR). Cần `export AWS_PROFILE=techx-new` và tunnel SSM tới cluster.

# Mandate #8 — Chuyển 3 kho dữ liệu lên dịch vụ quản lý (managed)
### Tài liệu giải thích toàn bộ quá trình — viết cho cả người KHÔNG rành kỹ thuật

> **Tóm tắt 1 câu:** Cửa hàng online của chúng ta đang tự chạy 3 "kho dữ liệu" quan trọng
> ngay bên trong hệ thống. Mandate #8 là việc chuyển 3 kho này sang cho **Amazon (AWS) trông
> coi hộ** — an toàn hơn, bền hơn — mà **không mất dữ liệu** và **không làm khách hàng gián đoạn
> một giây nào**.

---

## Phần 1 — Bối cảnh: Hình dung cho dễ

Hãy tưởng tượng cửa hàng online của chúng ta như một **nhà hàng lớn**. Trong bếp có 3 thứ tối
quan trọng:

| Kho dữ liệu | Vai trò (ví von) | Nếu hỏng thì sao? |
|---|---|---|
| **PostgreSQL** (một loại *database*) | **Sổ cái kế toán** — ghi mọi đơn hàng, sản phẩm, đánh giá | Mất đơn hàng, mất doanh thu |
| **Valkey** (một *bộ nhớ đệm*) | **Giỏ hàng tạm** của khách đang mua | Khách mất giỏ hàng đang chọn |
| **Kafka** (một *hàng đợi tin nhắn*) | **Băng chuyền đơn hàng** giữa các bộ phận | Đơn không được xử lý |

**Vấn đề:** cả 3 thứ này hiện đang **tự chạy** bên trong hệ thống của ta, mỗi thứ chỉ có **1 bản
duy nhất** trên **1 máy chủ duy nhất**. Giống như nhà hàng chỉ có **1 cuốn sổ cái, để trên 1 cái
bàn**. Lỡ cái bàn đó gãy (máy chủ đó hỏng) → mất sạch. Đây gọi là **"điểm hỏng đơn lẻ"** (single
point of failure — SPOF), và nó nằm ngay trên **luồng ra tiền** của cửa hàng.

**Giải pháp:** thuê Amazon (AWS) giữ hộ 3 kho này bằng các **dịch vụ quản lý** (managed service):
- PostgreSQL → **Amazon RDS**
- Valkey → **Amazon ElastiCache**
- Kafka → **Amazon MSK**

Khi Amazon giữ hộ, họ tự động: có **bản sao dự phòng** (nhiều máy, nhiều khu vực), **tự sao lưu**,
**tự mã hoá**, **tự vá lỗi**. Ta hết lo "cái bàn gãy".

---

## Phần 2 — Bài toán khó: "Thay bánh xe khi xe đang chạy"

Điều làm việc này khó không phải là dựng kho mới — mà là **chuyển sang kho mới mà không dừng cửa
hàng**. Cửa hàng đang có khách mua thật, đơn hàng thật, tiền thật, **24/7**.

Ba ràng buộc bắt buộc (không được vi phạm):
1. **Không mất một mẩu dữ liệu nào** — không mất đơn, không mất giỏ hàng.
2. **Không gián đoạn khách hàng** — khách vẫn mua được suốt quá trình (chỉ tiêu: tỉ lệ đặt hàng
   thành công luôn ≥ 99%).
3. **An toàn + trong ngân sách** — mã hoá, mật khẩu cất kỹ, đường truyền riêng tư; không phình chi phí.

Giống như thay 4 bánh xe của một chiếc xe **đang chạy trên cao tốc**, mà hành khách không được
cảm thấy xóc.

---

## Phần 3 — Chiến lược chung (áp dụng cho cả 3 kho)

Ta làm **từng kho một**, theo thứ tự **dễ → khó**: Valkey → Postgres → Kafka. Mỗi kho xong, kiểm
tra kỹ rồi mới sang kho tiếp. **Không gộp** để nếu có sự cố còn dễ khoanh vùng.

Với mỗi kho, nguyên tắc vàng:
- **Dựng kho mới song song** với kho cũ (kho cũ vẫn chạy bình thường).
- **Chuyển dần**, có bước kiểm chứng dữ liệu khớp 100% trước khi "lật công tắc".
- **Luôn giữ đường lui** (rollback): kho cũ **không bị xoá** cho tới khi mọi thứ được nghiệm thu.
- Mọi thay đổi đi qua quy trình chuẩn (viết ra, kiểm tra tự động, rồi hệ thống tự áp dụng) — không
  "sửa tay" trực tiếp lên hệ thống đang chạy.

---

## Phần 4 — Chuẩn bị (làm trước, không đụng gì đang chạy)

Trước khi chuyển, ta chuẩn bị 3 thứ — **hoàn toàn an toàn** vì chưa ai dùng kho mới:

1. **Dựng 3 kho managed trên AWS** (RDS, ElastiCache, MSK) — bằng "bản thiết kế bằng mã"
   (Terraform), để dựng lại chính xác nếu cần. Cả 3 đều bật **mã hoá**, đặt trong **mạng riêng
   tư** (không ai từ Internet chạm được).
2. **Cất mật khẩu vào két sắt** (AWS Secrets Manager) và cho hệ thống tự lấy khi cần — **không bao
   giờ** viết mật khẩu thẳng vào file.
3. **Cập nhật phần mềm** để nó *biết cách* nói chuyện an toàn (mã hoá + mật khẩu) với kho mới,
   nhưng **để công tắc TẮT** — nghĩa là phần mềm chạy y như cũ cho tới đúng lúc chuyển. Kiểu "lắp
   sẵn đường ống nhưng chưa mở van".

Nhờ cách này, việc *cài đặt* và việc *chuyển* được **tách rời** — cài xong để đó, khi nào sẵn sàng
mới mở van.

---

## Phần 5 — Chuyển Valkey (giỏ hàng) → ElastiCache ✅ ĐÃ XONG

**Thử thách riêng:** giỏ hàng thay đổi liên tục (khách thêm/bớt món mỗi giây). Làm sao chép sang
kho mới mà không bỏ sót giỏ nào?

**Mẹo thông minh — "cửa sổ 60 phút":** Trong hệ thống, mỗi giỏ hàng có **hạn 60 phút** — không đụng
tới trong 60 phút thì tự hết hạn. Suy ra: **giỏ nào còn sống thì chắc chắn đã được ghi trong 60 phút
gần nhất.**

Các bước:
1. **Ghi song song (dual-write):** bật cho dịch vụ giỏ hàng ghi **đồng thời** vào cả kho cũ *và* kho
   mới. Nhưng **đọc thì vẫn từ kho cũ** → khách không thấy gì khác.
2. **Chờ hơn 60 phút:** sau 60 phút, vì mọi giỏ còn sống đều đã được ghi ít nhất một lần, nên **kho
   mới chắc chắn có đủ mọi giỏ đang sống**.
3. **Kiểm chứng:** quét toàn bộ giỏ ở kho cũ, đối chiếu kho mới → **827/827 giỏ khách đều có mặt**
   ở kho mới. (Có đúng 1 "chìa khoá lạ" tên `cart` không phải giỏ khách — chỉ là dữ liệu rác kỹ
   thuật, không tính.)
4. **Lật công tắc đọc:** giờ mới cho khách **đọc + ghi từ kho mới** (ElastiCache, có mã hoá + mật
   khẩu). Đồng thời **đảo chiều ghi song song** → giờ ghi ngược về kho cũ để **giữ đường lui**.

**Kết quả:** giỏ hàng chạy trên ElastiCache, **không mất giỏ nào**, khách không gián đoạn. Kho
Valkey cũ vẫn được ghi đầy đủ (đường lui ~1 phút nếu cần quay lại).

---

## Phần 6 — Chuyển PostgreSQL (sổ cái) → RDS ✅ ĐÃ XONG

**Thử thách riêng:** đây là *sổ cái kế toán* — tuyệt đối không được sai một dòng. May mắn: chỉ có
**MỘT bộ phận duy nhất được phép ghi** vào sổ (dịch vụ `accounting`), các bộ phận khác chỉ **đọc**.

**Mẹo — "đóng băng người ghi":** tạm dừng đúng cái bộ phận ghi, thì sổ cái "đứng yên" — chép sang
sổ mới sẽ khớp tuyệt đối. Trong lúc đó khách **vẫn mua được** vì:
- Bộ phận đọc (xem sản phẩm, xem đánh giá) vẫn chạy bình thường.
- Đơn hàng mới **không mất** — chúng xếp hàng chờ ở "băng chuyền" Kafka.

Các bước:
1. **Đóng băng người ghi:** tạm dừng dịch vụ `accounting` → sổ cái cũ đứng yên. (Ghi lại mốc thời
   gian để lỡ cần quay lui.)
2. **Chép sổ (dump + restore):** sao toàn bộ sổ cái cũ sang RDS (chỉ vài giây cho ~70.000 đơn).
3. **Đối chiếu (parity):** đếm từng loại — đơn hàng, chi tiết đơn, giao vận, đánh giá, sản phẩm —
   ở cả hai bên. Vì sổ đang đứng yên nên số **khớp tuyệt đối**:

   | Loại | Sổ cũ | Sổ mới (RDS) |
   |---|---|---|
   | Đơn hàng | 70.478 | 70.478 ✅ |
   | Chi tiết đơn | 129.131 | 129.131 ✅ |
   | Giao vận | 70.478 | 70.478 ✅ |
   | Đánh giá | 50 | 50 ✅ |
   | Sản phẩm | 10 | 10 ✅ |

4. **Chuyển đường nối:** cập nhật 3 dịch vụ trỏ sang RDS (đường truyền mã hoá).
5. **Thả người ghi:** bật lại `accounting` (đã trỏ RDS). Nó tự **xử lý nốt các đơn đã xếp hàng** ở
   Kafka trong lúc đóng băng → ghi vào RDS. Số đơn tăng từ 70.478 lên 70.556 (78 đơn xếp hàng đã
   được xử lý), **không sót đơn nào**.

**Kết quả:** sổ cái chạy trên RDS (nhiều bản dự phòng, tự sao lưu, mã hoá), **không mất đơn**, khách
không gián đoạn. Kho Postgres cũ vẫn giữ làm đường lui.

---

## Phần 7 — Sự cố gặp phải & cách xử lý (kể thật, dễ hiểu)

Việc chuyển sổ cái (Postgres) gặp vài trục trặc — nêu ra để minh bạch và để rút kinh nghiệm:

- **"Ống nối bị khoá" (lỗi tường lửa mạng):** ban đầu phần mềm không nối được kho mới do quy tắc
  tường lửa mở nhầm "cửa". Đã sửa để mở đúng cửa cho cả 3 kho. *Không ảnh hưởng khách* (đường cũ vẫn
  chạy).
- **"Chép sổ bị thiếu quyền":** lần chép đầu dùng nhầm tài khoản không đủ quyền đọc hết sổ → chép
  lỗi. Đã đổi sang tài khoản quản trị để chép trọn vẹn.
- **"Đóng băng cứ tự tan" (khó nhất):** hệ thống của ta có một "người gác" tự động (ArgoCD) luôn
  đưa mọi thứ về đúng bản thiết kế. Khi ta tạm dừng bộ phận ghi, "người gác" cứ bật nó dậy lại. Phải
  mất vài lần thử mới tìm đúng cách **báo cho người gác "khoản này để yên"** (kỹ thuật gọi là
  `ignoreDifferences`), lúc đó việc đóng băng mới giữ được.

Điểm quan trọng: **trong suốt các trục trặc này, khách hàng KHÔNG bị ảnh hưởng** và **không dữ liệu
nào bị mất** — vì kho cũ luôn còn nguyên làm đường lui, và ta luôn kiểm chứng trước khi "lật công tắc".

---

## Phần 8 — Bảo mật (áp dụng cho cả 2 kho đã chuyển)

- **Mã hoá đường truyền (TLS):** dữ liệu đi trên đường luôn được khoá kín.
- **Mã hoá lưu trữ (at-rest):** dữ liệu nằm trong kho cũng được mã hoá.
- **Mật khẩu cất trong két (Secrets Manager):** không bao giờ để lộ trong file hay cấu hình; hệ
  thống tự lấy khi cần. RDS còn **tự đổi mật khẩu định kỳ**.
- **Mạng riêng tư:** kho mới **không thể** truy cập từ Internet — chỉ từ bên trong hệ thống. Đã kiểm
  chứng: từ ngoài không nối được.

---

## Phần 9 — Trạng thái hiện tại

| Kho | Tình trạng | Ghi chú |
|---|---|---|
| 🟢 Valkey → ElastiCache | **XONG** | Giỏ hàng chạy trên kho mới; kho cũ giữ làm đường lui |
| 🟢 PostgreSQL → RDS | **XONG** | Sổ cái chạy trên kho mới; không mất đơn; kho cũ giữ làm đường lui |
| ⬜ Kafka → MSK | **Chưa làm** (bước cuối) | Sẽ làm sau; phần mềm đã chuẩn bị sẵn |

- **2/3 kho đã lên managed**, zero mất dữ liệu, zero gián đoạn khách.
- Cả 3 kho **cũ vẫn đang chạy** — chưa xoá, làm đường lui cho tới khi được nghiệm thu.

---

## Phần 10 — Còn lại phải làm

1. **Chuyển Kafka → MSK** (băng chuyền đơn hàng) — bước cuối, rủi ro cao nhất vì liên quan trực tiếp
   khâu đặt hàng. Phần mềm đã sẵn sàng (mã hoá + mật khẩu đã lắp, đang tắt).
2. **Dọn dẹp (chỉ sau khi nghiệm thu cả 3 kho):** chụp ảnh sao lưu cuối cùng rồi mới gỡ 3 kho cũ.
   Đây là "điểm không quay lui" — làm cuối cùng, cẩn thận.

---

## Phụ lục — Từ điển thuật ngữ (cho người không chuyên)

- **Database (cơ sở dữ liệu):** nơi lưu dữ liệu có tổ chức, như một cuốn sổ cái điện tử khổng lồ.
- **Managed service (dịch vụ quản lý):** thay vì tự vận hành, thuê nhà cung cấp (AWS) lo hộ phần
  hạ tầng — họ tự sao lưu, vá lỗi, dự phòng.
- **Zero-downtime (không gián đoạn):** làm mà người dùng không hề bị ngắt quãng dịch vụ.
- **Zero-loss (không mất dữ liệu):** đảm bảo không một mẩu dữ liệu nào biến mất.
- **Rollback (đường lui):** khả năng quay lại trạng thái cũ ngay nếu có sự cố.
- **SPOF (điểm hỏng đơn lẻ):** một chỗ mà nếu nó hỏng thì cả hệ thống hỏng theo — thứ ta muốn loại bỏ.
- **TLS / mã hoá:** khoá kín dữ liệu để người ngoài không đọc trộm được.
- **Dual-write (ghi song song):** ghi dữ liệu vào cả kho cũ lẫn kho mới cùng lúc trong giai đoạn chuyển.
- **Parity check (đối chiếu):** so sánh dữ liệu hai bên để chắc chắn khớp 100% trước khi chuyển hẳn.

---

*Tài liệu này mô tả trạng thái tại thời điểm hoàn tất 2/3 kho (Valkey, Postgres). Bước Kafka và
phần dọn dẹp sẽ được cập nhật sau khi thực hiện.*

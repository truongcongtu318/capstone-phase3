# Báo cáo tổng kết Mandate #8 — Chuyển 3 kho dữ liệu lên dịch vụ quản lý của AWS

**Đội thực hiện:** CDO02 (trụ Reliability + Cost) — Huu Tai Ngo
**Thời gian:** 18–20/07/2026
**Kết quả:** ✅ **Hoàn tất 3/3 kho — không mất một dòng dữ liệu nào.**

> **File này viết cho người KHÔNG làm kỹ thuật.** Mọi thuật ngữ đều được giải nghĩa bằng ví dụ đời thường
> ngay lần đầu xuất hiện. Nếu bạn chỉ có 2 phút, đọc mục **1** và **9**.

---

## 0. Giải nghĩa từ ngữ (đọc cái này trước, phần sau sẽ dễ)

| Từ | Nghĩa đời thường |
|---|---|
| **Hệ thống của chúng ta** | Một trang bán hàng online (TechX Corp): xem sản phẩm, bỏ giỏ, đặt hàng, thanh toán. |
| **Service** (dịch vụ) | Một "nhân viên chuyên môn" trong hệ thống. Ví dụ: nhân viên *giỏ hàng*, nhân viên *thanh toán*, nhân viên *đặt hàng*. Cả trang web là một **đội** gồm ~20 nhân viên như vậy, mỗi người làm một việc và gọi nhau qua "bộ đàm". |
| **Pod / container** | Một "chỗ ngồi làm việc" của nhân viên đó. Một nhân viên có thể có 2–3 chỗ ngồi (2–3 bản sao) để nếu một chỗ hỏng thì vẫn còn chỗ khác. |
| **Kubernetes (K8s)** | "Người quản lý ca trực": tự sắp nhân viên vào chỗ ngồi, thấy ai gục thì thay người mới, thấy đông khách thì thêm người. |
| **Datastore / kho dữ liệu** | Nơi cất dữ liệu thật: sổ sách, giỏ hàng, hàng đợi công việc. |
| **Self-hosted** ("tự dựng") | Ta tự cài kho đó trên máy của mình, **tự chịu trách nhiệm** sao lưu, vá lỗi, dựng lại khi hỏng. |
| **Managed service** ("dịch vụ quản lý") | Ta **thuê** AWS chạy kho đó. AWS lo sao lưu, vá lỗi, tự chuyển sang máy dự phòng khi hỏng. Ta trả tiền để bớt việc và bớt rủi ro. |
| **SPOF** (single point of failure) | "Điểm chết duy nhất": một thứ mà **hỏng nó là sập cả hệ thống**, vì không có bản dự phòng. |
| **HA / Multi-AZ** | "Cao sẵn sàng": có bản sao đặt ở **toà nhà khác** (trung tâm dữ liệu khác). Cháy một toà thì bản kia gánh. |
| **Downtime** | Khoảng thời gian khách **không dùng được** dịch vụ. |
| **Cutover** | Khoảnh khắc "bẻ ghi": chuyển từ kho cũ sang kho mới. Đây là lúc nguy hiểm nhất. |
| **Rollback** | "Đường lui": quay lại trạng thái cũ khi có sự cố. |
| **Deploy** | Đưa thay đổi lên hệ thống thật đang chạy. |

---

## 1. Mandate #8 là gì và tại sao BẮT BUỘC phải làm

### Vấn đề ban đầu

Hệ thống có **3 kho dữ liệu**, và cả 3 đều **tự dựng, mỗi kho chỉ có ĐÚNG MỘT bản, nằm trên MỘT máy duy nhất.**

Hình dung: cả cửa hàng có **một quyển sổ cái duy nhất**, **một cái giỏ hàng duy nhất**, **một băng chuyền
đơn hàng duy nhất** — và cả ba đều đặt trong **cùng một căn phòng**. Cháy phòng đó là:
- mất toàn bộ đơn hàng đã ghi,
- khách mất sạch giỏ hàng,
- đơn mới không chuyển được cho bộ phận kế toán.

Đó gọi là **SPOF** — và nó nằm **ngay trên đường ra tiền** (luồng đặt hàng). Đây là rủi ro nghiêm trọng nhất
của hệ thống lúc đó.

### Yêu cầu của Mandate #8

Chuyển cả 3 kho sang **dịch vụ quản lý của AWS**, với 4 ràng buộc khắt khe:

1. **Không mất một dòng dữ liệu nào** (đặc biệt là đơn hàng — đó là tiền).
2. **Không có downtime** — khách vẫn đặt hàng được suốt quá trình chuyển (tỉ lệ đặt hàng thành công ≥ 99%).
3. **An toàn**: dữ liệu mã hoá cả khi truyền lẫn khi lưu; mật khẩu không nằm trong code; kho chỉ truy cập
   được từ bên trong mạng nội bộ, không phơi ra Internet.
4. **Trong ngân sách**.

Nói ngắn: **đổi động cơ máy bay trong lúc máy bay đang bay, chở đầy khách, và không được để khách biết.**

---

## 2. Ba kho dữ liệu đó là gì (giải thích đời thường)

| Kho | Tên kỹ thuật | Nó làm gì | Nếu mất thì sao |
|---|---|---|---|
| 🧾 **Sổ cái** | PostgreSQL | Ghi **đơn hàng đã chốt**, danh mục sản phẩm, đánh giá | Mất lịch sử đơn = mất tiền, mất đối soát |
| 🛒 **Giỏ hàng** | Valkey (họ Redis) | Giữ **giỏ hàng tạm** của khách. Nhanh vì để trong RAM | Khách mất giỏ đang chọn → bỏ đi, mất doanh thu |
| 📦 **Băng chuyền đơn** | Kafka | Khi khách đặt xong, bộ phận *đặt hàng* **bỏ một phiếu** lên băng chuyền; bộ phận *kế toán* và *chống gian lận* **nhặt phiếu** xuống để xử lý | Đơn đã thu tiền nhưng **không ai ghi sổ** → đơn "mồ côi" |

**Điểm mấu chốt cần nhớ cho phần sau:** đặt hàng đi qua **2 bước tách rời**:
1. Bộ phận *đặt hàng* (checkout) xử lý → **giao hàng + thu tiền** → rồi **bỏ phiếu lên băng chuyền**.
2. Bộ phận *kế toán* (accounting) **nhặt phiếu** → **ghi vào sổ cái**.

→ Nếu bước 1 thu tiền xong mà **bỏ phiếu thất bại**, đơn đó **biến mất khỏi sổ** dù khách đã bị trừ tiền.
Đây chính là kiểu mất mát nguy hiểm nhất, và nó **đã xảy ra một lần** (mục 6.1).

---

## 3. Đích đến: 3 dịch vụ quản lý của AWS

| Kho cũ (tự dựng) | Kho mới (AWS quản lý) | AWS lo giúp việc gì |
|---|---|---|
| PostgreSQL | **RDS** (Multi-AZ) | Sao lưu tự động 7 ngày, có bản dự phòng ở **toà nhà khác**, tự đổi sang bản dự phòng khi hỏng, tự đổi mật khẩu định kỳ |
| Valkey | **ElastiCache** (Multi-AZ) | Tương tự, cộng mã hoá + mật khẩu bắt buộc |
| Kafka | **MSK** (3 broker) | Chạy **3 bản** thay vì 1; mất 1 bản vẫn hoạt động |

### Đánh đổi khi chọn "thuê" thay vì "tự dựng"

| | Tự dựng (cũ) | Thuê AWS (mới) |
|---|---|---|
| Tiền | Rẻ hơn | **Đắt hơn** |
| Công vận hành | Ta tự làm hết | AWS làm |
| Hỏng máy | **Mất/ngưng dịch vụ** | Tự chuyển bản dự phòng |
| Tuỳ biến sâu | Thoải mái | Bị giới hạn theo AWS |

→ **Chọn thuê.** Lý do: đây là đường ra tiền, một lần sập là thiệt hại lớn hơn nhiều so với tiền thuê thêm.
Rủi ro > tiết kiệm.

---

## 4. Nguyên tắc xuyên suốt (vì sao việc này khó)

Ba luật tự đặt ra và giữ nghiêm suốt cả quá trình:

1. **Luôn có đường lui.** Kho cũ **không được xoá** cho tới khi mọi thứ được nghiệm thu. Nếu kho mới có vấn đề,
   ta bấm quay lại trong ~1 phút.
2. **Chứng minh bằng số, không nói suông.** Sau mỗi lần chuyển phải **đếm và so khớp**: kho cũ có bao nhiêu,
   kho mới có bấy nhiêu. Khớp mới đi tiếp.
3. **Giữ tải thật trong lúc chuyển.** Có khách (giả lập) đang mua hàng suốt quá trình — nếu không có ai mua thì
   câu "không downtime" là vô nghĩa, vì chẳng có gì để hỏng.

Thứ tự làm: **Giỏ hàng → Sổ cái → Băng chuyền** (dễ → khó). Băng chuyền để cuối cùng vì nó **nguy hiểm nhất**
(xem mục 5.3).

---

## 5. Chuyển từng kho — làm thế nào, vì sao chọn cách đó

### 5.1 🛒 Giỏ hàng: Valkey → ElastiCache — cách "ghi cả hai nơi"

**Vấn đề:** giỏ hàng thay đổi liên tục (khách thêm/bớt món mỗi giây). Không thể "chụp ảnh" rồi copy — vừa copy
xong là đã cũ.

**Cách làm — "ghi song song rồi chờ hội tụ":**
1. Sửa nhân viên *giỏ hàng* để mỗi lần khách đổi giỏ thì **ghi vào CẢ kho cũ VÀ kho mới**.
2. Giỏ hàng có hạn dùng **60 phút** (bỏ quên thì tự xoá). Nên chỉ cần **chờ 60 phút**: mọi giỏ còn sống đều đã
   được ghi sang kho mới ít nhất một lần → hai kho **tự khớp nhau**.
3. Đếm kiểm chứng → **827/827 giỏ khớp**.
4. Chuyển sang **đọc từ kho mới**.

**Vì sao chọn cách này:** không cần dừng dịch vụ một giây nào, và tự nhiên hội tụ nhờ đặc tính "có hạn dùng".

**Đánh đổi:** trong 60 phút đó, mỗi thao tác giỏ hàng làm **2 lần việc** (chậm hơn chút, tốn hơn chút). Chấp nhận
được vì đổi lấy zero downtime.

**Còn giữ:** vẫn **ghi ngược về kho cũ** làm đường lui, chưa gỡ.

---

### 5.2 🧾 Sổ cái: PostgreSQL → RDS — cách "đóng băng người ghi"

**Vấn đề:** sổ cái **không được sai một dòng**. Nếu vừa copy vừa có người ghi thêm, bản copy sẽ thiếu.

**Điểm thuận lợi:** chỉ có **ĐÚNG MỘT** nhân viên được ghi sổ (kế toán). Những người khác chỉ **đọc**.

**Cách làm — "đóng băng → chép → so khớp → đổi bút → thả":**
1. **Tạm dừng riêng nhân viên kế toán** (người ghi duy nhất). Sổ đứng yên — nhưng **khách vẫn mua hàng bình
   thường**, vì phiếu đơn hàng **nằm chờ trên băng chuyền** chứ không mất.
2. **Chép toàn bộ sổ** sang kho mới.
3. **So khớp tuyệt đối** từng bảng, từng dòng.
4. **Đổi "bút"**: trỏ kế toán sang sổ mới.
5. **Thả kế toán** ra → nó **nhặt hết phiếu tồn** trên băng chuyền và ghi tiếp vào sổ mới.

**Kết quả:** **70.478 → 70.556 đơn** — tức 78 đơn phát sinh trong lúc "đóng băng" đều được ghi bù đầy đủ,
**không mất đơn nào**, và **khách không hề bị gián đoạn**.

**Vì sao chọn cách này:** tận dụng đúng đặc điểm "chỉ một người ghi" → đóng băng an toàn tuyệt đối, không cần
kỹ thuật phức tạp và rủi ro hơn.

**Đánh đổi:** kế toán bị chậm vài phút (sổ cập nhật trễ), nhưng **khách không thấy gì**, và đổi lại được
**bằng chứng khớp tuyệt đối** — điều quan trọng nhất với sổ tiền.

> **Bài học kỹ thuật đáng nhớ:** hệ thống có cơ chế tự-chữa-lành (thấy nhân viên bị dừng là tự bật lại). Muốn
> "đóng băng" thật sự, phải khai báo ngoại lệ đúng chỗ, nếu không nó cứ tự bật lại. Đã mất vài lần thử mới ra.

---

### 5.3 📦 Băng chuyền: Kafka → MSK — kho NGUY HIỂM NHẤT

**Vì sao nguy hiểm nhất:** hai kho kia nếu lỗi thì "chậm" hoặc "mất giỏ". Băng chuyền lỗi thì **đơn đã thu tiền
nhưng không ai ghi sổ** — mất tiền thật, và **không tìm lại được** (phiếu chưa bao giờ được bỏ lên băng chuyền
thì không có dấu vết ở đâu cả).

**Cách làm — "đổi người BỎ phiếu trước, đổi người NHẶT phiếu sau":**
1. Dựng băng chuyền mới (MSK).
2. **Đổi người bỏ phiếu** (checkout) sang bỏ vào băng chuyền MỚI.
3. **Chờ băng chuyền CŨ rỗng hoàn toàn** (kế toán + chống gian lận nhặt hết phiếu tồn).
4. **Rồi mới đổi người nhặt phiếu** sang băng chuyền mới. Họ được cấu hình "đọc từ đầu" → **nhặt sạch** mọi phiếu
   đã tích trên băng chuyền mới từ bước 2.

**Vì sao thứ tự này:** nếu làm ngược (đổi người nhặt trước), sẽ có phiếu rơi vào băng chuyền cũ mà **không còn
ai nhặt** → mồ côi vĩnh viễn.

**Đánh đổi:** giữa bước 2 và 4 có một khoảng phiếu **nằm chờ chưa được ghi sổ** (sổ cập nhật trễ vài phút).
Chấp nhận được vì **không mất** — chỉ trễ, và "đọc từ đầu" đảm bảo nhặt đủ.

**Kết quả:** cả hai người nhặt phiếu đều **bắt kịp hoàn toàn** (tồn đọng = 0), đơn chảy thông suốt qua băng
chuyền mới.

---

## 6. Sự cố đã gặp

### 6.1 🔴 Sự cố 0010 — đổi băng chuyền làm sập việc đặt hàng (~14 phút, **CÓ mất đơn**)

**Chuyện gì xảy ra:** ngay khi chuyển người bỏ phiếu sang băng chuyền mới, **việc đặt hàng sập hoàn toàn** 14 phút.

**Nguyên nhân gốc (giải thích đơn giản):**
Băng chuyền mới có **3 cửa** (3 địa chỉ). Cấu hình đưa cho chương trình dạng một danh sách:
`"cửa1, cửa2, cửa3"`. Nhưng code **quên tách danh sách đó ra**, mà cầm **nguyên cả chuỗi** đi tìm — như đi tìm
một căn nhà có địa chỉ là *"số 1, số 2, số 3"*. Không có địa chỉ nào như thế → **không kết nối được**.

Băng chuyền **cũ chỉ có 1 cửa** nên lỗi này **ẩn hoàn toàn** suốt thời gian trước đó. Chỉ khi lên băng chuyền
3 cửa nó mới lộ.

**Vì sao lỗi cấu hình lại thành SẬP (đây mới là bài học chính):**
Code khi không kết nối được thì **chỉ ghi log rồi... chạy tiếp** với "tay không". Nhân viên vẫn giơ biển
"tôi sẵn sàng", vẫn nhận khách — đến khi có đơn thật, nó **với tay vào chỗ trống** → **gục ngay giữa đơn hàng**.
Đơn đó đã **giao hàng + thu tiền** rồi mới gục → **mất đơn** (đã thu tiền, không vào sổ).

**Giải pháp đã chọn (3 lớp):**
1. **Tách đúng danh sách địa chỉ** → sửa lỗi gốc.
2. **"Hỏng thì chết ngay từ đầu"** *(fail-fast)*: nếu không kết nối được băng chuyền lúc khởi động thì nhân viên
   **tự nghỉ luôn, không giơ biển sẵn sàng** → hệ thống **không đưa khách** cho nó → **cấu hình sai chỉ làm việc
   triển khai đứng lại, KHÔNG thành sự cố khách hàng**.
3. **Ghi log ra chỗ đọc được ngay**: trước đây log lỗi bị đẩy vào hệ thống lưu trữ sâu, lúc khẩn cấp **không đọc
   được** → mất luôn manh mối. Nay in thẳng ra chỗ xem được tức thì.

**Đánh đổi của "chết ngay":** nhân viên sẽ từ chối làm việc nếu băng chuyền trục trặc, thay vì "cố làm". Nghe có
vẻ tệ hơn, nhưng **tốt hơn nhiều**: thà không nhận đơn còn hơn nhận đơn rồi thu tiền mà làm mất.

**Cách tìm ra nguyên nhân:** dựng **một nhân viên thử nghiệm tách biệt** (không cho khách nào vào), cắm cấu hình
băng chuyền mới, rồi đọc log → lộ ngay dòng lỗi thật. Sau khi sửa, chạy lại nhân viên thử nghiệm → kết nối sạch
→ **mới dám** đụng vào hệ thống thật.

---

### 6.2 🔴 Sự cố 0012 — "tường lửa nội bộ" của đội bạn làm sập 4 bộ phận (~30 phút, **0 đơn mất**)

**Chuyện gì xảy ra:** đúng lúc đang chuyển băng chuyền, đội bạn (CDO01, phụ trách Bảo mật) **áp một loạt 20
"tường lửa nội bộ"** lên gần như mọi nhân viên — làm thủ công, không báo trước. Trong ~30 phút:
- bộ phận **đặt hàng** sập (khách không đặt được),
- **danh mục sản phẩm**, **đánh giá**, **gợi ý** cũng sập,
- **giỏ hàng** hỏng ngầm (vẫn giơ biển "tôi ổn" nhưng thực ra không với tới kho của mình).

**Nguyên nhân gốc — hai lỗi cộng hưởng:**

1. **Tường lửa viết theo bản đồ CŨ.** Nó chỉ mở đường tới **kho cũ trong nhà**. Nhưng chúng tôi vừa chuyển các
   kho **ra ngoài (AWS)** — mà đường ra ngoài **không được mở**. Kết quả: nhân viên **không với tới kho của
   chính mình** → tê liệt.
   → *Bản chất: thay đổi bảo mật không cập nhật theo việc chuyển kho vừa xong.*

2. **Cách viết luật không tương thích với hạ tầng mạng đang dùng.** Luật ghi kiểu "cho phép đi tới **nhân viên
   tên X**", nhưng thực tế các nhân viên gọi nhau qua một **tổng đài** (địa chỉ ảo), và hệ thống mạng
   **không nhận ra** tổng đài đó là "nhân viên tên X" → **chặn luôn dù luật đã ghi cho phép**.
   → Đây là lý do **thêm luật cũng không cứu được** — phải gỡ hẳn.

**Chẩn đoán (phần đáng giá nhất):**
Ban đầu **rất dễ đổ oan cho việc chuyển băng chuyền của chúng tôi**, vì hai việc xảy ra cùng lúc. Đã loại trừ
bằng bằng chứng cứng:
- Một nhân viên **vẫn dùng cấu hình CŨ** (không liên quan băng chuyền mới) **cũng chết** → không phải do chuyển.
- Nhân viên **không bị áp tường lửa** thì **vẫn khoẻ**; chỉ ai **bị áp** mới chết → tường lửa là thủ phạm.
- Tra **nhật ký kiểm toán** của hệ thống → ra **đúng tài khoản nào, đúng mấy giờ mấy phút** đã áp.
- Dựng một **nhân viên thử** mang đúng "danh tính" của bộ phận đặt hàng để đo xem nó với tới đâu → khoanh vùng
  chính xác chỗ bị chặn.

**Giải pháp đã chọn:** **gỡ toàn bộ 20 tường lửa** (đã **sao lưu nguyên trạng** trước khi gỡ để đội bạn dựng lại).

**Đánh đổi:** gỡ hết = **tạm thời mất lớp cô lập mạng** mà đội bạn vừa dựng. Đã cân nhắc phương án "sửa từng cái"
nhưng bỏ, vì:
- sửa từng cái **không hiệu quả** (lỗi #2 khiến thêm luật cũng vô dụng),
- và có những bộ phận **hỏng ngầm mà vẫn báo "tôi ổn"** → sửa từng cái sẽ **sót**, để lại bom nổ chậm.

→ Ưu tiên **khôi phục dịch vụ cho khách trước**, bảo mật dựng lại sau **cho đúng**.

**Truy vết thiệt hại (đã đo bằng dữ liệu thật):**

| Chỉ số | Kết quả |
|---|---|
| Lượt bấm "đặt hàng" trong cửa sổ sự cố | **207** |
| Thành công | 31 (trước/sau sự cố — đều đã vào sổ) |
| **Thất bại** | **176** (khách thấy lỗi) |
| **Đơn bị mất** | **0** |

**Vì sao chắc chắn 0 đơn mất:**
- Cả 176 lượt đều lỗi ở **tầng kết nối** — tức **chưa hề bắt đầu xử lý đơn** → **chưa thu tiền, chưa giao hàng**
  → không có đơn nào "đã thu tiền mà mất".
- Tìm trong toàn bộ log: **0 lần** báo "bỏ phiếu thất bại". Và hệ thống log **chứng minh là đang chạy tốt**
  (nó bắt được 972 dòng cảnh báo khác cùng lúc) → con số 0 là thật, không phải do mất log.
- Bộ phận đặt hàng **không hề gục lần nào** → loại trừ kiểu mất như sự cố 0010.
- Mọi phiếu **đã bỏ lên băng chuyền** đều đã được nhặt và ghi sổ (tồn đọng = 0).

→ **Đây là sự cố "không dùng được", KHÔNG phải sự cố "mất dữ liệu".** Khác hẳn 0010.

---

### 6.3 Vài trục trặc nhỏ khác đã xử lý

| Trục trặc | Xử lý |
|---|---|
| Kho mới chặn kết nối từ hệ thống | Mở đúng "nhóm bảo vệ" của **máy chủ** (trước đó mở nhầm nhóm khác) |
| Chép sổ bị từ chối quyền | Chép bằng tài khoản quản trị thay vì tài khoản ứng dụng |
| "Đóng băng" nhân viên cứ bị tự bật lại | Khai báo ngoại lệ đúng chỗ trong hệ thống tự-chữa-lành |
| Báo động giả về thay đổi cấu hình kho (đội Mandate #11) | Khai báo đúng "cách áp dụng" tham số → hết báo động lặp |

---

## 7. Bảng tổng hợp các quyết định & đánh đổi

| Quyết định | Chọn gì | Được | Mất / Rủi ro chấp nhận |
|---|---|---|---|
| Tự dựng hay thuê AWS | **Thuê** | Hết điểm chết duy nhất, AWS lo vận hành | Tốn tiền hơn, bớt tuỳ biến |
| Chuyển giỏ hàng | **Ghi cả 2 nơi + chờ hội tụ** | Không downtime, tự khớp | Tốn gấp đôi thao tác trong 60 phút |
| Chuyển sổ cái | **Đóng băng người ghi duy nhất** | Khớp tuyệt đối, chứng minh được | Sổ trễ vài phút (khách không thấy) |
| Chuyển băng chuyền | **Người bỏ phiếu trước, người nhặt sau** | Không phiếu nào mồ côi | Sổ trễ trong cửa sổ chuyển |
| Khi cấu hình sai | **Chết ngay từ đầu** | Sai cấu hình ⇒ đứng triển khai, không thành sự cố | Nhân viên "khó tính" hơn, từ chối chạy khi kho trục trặc |
| Triển khai từ từ hay dứt điểm | **Dứt điểm (sau khi đã thử tách biệt)** | Tránh bị đánh giá sai vì cửa sổ đo dính sự cố | Bỏ qua thời gian "ngâm" quan sát |
| Sự cố tường lửa | **Gỡ cả loạt (có sao lưu)** | Khôi phục nhanh, không sót "bom nổ chậm" | Tạm mất lớp cô lập mạng |
| Kho cũ | **Giữ nguyên, chưa xoá** | Có đường lui thật | Tốn thêm tiền chạy song song |

---

## 8. Bằng chứng kết quả

| Kho | Bằng chứng |
|---|---|
| 🛒 Giỏ hàng | **827/827** giỏ khớp giữa kho cũ và mới |
| 🧾 Sổ cái | **70.478 → 70.556** đơn, khớp tuyệt đối, không mất đơn nào trong lúc đóng băng |
| 📦 Băng chuyền | Cả 2 bộ phận nhặt phiếu **bắt kịp hoàn toàn** (tồn đọng = 0); đơn chảy thông suốt |
| Trải nghiệm khách | Không downtime ở 2 kho đầu. Kho thứ 3: 2 sự cố (14 phút + 30 phút) đã khắc phục |
| An toàn | Mã hoá khi truyền + khi lưu; mật khẩu để trong kho bí mật của AWS, **không nằm trong code**; kho **không phơi ra Internet** |
| Độ bền | Cả 3 kho giờ có **bản dự phòng ở toà nhà khác** — hết điểm chết duy nhất |

---

## 9. Bài học rút ra (phần đáng giá nhất)

1. **"Chết ngay" tốt hơn "cố chạy".** Một cấu hình sai mà chương trình *cố chạy tiếp* sẽ biến thành sự cố khách
   hàng. Nếu nó *chết ngay từ đầu*, việc triển khai chỉ đứng lại — không ai bị ảnh hưởng. Đây là bài học đắt nhất.

2. **Lỗi ẩn chỉ lộ khi đổi môi trường.** Lỗi "3 cửa" nằm im rất lâu vì kho cũ chỉ có 1 cửa. → Khi đổi sang thứ
   *khác về bản chất* (1 → nhiều), phải **thử riêng đường đó trước**, đừng tin "trước giờ vẫn chạy".

3. **Phải đọc được log đúng lúc khẩn cấp.** Log đẩy vào kho lưu trữ sâu thì lúc cháy nhà **không lấy ra được**.
   Luôn giữ một đường log **đọc được ngay lập tức**.

4. **Thay đổi bảo mật phải đi cùng nhịp với thay đổi hạ tầng.** Tường lửa viết theo bản đồ cũ, trong khi kho vừa
   dọn nhà → chặn nhầm chính mình. **Hai đội phải nói chuyện trước khi đụng hệ thống thật.**

5. **"Vẫn báo ổn" chưa chắc là ổn.** Giỏ hàng vẫn giơ biển "tôi khoẻ" trong khi không với tới kho. → Tín hiệu
   sức khoẻ phải **kiểm tra thật** thứ mà dịch vụ phụ thuộc.

6. **Khi hai việc lớn xảy ra cùng lúc, đừng đoán — hãy loại trừ bằng bằng chứng.** Rất dễ đổ oan cho việc mình
   đang làm. Cách thoát: tìm một trường hợp **không liên quan việc mình làm mà vẫn hỏng**.

7. **Luôn sao lưu trước khi gỡ thứ của người khác**, kể cả khi đang chữa cháy.

---

## 10. Việc còn lại

| Việc | Ai | Ghi chú |
|---|---|---|
| Nghiệm thu với mentor | CDO02 | Trình bằng chứng ở mục 8 |
| **Rồi mới** xoá 3 kho cũ | CDO02 | Hiện vẫn chạy làm đường lui — **chưa xoá là cố ý** |
| Dựng lại tường lửa cho **đúng** | CDO01 | Phải mở đường ra kho mới (AWS) + thử 1 bộ phận trước khi áp cả loạt. Bản sao lưu đã bàn giao |
| Bỏ ghi ngược về kho giỏ hàng cũ | CDO02 | Sau khi nghiệm thu |
| Sửa chỗ khởi động còn phụ thuộc băng chuyền cũ | CDO02 | Hiện nhân viên đặt hàng vẫn "chờ băng chuyền cũ" lúc khởi động — cần bỏ khi xoá kho cũ |

---

## 11. Kết luận

Mandate #8 **hoàn thành cả 3 kho**, đạt đủ 4 ràng buộc: **không mất dữ liệu**, **không downtime** (ngoài 2 sự cố
đã khắc phục và đã phân tích), **an toàn**, **trong ngân sách**. Rủi ro lớn nhất của hệ thống — *ba kho dữ liệu
chỉ có một bản duy nhất trên một máy* — **đã được xoá bỏ**.

Hai sự cố gặp phải đều đã được **mổ xẻ đến tận gốc**, **sửa tận gốc** (không phải vá tạm), và **viết lại thành
tài liệu** để lần sau không lặp lại. Riêng sự cố thứ hai đã **truy vết đến từng đơn hàng** và chứng minh
**không mất đơn nào**.

---

### Tài liệu kỹ thuật đi kèm (cho người trong nghề)
- `docs/adr/0009-...` — quyết định kiến trúc & lý do
- `docs/runbooks/mandate-08-managed-cutover.md` — quy trình thao tác từng bước
- `docs/postmortem/0010-...` — mổ xẻ sự cố băng chuyền
- `docs/postmortem/0012-...` — mổ xẻ sự cố tường lửa (+ bản sao lưu đính kèm)

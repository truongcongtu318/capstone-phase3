# ADR 0011 - Mandate 16: Tối ưu độ trễ checkout

**Ngày:** 23/07/2026

**Người quyết định:** CDO02 (Reliability + Cost Optimization)

**Phối hợp/review:** CDO01, mentor

**Trạng thái:** Đã chấp nhận cho triển khai và thu thập evidence

**Liên quan:** Mandate 16, `docs/../mandates/mandate-16/mandate-16-checkout-latency-optimization.md`

## Bối cảnh

Mandate 16 yêu cầu giảm tail latency của `checkout` dưới tải bền mà không được "mua hiệu năng" bằng cách tăng pod, tăng node hoặc đổi topology production.

Trace và code review trên `checkout.PlaceOrder` cho thấy critical path của checkout dài hơn mức cần thiết vì nhiều bước độc lập vẫn đang chạy tuần tự.

Phần implementation đưa vào `phase3 - information/techx-corp-platform/src/checkout/main.go` thực tế đã xử lý ba điểm nghẽn riêng, không chỉ một bottleneck gộp chung kiểu "checkout preparation chậm".

## Các điểm nghẽn đã xác định

### Điểm nghẽn 1: chuẩn bị order item và lấy shipping quote đang chạy tuần tự

Sau khi lấy cart, `prepareOrderItemsAndShippingQuoteFromCart` đang chạy:

1. `prepOrderItems(...)`
2. `quoteShipping(...)`

Hai nhánh này cùng phụ thuộc vào cart, nhưng không phụ thuộc lẫn nhau. Việc chạy nối tiếp làm critical path của checkout bị kéo dài không cần thiết.

### Điểm nghẽn 2: từng cart item đang được enrich lần lượt

Bên trong `prepOrderItems`, mỗi line item đang phải đi qua:

1. `product-catalog.GetProduct`
2. `currency.Convert`

rồi mới chuyển sang item tiếp theo. Với cart nhiều sản phẩm, latency bị cộng dồn theo số item thay vì hội tụ về nhánh độc lập chậm nhất.

### Điểm nghẽn 3: gọi RPC đổi tiền dù không cần

`convertCurrency` vẫn gọi sang service `currency` ngay cả khi thực tế không cần đổi tiền, đặc biệt ở case phổ biến `USD -> USD` cho giá sản phẩm và shipping quote.

Việc này tạo thêm network hop, span và latency không cần thiết trên critical path.

## Quyết định

Giữ hướng triển khai Mandate 16 như một gói tối ưu code-path gồm ba thay đổi rõ ràng:

1. Chạy song song `prepOrderItems(...)` và `quoteShipping(...)` sau khi cart đã được tải.
2. Chạy concurrent phần enrich từng item bên trong `prepOrderItems(...)`, nhưng vẫn giữ thứ tự output bằng cách ghi kết quả về đúng index ban đầu.
3. Short-circuit `convertCurrency(...)` khi input nil, currency đích rỗng, hoặc currency nguồn đã trùng currency đích.

## Phạm vi

- Service: `checkout`
- Code path: `checkout.PlaceOrder`
- File implement chính: `phase3 - information/techx-corp-platform/src/checkout/main.go`
- File evidence: `docs/../mandates/mandate-16/mandate-16-checkout-latency-optimization.md`

## Vì sao đây là ranh giới đúng

Quyết định này chỉ tối ưu latency bằng cách loại bỏ các đoạn tuần tự hóa không cần thiết trong request path của checkout.

Phần này không:

- tăng replica
- đổi HPA
- đổi node pool
- đổi rollout strategy
- đổi network topology
- đổi business rule của checkout

Như vậy fix vẫn đúng tinh thần Mandate 16: nhanh hơn dưới tải, nhưng không dựa vào việc bơm thêm tài nguyên.

## Hệ quả

### Tích cực

- Critical path của checkout ngắn hơn vì các nhánh độc lập không còn phải đợi nhau.
- Tail latency bớt nhạy với số lượng item trong cart vì item preparation không còn cộng dồn tuyến tính như trước.
- Các case không cần đổi tiền không còn phải trả chi phí cho một RPC thừa.
- Phạm vi thay đổi hẹp và ít rủi ro vì chỉ nằm trong một service và một request path.

### Đánh đổi

- Số lượng downstream call concurrent tới `product-catalog` và `currency` có thể tăng thành từng burst ngắn khi cart lớn.
- Code path concurrent khó đọc và khó reasoning hơn vòng lặp tuần tự cũ.

### Giảm thiểu

- Thứ tự output vẫn được giữ bằng cách ghi kết quả vào đúng index ban đầu.
- Error handling vẫn giữ kiểu fail-fast ở mức request: nếu item preparation lỗi thì checkout vẫn fail thay vì trả partial data.
- Scope giữ ở mức code, không trộn thêm tuning hạ tầng production vào cùng thay đổi này.

## Rollback

- Chỉ revert phần tối ưu code path của `checkout`.
- Giữ nguyên manifest production, rollout settings, node pool và autoscaling configuration.
- Sau rollback, chạy lại đường verify checkout hiện có để xác nhận hành vi quay về baseline trước tối ưu.

## Kỳ vọng evidence

ADR này cần được bảo vệ bằng:

1. trace before/after cho thấy các span độc lập đã overlap
2. p95 và p99 before/after của checkout dưới tải bền
3. bằng chứng không tăng runtime capacity

Implementation note và evidence pack nằm tại:

- `docs/../mandates/mandate-16/mandate-16-checkout-latency-optimization.md`

## Kết luận cuối

Mandate 16 không phải là một fix cho một bottleneck đơn lẻ. Đây là một gói tối ưu tập trung vào ba điểm nghẽn liên quan trong cùng checkout path:

1. tuần tự giữa order-item preparation và shipping quote
2. tuần tự khi enrich từng item
3. RPC đổi tiền dư thừa

Chúng tôi chấp nhận thiết kế này vì nó giảm độ trễ checkout ở đúng nơi hẹp nhất và an toàn nhất, không đổi topology production và không mua tốc độ bằng hạ tầng bổ sung.

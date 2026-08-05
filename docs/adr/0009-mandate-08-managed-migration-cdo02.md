# ADR 0009 — Mandate #8: đưa cả 3 store lên managed (RDS / ElastiCache / MSK)

**Ngày:** 16/07/2026
**Người quyết định (ký):** CDO02 (Reliability + Cost Optimization)
**Directive:** `MANDATE-08-managed-migration.md` (repo chương trình: `TechX-Corp/xbrain-learners` →
`phase3/mandates/`) — hạn **20/07/2026**
**Trạng thái:** 🟡 Kế hoạch — chờ review, chưa thực thi
**Trụ:** Reliability (chính) · chạm Cost Optimization (right-size, Multi-AZ vs single) + Security (TLS/secret/private endpoint) + Auditability (ADR + dấu vết cutover)
**Thay thế:** [ADR 0002](0002-managed-services-evaluation.md) ở phần kết luận "hoãn MSK" (xem §Vì sao đảo chiều)

---

## Bối cảnh

Directive #8 bắt buộc **cả 3 store** — PostgreSQL, Valkey, Kafka — lên managed service (RDS,
ElastiCache, MSK), **không còn pod data tự host** trong cluster. Ràng buộc: **không mất dữ liệu**,
**không downtime khách** (checkout giữ SLO ≥99% suốt cutover), **TLS in-transit + encryption at
rest + credential trong Secrets Manager + endpoint riêng tư**, và **trong ngân sách ~$300/tuần**.

Directive #8 và #9 loại trừ nhau: đội **chưa** managed làm #8. TF3 đang chạy cả 3 store bằng pod
in-cluster → **#8 áp dụng cho TF3**.

## Hiện trạng đã audit (đo thực tế trên cluster)

| Store | Đo được | Hệ quả |
|---|---|---|
| Postgres | **17.6**, **29 MB**, 3 schema (`accounting` 3 bảng, `reviews` 1, `catalog` 1), extension chỉ `plpgsql` | RDS có **đúng 17.6**; không extension lạ → không vướng tương thích |
| Valkey | **9.0.1**, chỉ `cart` dùng, AOF on | ElastiCache có **đúng Valkey 9.0** |
| Kafka | **3.9.1 KRaft**, 1 broker, **1 topic `orders`**, producer=`checkout`, consumer group=`accounting`+`fraud-detection` | MSK có **3.9.x.kraft**; topology đơn giản |
| Mạng | VPC `vpc-0c0b86b42bbbefd55`, **3 private subnet / 3 AZ** (1a/1b/1c) | đủ cho Multi-AZ + private endpoint, không cần đụng VPC |

**Không store nào phải nhảy version** — managed khớp version in-cluster 1:1. Rủi ro migration vì
thế **không nằm ở tương thích engine**, mà nằm ở **cơ chế cutover + TLS + credential**.

### Ba phát hiện định hình scope

**1. TLS bắt buộc → phải sửa CODE 4 service** (không chỉ đổi env):

| Service | Bằng chứng trong source | Cần |
|---|---|---|
| `cart` | `cart/src/cartstore/ValkeyCartStore.cs:52` hardcode `ssl=false` | sửa code |
| `checkout` | `checkout/kafka/producer.go` — `sarama.NewConfig()` không set `Net.TLS.Enable` | sửa code |
| `accounting` | `accounting/Consumer.cs:182` — `ConsumerConfig` không set `SecurityProtocol` | sửa code |
| `fraud-detection` | `main.kt:47` — chỉ set `BOOTSTRAP_SERVERS_CONFIG` | sửa code |
| **Postgres (3 client)** | conn string đến từ **env** `DB_CONNECTION_STRING` | chỉ đổi `sslmode=require` — **không sửa code** |

**2. Credential plaintext** `otelu/otelp` nằm trong `techx-corp-chart/values.yaml`, ở **3 format khác nhau**:
- accounting (.NET/Npgsql): `Host=postgresql;Username=otelu;Password=otelp;Database=otel`
- product-catalog (Go): `postgres://otelu:otelp@postgresql/otel?sslmode=disable`
- product-reviews (Python/libpq): `host=postgresql user=otelu password=otelp dbname=otel`

→ Secrets Manager phải render **3 kiểu**, không dùng chung 1 string được.

**3. Kafka nằm TRÊN luồng đồng bộ ra tiền — rủi ro cao nhất.** `checkout` dùng `SyncProducer` +
`RequiredAcks=WaitForAll` và **await** kết quả publish (REL-09, cố ý — để không mất đơn). Hệ quả:
**MSK không nối được = `PlaceOrder` fail ngay = vỡ SLO ≥99%**. Ngược lại `accounting`/`fraud-detection`
là consumer **async**, trễ vài phút không ảnh hưởng khách.

**4. `accounting` là NGƯỜI GHI DUY NHẤT vào Postgres — và nó ghi async.** Audit source:

| Service | Truy cập Postgres | Bằng chứng |
|---|---|---|
| `product-catalog` | **CHỈ ĐỌC** | không có INSERT/UPDATE/DELETE nào trong source |
| `product-reviews` | **CHỈ ĐỌC** | `database.py` — mọi query là `SELECT` + `fetchall()`; `commit()` chỉ để đóng read-transaction (REL-05 connection pool) |
| `accounting` | **GHI** | `Consumer.cs:133/146/162/163` — `_dbContext.Add(...)` + `SaveChanges()`, **từ Kafka consumer**, `EnableAutoCommit=false` (REL-09) |

`catalog.products` (10 dòng) và `reviews.productreviews` (50 dòng) là **seed data tĩnh**, không ghi lúc chạy.

Đây là chìa khoá của cả kế hoạch Postgres (xem §4 Quyết định): **đóng băng người ghi duy nhất** thì
Postgres thành read-only → dump/restore ra parity **chính xác tuyệt đối**, mà khách **không hề bị ảnh
hưởng** (accounting là back-office async). Không cần logical replication, **không cần đụng `wal_level`**.

## Vì sao đảo chiều kết luận ADR 0002

ADR 0002 (12/07) quyết định **hoãn MSK** vì "phá ngân sách". Hai cơ sở của kết luận đó **đã không còn đúng**:

1. **Giả định EKS ngốn ~$500/mo extended support** → thực tế **EKS đang ở 1.35** (standard support).
   Khoản phạt đó không tồn tại; ngân sách rộng hơn hẳn so với lúc viết ADR 0002.
2. **Con số "MSK ~$540/mo"** trong ADR 0002 là giá **MSK Serverless**. **MSK provisioned** với
   `kafka.m7g.large` (~$390/mo, xem §Cost — bản nháp dùng t3.small nhưng 3.9.x không hỗ trợ) vẫn
   **rẻ hơn Serverless**, dù không còn "rẻ hơn nhiều lần" như ước tính t3.small ban đầu.

Ngoài ra ADR 0002 đã tự ghi điều kiện: *"Nếu BTC ra mandate migrate datastore theo cách khác (VD bắt
buộc MSK) → thực thi theo mandate"*. Directive #8 chính là trường hợp đó. ADR 0009 này thực thi
điều kiện đã ghi sẵn, **không phải đảo ngược tuỳ tiện**.

## Quyết định

### 1. Cấu hình từng store (right-size + Multi-AZ có lý do)

| Store | Chọn | Multi-AZ? | Vì sao | Giá (đã verify) |
|---|---|---|---|---|
| **RDS PostgreSQL 17.6** | `db.t4g.micro` | **CÓ** | Dữ liệu **tài chính** (`order` 29k, `orderitem` 53k). Durability giá trị cao nhất; **+$19/mo** so với Single-AZ là rẻ so với mất đơn. Graviton (t4g) rẻ hơn t3 cùng hiệu năng. | **$37.23/mo** + storage |
| **ElastiCache Valkey 9.0** | `cache.t4g.micro`, 1 primary + **1 replica** | **CÓ** | Giỏ hàng là dữ liệu "mềm" (khách thêm lại được) **nhưng `cart` nằm TRÊN luồng đồng bộ** browse→cart→checkout — mất cache = vỡ SLO browse/cart, không chỉ mất data. Replica cho auto-failover. Engine Valkey rẻ hơn Redis 20%. | **$28.04/mo** (2 node) |
| **MSK Kafka 3.9.x KRaft** | **3× `kafka.m7g.large`** / 3 AZ, **RF=3, min.insync.replicas=2** (t3.small bị loại — xem §Cost) | **CÓ** (3 AZ) | `checkout` dùng `acks=all`: cần ISR ≥ min.insync. RF=3/min.insync=2 → **chịu mất 1 broker mà vẫn produce được**, mỗi ack đảm bảo ≥2 bản sao. Phương án 2 broker rẻ hơn ~$130/mo nhưng buộc phải chọn giữa "mất 1 broker ⇒ checkout fail" và "ack chỉ 1 bản sao ⇒ mất đơn" — xem §Đánh đổi. | **~$390/mo** + storage |

### Cost (cập nhật 18/07 sau khi apply thật)

⚠️ **Đính chính lớn về MSK:** bảng cost cũ dùng `kafka.t3.small` ($126.57/mo). Khi apply thật (18/07),
`CreateCluster` trả `BadRequestException: Unsupported InstanceType` — **MSK 3.9.x KHÔNG còn hỗ trợ
t3.small**; instance nhỏ nhất hợp lệ là `kafka.m5.large` / `kafka.m7g.large` / `express.m7g.large`.
Đã đổi sang **`kafka.m7g.large`** (Graviton, rẻ nhất nhóm hợp lệ). Đây là sai sót trong bản nháp:
không kiểm compat instance↔version trước. Con số MSK bên dưới đội lên đáng kể.

| Khoản | Đơn giá | $/tháng |
|---|---|---|
| RDS `db.t4g.micro` **Multi-AZ** | $0.0510/hr (verify Pricing API) | **37.23** |
| RDS gp3 storage 20 GB Multi-AZ | $0.276/GB-mo | **5.52** |
| ElastiCache **Valkey** `cache.t4g.micro` × 2 | $0.0192/hr/node | **28.04** |
| MSK **`kafka.m7g.large`** × 3 broker | **$0.2550/hr/broker** (Pricing API `APS1-Kafka.m7g.large`, xác nhận 22/07) | **558.45** |
| MSK storage GP2 10 GB × 3 | $0.12/GB-mo | **3.60** |
| Secrets Manager × 3 (RDS-managed / elasticache-auth / MSK-scram) | $0.40/secret-mo | **1.20** |
| KMS customer-managed key (bắt buộc cho MSK SCRAM secret, §3) | ~$1/key-mo | **1.00** |
| **TỔNG** | | **≈ $635/mo ≈ $146/tuần** |

#### Đính chính lần 2 (22/07) — con số thật thay cho ước lượng

Ước lượng ~$0.178/hr/broker ở bản 18/07 **thấp hơn thực tế 43%**. Đã lấy giá chính thức từ AWS Pricing
API (`get-products --service-code AmazonMSK`, location `Asia Pacific (Singapore)`) và đối chiếu với Cost
Explorer: MSK tiêu **$18.36/ngày** đúng bằng `3 × $0.2550 × 24`. Cảnh báo "phải xác nhận sau vài ngày"
ở bản trước là đúng chỗ, và kết quả xác nhận là **đội hơn ước lượng**, không phải ít hơn.

**Hệ quả với ràng buộc ngân sách:** tổng chi toàn TF3 đo ngày 21/07 là **$426/tuần so với trần $300** →
**đang vượt 42%**. Nhưng phân rã cho thấy Mandate #8 không phải nguyên nhân duy nhất: $96.7/tuần thuộc
tầng AI (riêng **$80.6/tuần là 2 OCU OpenSearch Serverless mồ côi**, KB kẹt `DELETE_UNSUCCESSFUL`) và
$23.2/tuần thuộc stack `thermal-power-plant-*` ở Tokyo **không thuộc Phase 3**. Kế hoạch đưa về
**$269.7/tuần mà không đảo ngược quyết định nào của ADR này** — xem `docs/../reports/cost-breakdown-2026-07-22.md`
và mục G.3 của báo cáo nghiệm thu.

#### Đã kiểm chứng: $558/mo là giá sàn tuyệt đối của MSK KRaft

Ngày 22/07 thử lại có hệ thống để chắc chắn không bỏ sót phương án rẻ hơn:

| Phép thử | Kết quả |
|---|---|
| `t3.small` + `3.9.x.kraft` | ❌ `BadRequestException: Unsupported InstanceType` |
| `t3.small` + `3.8.x.kraft` | ❌ `BadRequestException` |
| `t3.small` + `3.8.x` (ZooKeeper) | ✅ tạo được — **rào cản là KRaft mode, không phải version** |

Đính chính bản 18/07: lý do t3.small bị loại **không phải "3.9.x không hỗ trợ"** mà là **chế độ KRaft**
không hỗ trợ. Danh sách hợp lệ cho mọi version KRaft chỉ gồm `express.m7g.*` / `kafka.m5.*` /
`kafka.m7g.*`, trong đó `m7g.large` ($0.2550) rẻ hơn `m5.large` ($0.2630) — lựa chọn hiện tại **đã là
đáy nhóm hợp lệ**. Ngoài ra: `update-broker-count` chỉ tăng không giảm; MSK không có API stop/start;
PublicAccess/PrivateLink/provisioned-throughput/replicator/tiered-storage đều đã tắt.

**MSK Serverless** (Pricing API): $0.9375/hr/cụm = **$684/mo** chưa kể partition-hour và bytes → **đắt
hơn provisioned**. Kết luận "hoãn Serverless" của ADR 0002 đúng chiều, chỉ sai độ lớn ($540 → $684).

**Phương án 2 broker** (RF=2/min.insync=1, 2 AZ): MSK **$372/mo** → rẻ hơn $186/mo. Đã cân nhắc và loại
— xem §Đánh đổi (order data cần RF=3). Nếu áp lực cost tăng, đây là đòn bẩy.

**Phương án `MSK 3.8.x` ZooKeeper + `t3.small` = $127/mo** (tiết kiệm $431/mo) **vẫn tuân thủ directive**
— directive yêu cầu "Kafka → MSK", không quy định KRaft. Không chọn ở thời điểm này vì: (1) MSK không
cho chuyển KRaft → ZooKeeper nên phải dựng cụm mới + **cutover Kafka lần 3**, tức đánh đổi yêu cầu 2
(zero-loss / SLO ≥99%) — đúng chỗ đã sinh ra sự cố 0010; (2) ZooKeeper mode đang bị khai tử (`3.9.x` ZK
đã `DEPRECATED`, Kafka 4.x bỏ hẳn ZooKeeper) nên sẽ phải migrate lại. **Ghi vào backlog COST**, xem lại
sau nghiệm thu nếu áp lực ngân sách còn.

**Ghi chú Valkey rẻ hơn Redis:** ElastiCache tính Valkey **$0.0192/hr** vs Redis **$0.0240/hr**
(−20%). Ta đang chạy Valkey 9.0.1 in-cluster → chọn engine Valkey vừa khớp version vừa rẻ hơn.

> ⚠️ Cả **baseline chi hiện tại (~$100/tuần)** lẫn **đơn giá MSK m7g.large** đều là ƯỚC LƯỢNG —
> AWS Cost Explorer account mới (197826770971) chưa đủ dữ liệu. **Việc cần làm gấp: dựng AWS Budgets +
> Cost Anomaly Detection** để có số thật (đặc biệt quan trọng giờ MSK đắt hơn dự kiến).
> Chưa tính data transfer cross-AZ client↔broker MSK (lưu lượng hiện ~0.85 đơn/s, message nhỏ → không đáng kể).

### 2. TLS + auth gated bằng env — tách "deploy code" khỏi "cutover"

Sửa 4 service để **TLS và authentication** đều **có công tắc env**, mặc định **tắt** (= hành vi hiện tại):

| Service | Biến | Mặc định | Khi cutover |
|---|---|---|---|
| `cart` | `VALKEY_TLS` + `VALKEY_AUTH_TOKEN` | `false` / rỗng | `ssl=true,password=$VALKEY_AUTH_TOKEN` trong `ValkeyCartStore` |
| `checkout` | `KAFKA_SECURITY_PROTOCOL` + `KAFKA_SASL_USERNAME`/`_PASSWORD` | `PLAINTEXT` / rỗng | `SASL_SSL` + `Net.SASL` SCRAM-SHA-512 (sarama) |
| `accounting` | `KAFKA_SECURITY_PROTOCOL` + `KAFKA_SASL_USERNAME`/`_PASSWORD` | `PLAINTEXT` / rỗng | `SecurityProtocol=SaslSsl, SaslMechanism=ScramSha512` |
| `fraud-detection` | `KAFKA_SECURITY_PROTOCOL` + `KAFKA_SASL_USERNAME`/`_PASSWORD` | `PLAINTEXT` / rỗng | `security.protocol=SASL_SSL, sasl.mechanism=SCRAM-SHA-512` |

⚠️ **`checkout` (sarama) tốn công nhất:** sarama **không có sẵn** SCRAM client — phải tự implement
`sarama.SCRAMClient` (thường dùng `github.com/xdg-go/scram`). Đây là thay đổi code thật, không phải
một cờ. Tính vào ước lượng công.

`cart` cần **thêm một việc nữa**: nhánh **dual-write** tạm (`VALKEY_DUAL_WRITE_ADDR`, rỗng = tắt) —
điều kiện của chứng minh §5. **Tổng: 4 service sửa code; `cart` 3 việc (TLS + auth + dual-write),
`checkout` 2 việc trong đó có SCRAM client tự viết.**

**Vì sao:** deploy code với cờ tắt = **hành vi không đổi**, vẫn nói chuyện được với store cũ
plaintext → deploy được sớm, an toàn, review kỹ, **không dính vào cửa sổ cutover**. Tới lúc cutover
chỉ **bật cờ + đổi endpoint**. **Rollback = tắt cờ + trả endpoint cũ** (một thay đổi values, ArgoCD
sync ~1 phút) thay vì phải revert image.

MSK/ElastiCache dùng **TLS server-side với CA công cộng của AWS** → client chỉ cần bật TLS, **không
cần mount custom CA bundle** (giữ thay đổi code tối thiểu).

### 3. Authentication + credential → Secrets Manager cho **cả ba** store

Yêu cầu #3 của directive là *"credential để trong Secrets Manager"* — áp cho **cả 3 store**, không
riêng Postgres. TLS + private endpoint **không thay thế được authentication**: chúng chỉ chống nghe
lén và chặn truy cập từ ngoài VPC. **Bên trong VPC, không auth = bất kỳ pod nào cũng đọc/ghi được
topic `orders` và toàn bộ giỏ hàng.** Với dữ liệu đơn hàng, đó là lỗ hổng thật, không phải hình thức.

| Store | Cơ chế auth | Secret | Ghi chú |
|---|---|---|---|
| **RDS** | user/password (native) | `techx-tf3/postgres` | như cũ |
| **ElastiCache Valkey** | **AUTH token** (`--auth-token`) | `techx-tf3/elasticache-auth` | **bắt buộc** `transit_encryption_enabled=true` (đã có) |
| **MSK** | **SASL/SCRAM-SHA-512** | `AmazonMSK_techx-tf3/kafka-scram` | MSK **tích hợp Secrets Manager native** (`batch-associate-scram-secret`) |

**Ràng buộc MSK/SCRAM (đã verify qua CLI):** secret **phải** có tiền tố tên `AmazonMSK_` và **phải**
mã hoá bằng **customer-managed KMS key** (MSK từ chối key `aws/secretsmanager` mặc định) → phát sinh
1 CMK (~$1/mo). Bootstrap dùng `BootstrapBrokerStringSaslScram` (cổng 9096), **không** phải `...Tls` (9094).

**Vì sao SASL/SCRAM chứ không phải SASL/IAM:** IAM auth (qua IRSA) an toàn hơn về nguyên tắc — không
có credential nào để rò rỉ hay xoay. Nhưng client phải hỗ trợ: Kotlin/Java có `aws-msk-iam-auth` sẵn,
còn **sarama (Go) cần tự viết `AccessTokenProvider`** và **confluent-kafka-dotnet hỗ trợ yếu**. Với
**3 ngôn ngữ khác nhau và 4 ngày**, SCRAM là lựa chọn khả thi — và nó **đúng nghĩa đen yêu cầu
"credential trong Secrets Manager"** vì MSK đọc thẳng secret từ đó. IAM auth ghi nhận là hướng nâng
cấp sau mandate.

**Đưa vào pod:** **External Secrets Operator** (hoặc Secrets Store CSI) đọc 3 secret trên → sinh K8s
secret, inject qua `valueFrom.secretKeyRef`. Riêng Postgres phải render **3 format khác nhau**
(.NET `Host=...;` / Go-URL `postgres://` / libpq `host=... user=...`) vì 3 client parse khác nhau.

**Nguyên tắc thao tác (áp cho cả runbook):** credential **chỉ rời Secrets Manager khi bắt buộc**.
- Thao tác **MSK** chạy từ pod trong cluster, credential bơm bằng **`secretKeyRef`** → giá trị thật
  **không nằm trong pod spec**, `kubectl get pod -o yaml` không lộ. Truyền credential bằng `--env=`
  (giá trị thật) chỉ là **break-glass**, và nếu đã dùng thì **phải xoay lại secret** sau đó.
- Thao tác **RDS/ElastiCache** chạy từ máy vận hành qua SSM tunnel nên **buộc** phải kéo password/token
  về shell — đây là **giới hạn có ý thức** của việc dùng tunnel, đổi lấy thao tác đơn giản. Bù lại:
  không ghi ra file, không paste vào PR/chat, và secret **xoay được** sau cutover.

**Gỡ sạch `otelu/otelp` khỏi `values.yaml`** — vá luôn lỗ hổng token plaintext ADR 0002 đã ghi nhận.

**Chi phí:** 3 secret × $0.40 + 1 CMK ~$1 ≈ **$2.20/mo**.

### 4. Thứ tự cutover: Valkey → Postgres → Kafka (dễ → khó)

Làm cái rủi ro thấp trước để **kiểm chứng toàn bộ đường ống** (terraform → secret → TLS flag →
cutover → verify → rollback) trên store ít nguy hiểm nhất, rồi mới đụng Postgres và Kafka.
Chi tiết từng bước: [`docs/runbooks/mandate-08-managed-cutover.md`](../runbooks/mandate-08-managed-cutover.md).

**Ý tưởng cốt lõi cho Kafka — không cần dual-consume**, tận dụng `AutoOffsetReset=Earliest`:

```
a. Dựng MSK + tạo topic `orders` (RF=3, min.insync=2)
b. Chuyển producer `checkout` → MSK   (đơn mới vào MSK, chưa ai đọc)
c. ⚠️ CHỜ MỌI pod `checkout` lên revision mới  ← BẮT BUỘC, xem §5. Bỏ qua bước này = mất đơn
d. Chờ consumer cũ hút cạn Kafka cũ (lag = 0)   ← chỉ đo SAU khi (c) xong
e. Chuyển consumer `accounting`/`fraud-detection` → MSK
   → consumer group mới trên MSK, đọc từ Earliest → ăn sạch backlog từ (b)
→ 0 mất message, 0 downtime khách (consumer async, trễ vài phút chấp nhận được)
```

**Postgres zero-downtime — "đóng băng người ghi duy nhất"** (KHÔNG dùng logical replication):

```
a. Scale `accounting` → 0     (người ghi DUY NHẤT dừng; Postgres thành read-only)
   → checkout vẫn publish vào Kafka bình thường, đơn dồn lại ở topic `orders`
   → product-catalog/product-reviews vẫn ĐỌC bình thường  → KHÁCH KHÔNG BIẾT GÌ
b. pg_dump → restore sang RDS  (29 MB → vài giây)
c. Parity check trên nguồn ĐÃ ĐÓNG BĂNG → row count/checksum khớp TUYỆT ĐỐI
d. Đổi DB_CONNECTION_STRING của 3 service → RDS  (rolling, maxUnavailable:0 + preStop → 0 rớt request)
e. Scale `accounting` → 1 (số replica gốc), trỏ RDS
   → offset CHƯA commit (EnableAutoCommit=false, REL-09) → replay sạch đơn dồn từ (a) vào RDS
→ 0 mất đơn, 0 downtime khách. Giá phải trả: accounting trễ vài phút (back-office, không ai thấy).
```

**Vì sao không dùng logical replication:** nó đòi `wal_level=logical`, mà Postgres in-cluster đang
`wal_level=replica` (đã kiểm tra) → đổi tham số này **bắt buộc restart Postgres** = **read outage cho
`product-catalog`/`product-reviews`** = vỡ SLO browse. Nghịch lý: để migrate "zero-downtime" bằng
logical replication thì trước đó phải chịu một downtime. Cách "đóng băng người ghi" **né hoàn toàn**
nghịch lý này, đơn giản hơn, ít bộ phận chuyển động hơn, và cho **parity chứng minh được tuyệt đối**
(nguồn đứng yên lúc so).

**Điều kiện an toàn:** retention topic `orders` phải dài hơn cửa sổ cutover. **Đã verify trên broker:**
`log.retention.hours=168` (7 ngày), `log.retention.bytes=-1` (không giới hạn dung lượng), topic `orders`
không override → **7 ngày ≫ cửa sổ ~10 phút**. ✅ Vẫn xác nhận lại trước khi bắt đầu.

### 5. Đạt **100% không mất dữ liệu** — chứng minh cho từng store

Directive #8 đòi "không mất dữ liệu, không downtime khách". Dưới đây là **lập luận vì sao mỗi store
đạt tuyệt đối**, không phải "cố gắng hạn chế".

#### Postgres — chứng minh
1. `accounting` là **người ghi duy nhất** (đã audit source, §Hiện trạng #4) → dừng nó ⇒ nguồn **bất biến**.
2. Nguồn bất biến ⇒ `pg_dump`/restore là **ảnh chụp đầy đủ**, và parity check so trên nguồn đứng yên
   là **bằng chứng tuyệt đối** (không có race "số đổi trong lúc đếm").
3. Đơn phát sinh trong cửa sổ **không mất**: `checkout` vẫn publish vào Kafka; `accounting` dùng
   `EnableAutoCommit=false` (REL-09) nên **offset chưa commit** → khi bật lại, nó **replay đúng từ chỗ dừng**.
4. Khách không bị ảnh hưởng: reader (`product-catalog`/`product-reviews`) **không hề dừng**; lúc rolling
   restart, pod cũ đọc PG cũ / pod mới đọc RDS — **hai nguồn giống hệt nhau vì đã đóng băng** ⇒ đọc nhất quán.

> ∎ **Mất mát = 0. Ảnh hưởng khách = 0.** Giá phải trả duy nhất: accounting trễ vài phút (back-office).

#### Kafka — chứng minh (kèm **thứ tự bắt buộc**)
1. Chuyển producer trước: trong lúc rolling, pod cũ → Kafka cũ, pod mới → MSK. **Cả hai đều sống** ⇒
   không có `PlaceOrder` nào fail.
2. ⚠️ **Điểm chết người:** phải **chờ MỌI pod `checkout` lên revision mới** rồi *mới* đo lag Kafka cũ.
   Nếu đo lag=0 khi vẫn còn pod cũ đang produce, một message có thể rơi vào Kafka cũ **sau** lúc đo →
   chuyển consumer đi → **message đó mồ côi vĩnh viễn**. Đây là lỗi thứ tự tinh vi, phải tuân thủ đúng.
3. Sau khi lag cũ = 0 và không còn producer nào trỏ Kafka cũ ⇒ Kafka cũ **đóng băng và đã cạn**.
4. Consumer chuyển sang MSK với group mới + `AutoOffsetReset=Earliest` ⇒ đọc **từ đầu** topic MSK ⇒
   nuốt trọn backlog tích từ bước 1.

> ∎ **Mất mát = 0** nếu và chỉ nếu tuân thủ thứ tự: *producer rolled xong hết → lag cũ = 0 → mới chuyển consumer*.

#### Valkey — chứng minh (dựa trên **TTL 60 phút của chính app**)
Phát hiện quyết định: `ValkeyCartStore.cs:174,199` — **mọi lần ghi** (`AddItem`/`EmptyCart`) đều
`KeyExpireAsync(userId, TimeSpan.FromMinutes(60))`. **Đọc không gia hạn TTL.**
Đã verify trên cluster: **864 key, TTL mẫu 102s/3106s/3092s, quét 50 key không có key nào thiếu TTL**.

Suy ra **bất biến**: *một giỏ còn sống tại thời điểm T ⟺ nó được GHI trong khoảng [T−60ph, T]*.

**Chiến lược "cửa sổ hội tụ 60 phút":**
```
T0      : deploy cart DUAL-WRITE (ghi cả valkey cũ + ElastiCache), ĐỌC vẫn từ cũ
          → hành vi khách không đổi; cũ vẫn là nguồn sự thật
T0+60ph : MỌI giỏ còn sống đều đã được ghi ít nhất 1 lần trong [T0, T0+60ph]
          (vì nếu không ghi trong 60ph qua thì nó đã TTL-expire rồi)
          ⇒ ElastiCache chứa TOÀN BỘ giỏ còn sống — chứng minh được, không cần bulk copy
T0+60ph : lật ĐỌC sang ElastiCache, **VẪN GIỮ dual-write**  → 0 mất giỏ, 0 downtime
          → valkey cũ tiếp tục được ghi đầy đủ ⇒ rollback bất kỳ lúc nào cũng KHÔNG mất gì
sau nghiệm thu : mới gỡ dual-write → rồi gỡ valkey cũ
```
**Vì sao đúng tuyệt đối:** tập giỏ "còn sống" tại `T0+60ph` là **tập con** của tập giỏ "được ghi trong
cửa sổ dual-write". Giỏ nào không được ghi trong cửa sổ đó thì **đã bị chính app xoá bằng TTL** — đó là
hành vi thiết kế của ứng dụng, **không phải mất mát do migration**.

> ∎ **Mất mát = 0. Không cần bulk copy, không cần `MIGRATE`/`DUMP`, không phụ thuộc tính năng AWS nào.**
> Chỉ cần một nhánh dual-write tạm trong `cart` + chờ đủ 60 phút.

**Đây là lời giải thay thế cho điểm yếu ở bản nháp trước** (bản trước chấp nhận "mất giỏ đang mở" và
định xin mentor thông cảm). **Không cần thoả hiệp nữa.**

## Đánh đổi đã cân

- **MSK 3 broker (~$390) thay vì 2 (~$262):** đắt hơn **~$130/mo** (m7g.large, sau khi t3.small bị loại), đổi lấy RF=3/min.insync=2 →
  `acks=all` **vẫn produce được khi mất 1 broker**, và mỗi ack đảm bảo ≥2 bản sao. Với 2 broker phải
  chọn: min.insync=2 (mất 1 broker ⇒ **checkout fail ngay**) hoặc min.insync=1 (ack chỉ 1 bản sao ⇒
  broker đó chết là **mất đơn**). Vì `checkout` **chặn đồng bộ** trên publish, cả hai đều không chấp
  nhận được với **dữ liệu đơn hàng**. Trả thêm $42/mo.
- **ElastiCache có replica ($28.04) thay vì single ($14.02):** trái với tinh thần "đừng nhân đôi mọi thứ"
  của [ADR 0007](0007-mandate-03-maintenance-no-downtime-cdo02.md), nhưng khác biệt là `cart` **nằm
  trên luồng đồng bộ** — mất nó vỡ SLO browse/cart chứ không chỉ mất dữ liệu mềm. Đây là nhân đôi
  **có lý do đo được**, không phải cho chắc.
- **RDS Multi-AZ ($37.23) thay vì single ($18.25):** dữ liệu tài chính; **+$19/mo** là khoản rẻ nhất
  trong ADR này để đổi lấy auto-failover + durability.
- **Dual-write `cart` + chờ 60 phút** (§5) thay vì cutover thẳng: thêm một nhánh code tạm + một cửa sổ
  chờ 60 phút, đổi lấy **0 mất giỏ chứng minh được**. Đáng — đây là khác biệt giữa "đạt mandate" và
  "xin mentor thông cảm".
- **TLS gated bằng env:** thêm một nhánh code + một biến cấu hình (phức tạp hơn bật cứng), đổi lấy
  **deploy tách khỏi cutover** + **rollback không cần rebuild image**. Đáng.
- **Bỏ toàn bộ công PVC Kafka in-cluster** (REL-10, 3 lần cutover, `publishNotReadyAddresses`): sunk
  cost, #8 bắt buộc gỡ pod Kafka. Không tiếc — nhưng ghi lại để hội đồng thấy đây là quyết định của
  directive, không phải làm thừa.

## Giới hạn đã biết (nói thẳng, không giấu)

- **Đơn giá đã verify qua Pricing API, nhưng baseline chi hiện tại (~$100/tuần) vẫn là ước lượng** —
  Cost Explorer account mới chưa dùng được. Phải dựng AWS Budgets để có số thật.
- **`checkout` chặn đồng bộ trên Kafka** là điểm mong manh nhất của cả mandate. Kể cả sau MSK, một sự
  cố MSK vẫn kéo `PlaceOrder` fail. Fix gốc (publish async + outbox) **ngoài phạm vi #8** — ghi nhận
  là nợ kỹ thuật, không giả vờ đã giải quyết.
- **Cutover Kafka phụ thuộc THỨ TỰ** (§5): nếu đo lag Kafka cũ khi vẫn còn pod `checkout` revision cũ
  đang produce → message mồ côi. Không có cơ chế tự động chặn sai thứ tự này — **phải kỷ luật thao tác
  theo runbook**. Đây là rủi ro con người, không phải rủi ro kỹ thuật.
- **Dual-write `cart` cần đúng 60 phút chờ.** Rút ngắn cửa sổ = phá vỡ chứng minh ở §5. Nếu áp lực
  deadline khiến ai đó "chờ 20 phút cho nhanh" thì **mất giỏ thật**. Cửa sổ 60 phút là **bắt buộc**,
  không phải khuyến nghị. (An toàn hơn: chờ 65-70 phút cho biên.)
- **`accounting` phải là người ghi Postgres duy nhất — mãi mãi trong cửa sổ cutover.** Nếu sau này có
  service khác ghi vào Postgres, chứng minh ở §5 **sụp**. Phải re-audit trước khi thực thi nếu code đã đổi.
- **4 ngày cho toàn bộ khối lượng** (5 code change gồm dual-write + build image + terraform 3 service +
  Secrets Manager + 3 cutover + cửa sổ chờ 60 phút + bằng chứng parity + rollback) là **rất căng**.
  #8 không cho thương lượng phạm vi. Nếu trượt, ưu tiên giữ **Postgres** (giá trị durability cao nhất).

## Ràng buộc đã tôn trọng

- **Ngân sách:** ≈**$208/tuần** vs trần **$300/tuần** (MSK m7g.large ước lượng sau khi t3.small bị loại — xem §Cost, cần Budgets xác nhận).
- **Không đụng flagd.** Storefront vẫn public, cổng vận hành vẫn private (Directive #1) — 3 store
  đều đặt trong **private subnet**, **không public endpoint**. Security group mở tối thiểu: inbound từ
  **SG node group** (app), cộng **SG bastion** cho RDS/ElastiCache (đường vận hành/migration qua SSM
  tunnel — xem runbook §0). MSK không cần SG bastion (thao tác qua pod trong cluster).
- **Encryption at rest** bật trên cả 3 (KMS mặc định của AWS, $0).

## Bằng chứng hoàn thành (nộp cho mentor)

1. **3 store chạy trên RDS / ElastiCache / MSK**, app trỏ vào đó — `kubectl get pods` cho thấy
   **không còn pod `postgresql` / `valkey-cart` / `kafka`**.
2. **Data parity:** row count + checksum trước/sau cho 5 bảng (`order`, `orderitem`, `shipping`,
   `productreviews`, `products`); Kafka: tổng offset topic `orders` + consumer lag = 0.
3. **SLO giữ:** checkout ≥99% suốt cửa sổ cutover (Grafana SLO dashboard, đo bằng
   `CheckoutService/PlaceOrder` span error rate).
4. **Bảo mật:** endpoint private — chứng minh bằng **không kết nối được từ ngoài VPC** +
   `PubliclyAccessible=false` (KHÔNG dùng `nslookup` làm bằng chứng: DNS của RDS/ElastiCache **vẫn
   resolve** ra IP private từ ngoài, chỉ là không route tới được); **TLS on** (`sslmode=require` /
   `ssl=true` / `SASL_SSL`); **auth on** cả 3 store (§3); `values.yaml` **không còn** `otelu/otelp` plaintext.
5. **Rollback plan** (dưới) + ADR này ký tên.

## Rollback

Mỗi store rollback **độc lập**, không cần rebuild image (nhờ TLS gated bằng env):

| Store | Rollback | Thời gian | Mất mát |
|---|---|---|---|
| Valkey | trả `VALKEY_ADDR` + tắt `VALKEY_TLS` → pod valkey cũ (**giữ chạy tới khi nghiệm thu**) | ~1 phút (ArgoCD sync) | **không mất gì** — dual-write vẫn bật tới khi nghiệm thu nên valkey cũ luôn đầy đủ |
| Postgres | trả `DB_CONNECTION_STRING` → postgres cũ. Nếu `accounting` đã ghi vào RDS: **reset offset consumer group `accounting` về mốc trước cutover** → replay lại vào postgres cũ (Kafka còn giữ message) | ~2 phút | **không mất gì** (nhờ replay từ Kafka) |
| Kafka | trả `KAFKA_ADDR` → kafka cũ + `KAFKA_SECURITY_PROTOCOL=PLAINTEXT` | ~1 phút | message trong MSK chưa consume → phải replay tay |

**Nguyên tắc chốt:** **KHÔNG xoá pod/PVC store cũ** cho tới khi mentor nghiệm thu xong cả 3. Store cũ
là đường lui duy nhất. Chỉ gỡ ở bước cuối (yêu cầu #1: "không còn pod data tự host").

**Điểm không quay lui được (point of no return):** sau khi gỡ pod store cũ. Trước đó mọi bước đều lùi
được bằng 1 thay đổi values.

## Trạng thái thực thi

- [x] Cost (chốt 22/07 bằng Pricing API + Cost Explorer) — **≈$635/mo ≈ $146/tuần**; MSK dùng `m7g.large` vì **KRaft mode** loại t3.small (đã kiểm chứng, không phải do số version); $558/mo là giá sàn tuyệt đối
- [ ] Dựng AWS Budgets **theo tuần** + Cost Anomaly Detection — budget hiện có tên `Phase2-Cost-300` chu kỳ **MONTHLY**, sai chu kỳ so với trần $300/**tuần** nên không bao giờ cảnh báo đúng
- [ ] Re-audit "`accounting` là writer Postgres duy nhất" ngay trước khi cutover (điều kiện của chứng minh §5)
- [ ] Terraform: RDS (Multi-AZ, PG 17.6) + ElastiCache (Valkey 9.0, 1 replica, **auth-token**) + MSK (3 broker, 3.9.x KRaft, **SASL/SCRAM**) — private subnet, SG chỉ từ node group, encryption at rest + in-transit
- [ ] Terraform: **KMS customer-managed key** + 3 secret (postgres / elasticache-auth / `AmazonMSK_`-prefixed scram) + `batch-associate-scram-secret` gắn secret vào MSK
- [ ] Secrets Manager + External Secrets → 3 format conn string Postgres + auth token + SCRAM user/pass; gỡ plaintext khỏi `values.yaml`
- [ ] Code: TLS **+ auth** gated bằng env cho `cart` / `checkout` / `accounting` / `fraud-detection` + build image
      (gồm **SCRAM client tự viết cho sarama** ở `checkout` — xem §2)
- [ ] Code: **dual-write tạm trong `cart`** (`VALKEY_DUAL_WRITE_ADDR`) — điều kiện của chứng minh §5
- [ ] Cutover Valkey: bật dual-write → **chờ đủ 60 phút** → lật đọc → verify → **giữ pod cũ**
- [ ] Cutover Postgres (đóng băng `accounting` → dump/restore → đổi conn string → resume) → verify parity → **giữ pod cũ**
- [ ] Cutover Kafka (producer → drain → consumer) → verify lag=0 → **giữ pod cũ**
- [ ] Mentor nghiệm thu cả 3 + bằng chứng parity + SLO
- [ ] Gỡ pod `postgresql` / `valkey-cart` / `kafka` + PVC (**điểm không quay lui**)

---
*Ký: CDO02 (Reliability + Cost Optimization). Phối hợp: CDO01 (Security — SG/TLS/secret review),
AIO02 (detector cần theo dõi store mới). Thay thế kết luận "hoãn MSK" của [ADR 0002](0002-managed-services-evaluation.md);
đường HA gốc cho `checkout`-blocking-on-Kafka (outbox pattern) là nợ kỹ thuật ngoài phạm vi #8.*

# Mandate #8 — Tài liệu tổng quan: migrate 3 datastore lên managed service

**Người lập & chịu trách nhiệm thực thi:** Huu Tai Ngo (CDO02 — Reliability + Cost Optimization)
**Ngày:** 16/07/2026 · **Hạn mandate:** hết ngày 20/07/2026
**Vai trò tài liệu này:** bức tranh đầy đủ — nguyên nhân, mục tiêu, giải pháp từng store, trade-off,
thứ tự ưu tiên, rủi ro. Đọc file này trước; chi tiết kỹ thuật đi sâu ở:
[ADR 0009](adr/0009-mandate-08-managed-migration-cdo02.md) (quyết định + chứng minh) ·
[Execution plan](../../mandates/mandate-08/mandate-08-execution-plan.md) (lịch 4 ngày + kết quả re-verify hệ thống) ·
[Runbook cutover](runbooks/mandate-08-managed-cutover.md) (lệnh từng bước).

---

## 1. Vì sao phải làm — nguyên nhân gốc, không phải vì directive bắt

Directive #8 yêu cầu đưa PostgreSQL / Valkey / Kafka lên RDS / ElastiCache / MSK. Nhưng kể cả không
có directive, hiện trạng tự nó đã là vấn đề:

**1.1. Cả 3 store là SPOF thật trên luồng ra tiền.** Mỗi store chạy đúng 1 pod, cả 3 dồn trên đúng
1 node stateful (`stateful_1a`, AZ 1a). Node đó chết — vì hardware, vì AZ outage, vì một lỗi vận
hành — thì đồng thời: mất khả năng nhận đơn (checkout chặn đồng bộ trên Kafka), mất giỏ hàng
(cart/Valkey), mất đọc catalog + reviews (Postgres). Đây không phải rủi ro lý thuyết: backlog REL-08
đã ghi nhận từ tuần 1, tạm quản bằng planned-failover (PR #117) — nghĩa là *chấp nhận có downtime
khi có sự cố node*, chỉ là downtime có kịch bản. ADR 0005 đã ký chấp nhận rủi ro này **có thời hạn**;
mandate #8 là lúc trả nợ.

**1.2. Không có backup tự động.** PVC (REL-10) chỉ chống pod restart, không chống mất EBS volume /
xoá nhầm / hỏng dữ liệu. Dữ liệu kế toán (`accounting.order` ~41k dòng và đang tăng) hiện không có
bất kỳ bản sao nào ngoài chính volume đang chạy. RDS cho point-in-time recovery + snapshot tự động —
thứ tự dựng lấy trong cluster tốn công gấp nhiều lần.

**1.3. Bảo mật dưới chuẩn.** Kết nối nội bộ **plaintext** (không TLS), Kafka/Valkey **không có
authentication** — bất kỳ pod nào trong VPC cũng đọc/ghi được topic `orders` và toàn bộ giỏ hàng.
Credential Postgres (`otelu/otelp`) nằm **plaintext trong `values.yaml`** (đã ghi nhận từ ADR 0002).
Với dữ liệu đơn hàng, đây là lỗ hổng thật, không phải hình thức.

**1.4. Chi phí vận hành con người.** Tự host = tự lo patch version, tự lo failover, tự viết runbook
cho từng kịch bản hỏng. Đội 3 người không có băng thông đó dài hạn — bằng chứng là REL-13/REL-16
(Grafana/Kafka OOM) đều là sự cố "tự vận hành thiếu tay".

**Tóm lại:** mandate #8 không phải "chuyển nhà cho đẹp" — nó đóng cùng lúc 4 lỗ: SPOF, backup,
bảo mật, và công vận hành.

## 2. Mục tiêu — 5 yêu cầu của directive, diễn giải thành tiêu chí đo được

| # | Directive nói | Tiêu chí nghiệm thu đo được |
|---|---|---|
| 1 | Cả 3 store lên managed, không còn pod data tự host | `kubectl get pods` không còn `postgresql`/`valkey-cart`/`kafka`; app trỏ RDS/ElastiCache/MSK |
| 2 | Không mất data, không downtime, checkout ≥99% suốt cutover | Parity: row count + checksum khớp tuyệt đối; Kafka lag=0; Grafana SLO checkout ≥99% trong mọi cửa sổ cutover |
| 3 | TLS in-transit, encryption at rest, secret trong Secrets Manager, endpoint private | `sslmode=require`/`ssl=true`/`SASL_SSL`; KMS at-rest cả 3; 3 secret + không còn plaintext trong values.yaml; `PubliclyAccessible=false` + không nối được từ ngoài VPC |
| 4 | Schema + data seed nạp đủ, app đọc/ghi như trước | e2e storefront: browse/cart/checkout hoạt động y nguyên |
| 5 | Cost-aware, giải thích Multi-AZ vs single, trong ngân sách | +$202/mo (≈$46.7/tuần), tổng ≈$147/tuần < trần $300/tuần; lý do Multi-AZ từng store ở §4 |

## 3. Giải pháp tổng thể — 3 nguyên tắc xuyên suốt

**Nguyên tắc 1 — Tách "deploy code" khỏi "cutover".** Mọi thay đổi code (TLS, auth, dual-write)
đều gated bằng env, mặc định **tắt** (= hành vi hiện tại). Deploy sớm, verify hành vi y nguyên,
rồi cutover chỉ còn là "bật cờ + đổi endpoint" — một thay đổi values, ArgoCD sync ~1 phút.
*Vì sao:* mỗi bước chỉ đổi **một biến**; có lỗi biết ngay tại đâu; rollback không cần rebuild image.

**Nguyên tắc 2 — Zero-loss phải chứng minh được, không phải "cố gắng hạn chế".** Mỗi store có một
lời giải dựa trên **đặc tính đã audit** của chính hệ thống (chi tiết §4). Không dựa vào may mắn,
không dựa vào "làm nhanh thì chắc không sao".

**Nguyên tắc 3 — Store cũ là đường lui duy nhất.** Không xoá pod/PVC cũ cho tới khi mentor nghiệm
thu cả 3. Điểm không quay lui (point of no return) là bước **cuối cùng**, không phải bước giữa.

## 4. Từng store: hiện trạng → giải pháp → vì sao → trade-off

### 4.1 Valkey (cart) → ElastiCache Valkey 9.0

**Hiện trạng (đo 16/07):** Valkey 9.0.1, 1 pod, AOF on, ~4.100 key, chỉ `cart` dùng.
**Đích:** ElastiCache Valkey 9.0, `cache.t4g.micro` ×2 (1 primary + 1 replica), TLS + AUTH token — $28/mo.

**Cách cutover — "cửa sổ hội tụ TTL 60 phút":** phát hiện quyết định là app **tự đặt TTL 60 phút
mọi lần ghi** (`ValkeyCartStore.cs:174,199`) và đọc không gia hạn. Suy ra: giỏ nào còn sống thì
chắc chắn được ghi trong 60 phút gần nhất. Vậy: bật **dual-write** (ghi cả cũ lẫn mới, đọc từ cũ)
→ chờ đủ 60 phút → mọi giỏ còn sống đã có mặt ở ElastiCache → lật đọc sang. Giỏ nào không được
ghi trong cửa sổ = đã bị chính app xoá bằng TTL — không phải mất mát do migration.

**Vì sao không bulk-copy (`DUMP`/`MIGRATE`/snapshot)?** Copy xong dữ liệu vẫn tiếp tục đổi → luôn
có khe hở giữa "chụp" và "lật". Dual-write + TTL đóng khe hở đó bằng logic, không cần tính năng AWS nào.

**Trade-off đã cân:**
- *Replica ($28) vs single ($14):* cart nằm **trên luồng đồng bộ** browse→cart→checkout — mất cache
  là vỡ SLO ngay, không chỉ mất dữ liệu mềm. +$14/mo cho auto-failover là rẻ.
- *Thêm nhánh dual-write tạm trong code:* tốn một PR + phải gỡ sau nghiệm thu, đổi lấy chứng minh
  zero-loss tuyệt đối. Bản nháp trước định chấp nhận "mất giỏ đang mở, xin mentor thông cảm" — đã bỏ.
- *Cửa sổ 60 phút là BẮT BUỘC:* rút ngắn = phá chứng minh = mất giỏ thật. Chờ 65–70 phút cho biên.

### 4.2 PostgreSQL → RDS PostgreSQL 17.6

**Hiện trạng (đo 16/07):** PG 17.6, 38 MB, 3 schema (`accounting` 3 bảng ~157k dòng tổng,
`catalog` 10 dòng seed, `reviews` 50 dòng seed), extension chỉ `plpgsql`, `wal_level=replica`.
**Đích:** RDS `db.t4g.micro` **Multi-AZ**, gp3 20GB, TLS — $43/mo cả storage.

**Cách cutover — "đóng băng người ghi duy nhất":** audit source + `pg_stat_activity` live xác nhận
**chỉ `accounting` ghi** vào Postgres (product-catalog/product-reviews thuần đọc — đã kiểm từng câu
query). Mà `accounting` là consumer Kafka **async, back-office** — dừng nó vài phút khách không hề
biết. Vậy: scale `accounting`→0 (DB thành read-only, đơn mới dồn an toàn ở Kafka vì REL-09 offset
manual-commit) → `pg_dump`/restore (38 MB, vài giây) → parity check **trên nguồn đứng yên** (chính
xác tuyệt đối, không có race "số đổi trong lúc đếm") → đổi conn string 3 service (rolling
`maxUnavailable:0`) → scale `accounting`→1 trỏ RDS → replay từ offset chưa commit.

**Vì sao không dùng logical replication (cách "chuẩn sách vở")?** Nó đòi `wal_level=logical` — đổi
tham số này phải **restart Postgres** = read-outage cho catalog/reviews = vỡ SLO browse **trước khi
migration bắt đầu**. Nghịch lý: muốn zero-downtime bằng logical replication thì phải trả một cục
downtime trước. Cách đóng băng né hoàn toàn, ít bộ phận chuyển động hơn, parity mạnh hơn.

**Trade-off đã cân:**
- *Multi-AZ ($37) vs single ($18):* đây là **dữ liệu tài chính** — durability đáng giá nhất hệ thống.
  +$19/mo là khoản rẻ nhất toàn mandate để đổi lấy auto-failover.
- *Giá phải trả của "đóng băng":* số liệu kế toán trễ vài phút trong cửa sổ. Không ai nhìn thấy —
  không phải SLI nào của khách.
- *Điều kiện sống còn:* chứng minh sụp nếu xuất hiện writer thứ hai. Bắt buộc **re-audit ngay trước
  cutover** (đã ghi vào execution plan bước 3.1).

### 4.3 Kafka → Amazon MSK 3.9 KRaft

**Hiện trạng (đo 16/07):** Kafka 3.9.1 KRaft, 1 broker, topic `orders` **1 partition** (~35.7k
offset), producer=`checkout` (đồng bộ, `acks=all` — REL-09), consumer=`accounting`+`fraud-detection`
(async, offset commit, lag≈0), retention 168h.
**Đích:** MSK provisioned `kafka.t3.small` ×3 broker / 3 AZ, RF=3, `min.insync.replicas=2`,
SASL/SCRAM — $130/mo cả storage.

**Cách cutover — producer-first, không dual-consume:** chuyển `checkout` sang MSK trước (trong lúc
rolling, pod cũ ghi Kafka cũ, pod mới ghi MSK — cả hai đều sống, không đơn nào fail) → **chờ mọi pod
checkout lên revision mới** → chờ consumer hút cạn Kafka cũ (lag=0) → chuyển 2 consumer sang MSK,
group mới + `AutoOffsetReset=Earliest` → ăn trọn backlog từ đầu topic MSK. Kafka cũ lúc đó đã đóng
băng và cạn — không message nào bị bỏ lại.

**Điểm chết người phải tôn trọng:** đo lag Kafka cũ **khi vẫn còn pod checkout revision cũ** đang
produce → một message có thể rơi vào Kafka cũ *sau* lúc đo → mồ côi vĩnh viễn. Thứ tự
"rollout xong hết → lag=0 → mới chuyển consumer" là bắt buộc, không hoán đổi được.

**Trade-off đã cân — đây là quyết định tiền lớn nhất:**
- *3 broker ($127) vs 2 broker ($85):* vì `checkout` **chặn đồng bộ** với `acks=all`, với 2 broker
  phải chọn một trong hai cái tệ: `min.insync=2` → mất 1 broker là **checkout fail ngay** (vỡ SLO);
  `min.insync=1` → ack chỉ 1 bản sao → broker đó chết là **mất đơn thật**. 3 broker / RF=3 /
  min.insync=2 chịu được mất 1 broker mà vẫn nhận đơn, mỗi ack ≥2 bản sao. +$42/mo mua đúng thứ
  mandate đòi: không mất đơn.
- *SCRAM vs IAM auth:* IAM sạch hơn về nguyên tắc (không có credential để lộ), nhưng sarama (Go)
  phải tự viết `AccessTokenProvider`, confluent-dotnet hỗ trợ yếu — 3 ngôn ngữ × 4 ngày là không
  khả thi. SCRAM có đường đi rõ cho cả 3 client, và đúng nghĩa đen "credential trong Secrets
  Manager" (MSK đọc secret native). IAM ghi nhận là nâng cấp sau.
- *Chi phí ẩn của SCRAM:* secret phải prefix `AmazonMSK_` + mã hoá bằng **customer-managed KMS key**
  (MSK từ chối key mặc định) → +1 CMK ~$1/mo. Đã verify ràng buộc này qua CLI trước, không để
  đến lúc cutover mới phát hiện.
- *Sunk cost:* toàn bộ công PVC Kafka in-cluster (REL-10, REL-16) bị thay thế. Không tiếc — directive
  bắt buộc, và số tiền đó đã mua được 3 ngày vận hành an toàn tới giờ.

## 5. Thứ tự ưu tiên và vì sao

**Thứ tự cutover: Valkey → Postgres → Kafka.** Không phải ngẫu nhiên:

1. **Valkey trước** — dữ liệu "mềm" nhất (giỏ hàng, khách thêm lại được nếu thảm hoạ), lời giải
   độc lập nhất. Chạy đầu tiên để **kiểm chứng toàn bộ đường ống** (terraform → secret → TLS flag →
   cutover → verify → rollback) trên store ít nguy hiểm nhất. Lỗi quy trình nào cũng lộ ra ở đây
   với giá rẻ.
2. **Postgres giữa** — dữ liệu giá trị nhất nhưng lời giải **chắc chắn nhất** (nguồn đóng băng,
   parity tuyệt đối). Làm khi đường ống đã được Valkey kiểm chứng.
3. **Kafka cuối** — rủi ro cao nhất (nằm trên luồng đồng bộ của checkout, thứ tự thao tác ngặt
   nghèo nhất). Làm cuối khi kinh nghiệm 2 lần cutover trước đã nóng máy, và nếu trượt deadline
   thì 2 store giá trị nhất đã xong.

**Nếu buộc phải cắt phạm vi (trượt tiến độ):** giữ Postgres > Valkey > Kafka — xếp theo giá trị
durability của dữ liệu, đúng kết luận ADR.

**Thứ tự chuẩn bị: Terraform trước tất cả** — MSK provision 30–60+ phút là đường găng dài nhất;
hạ tầng đứng chờ được, code thì cần review. Build image sớm vì pipeline CI vừa đại tu (PR #153/158/159)
— lần build đầu qua pipeline mới cần buffer sửa lỗi.

## 6. Danh sách việc đầy đủ (workstream)

**WS1 — Hạ tầng (Terraform, module `datastores`):**
RDS + ElastiCache + MSK (thông số §4) · KMS CMK · 3 secret (`techx-tf3/postgres`,
`techx-tf3/elasticache-auth`, `AmazonMSK_techx-tf3/kafka-scram`) · SG: inbound chỉ từ SG node group
(`sg-07041162a3127bae5` + cluster SG), RDS/ElastiCache thêm SG bastion (`sg-05b1a13ae5f49ebbd`) cho
đường vận hành · `PubliclyAccessible=false`, private subnet 3 AZ · encryption at rest cả 3 ·
`batch-associate-scram-secret` gắn secret vào MSK. Luôn `plan -out=tfplan` → review → `apply tfplan`.

**WS2 — Code (4 service, tất cả gated bằng env, default tắt):**
- `checkout` (Go/sarama): SCRAM-SHA-512 client (`xdg-go/scram` — sarama không có sẵn, phải tự
  implement `sarama.SCRAMClient`) + `KAFKA_SECURITY_PROTOCOL`/`KAFKA_SASL_*`. **Nặng nhất, làm đầu tiên.**
- `cart` (C#): `VALKEY_TLS` + `VALKEY_AUTH_TOKEN` + nhánh **dual-write** `VALKEY_DUAL_WRITE_ADDR`.
- `accounting` (C#): `SecurityProtocol=SaslSsl, SaslMechanism=ScramSha512` qua env.
- `fraud-detection` (Kotlin): `security.protocol`/`sasl.mechanism` qua env.

**WS3 — Secret vào cluster (External Secrets Operator — đã Running):**
3 ExternalSecret; riêng Postgres render **3 format** conn string (.NET `Host=...;` / Go-URL
`postgres://...` / libpq `host=...`) vì 3 client parse khác nhau · gỡ sạch `otelu/otelp` plaintext
khỏi `values.yaml` · ⚠️ update `values.schema.json` cùng lúc (schema `additionalProperties:false` —
quên là ArgoCD ComparisonError chết pipeline, đã xảy ra một lần).

**WS4 — Cutover** (3 phiên, theo runbook, load-gen nền + Grafana SLO mở suốt): trình tự và verify
từng bước xem [execution plan §2](../../mandates/mandate-08/mandate-08-execution-plan.md).

**WS5 — Bằng chứng + nghiệm thu + dọn dẹp:** gói evidence (§2 bảng tiêu chí) → mentor xác nhận →
**chỉ sau đó** gỡ pod/PVC cũ → cập nhật CLAUDE.md, backlog (đóng REL-08), báo cáo mandate.

## 7. Rủi ro chính và cách khống chế

| Rủi ro | Xác suất/Va đập | Khống chế |
|---|---|---|
| Pod checkout mới không nói chuyện được với MSK (credential/SG/endpoint sai) → PlaceOrder fail = đánh thẳng SLO | Trung bình / **Cao nhất mandate** | Smoke test produce/consume từ pod CLI với đúng secret **trước** rollout; checkout đi qua **Argo Rollouts canary** (pod hỏng chỉ dính % nhỏ traffic); rollback env ~1 phút |
| Đo lag Kafka cũ khi còn pod checkout cũ → message mồ côi | Thấp nếu theo runbook / Mất đơn thật | Gate cứng trong runbook: `rollout status` xong + đếm pod revision cũ = 0 rồi mới đo lag |
| Writer thứ hai vào Postgres xuất hiện sau ngày audit | Thấp / Phá chứng minh parity | Re-audit bắt buộc ngay trước freeze (plan bước 3.1) |
| Rút ngắn cửa sổ dual-write 60' vì sốt ruột | Con người / Mất giỏ thật | Ghi rõ BẮT BUỘC ở mọi tài liệu; hẹn giờ 70 phút |
| CI pipeline mới trục trặc khi build 4 image | Trung bình / Trễ lịch | Build sớm ngày 1; đã có 1 run thật thành công (16/07) làm bằng chứng pipeline sống |
| Mandate #5 (PR #145) **đã merge + Kyverno 4 policy ĐÃ Enforce** (18/07) → pod helper runbook bị admission từ chối; image rebuild phải digest-pin; cart giờ `readOnlyRootFilesystem` | Đã xảy ra / Kẹt cutover nếu không thích ứng | **Vận hành dưới enforce ngay từ đầu** — pod helper dùng template compliant (đã test PASS), rebuild qua CI digest-pin, verify cart start clean; chi tiết + đối sách ở [execution plan §3bis](../../mandates/mandate-08/mandate-08-execution-plan.md). Không xin tắt policy. Còn cần: CDO01 xác nhận không rollout đụng 3 pod datastore trong tuần cutover |
| BTC bơm sự cố flagd giữa cutover | Bất kỳ lúc nào / Nhiễu chẩn đoán | Dừng cutover, xử sự cố trước (fallback/containment), tuyệt đối không đụng flagd; cutover dời — deadline còn buffer |
| Sự cố AWS (như CloudFront 16/07) | Thấp / Mất thời gian | Không nằm trong kiểm soát; buffer tối 19/07 |

**Stop conditions (dừng ngay, không thương lượng):** parity lệch dù 1 dòng → dừng + resume về store
cũ; SLO checkout chạm 99% trong bất kỳ cửa sổ nào → rollback store đang cutover; bất kỳ bước nào
lệch runbook → dừng lại hỏi, không improvise trên luồng ra tiền.

## 8. Rollback — mỗi store lùi độc lập, không rebuild image

| Store | Thao tác | Thời gian | Mất mát |
|---|---|---|---|
| Valkey | trả `VALKEY_ADDR` + tắt TLS (pod cũ vẫn được dual-write ghi đầy đủ tới khi nghiệm thu) | ~1 phút | 0 |
| Postgres | trả `DB_CONNECTION_STRING`; nếu accounting đã ghi RDS → reset offset group về mốc trước cutover, replay vào PG cũ | ~2 phút | 0 (nhờ replay Kafka) |
| Kafka | trả `KAFKA_ADDR` + `PLAINTEXT` | ~1 phút | message trong MSK chưa consume phải replay tay |

Điểm không quay lui duy nhất: **gỡ pod/PVC store cũ** — chỉ làm sau khi mentor nghiệm thu cả 3.

## 9. Chi phí — tổng hợp (đơn giá verify qua AWS Pricing API 16/07, ap-southeast-1)

| Khoản | $/tháng | Ghi chú |
|---|---|---|
| RDS `db.t4g.micro` Multi-AZ + gp3 20GB | 42.75 | dữ liệu tài chính — durability đáng nhất |
| ElastiCache Valkey `cache.t4g.micro` ×2 | 28.04 | engine Valkey rẻ hơn Redis 20% |
| MSK `kafka.t3.small` ×3 + GP2 10GB×3 | 130.17 | khoản lớn nhất — mua "không mất đơn" (§4.3) |
| Secrets Manager ×3 + KMS CMK | 2.20 | ràng buộc MSK/SCRAM |
| **Tổng** | **≈ 202** | ≈ $46.7/tuần; tổng hệ thống ≈ $147/tuần < trần $300/tuần |

Baseline chi hiện tại (~$100/tuần) vẫn là ước lượng — Cost Explorer account mới chưa đủ dữ liệu;
việc dựng AWS Budgets + Cost Anomaly Detection nằm trong checklist ADR.

## 10. Sau mandate — nợ kỹ thuật ghi nhận, không giả vờ đã xong

- **`checkout` vẫn chặn đồng bộ trên Kafka**: MSK gặp sự cố thì PlaceOrder vẫn fail. Fix gốc =
  publish async + outbox pattern — ngoài phạm vi #8, là backlog item kế tiếp của CDO02.
- **SASL/IAM cho MSK** (thay SCRAM) — bỏ hẳn credential khỏi vòng đời secret.
- **Xoay toàn bộ secret** đã đi qua tay người vận hành trong cutover (nguyên tắc break-glass ở ADR §3).
- Gỡ nhánh dual-write tạm trong `cart` sau nghiệm thu (code chết phải chết hẳn).

---
*Người lập & thực thi: **Huu Tai Ngo** — CDO02. Số liệu hiện trạng đo trực tiếp trên cluster/AWS
16/07/2026 (chi tiết phép đo: [execution plan §1](../../mandates/mandate-08/mandate-08-execution-plan.md)). Phối hợp: CDO01
(SG/TLS/secret review + trình tự merge Mandate #5), AIO02 (detector trỏ endpoint mới).*

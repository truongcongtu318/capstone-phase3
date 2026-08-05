# Cost breakdown — account 197826770971 (quét 22/07/2026)

**Người quét:** CDO02 (Reliability + Cost Optimization)
**Nguồn số liệu:** AWS Cost Explorer, `RECORD_TYPE = Usage` (bỏ Credit — account đang được credit phủ
100%, nhìn hoá đơn ròng sẽ thấy $0 và **không phản ánh mức tiêu thật**)
**Ngày lấy làm run-rate:** **21/07/2026** — ngày đủ 24h gần nhất có dữ liệu hoàn chỉnh (22/07 còn đang
chạy, CE trễ ~8–12h; 19–20/07 có 2 sự cố nên nhiễu)
**Trần ngân sách:** **$300/tuần/TF** ([BUDGET.md](../phase3%20-%20information/onboarding/BUDGET.md))

---

## 0. Kết luận trong 30 giây

| | $/ngày | **$/tuần** | $/tháng (30,4d) | Tỷ trọng |
|---|---:|---:|---:|---:|
| **A. CDO** (nền tảng + storefront, `ap-southeast-1` + global) | 43,79 | **306,5** | 1.331 | 71,9% |
| **B. AI** (AIO02: Bedrock + vector store, `us-east-1`/`us-west-2`) | 13,81 | **96,7** | 420 | 22,7% |
| **C. Ngoài phạm vi Phase 3** (`ap-northeast-1`) | 3,31 | **23,2** | 101 | 5,4% |
| **TỔNG** | **60,92** | **426,4** | **1.852** | 100% |

> ### 🔴 ĐANG VƯỢT TRẦN
> **$426,4/tuần so với trần $300/tuần → 142%.**
> Riêng phần CDO ($306,5) đã vượt trần một mình, chưa tính AI.
> Tuần thực tế gần nhất (15–21/07) tiêu **$346,68** — và tuần đó MSK mới chạy 3,5/7 ngày.
> Với MSK chạy đủ tuần, con số đúng là $426.

**5 việc dưới đây kéo về $269,7/tuần (90% trần) mà không giảm một chút reliability nào** — xem §4.

---

## 1. Phần A — CDO ($306,5/tuần)

| Hạng mục | Tài nguyên thật | $/ngày | $/tuần | $/tháng |
|---|---|---:|---:|---:|
| **MSK** | `techx-tf3-kafka` — **3 × kafka.m7g.large** + 30GB gp2 | **18,48** | **129,4** | **562** |
| EC2 node | 4×t3.large (nodegroup `default`, min=4) + 1×t3.medium (`db-1a`) + 1×t3.micro (bastion) + 2 spot | 9,52 | 66,7 | 289 |
| VPC | **5 interface endpoint × 3 AZ = 15 ENI** ($32,8/tuần) + public IPv4 | 4,81 | 33,7 | 146 |
| CloudWatch | `/aws/eks/techx-corp-tf3/cluster` — ingestion ~3,9 GB/ngày, **99,8% là `audit`** (xem §4.0) | 2,82 | 19,8 | 86 |
| EKS | control plane `techx-corp-tf3` | 2,40 | 16,8 | 73 |
| EC2-Other | NAT gateway ($0,62/ngày) + EBS gp3 + data transfer nội vùng | 2,40 | 16,8 | 73 |
| **RDS** | `techx-tf3-postgres` — db.t4g.micro **Multi-AZ**, gp3 20GB | 1,40 | 9,8 | 43 |
| **ElastiCache** | `techx-tf3-valkey` — 2 × cache.t4g.micro, Multi-AZ | 0,92 | 6,5 | 28 |
| ELB | `techx-tf3-frontend-internal` (ALB internal) | 0,60 | 4,2 | 18 |
| WAF | WebACL global (CloudFront) | 0,19 | 1,4 | 6 |
| Lặt vặt | Secrets Manager, KMS CMK, ECR, S3, Budgets, Cost Explorer | 0,23 | 1,6 | 7 |
| **Tổng A** | | **43,79** | **306,5** | **1.331** |

### 1.1 Ba dòng đắt nhất chiếm 75% chi phí CDO

**① MSK = $562/tháng — chiếm 42% ngân sách CDO, 30% toàn account.**
`kafka.m7g.large` là instance **nhỏ nhất mà MSK 3.9.x chấp nhận** — `kafka.t3.small` bị `CreateCluster`
trả `BadRequest` (đã ghi trong [`variables.tf:118`](../infra/modules/datastores/variables.tf#L118)).
Không phải chọn sai lúc apply, mà là **ràng buộc của engine version**.

**② EC2 node = $289/tháng.** Cụm hiện có 7 node ≈ 14 vCPU, trong khi tổng CPU **request** của
namespace `techx-tf3` chỉ **3,125 vCPU** (26 workload, xem §1.2). Dư địa right-size rất lớn.

**③ VPC endpoint = $146/tháng.** 5 interface endpoint (`ecr.dkr`, `ecr.api`, `ssm`, `ec2messages`,
`ssmmessages`) × 3 AZ = 15 ENI × $0,013/h. Endpoint được thêm để **né phí NAT** — nhưng NAT data
processing thực tế chỉ **$0,09/ngày**. Đang trả $4,7/ngày để tiết kiệm $0,09/ngày.

### 1.2 CPU/RAM request theo workload (đo trên cluster, 38 pod)

| Workload | Pod | mCPU | MiB | | Workload | Pod | mCPU | MiB |
|---|--:|--:|--:|---|---|--:|--:|--:|
| opensearch | 1 | 250 | 750 | | product-catalog | 2 | 100 | 64 |
| aiops-engine 🤖 | 1 | 200 | 256 | | recommendation | 1 | 100 | 64 |
| cart | 2 | 200 | 128 | | accounting | 1 | 50 | 150 |
| checkout-rollout | 2 | 200 | 64 | | fraud-detection | 1 | 50 | 256 |
| frontend | 2 | 200 | 200 | | quote | 2 | 50 | 64 |
| load-generator | 1 | 200 | 1024 | | shipping | 2 | 50 | 16 |
| otel-gateway | 2 | 200 | 512 | | email | 1 | 25 | 64 |
| product-reviews 🤖 | 2 | 200 | 160 | | image-provider | 1 | 25 | 16 |
| prometheus | 1 | 150 | 450 | | llm (mock) 🤖 | 1 | 25 | 96 |
| flagd | 1 | 125 | 282 | | ad | 1 | 100 | 256 |
| grafana | 1 | 125 | 800 | | cloudflared | 2 | 100 | 64 |
| currency | 2 | 100 | 24 | | frontend-proxy | 2 | 100 | 128 |
| payment | 2 | 100 | 200 | | jaeger | 1 | 100 | 750 |
| | | | | | **TỔNG** | **38** | **3.125** | **6.838** |

🤖 = pod thuộc AIO02 (425 mCPU / 512 MiB ≈ **13,6% CPU request** của namespace).

---

## 2. Phần B — AI / AIO02 ($96,7/tuần)

| Hạng mục | Tài nguyên | $/ngày | $/tuần | $/tháng |
|---|---|---:|---:|---:|
| **OpenSearch Serverless** | **2 OCU** (1 Indexing + 1 Search) `us-east-1` | **11,52** | **80,6** | **350** |
| OpenSearch managed | domain `techx-products-search` t3.small.search (KB `techx-products-kb-v2`) | 0,86 | 6,1 | 26 |
| Bedrock `us-east-1` | Nova Lite/Micro/Pro, Titan Embedding, **Guardrail** | 0,71 | 5,0 | 22 |
| Bedrock `ap-southeast-1` | Nova Lite/Micro/Pro | 0,36 | 2,5 | 11 |
| Bedrock `us-west-2` | Llama 3.1 70B | 0,32 | 2,2 | 10 |
| OpenSearch storage/transfer + ECR | | 0,04 | 0,3 | 1 |
| **Tổng B** | | **13,81** | **96,7** | **420** |

### 2.1 🔴 83% chi phí AI là 2 OCU không gắn với collection nào nhìn thấy được

`aws opensearchserverless list-collections` (us-east-1 **và** ap-southeast-1) trả về **rỗng**, và
`batch-get-collection` cho cả 2 collection ARN cũng **không trả gì** — nhưng OCU **vẫn tính tiền
đều $11,52/ngày**, bao gồm cả ngày 22/07.

Hai Knowledge Base trỏ tới AOSS:

| KB | Trạng thái | Vector store |
|---|---|---|
| `aiops-playbooks-kb-f6230446` | ACTIVE | AOSS `trr490g18kpnofbpupe3` |
| `shopping-products-kb` | 🔴 **DELETE_UNSUCCESSFUL** | AOSS `qs4tp08mw4mnymmaypzf` |
| `techx-products-kb-v2` | ACTIVE | ✅ OpenSearch **managed** t3.small ($26/tháng) |

**$350/tháng — khoản lãng phí đơn lẻ lớn nhất toàn account.** AOSS tính **sàn 2 OCU × $0,24/h**
bất kể có truy vấn hay không, nên một collection mồ côi tốn y hệt một collection đang phục vụ.

`techx-products-kb-v2` đã chuyển sang managed domain và chỉ tốn $26/tháng — **chứng minh đường đi
đúng đã có sẵn**: đưa nốt `aiops-playbooks-kb` sang cùng domain đó thì AOSS về $0.

### 2.2 Bedrock trải trên 3 region

Nova chạy ở cả `us-east-1` **và** `ap-southeast-1`; Llama 3.1 70B ở `us-west-2`. Guardrail
(`shopping-copilot-guardrail`) tốn **$4,20 MTD = 34% tổng chi Bedrock** — đắt hơn cả token của
Nova Micro. Đáng rà lại có cần bật guardrail trên mọi lời gọi không.

---

## 3. Phần C — Không thuộc Phase 3 nhưng vẫn tính vào ngân sách TF3 ($23,2/tuần)

Toàn bộ nằm ở **`ap-northeast-1` (Tokyo)**, tạo **01–02/07/2026** — trước khi TF3 vào account này.
Không liên quan TechX Corp, không CDO, không AI.

| Tài nguyên | $/ngày | $/tháng |
|---|---:|---:|
| ECS Fargate `thermal-power-plant-api-service` (1 task) | 0,74 | 23 |
| EC2 t2.small `thermal-power-plant-jenkins` | 0,73 | 22 |
| RDS MySQL db.t3.micro `thermal-power-plant-db` | 0,71 | 22 |
| ALB `thermal-power-plant-alb` (internet-facing) | 0,58 | 18 |
| Public IPv4 | 0,48 | 15 |
| EBS + ECR | 0,06 | 2 |
| **Tổng C** | **3,31** | **101** |

Rác khác (chi phí ~0 nhưng nên dọn): S3 `sosflow-alb-logs`/`sosflow-frontend`,
ECR `tf-2-ai-engine`, Lambda `tf2-finops-ai-test`, log group `/sosflow/*`.

---

## 4. Đường về dưới trần — 5 việc, không mất reliability

| # | Việc | Chủ | Tiết kiệm/tuần | Rủi ro |
|---|---|---|---:|---|
| 1 | Xoá KB `shopping-products-kb` (DELETE_UNSUCCESSFUL) + gộp `aiops-playbooks-kb` sang managed domain `techx-products-search` → AOSS về 0 OCU | **AIO02** | **−$80,6** | Không — KB đã hỏng; KB còn lại chuyển sang domain đã chạy sẵn |
| 2 | Xoá stack `thermal-power-plant-*` (Tokyo) | Chủ sở hữu | **−$23,2** | Không thuộc Phase 3 — **cần xác nhận chủ trước khi xoá** |
| 3 | **VPC endpoint 15 ENI → 3 ENI**: bỏ hẳn `ecr.dkr`/`ecr.api`; thu `ssm`/`ec2messages`/`ssmmessages` từ 3 AZ về 1 AZ (AZ của bastion, `1a`) | CDO01/02 | **−$26,2** | Pull image qua NAT (+~$0,3/tuần); mất SSM nếu AZ 1a chết — vẫn còn đường Cloudflare Zero Trust |
| 4 | Hạ nodegroup `default` min 4 → 3, để Karpenter spot hấp thụ phần thiếu (spot t3.large $0,0384/h vs on-demand $0,1056/h — rẻ hơn 64%) | **CDO02** | **−$17,8** | Thấp — cụm đang 45% CPU request nhưng chỉ **6,7% dùng thật** |
| 5 | Gỡ nodegroup `techx-corp-tf3-db-1a` (t3.medium) | **CDO02** | **−$8,9** | Không — xem §4.1 |
| | **Sau 5 việc** | | **$426,4 → $269,7** | ✅ **90% trần, dư $30/tuần** |

Chú ý: 5 việc này **không đụng tới MSK/RDS/ElastiCache** — tức là đưa được về trần mà không phải
đảo ngược bất kỳ quyết định reliability nào của Mandate #8.

Nếu cần thêm biên, đòn bẩy kế tiếp là chuyển 3 node `t3.large` on-demand còn lại sang spot
(−$33,6/tuần → **$236/tuần**). **Không khuyến nghị** — đội đang được chấm trụ Reliability, đặt toàn bộ
đáy cluster lên spot là rủi ro không cần thiết khi đã dư trần.

### 4.0 ⛔ Rút lại một khuyến nghị: hạ retention CloudWatch KHÔNG tiết kiệm gì

Bản đầu của tài liệu này đề xuất *"hạ retention `/aws/eks/.../cluster` 90 → 30 ngày, tiết kiệm ~$10/tuần"*.
**Sai** — đã đo lại bằng CloudWatch Logs Insights:

| Loại log | Dung lượng | Tỷ trọng |
|---|---:|---:|
| `kube-apiserver-audit` | **161,6 MB/giờ** (104.171 dòng/giờ) | **99,8%** |
| `kube-apiserver` | 0,3 MB/giờ | 0,2% |
| `authenticator` | 0,1 MB/giờ | 0,1% |

Chi phí nằm ở **ingestion** ($0,63/GB × ~3,9 GB/ngày ≈ $2,44/ngày), **không phải storage** — lưu trữ
3,9 GB chỉ tốn $0,12/tháng. Hạ retention tiết kiệm gần như **$0**. Đòn bẩy thật là **tắt log type**, mà
99,8% khối lượng là `audit`.

**Khuyến nghị: giữ `audit`.** $17/tuần chính là thứ đã truy ra được ai apply tay làm sập production
trong sự cố 0012. Đổi trụ Auditability lấy 4% ngân sách là lỗ.

### 4.1 Node `db-1a` giờ chạy không tải — hệ quả trực tiếp của §8

Node `ip-10-0-4-166` (t3.medium, taint `techx.io/workload=stateful`) tồn tại **chỉ để** chứa
postgresql + valkey-cart + kafka. Sau §8 (PR #324), pod trên node đó còn đúng 4 DaemonSet:

```
kube-system/aws-node-qk5lj
kube-system/ebs-csi-node-ptsvb
kube-system/kube-proxy-cpkjx
observability-system/otel-node-agent-5fgtp
```

**Zero workload pod.** Nodegroup min=max=desired=1 nên không tự co. Gỡ được ngay sau khi mentor
nghiệm thu và 3 PVC được xoá.

### 4.2 Việc nên làm dù không tiết kiệm tiền: sửa AWS Budget

Budget hiện có tên **`Phase2-Cost-300`, chu kỳ MONTHLY, hạn mức $300** — trong khi trần Phase 3 là
**$300/TUẦN**. Budget này sẽ báo động sai hoàn toàn (đã tiêu $487 trong tháng mà chưa hề cảnh báo
đúng ngữ cảnh tuần). Cần tạo budget mới theo tuần + gắn SNS.

---

## 5. ⚠️ Sai lệch cần sửa trong hồ sơ nghiệm thu Mandate #8

[`docs/mandates/mandate-08/mandate-08-nghiem-thu.md`](mandates/mandate-08/mandate-08-nghiem-thu.md) (dòng 24, 87, 93, 94, 335, 336) đang ghi:

> MSK 3.9 KRaft, **kafka.t3.small × 3 broker** — **~$130/tháng** · 3 broker ($127) vs 2 broker ($85)
> · Tổng **+$202/mo ≈ $46,7/tuần → tổng ≈ $147/tuần, dưới trần $300/tuần**

**Thực tế đang chạy:** `kafka.m7g.large × 3` = **$562/tháng**, tức **gấp 4,3 lần** con số trong báo cáo.

| | Báo cáo đang ghi | Thực đo (CE, 21/07) |
|---|---:|---:|
| MSK | ~$130/tháng | **$562/tháng** |
| RDS | ~$43/tháng | $43/tháng ✅ |
| ElastiCache | ~$28/tháng | $28/tháng ✅ |
| KMS + Secrets | ~$1/tháng | $4/tháng |
| **Tổng delta Mandate #8** | **+$202/mo = $46,7/tuần** | **+$637/mo = $147/tuần** |
| **Tổng chi TF3** | "≈$147/tuần, dưới trần ✅" | **$426/tuần, vượt trần 142% 🔴** |

**Vì sao lệch:** phần chi phí được viết từ **kế hoạch ban đầu** (t3.small), nhưng lúc apply thì MSK
từ chối t3.small và Terraform đã đổi sang `kafka.m7g.large`. ADR 0009 **đã đính chính từ 18/07**
(§Cost) — chỉ có file nghiệm thu là chưa được cập nhật theo.

> **✅ Đã sửa 22/07** — cả `mandates/mandate-08/mandate-08-nghiem-thu.md` (mục 0, §A.2, Tiêu chí 5, §G.3 mới) lẫn
> `docs/adr/0009-...md` (§Cost, đính chính lần 2) nay đều mang con số thật.

### 5.1 Đã kiểm chứng: $558/tháng là giá sàn tuyệt đối, không phải lựa chọn

Ngày 22/07 thử lại có hệ thống bằng `CreateCluster` (cụm nháp, đã xoá ngay, tổng chi phí **$0,066**):

| Phép thử | Kết quả |
|---|---|
| `t3.small` + `3.9.x.kraft` *(version đang chạy)* | ❌ `BadRequestException: Unsupported InstanceType` |
| `t3.small` + `3.8.x.kraft` | ❌ `BadRequestException` |
| `t3.small` + `3.8.x` (ZooKeeper) | ✅ tạo được |

⇒ **Rào cản là chế độ KRaft, không phải số version** — khác với những gì
[`variables.tf:118`](../infra/modules/datastores/variables.tf#L118) ghi.

Danh sách instance hợp lệ MSK trả về cho **mọi** version KRaft: `express.m7g.*`, `kafka.m5.*`,
`kafka.m7g.*`. Trong đó `kafka.m7g.large` ($0,2550/h) **rẻ hơn** `kafka.m5.large` ($0,2630/h) → lựa chọn
hiện tại đã ở đáy nhóm hợp lệ. Rà thêm: `update-broker-count` chỉ tăng không giảm · MSK **không có API
stop/start** · PublicAccess `DISABLED` · PrivateLink tắt · không provisioned throughput · không
replicator · không tiered storage · MSK không thuộc Savings Plans. **Không còn gì để cắt.**

### 5.2 Đối chiếu directive gốc — SNS/SQS bị loại, ZooKeeper thì không

Đã đọc nguyên văn `MANDATE-08-managed-migration.md`:

- **Yêu cầu 1** gọi đích danh: *"PostgreSQL → **RDS**, Redis/Valkey → **ElastiCache**, Kafka → **MSK**"*
  ⇒ phương án thay Kafka bằng SNS+SQS (~$7/tháng) **không tuân thủ**, loại.
- **Yêu cầu 5 (Cost-aware)** và **mục Ràng buộc** nhắc trần *hai lần* ⇒ vượt trần là **vi phạm ràng buộc
  directive**, không phải mục tiêu mềm. Trần tính theo **TF**, nên chi phí AIO02 và stack Tokyo đều tính chung.
- Directive **không quy định KRaft** ⇒ `MSK 3.8.x` ZooKeeper + `t3.small` = **$127/tháng vẫn tuân thủ**,
  tiết kiệm $431/tháng. Không làm ở thời điểm này vì phải dựng cụm mới + **cutover Kafka lần 3** (đánh đổi
  yêu cầu 2 zero-loss/SLO — đúng chỗ đã sinh sự cố 0010), và ZooKeeper mode đang bị khai tử. **Đưa vào
  backlog COST**, xem lại sau nghiệm thu.

---

## 5.3 Quét vòng 2 — những chỗ còn lại

Sau khi chốt 5 việc chính, đã rà tiếp toàn bộ service còn lại. Kết quả: **không còn khoản lớn nào**,
nhưng có vài phát hiện đáng ghi.

### Phát hiện đáng chú ý nhất: VPC endpoint đắt hơn 3,3× cái NAT nó thay thế

| Khoản (đo 21/07) | $/ngày | $/tháng |
|---|---:|---:|
| **VPC interface endpoint** (5 × 3 AZ = 15 ENI) | **4,68** | **142** |
| NAT gateway — giờ | 1,416 | 43 |
| NAT gateway — **xử lý dữ liệu** | 0,231 | 7 |

Endpoint được dựng để né phí NAT, nhưng toàn bộ lưu lượng đi NAT chỉ tốn **$7/tháng**. Đang trả
**$142/tháng để tiết kiệm $7/tháng**. Phương án quyết liệt — bỏ **cả 5** endpoint, để mọi thứ đi NAT —
tiết kiệm **$32,8/tuần** thay vì $26,2 như kế hoạch, đổi lại nếu NAT chết thì mất luôn đường SSM
(vẫn còn Cloudflare Zero Trust làm đường 2). Kế hoạch ở §4 chọn bản an toàn hơn: giữ bộ `ssm` ở 1 AZ.

### Đã kiểm tra và xác nhận **không** có lãng phí

| Khoản | Trạng thái |
|---|---|
| RDS backup | retention 7 ngày, dữ liệu 29 MB / 20 GB cấp phát → **nằm trong mức backup miễn phí** |
| RDS Performance Insights / Enhanced Monitoring | **đã tắt cả hai** — không phát sinh |
| ElastiCache snapshot | retention 3 ngày, dữ liệu vài MB → không đáng kể |
| Snapshot thủ công trước §8 (RDS + ElastiCache) | dung lượng nén theo dữ liệu thật, không phải 20 GB → ~$0 |
| NAT gateway | **đúng 1 cái** (COST-07 đã làm) — $1,416/ngày = 24h × $0,059 |
| Elastic IP | 1 địa chỉ, đang gắn NAT → **không có EIP mồ côi** |
| EBS snapshot | **không có cái nào** |
| CloudFront | dưới ngưỡng miễn phí |

### Khoản nhỏ nên dọn

| Khoản | $/tháng | Chủ | Ghi chú |
|---|---:|---|---|
| ECR `tf-2-ai-engine` — **89 image, 11,15 GB** | ~1,1 | AIO02 | rác từ TF2, không có lifecycle policy |
| ECR `shopping-copilot` — 3 image, 0,25 GB | ~0 | AIO02 | không có pod nào chạy service này |
| Pod `llm` (mock) — 25m/96Mi | 0 tiền mặt | AIO02 | `product-reviews` đã dùng Bedrock, không còn gọi mock; dọn cho gọn cluster |
| 3 EBS gp2 mồ côi (6 GB) từ PVC store cũ | ~0,7 | CDO02 | xoá sau nghiệm thu — **`reclaimPolicy: Delete`, xoá PVC là mất EBS vĩnh viễn** |

### Right-size resource request — đòn bẩy gián tiếp lên số node

Số node bị quyết định bởi **request**, không phải mức dùng thật. Đo bằng `kubectl top` cho thấy hai
hướng lệch ngược nhau:

| Pod | Request | Dùng thật | Lệch |
|---|---:|---:|---|
| `load-generator` | 1024 Mi | 123 Mi | **thừa 8,3×** — chiếm chỗ xếp pod vô ích |
| `grafana` | 800 Mi | 419 Mi | thừa 1,9× |
| `jaeger` | 750 Mi | 418 Mi | thừa 1,8× |
| `opensearch-0` | 750 Mi | **1275 Mi** | ⚠️ **thiếu 1,7×** — rủi ro OOM (đúng loại sự cố REL-13/REL-16) |
| `prometheus` | 450 Mi | **814 Mi** | ⚠️ **thiếu 1,8×** — rủi ro OOM |

Việc cần làm không phải "giảm hết cho rẻ" mà là **chỉnh cho khớp thực tế**: hạ `load-generator` xuống
~256 Mi (giải phóng 768 Mi năng lực xếp pod) và **tăng** request của `opensearch`/`prometheus` cho khớp
mức dùng. Vế thứ hai *không* tiết kiệm tiền — nó phòng đúng loại sự cố OOM mà backlog REL-13/REL-16 đã
gặp một lần rồi.

### Cố ý không đụng

- **`load-generator` LOCUST_USERS=10** — đây là nguồn tải giả lập của nền tảng, cũng là thứ sinh ra mọi
  số đo SLO. Hạ nó xuống để giảm chi phí Bedrock/MSK/data-transfer là **làm hỏng phép đo**, không phải
  tối ưu.
- **Cross-AZ data transfer $11/tháng** — hệ quả trực tiếp của topologySpread + Multi-AZ. Đây là giá của
  thiết kế Reliability, trả có chủ đích.
- **Log `audit`** — xem §4.0.

---

## 6. Phụ lục — cách tái lập số liệu

```bash
export AWS_PROFILE=techx-new

# Tong theo service, ngay du lieu day du gan nhat (bo Credit)
aws ce get-cost-and-usage --time-period Start=2026-07-21,End=2026-07-22 \
  --granularity DAILY --metrics UNBLENDED_COST \
  --group-by Type=DIMENSION,Key=SERVICE \
  --filter '{"Dimensions":{"Key":"RECORD_TYPE","Values":["Usage"]}}'

# Tach CDO / AI / ngoai pham vi = tach theo REGION
aws ce get-cost-and-usage --time-period Start=2026-07-21,End=2026-07-22 \
  --granularity DAILY --metrics UNBLENDED_COST \
  --group-by Type=DIMENSION,Key=REGION \
  --filter '{"Dimensions":{"Key":"RECORD_TYPE","Values":["Usage"]}}'
```

> **Bẫy đã gặp:** để mặc định (không lọc `RECORD_TYPE`) thì Cost Explorer trả **~$0** vì credit phủ
> hết — dễ tưởng nhầm là không tốn tiền. Luôn lọc `RECORD_TYPE = Usage` khi đánh giá trụ Cost.

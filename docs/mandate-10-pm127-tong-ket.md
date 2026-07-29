# Mandate #10 / PM-127 — Tổng kết: đã làm gì, sai ở đâu, quyết định vì sao

**Người thực hiện:** CDO02 (Vietsory)
**Thời gian:** 27–28/07/2026
**Phạm vi:** yêu cầu **#3** của [Directive #10](https://github.com/TechX-Corp/xbrain-learners/blob/main/phase3/mandates/MANDATE-10-secure-delivery-pipeline.md) — *bất biến + xác thực nguồn gốc*
**Trạng thái:** ✅ đóng, có bằng chứng chạy lại được

> Tài liệu này viết cho **cả TF3**, không riêng CDO02. Mục tiêu là để người sau
> không phải dò lại 2 ngày mới hiểu tại sao pipeline lại làm theo cách này —
> và để không ai vô tình phá nó bằng một PR trông vô hại.

---

## 1. PM-127 KHÔNG phải là Mandate #10

Directive #10 có **6 yêu cầu**. PM-127 chỉ đóng yêu cầu #3.

| # | Yêu cầu | Ticket | Ai làm |
|---|---|---|---|
| 1 | CI đỏ = không merge, không deploy | PM-124/126 | CDO01 |
| 2 | Scan HIGH/CRITICAL là cổng chặn | PM-125 | CDO01 |
| 3 | **Bất biến + ký + SBOM + admission enforce** | **PM-127** | **CDO02** |
| 4 | Pin commit SHA / digest | PM-129 | CDO01 |
| 5 | Truy ngược từ pod đang chạy | PM-129 | CDO01 |
| 6 | Chỉ build cái gì đổi | — | có sẵn (job `prepare`) |

Đọc nhầm PM-127 = Mandate #10 sẽ dẫn tới kết luận "mandate xong rồi" trong khi
phần **nộp** của mandate là **3 màn demo live** cho mentor tự bấm — xem §8.

---

## 2. Trước và sau

| | Trước 27/07 | Sau 28/07 |
|---|---|---|
| Image first-party có chữ ký | Chỉ image build mới | **21/21 digest đang chạy** |
| SBOM tra được theo digest | Không | **1 lệnh**, cả amd64 + arm64 |
| Admission kiểm chữ ký | `Audit` (cảnh báo suông) | **`Enforce`** — chặn thật |
| Image bên thứ ba | 7 reference dùng tag trôi | **11/11 pin digest**, có catalog duyệt |
| Quên cập nhật catalog | Pod bị từ chối lúc chạy | **PR đỏ** trước khi merge |
| Pipeline SBOM | **Hỏng** — mọi build multi-platform fail | Chạy được |

Điểm cuối quan trọng nhất: **trước PM-127 pipeline SBOM đang hỏng thật**, không
phải "chưa bật". Mọi build multi-platform đều fail ở bước attest. Xem §4.1.

---

## 3. Kiến trúc: vì sao là **hai** policy chứ không phải một

Mandate viết *"cluster chỉ chạy image đã ký"*. Áp nguyên văn thì không khả thi:
`busybox`, `prometheus`, `cloudflared`, `flagd` là image của bên thứ ba —
**TF3 không có khoá để ký chúng**, và ký lại image người khác cũng không chứng
minh được gì về nguồn gốc.

Nên chia đôi trách nhiệm:

| Policy | Áp cho | Kiểm gì |
|---|---|---|
| `verify-first-party-signatures` | `techx-corp@sha256:*` | Chữ ký cosign keyless đúng workflow + SBOM |
| `allow-approved-external-image-digests` | mọi image còn lại | Digest **khớp tuyệt đối** một catalog đã review |

Hai policy **phủ kín namespace, không chừa khe**: cái gì không phải first-party
thì rơi xuống cái thứ hai. Có unit test khoá tính chất này
(`test_external_policy_defers_every_first_party_form_to_the_signature_policy`).

**Nếu chỉ bật policy first-party** thì `nginx@sha256:…` chạy được trong
`techx-tf3` — và câu *"cluster chỉ chạy image đã ký"* thành **sai**. Đây là lý do
policy external tồn tại, dù nhìn qua tưởng là việc thừa.

### Câu trả lời cho mentor nếu bị hỏi

> *"busybox có chữ ký cosign không?"*

**Không, và không thể có.** Đảm bảo với image bên thứ ba là: pin **digest tuyệt
đối** (không tag), nằm trong catalog đã review, và **mọi thay đổi catalog phải
qua PR** có CI gác. Digest là thứ không giả được — đổi 1 byte là đổi digest.

---

## 4. Những lỗi đã gặp — phần đáng đọc nhất

### 4.1 Pipeline SBOM hỏng vì ghi **hai lần** vào một tag bất biến

**Triệu chứng:** mọi build multi-platform fail ở bước attest, `TAG_INVALID`.
Fail thật ở run `30271215463` và `30275177873`.

**Nguyên nhân:** cosign chạy ở **legacy layout** — mọi attestation của một digest
nằm chung **một** tag `sha256-<digest>.att`. ECR bật **immutable tag** (PM-95) nên
tag đó chỉ ghi được **đúng một lần**. Workflow lại gọi `cosign attest` **hai lần**
lên cùng index digest: một lần CycloneDX, một lần "mapping index→platform".
Predicate type khác nhau **không cứu được** — vẫn cùng một tag.

**Vì sao phải dùng legacy layout:** Kyverno `verifyImages` **chỉ đọc legacy**.
Chuyển sang OCI 1.1 referrers thì attestation đẹp hơn nhưng **admission mù**.

**Cách sửa:** bỏ hẳn lệnh attest thứ hai. Thông tin mapping được **nhúng vào
trong chính predicate của từng child** (`techx.indexDigest`, `techx.subjectDigest`,
`techx.platform`) — vẫn được ký, vẫn truy được, mà chỉ tốn một lần ghi. (PR #493)

> **Bài học:** khi registry bất biến, "thêm một attestation nữa cho đầy đủ" là
> thao tác **phá pipeline**, không phải cải tiến.

### 4.2 Backfill ghi sai commit — hỏng đúng thứ mandate cần

20 digest đang chạy production chưa có chữ ký. Chọn **backfill** (ký + attest lên
digest có sẵn) thay vì rebuild — rebuild 20 image nghĩa là **20 lần rollout
production không cần thiết**, đổi cả digest đang chạy.

**Lỗi:** bản đầu ghi `sourceSha` = commit **lúc backfill**, không phải commit
**đã build ra image**. Chuỗi truy ngược vẫn "chạy" nhưng dẫn tới một commit
**không liên quan** — tức là hỏng đúng yêu cầu #5 của mandate.

**Sửa:** truyền SHA gốc theo từng cặp; 20 SHA thật được truy lại từ các commit
promotion (`bump images from <sha>`). (PR #498)

> **Bài học:** provenance sai còn **nguy hiểm hơn** không có provenance — nó tạo
> niềm tin giả và qua được kiểm tra hình thức.

### 4.3 Cosign v3 báo "thiếu SBOM" trong khi SBOM vẫn ở đó

cosign v3 ưu tiên đọc OCI 1.1 referrers. Với digest cũ, nó thấy chữ ký kiểu mới,
kết luận **thiếu CycloneDX** — một **false negative trông y hệt bằng chứng hỏng**.

**Sửa:** `scripts/ci/get-sbom.sh` **chặn sai major version** kèm hướng dẫn cài
đúng bản. Dùng nhầm công cụ giờ báo lỗi rõ ràng thay vì trả kết quả sai. (PR #498)

### 4.4 SHA ngắn lọt kiểm tra, làm kẹt image `ad`

Regex nhận SHA dài 7–40 ký tự, nhưng `prepare-cyclonedx-sbom.py` đòi **đúng 40** —
và nó chỉ kiểm **sau khi chữ ký đã push**. Kết quả: `ad` mắc kẹt ở trạng thái
**có `.sig` nhưng không có `.att`**, mà tag `.att` thì không ghi lại được.

**Sửa:** kiểm đúng 40 ký tự **trước mọi thao tác ghi registry**, cộng thêm nhánh
phục hồi cho digest đã lỡ có `.sig`. (PR #499)

> **Bài học:** validate **trước** khi ghi vào nơi không xoá được.

### 4.5 Drift check fail trong CI vì `charts/*.tgz` bị gitignore

Script render chart như ArgoCD làm, nhưng `charts/*.tgz` và `Chart.lock` không
được commit → `helm template` fail. Tệ hơn: script **nuốt stderr của helm** nên
log CI không nói được gì.

**Sửa:** copy chart ra thư mục tạm + `helm dependency build` trước khi render, và
**đẩy stderr ra ngoài**. (PR #525)

### 4.6 Chính cái gate đó bắt được lỗi của người viết ra nó

Sau khi gate hoạt động, một PR ghi digest `shopping-copilot` **lấy từ trí nhớ**
(`589cb030`) trong khi digest thật là `347bad1e`. **CI đỏ ngay.**

Nếu không có gate, sai số này chỉ lộ ra khi **pod bị từ chối trên production**.
Đây là bằng chứng thực tế cho việc gate đáng tồn tại. (PR #529)

### 4.7 Test admission bị **tầng khác** chặn — chạy 3 lần mới ra kết quả dùng được

`techx-tf3` có **3 tầng admission trước Kyverno**:

| Tầng | Đòi gì |
|---|---|
| PodSecurity `restricted` | `runAsNonRoot`, `seccompProfile`, `capabilities.drop: [ALL]`… |
| `mandate05-native-resource-requirements` | `requests` **và** `limits`, cả cpu lẫn memory |
| `mandate05-native-image-reference` | cấm `:latest`; `techx-corp` bắt buộc `@sha256` |

| Lần | Kết quả | Vì sao |
|---|---|---|
| 1 | 5/6 vô hiệu | thiếu `securityContext` → PodSecurity chặn trước |
| 2 | 5/6 vô hiệu | thiếu `resources` → resource VAP chặn trước |
| 3 | **6/6 hợp lệ** | đọc hết cả 3 tầng rồi mới viết lại fixture |

**Chỗ nguy hiểm:** ở lần 1 và 2, các case `deny-*` **vẫn "lỗi"** — đọc lướt thì
tưởng test đã pass, trong khi **Kyverno chưa hề được gọi**. Một case deny **thất
bại trông y hệt thành công**.

**Cách phân biệt duy nhất đáng tin:** message **phải nêu tên policy đang test**.
Nếu nó nhắc `PodSecurity` hay `mandate05-native-resource-requirements` → **bỏ kết quả**.

Vì lý do này `deny-04` cố tình dùng `busybox:1.36` chứ **không** dùng `:latest` —
`:latest` bị native VAP bắt trước, fixture kiểu đó chứng minh nhầm tầng.

### 4.8 Vài lỗi nhỏ nhưng tốn thời gian

| Lỗi | Hệ quả |
|---|---|
| `tr -d "\x27\""` | `tr` không hiểu `\x27` → **xoá sạch ký tự `2` và `7`**, `sha256` thành `sha56` |
| PM-149 scope guard bắn nhầm PR #497 | Đếm file test CI dùng chung là nội dung PM-149 |
| Tưởng "không đụng Grafana" | `k8s-sidecar` **chạy trong chính pod Grafana** |
| Gán nhầm digest opensearch cho Grafana | Nó thuộc CronJob `otelLogsRetention` (Directive #18) |
| Dùng snapshot `.sig` cache | Danh sách lạc hậu 2 mục → suýt kết luận sai trước khi bật Enforce |

---

## 5. Các quyết định và lý do

| # | Quyết định | Lý do | Đánh đổi |
|---|---|---|---|
| D1 | Giữ **cosign legacy layout** (v2.6.2) | Kyverno `verifyImages` chỉ đọc được layout này | Mỗi digest chỉ ghi được **1** tag `.att` → xem §4.1 |
| D2 | Bỏ attestation mapping riêng, **nhúng vào child predicate** | Hệ quả bắt buộc của D1 + ECR immutable | Mapping không tra được bằng lệnh cosign riêng |
| D3 | **Hai** policy thay vì một | Không thể ký image bên thứ ba | Phải nuôi một catalog |
| D4 | **Backfill** thay vì rebuild 20 image | Rebuild = 20 rollout production vô ích, đổi digest đang chạy | Cần script riêng, và §4.2/§4.4 |
| D5 | `sourceSha` = commit **build gốc** | Nếu không thì truy ngược dẫn sai chỗ | Phải truy lại 20 SHA từ commit promotion |
| D6 | **CI gate** cho drift catalog | Không dựa vào việc con người nhớ | Thêm 1 required check |
| D7 | Enforce **external trước**, first-party sau | Tách rủi ro: nếu sập thì biết ngay do vế nào | Chậm hơn 1 nhịp |
| D8 | Giữ `deny-02` dù bị **VAP** chặn chứ không phải Kyverno | Là bằng chứng hai tầng **chồng lấn** chứ không để hở | Phải giải thích thêm khi đọc |

---

## 6. Vận hành hằng ngày — đọc trước khi sửa image

### Thêm hoặc đổi image **bên thứ ba**

1. Pin **digest tuyệt đối** trong values / manifest gitops (không để tag trần).
2. Thêm đúng mục đó vào [`docs/evidence/mandate-10/external-image-allowlist.yaml`](evidence/mandate-10/external-image-allowlist.yaml)
   **và** `gitops/policies/kyverno/allow-approved-external-image-digests.yaml`.
3. Mở PR. Nếu hai nơi lệch nhau → **CI đỏ**, không merge được.

**Quên bước 2 = pod bị từ chối trên production.** Gate sinh ra để bạn gặp lỗi này
trong PR chứ không phải lúc 2 giờ sáng.

### Thêm image **first-party** mới

Không phải làm gì thêm — `build-push-ecr.yml` tự ký + attest. Chỉ cần **đừng**
thêm lệnh `cosign attest` thứ hai lên cùng một digest (§4.1).

### Sửa `build-push-ecr.yml`

Có contract test canh: `scripts/ci/test_workflow_sbom_contract.py` sẽ đỏ nếu tag
attestation của index bị ghi quá một lần.

### ⚠️ `kubectl debug` giờ bị chặn

Đúng chủ đích — chính cơ chế này bắt được **3 container `nicolaka/netshoot` bỏ
quên** trên pod `fraud-detection` ngày 28/07. Cần troubleshoot thì dùng image
trong catalog, hoặc thêm image mới qua PR.

---

## 7. Bằng chứng nằm ở đâu

| Nội dung | Đường dẫn |
|---|---|
| Ma trận nghiệm thu + các bẫy | [`acceptance-matrix.md`](evidence/mandate-10/pm127/acceptance-matrix.md) |
| Kết quả test admission 6/6 | [`admission-test-results-2026-07-28.md`](evidence/mandate-10/pm127/admission-test-results-2026-07-28.md) |
| Bộ fixture chạy lại được | [`admission-tests/`](evidence/mandate-10/pm127/admission-tests/) |
| Truy ngược provenance từ pod | [`provenance-walkthrough.md`](evidence/mandate-10/pm127/provenance-walkthrough.md) |
| Pilot `currency` (run 30287961994) | [`currency-pilot-evidence.json`](evidence/mandate-10/pm127/2026-07-27/pilot/currency-pilot-evidence.json) |
| Backfill 20 digest (run 30333294916) | [`first-party-backfill-evidence.json`](evidence/mandate-10/pm127/2026-07-28/backfill/first-party-backfill-evidence.json) |
| Catalog image bên thứ ba | [`external-image-allowlist.yaml`](evidence/mandate-10/external-image-allowlist.yaml) |

**Chữ ký:** identity `build-push-ecr.yml@refs/heads/main`, issuer
`token.actions.githubusercontent.com`. Verify bằng **cosign v2.x** — v3 cho kết
quả sai, xem §4.3.

---

## 8. Còn thiếu gì ở **cấp mandate**

Sáu yêu cầu kỹ thuật đã đủ. Phần **nộp** thì mandate đòi mentor **tự bấm nút**:

| Phải nộp | Năng lực | Kịch bản demo |
|---|---|---|
| PR CI cố tình đỏ → chặn merge | ✅ PM-124, PR #350/#351 `BLOCKED` thật | rải rác |
| Deploy image chưa ký → admission từ chối | ✅ 6/6 hôm nay | trong README fixture |
| Chỉ vào pod đang chạy → truy ngược full provenance | ✅ `trace-provenance.sh` PASS 26/07 | runbook riêng |

**Còn thiếu:**

- **ADR ký tên cho Mandate #10** — chưa có. 10 mandate khác đều có ADR.
- **Một kịch bản demo hợp nhất** — 3 màn đang nằm ở 3 tài liệu khác nhau.
- Hạn nộp là **hết 20/07**; hoàn tất thực tế **28/07**. Ghi đúng ngày, không lùi.

> [!NOTE]
> ADR + demo cuối được map cho **PM-132 (CDO01)** trong
> [`mandate-10-gap-analysis.md`](docx_cdo01/mandate-10-gap-analysis.md).
> **Cần chốt ai cầm** — mandate này thi head-to-head toàn TF, hai bản hồ sơ
> chồng nhau thì yếu hơn một bản thống nhất.

---

## 9. Rủi ro đã biết, chấp nhận có chủ đích

**`kubectl rollout undo` sẽ bị chặn.** 79/266 ReplicaSet đã chết còn trỏ digest
chưa ký. Không cái nào đang tạo pod.

Đường rollback được hỗ trợ là **`git revert` + ArgoCD** — deploy lại digest từ
`values-prod.yaml`, toàn bộ đã ký, không ảnh hưởng.

*Một revision không chứng minh được nguồn gốc thì đúng ra không nên quay lại được.*

**Cảnh báo `PolicyViolation` vẫn xuất hiện và đó là đúng.** Toàn bộ là ReplicaSet
chết (`DESIRED=0`) mà background scan vẫn quét. **Chỉ đo trên pod `Running`** —
đọc số violation thô sẽ ra kết luận sai.

---

## 10. Việc còn mở (ngoài phạm vi PM-127)

| Việc | Ghi chú |
|---|---|
| CronJob `aiops-anomaly-training` Failed 2 lần liên tiếp | Hỏng sẵn từ trước, không liên quan supply chain. **AIO02** |
| 266 ReplicaSet trong `techx-tf3`, 79 trỏ digest chưa ký | Nên đặt `revisionHistoryLimit`. Không ảnh hưởng runtime |
| `deploymentState: planned-audit-remediation` trong catalog | Đã lạc hậu — hai policy giờ ở `Enforce`. Field này không có code nào đọc, sửa là việc 1 dòng |
| `deny-05` (ephemeral container) chưa chạy bằng manifest | Cần `kubectl debug`. Nhánh policy đã khoá bằng unit test và **đã chứng minh trên thực tế** (vụ `netshoot`) |

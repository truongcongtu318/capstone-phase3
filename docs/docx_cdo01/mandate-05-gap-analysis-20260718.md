# Mandate 5 — Gap analysis thật (18/07/2026), đối chiếu mandate gốc × Jira DoD × cluster sống

**Nguồn đối chiếu:**
- Mandate gốc: `/Users/tan/Desktop/notes-for-phase3/xbrain-learners/phase3/mandates/MANDATE-05-runtime-hardening.md` (deadline **17/07/2026** — **đã qua hạn 1 ngày**)
- Jira: PM-92, PM-101, PM-104, PM-110, PM-111, PM-112, PM-113, PM-114 (đọc full DoD + output đã nộp, 18/07)
- Cluster sống: `techx-corp-tf3` (account 197826770971), verify trực tiếp bằng `kubectl`/`cosign`/`gh`, snapshot lúc viết doc này

**Phát hiện quan trọng nhất trước khi đọc chi tiết bên dưới:** Jira + `docs/../mandates/mandate-05/mandate-05-runtime-hardening-completion-plan.md` (viết 17/07, trước PR #207/208/209) đang báo tiến độ **9/13 DoD = 69.2%**, coverage baseline chỉ **~17.9%**. Nhưng cluster sống hôm nay đã tốt hơn HẲN — coverage thật đo lại là **95.1%** (xem mục 1). Có 1 loạt PR merge tối 17/07 (`#207`, `#208`, `#209`, và các fix lẻ `fe2adde`, `12c4eea`...) đã âm thầm đóng gần hết gap, nhưng **không ai cập nhật lại Jira/docs cho khớp** — đây tự nó là 1 việc cần làm hôm nay (mục 4, việc #6).

---

## 1. Đối chiếu 4 yêu cầu gốc của Mandate 5 với cluster sống

| # | Yêu cầu mandate | Trạng thái thật (verify sống 18/07) |
|---|---|---|
| 1 | Không container nào chạy root | ✅ **95.1%** (58/61 container) đạt đủ `runAsNonRoot` + `allowPrivilegeEscalation:false` + `capabilities.drop:[ALL]` + `seccompProfile:RuntimeDefault`. Chỉ còn 2 gap thật: `aiops-engine` (thiếu 2/4 rule, không thuộc GitOps CDO01) và `kafka`'s `init-kafka-data` (root có chủ đích, đã ghi exception — xem mục 2). |
| 2 | Không xài image trôi, pin digest/tag cố định | ✅ **0 vi phạm thật**. 20/20 image ECR `techx-corp` đang chạy đều pin bằng digest `sha256:...`. Không còn image nào chạy `:latest` (chuỗi `curlimages/curl:latest` từng thấy là do pod debug `flagdcheck` của chính tôi để sót lại — **đã xoá**). Image external dùng tag cố định (`v0.12.9`, `2026.7.1`, `3.6.0`...), không phải `:latest`. |
| 3 | Mọi workload có resource request/limit | ✅ **0 vi phạm thật** trên Kyverno `require-resource-requests` (đối chiếu 46/46 pod sống trong `techx-tf3`, không có `PolicyReport` nào FAIL còn hiệu lực). |
| 4 | **Enforce tự động tại admission** | 🔴 **CHƯA — đây là gap thật duy nhất còn chặn cả mandate.** Cả 4 `ClusterPolicy` (`custom-baseline-security-context`, `disallow-latest-tag`, `require-first-party-image-digest`, `require-resource-requests`) đều **còn `validationFailureAction: Audit`**, chưa cái nào `Enforce`. Nghĩa là **1 manifest vi phạm hôm nay vẫn apply được bình thường, không bị chặn** — đúng cái mentor sẽ tự tay thử và sẽ KHÔNG thấy bị từ chối nếu demo ngay bây giờ. |

**Kết luận mục 1:** 3/4 yêu cầu nội dung đã đạt gần như tuyệt đối trên cluster sống. Cái còn thiếu không phải là "làm thêm remediation" (phần đó gần xong) mà là **bấm nút chuyển Audit → Enforce** — việc này khả thi làm trong hôm nay vì số vi phạm thật đang gần bằng 0.

---

## 2. [CẬP NHẬT 18/07 sau PR #222] Đối chiếu exclude THẬT trong từng file policy — chi tiết hơn hẳn `exception-register.yaml`

**PR #222 đã xử lý đúng phần `flagd-ui` resources**: thêm đủ 4 field (`requests.cpu/memory`, `limits.cpu/memory`) vào cả `values.yaml`/`values-prod.yaml`, xoá exception `m05-resources-flagd-ui-sidecar`, và **gỡ sạch exclude `flagd` khỏi `require-resource-requests.yaml`** — file này giờ **không còn exclude nào cả**, sạch hoàn toàn. Việc này đã xong, không cần làm gì thêm cho policy này.

**Nhưng soát kỹ lại toàn bộ 3 file policy còn lại (không chỉ dựa vào `exception-register.yaml` — file đó ghi ở mức "workload X exception khỏi policy Y", trong khi Kyverno thật sự exclude ở mức TỪNG RULE riêng lẻ, chi tiết hơn nhiều) phát hiện thêm 1 việc chưa ai ghi nhận: `require-run-as-non-root` trong `baseline-security-context.yaml` đang exclude `currency, llm, product-reviews` — set exception này **không có trong `exception-register.yaml` luôn** (bị bỏ sót khi ghi hồ sơ), và PM-111 đã vá xong base image 3 service này từ lâu (verify sống: cả 3 đã `runAsNonRoot: true`) — **exclude này giờ thừa 100%, an toàn xoá**.

**Bảng đầy đủ, đúng ở cấp RULE (không phải cấp workload) — đây là cấp cần sửa thật trong YAML:**

| Rule trong `baseline-security-context.yaml` | Đang exclude ai | Còn cần giữ ai | Xoá ai |
|---|---|---|---|
| `require-effective-non-root` | flagd, jaeger, kafka, opentelemetry-collector, postgresql, aiops-engine | **kafka** (init-kafka-data thật sự chạy root), **aiops-engine** | flagd, jaeger, opentelemetry-collector, postgresql |
| `deny-container-run-as-user-zero` | kafka | **kafka** (giữ nguyên) | — |
| `require-allow-privilege-escalation-false` | flagd, jaeger, kafka, opensearch, opentelemetry-collector, postgresql, prometheus | **kafka** (init-kafka-data chưa set APE) | flagd, jaeger, opensearch, opentelemetry-collector, postgresql, prometheus |
| `require-run-as-non-root` | currency, llm, product-reviews | *(không cần giữ ai)* | **currency, llm, product-reviews — xoá hết, rule này về exclude rỗng** |
| `drop-all-capabilities` | flagd, jaeger, kafka, opentelemetry-collector, postgresql, prometheus | **kafka** (init-kafka-data chưa drop-ALL) | flagd, jaeger, opentelemetry-collector, postgresql, prometheus — **và cần THÊM `aiops-engine`** (đang FAIL thật, chưa có exclude nào che) |
| `require-seccomp-profile-runtime-default` | flagd, jaeger, opensearch, opentelemetry-collector, postgresql, prometheus | *(không ai, kafka tự pass rồi)* | flagd, jaeger, opensearch, opentelemetry-collector, postgresql, prometheus — **và cần THÊM `aiops-engine`** (đang FAIL thật) |
| `deny-pod-run-as-user-zero`, `deny-privileged-containers` | *(không exclude gì)* | — | đã sạch, không cần sửa |

Và `require-first-party-image-digest.yaml` còn đúng 1 exclude thừa: `flagd` (cả main container lẫn flagd-ui) — main container `flagd` dùng ảnh external `ghcr.io/open-feature/flagd:v0.12.9` nên vốn không thuộc phạm vi rule này; `flagd-ui` đã chạy digest thật (`sha256:fe39070c...`) nên cũng tự pass — **xoá exclude này an toàn**.

**Đối chiếu ngược lại `exception-register.yaml`** (giờ còn 10 entry sau PR #222) — sau khi làm đúng bảng trên, file này chỉ nên còn giữ lại:
- `m05-baseline-kafka-init-chown` (đúng, có thật)
- `m05-baseline-aiops-engine-runtime` (đúng nhưng cần **sửa lại đúng 2 rule**: `drop-all-capabilities` + `require-seccomp-profile-runtime-default` — không phải 4 rule như đang ghi)

8 entry còn lại (`m05-baseline-flagd-control-plane`, `m05-image-flagd-ui-digest-pin`, `m05-image-kafka-digest-pin`, `m05-baseline-postgresql-stateful`, `m05-baseline-jaeger-observability`, `m05-baseline-prometheus-observability`, `m05-baseline-opensearch-stateful-observability`, `m05-baseline-otel-agent`) đều stale, xoá được — khớp với việc xoá exclude tương ứng ở bảng trên.

**⚠️ Điểm rủi ro vận hành cần biết trước khi Enforce (không chỉ là dọn giấy tờ):** `aiops-engine` hiện **CHƯA có exclude nào** cho `drop-all-capabilities` và `require-seccomp-profile-runtime-default` — nếu bật Enforce cho `custom-baseline-security-context` MÀ CHƯA thêm exclude (hoặc chưa được AIO02 fix), **mọi lần AIO02 tự `kubectl apply`/redeploy `aiops-engine` sau đó sẽ bị admission từ chối thật**, không phải vô hại. Đây không phải việc "làm sau cũng được" — phải chốt xong TRƯỚC khi Enforce `custom-baseline-security-context`.

---

## 3. PM-101 (Trivy/Cosign) — thật ra đã tốt hơn Jira ghi

- **Cosign**: verify trực tiếp cả **20/20 digest first-party đang chạy sống** → **PASS toàn bộ** (`cosign verify --certificate-identity-regexp=".../Phase3-TF3-Infra-Sentinel" --certificate-oidc-issuer="https://token.actions.githubusercontent.com"`). DoD PM-101 yêu cầu "18 service tự build đều có chữ ký" — **đã vượt (20/20)**, dù Jira vẫn ghi "In Progress" và completion-plan ghi "full first-party Cosign verification is still missing".
- **Trivy**: gate đã chạy trong `build-push-ecr.yml` (đã review kỹ ở PR #148/#153 trước đây), nhưng chưa tổng hợp lại thành 1 bảng evidence digest↔Git SHA↔Actions run↔Trivy report như DoD yêu cầu — đây là việc **giấy tờ**, không phải việc kỹ thuật còn thiếu.

## 4. PM-114 (Kyverno verifyImages Cosign + external allow-list) — thật sự vẫn "To Do", nhưng KHÔNG phải core mandate

Xác nhận: cả 4 `ClusterPolicy` hiện tại **không có policy nào làm `verifyImages`** (Cosign admission-time). Đây đúng là gap thật duy nhất còn "To Do" hoàn toàn. Nhưng cả PM-101 DoD lẫn PM-104 DoD đều tự ghi rõ đây là phần **"nâng cao, không bắt buộc"/"tuỳ chọn"** — mandate gốc chỉ yêu cầu 4 điều ở mục 1, không yêu cầu Cosign admission-verify. **Không nên ưu tiên hôm nay** trừ khi đã xong việc #4 bên dưới và còn dư thời gian.

---

## 4.5. [CẬP NHẬT 18/07, đã tự sửa lại kết luận sai lúc đầu] PR #223/#224/#225 review — khớp gần hết khuyến nghị; "bug" ban đầu báo thực ra là LimitRange, không phải lỗi Kyverno

**PR #223 (exception cleanup):** đối chiếu từng dòng với bảng khuyến nghị ở mục 2 — **khớp gần như chính xác 100%**, đúng từng rule, đúng workload cần gỡ/giữ. Còn bắt được thêm 1 lỗi tôi bỏ sót: rule `require-run-as-non-root` (bản cũ) có `match` KHÔNG giới hạn `namespaces`/`operations` (chỉ có `kinds: [Pod]`) — nghĩa là rule này từng áp cho **mọi namespace**, phải "vá tạm" bằng cách exclude riêng `kube-system/argocd/kyverno`. PR #223 sửa đúng gốc: thêm `namespaces: [techx-tf3]` + `operations: [CREATE, UPDATE]` vào `match`, bỏ được exclude vá tạm đó. ADR 0010 cũng đã update status + exceptions đúng thực tế. Việc dọn exclude coi như **xong**.

**PR #224:** chuyển `require-resource-requests` sang `Enforce` — đúng, đúng thứ tự ưu tiên (policy sạch nhất, làm trước).

**PR #225 (fix bug gốc):** đổi cách viết rule từ `deny: conditions:` (JMESPath fallback) sang `pattern: {resources: {requests: {cpu: "?*", ...}}}` — hướng sửa đúng, có thêm test regression. **Việc này là fix thật, hợp lệ, giữ nguyên.**

**Phần tôi từng báo sai (đã tự sửa sau khi user chỉ ra và test lại kỹ):** test dry-run 1 Pod trần thiếu `resources` trong `techx-tf3`, thấy không bị chặn, vội kết luận là "bug engine Kyverno". **Kết luận đó sai.** Xem nội dung object dry-run trả về (`-o yaml`) cho thấy: pod đã được **`LimitRange techx-limits` tự điền default TRƯỚC KHI Kyverno kịp đánh giá** (đúng thứ tự admission chuẩn K8s: mutating admission chạy trước validating webhook) — pod thật sự **có đủ 4 field** (`requests.cpu=100m/mem=50Mi`, `limits.cpu=200m/mem=150Mi`, khớp chính xác số của LimitRange) lúc Kyverno nhìn thấy, nên `"validation passed"` là **kết luận đúng của Kyverno**, không phải lỗi engine.

| Test case | Kết quả | Giải thích đúng |
|---|---|---|
| `Deployment` thiếu hoàn toàn `resources` | ✅ Bị chặn | LimitRange **không** mutate object `Deployment` (chỉ mutate `Pod`), autogen-rule thấy đúng sự thật: rỗng → chặn đúng |
| `Pod` trần thiếu `resources`, namespace `techx-tf3` | Không bị chặn | **Không phải bug** — LimitRange đã điền default hợp lệ trước khi Kyverno xem, pod thật sự đạt pattern |
| `Pod` trần thiếu `resources`, namespace `argocd` | Không bị chặn | **Không liên quan LimitRange** — rule `match.namespaces` chỉ khai `["techx-tf3"]`, policy này chưa bao giờ áp dụng cho `argocd` |

**Kết luận đúng:** không có bug Kyverno nào cả. Với **100% cách production thật đang deploy** (Deployment/StatefulSet/DaemonSet/Job qua Helm chart) — Enforce hoạt động đúng, chặn thật, đã verify bằng `admission webhook "validate.kyverno.svc-fail" denied...`. Pod trần chỉ là edge case không ai dùng trong production, và LimitRange đóng đúng vai trò lưới an toàn cho case đó — hợp lệ, có chủ đích (LimitRange được tạo từ 13/07 chính là để làm việc này).

**Việc duy nhất còn đáng lưu ý (không phải sửa code, chỉ là chọn đúng cách demo):** khi chuẩn bị manifest `bad-missing-resources.yaml` cho phần demo mentor, **nên dùng `kind: Deployment`, không dùng `Pod` trần** — vì Pod trần trong `techx-tf3` sẽ được LimitRange hợp lệ hoá, không thể hiện đúng ý "policy chặn thiếu resources". Nên ghi chú thêm 1 câu trong ADR 0010: "LimitRange là lưới an toàn cho Pod tạo trực tiếp (không dùng trong production); Kyverno enforce ở tầng controller — nơi mọi workload thật được khai báo."

---

## 4.6. [PHÁT HIỆN NGHIÊM TRỌNG 18/07 ~17:45] `custom-baseline-security-context` KHÔNG hề bảo vệ Deployment/StatefulSet/DaemonSet/Job — chỉ bảo vệ Pod trần

Sau khi cả 4 policy đã chuyển `Enforce` (PR #226-#230, theo báo cáo của member), tôi viết 4 manifest test thật (đặt tại `docs/evidence/mandate-05/rejection-demo/`, đều dùng `kind: Deployment` để đi đúng đường admission thật của production) và chạy `kubectl apply --dry-run=server` trực tiếp trên cluster sống:

| File | Vi phạm | Kết quả |
|---|---|---|
| `bad-latest-image.yaml` | `disallow-latest-tag` | ✅ Bị chặn đúng |
| `bad-digest.yaml` | `require-first-party-image-digest` | ✅ Bị chặn đúng |
| `bad-missing-resources.yaml` | `require-resource-requests` | ✅ Bị chặn đúng |
| **`bad-root.yaml`** | `custom-baseline-security-context` | 🔴 **KHÔNG bị chặn — `deployment.apps/mandate5-demo-bad-root created (server dry run)`** |

**Nguyên nhân xác định chắc chắn (đã verify bằng nhiều nguồn độc lập, không suy đoán):**

```sh
kubectl get clusterpolicy custom-baseline-security-context -o jsonpath='{.status.autogen.rules[*].name}'
# → RỖNG (3 policy còn lại đều có autogen-* rules)

kubectl get clusterpolicy custom-baseline-security-context -o jsonpath='{.status.rulecount}'
# → {"generate":0,"mutate":0,"validate":8,"verifyimages":0} — chỉ 8 rule Pod gốc, không có bản autogen cho controller nào
```

Kyverno có cơ chế **tự động sinh thêm rule tương đương cho `Deployment/StatefulSet/DaemonSet/Job/CronJob/ReplicaSet`** (gọi là "autogen") từ 1 rule viết cho `kind: Pod` — 3 policy còn lại đều có autogen hoạt động đúng (`autogen-require-cpu-memory-requests-limits`, `autogen-require-explicit-non-latest-image-reference`, `autogen-require-techx-ecr-sha256-digest`). Riêng `custom-baseline-security-context` thì **autogen không sinh ra được rule nào cả** (không có warning/error log rõ ràng nào giải thích lý do — `kubectl describe clusterpolicy` mục "Autogen:" trống hoàn toàn) — khả năng cao do 2 rule (`require-effective-non-root`, `require-seccomp-profile-runtime-default`) dùng cú pháp trộn lẫn field cấp container (`element.securityContext.X` trong `foreach`) VÀ field cấp pod (`request.object.spec.securityContext.X` fallback) trong CÙNG 1 điều kiện `deny.conditions` — tổ hợp này có thể vượt quá khả năng viết lại tự động của Kyverno autogen (chỉ là giả thuyết có cơ sở, chưa phải kết luận cuối từ Kyverno source, cần xác nhận thêm nếu muốn chắc 100%).

**Vì sao evidence doc của team (`docs/docx_cdo01/enforce-cutover-20260718.md`) không phát hiện ra:** bộ test `tests/kyverno/mandate-05/kyverno-test.yaml` (`kyverno test` CLI) và các lần test thủ công trước đó (thấy trong log Kyverno, user `aio2-admin-team` test lúc 09:50 UTC) đều dùng **`kind: Pod` trực tiếp** làm fixture (`mandate05-root`, `mandate05-insecure-baseline`...) — case này đúng là bị chặn thật (vì rule gốc viết cho `kind: Pod` vẫn hoạt động đúng), nên mọi test trước giờ đều PASS/đúng như kỳ vọng. **Không ai từng test bằng `kind: Deployment` cho riêng policy này** — nên lỗ hổng không lộ ra cho tới lúc tôi test hôm nay.

**Mức độ nghiêm trọng — đã đính chính sau khi test thật (không dry-run) theo câu hỏi của user:** apply thật `bad-root.yaml` (kind Deployment) → Deployment **và** ReplicaSet đều tạo được (không có autogen rule nào chặn 2 kind này), nhưng khi ReplicaSet-controller cố tạo Pod thật từ template thì **bị Kyverno chặn thật** (`FailedCreate`, admission webhook denied, đúng 5 rule fail) — **không có Pod root nào thực sự chạy được**, bảo vệ đầu-cuối vẫn có hiệu lực nhờ rule gốc (viết cho `kind: Pod`) vẫn đúng. Vậy đây **không phải** "không bảo vệ được workload nào" như bản nháp đầu tôi viết — bảo vệ thật sự vẫn còn, chỉ khác ở **thời điểm và cách rejection xảy ra**: mandate muốn "từ chối **ngay lúc apply**", nhưng ở đây `kubectl apply` Deployment vẫn báo `created` (trông như thành công), rejection chỉ lộ ra sau đó qua `kubectl get pods`/`describe rs`/events — sai UX so với ý mandate, không phải sai an toàn. Nếu mentor demo bằng Deployment và chỉ nhìn output `kubectl apply` mà không kiểm tra thêm, dễ hiểu lầm là "không bị chặn". **Vẫn nên sửa trước khi demo** để rejection xảy ra ngay ở bước Deployment (đúng chữ "ngay lúc apply"), nhưng không phải gap an toàn khẩn cấp như đánh giá ban đầu.

**Đề xuất hướng sửa (cần member có kinh nghiệm Kyverno xác nhận lại):**
1. Thử tách 2 rule đang dùng cú pháp trộn field (`require-effective-non-root`, `require-seccomp-profile-runtime-default`) — bỏ phần fallback `request.object.spec.securityContext.X` (pod-level), chỉ giữ `element.securityContext.X` (container-level) trong `deny.conditions`, xem autogen có sinh ra được không.
2. Hoặc thêm annotation `pod-policies.kyverno.io/autogen-controllers: Deployment,DaemonSet,Job,StatefulSet,CronJob,ReplicaSet` vào policy để ép Kyverno thử sinh autogen tường minh — nếu có lỗi cụ thể, Kyverno sẽ báo rõ hơn là im lặng bỏ qua như hiện tại.
3. Dù chọn hướng nào, **bắt buộc test lại bằng đúng `bad-root.yaml` (kind: Deployment)** ở `docs/evidence/mandate-05/rejection-demo/` sau khi sửa, tới khi thấy bị admission webhook từ chối mới coi là xong.

---

### ✅ ĐÃ SỬA XONG — PR #232 (`codex/mandate-05-controller-root-autogen`), merge 18/07

Member chọn hướng **thứ 3, chủ động hơn cả 2 đề xuất trên**: không phụ thuộc vào cơ chế autogen của Kyverno nữa — thêm tường minh `Deployment, StatefulSet, DaemonSet, Job, CronJob, ReplicaSet, ReplicationController, Rollout` vào `match.resources.kinds` của cả 8 rule, viết lại mọi `list:`/field-path bằng JMESPath OR-fallback tự nhận diện đúng schema từng kind (`spec.jobTemplate.spec.template.spec.containers` cho CronJob → `spec.template.spec.containers` cho Deployment/StatefulSet/DaemonSet/ReplicaSet/Rollout → `spec.containers` cho Pod trần), và đổi `exclude` (label-selector, chỉ so khớp label object đang xét) sang `preconditions` (JMESPath, đọc đúng label pod template bên trong, tránh bị giả mạo qua label cấp Deployment). Cách này còn xử lý được cả `Rollout` (Argo Rollouts CRD) — thứ mà autogen gốc của Kyverno không bao giờ cover được dù sửa đúng cú pháp, trong khi `checkout-rollout` (service thật) lại đang dùng đúng kind này.

Review kỹ toàn bộ diff trước khi merge (không tìm thấy lỗi logic khi trace tay JMESPath qua từng kind), có bộ test fixture đầy đủ cho cả 5 controller kind + 1 test chống giả mạo label rất tinh (`deployment-controller-label-bypass.yaml` — gắn nhãn `kafka`/`aiops-engine` ở cấp Deployment nhưng pod template mang label khác, kỳ vọng vẫn bị chặn — đúng, vì exception phải đọc đúng label pod template chứ không phải label object ngoài).

**Verify lại trên cluster sống sau khi merge + ArgoCD sync (18/07):**
```sh
kubectl get clusterpolicy custom-baseline-security-context -o jsonpath='{.spec.validationFailureAction}{"  ready="}{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
# -> Enforce  ready=True

kubectl apply --dry-run=server -f docs/evidence/mandate-05/rejection-demo/bad-root.yaml
```
Kết quả: **bị chặn ngay ở bước `kubectl apply`** (không còn phải đợi tới bước ReplicaSet tạo Pod như trước) —
```
Error from server: error when creating "bad-root.yaml": admission webhook "validate.kyverno.svc-fail" denied the request:
custom-baseline-security-context: drop-all-capabilities, require-allow-privilege-escalation-false,
require-effective-non-root, require-run-as-non-root, require-seccomp-profile-runtime-default: ...
```
3 file demo còn lại vẫn bị chặn đúng như trước (không regression). Không pod nào CrashLoop, `PolicyReport` vẫn sạch 0 fail trên pod sống, `checkout-rollout` (Rollout thật) vẫn `Healthy`, `kafka` vẫn `Running` (exception vẫn hoạt động đúng).

**Gap này coi như đã đóng hoàn toàn — cả 4/4 policy giờ đều chặn đúng ngay tại `kubectl apply`, đúng nghĩa "ngay lúc apply" của mandate.**

---

## 5. Việc cần làm GẤP hôm nay (18/07) — theo đúng thứ tự ưu tiên

1. **Dọn exclude THEO ĐÚNG CẤP RULE** (xem bảng chi tiết mục 2 — không phải xoá theo workload như bản đầu, phải sửa từng rule): gỡ `flagd/jaeger/opentelemetry-collector/postgresql` khỏi `require-effective-non-root`; gỡ `flagd/jaeger/opensearch/opentelemetry-collector/postgresql/prometheus` khỏi `require-allow-privilege-escalation-false`; gỡ hết `currency/llm/product-reviews` khỏi `require-run-as-non-root` (rỗng luôn); gỡ `flagd/jaeger/opentelemetry-collector/postgresql/prometheus` khỏi `drop-all-capabilities` **và thêm `aiops-engine`**; gỡ `flagd/jaeger/opensearch/opentelemetry-collector/postgresql/prometheus` khỏi `require-seccomp-profile-runtime-default` **và thêm `aiops-engine`**; **giữ nguyên `kafka`** ở 4 rule (`require-effective-non-root`, `deny-container-run-as-user-zero`, `require-allow-privilege-escalation-false`, `drop-all-capabilities`) vì `init-kafka-data` thật sự cần root/chưa set APE/chưa drop-ALL. Gỡ exclude `flagd` khỏi `require-first-party-image-digest.yaml`. Đồng bộ lại `exception-register.yaml` cho khớp — cuối cùng chỉ còn đúng 2 entry: `kafka-init-chown` + `aiops-engine` (sửa lại đúng 2 rule).
2. **Chốt aiops-engine TRƯỚC KHI Enforce `custom-baseline-security-context`** (không phải việc làm sau) — hoặc xin AIO02 thêm `securityContext`, hoặc thêm exclude thật cho `aiops-engine` ở đúng 2 rule còn thiếu (`drop-all-capabilities`, `require-seccomp-profile-runtime-default`) kèm chữ ký/ngày review. **Nếu bỏ qua bước này, lần AIO02 tự deploy `aiops-engine` tiếp theo sau khi Enforce sẽ bị admission từ chối thật** — rủi ro vận hành thật, không chỉ là thiếu giấy tờ.
3. **Chuẩn bị 4 manifest âm tính** (không phải 3) — mỗi manifest chỉ nên vi phạm ĐÚNG 1 policy để chứng minh từng policy hoạt động độc lập: `bad-root.yaml` (baseline-security-context), `bad-latest-image.yaml` (disallow-latest-tag — dùng tag `:latest`), `bad-digest.yaml` (require-first-party-image-digest — dùng ảnh ECR `techx-corp` với tag cố định thay vì digest, KHÔNG phải `:latest`, để test riêng policy này chứ không trùng với `bad-latest-image.yaml`), `bad-missing-resources.yaml` (require-resource-requests — **bắt buộc dùng `kind: Deployment`, KHÔNG dùng `Pod` trần**, vì `LimitRange techx-limits` sẽ tự điền default hợp lệ cho Pod trần khiến demo không thể hiện đúng ý policy — xem mục 4.5). Test bằng `kubectl apply --dry-run=server` **trước khi** chuyển Enforce thật, xác nhận từng cái bị đúng policy tương ứng chặn (không phải bị chặn bởi policy khác trùng lúc).
4. **Chuyển 4 `ClusterPolicy` từ `Audit` → `Enforce`, từng cái một**, đúng thứ tự đã định sẵn trong completion plan: `require-resource-requests` → `custom-baseline-security-context` → `disallow-latest-tag` → `require-first-party-image-digest`. Sau mỗi bước: chờ ArgoCD Synced/Healthy, smoke-test storefront (`curl -I` qua `frontend-proxy`), xác nhận không pod nào CrashLoop, rồi mới sang policy tiếp theo. Đây là bước có rủi ro thật (dù đã gần 0 vi phạm) — theo nguyên tắc thận trọng đã dùng xuyên suốt, làm từng bước nhỏ, không dồn 1 lần.
5. **Chạy demo rejection thật** — `kubectl apply` cả 3 manifest âm tính sau khi đã Enforce, chụp lại output bị từ chối làm evidence.
6. **Ký & hoàn thiện ADR `docs/adr/0010-mandate-05-runtime-hardening.md`** — hiện đang "Status: Draft", nội dung còn viết theo hướng "sẽ enforce" (tương lai) chứ chưa phản ánh đúng trạng thái cuối (đã enforce, còn đúng 2 exception thật). Cập nhật lại theo thực tế mới rồi xin chữ ký mentor/reviewer.
7. **Cập nhật lại Jira** (PM-92, PM-101, PM-110, PM-111, PM-112 đang "In Progress", PM-113 "In Review") — nhiều DoD trong số này **đã đạt thật trên cluster** (vd PM-111: `currency`/`llm`/`product-reviews` đã `runAsNonRoot:true` từ lâu; PM-110: coverage đã 95.1% ≥ 80%) nhưng Jira chưa ghi nhận — nên comment kèm bằng chứng lệnh verify (mục 6 bên dưới), tránh báo cáo tình trạng cũ.
8. **(Sau khi xong 1-7, không gấp)** PM-114 — viết 2 `ClusterPolicy` Cosign verifyImages + external allow-list, ở chế độ Audit trước, theo đúng DoD đã ghi trong Jira.

---

## 6. Lệnh verify cho từng phần — dùng để tự kiểm tra lại bất cứ lúc nào

### 6.0. Điều kiện tiên quyết mỗi lần verify
```sh
kubectl get ns techx-tf3   # phải ra Active; nếu timeout xem PHASE3-AGENT-HANDOFF.md mục 7
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com   # cần cho bước cosign verify
```

### 6.1. Yêu cầu #1 — không container chạy root
```sh
kubectl get pods -n techx-tf3 -o json > /tmp/allpods.json
python3 - << 'EOF'
import json
pods = json.load(open('/tmp/allpods.json'))
total=0; ok=0; bad=[]
for p in pods['items']:
    pod_sc = p['spec'].get('securityContext') or {}
    pod_seccomp = (pod_sc.get('seccompProfile') or {}).get('type')
    for c in p['spec'].get('containers',[]) + p['spec'].get('initContainers',[]):
        sc = c.get('securityContext') or {}
        total += 1
        ape = sc.get('allowPrivilegeEscalation')
        caps = (sc.get('capabilities') or {}).get('drop', [])
        seccomp = (sc.get('seccompProfile') or {}).get('type') or pod_seccomp
        if ape is False and 'ALL' in caps and seccomp == 'RuntimeDefault':
            ok += 1
        else:
            bad.append((p['metadata']['name'], c['name']))
print(f"{ok}/{total} = {ok/total*100:.1f}% dat baseline (muc tieu DoD PM-92/110: >=80%)")
print("Con thieu:", bad)
EOF
```

### 6.2. Yêu cầu #2 — không image trôi, pin digest
```sh
# Không còn image nào dùng :latest hoặc thiếu digest/tag cố định
kubectl get pods -n techx-tf3 -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' | sort -u | grep -E ':latest$|^[^@:]+$' && echo "CO VI PHAM" || echo "OK — khong co :latest"

# Đếm image first-party ECR có digest hợp lệ
kubectl get pods -n techx-tf3 -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' \
  | grep '197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp' | grep -c '@sha256:'
```

### 6.3. Yêu cầu #3 — resource requests/limits

```

kubectl get pods -n techx-tf3 -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range .spec.containers[*]}{"  "}{.name}{"  req.cpu="}{.resources.requests.cpu}{"  req.mem="}{.resources.requests.memory}{"  lim.cpu="}{.resources.limits.cpu}{"  lim.mem="}{.resources.limits.memory}{"\n"}{end}{end}'

```

```sh
kubectl get policyreports -A -o json | python3 -c "
import json, sys
r = json.load(sys.stdin)
fails = [x for x in r['items'] for res in x.get('results',[]) if res.get('policy')=='require-resource-requests' and res.get('result')=='fail']
print('FAIL count:', len(fails))
"
```
(Nhớ đối chiếu report với pod đang sống — xem cạm bẫy ReplicaSet cũ ở `docs/mandate-05-kyverno-audit-fail-remediation.md`.)

### 6.4. Yêu cầu #4 — Enforce tại admission (mục tiêu cuối)
```sh
# Trạng thái hiện tại của từng policy — PHẢI ra Enforce hết trước khi coi mandate xong
kubectl get clusterpolicy -o jsonpath='{range .items[*]}{.metadata.name}{"  action="}{.spec.validationFailureAction}{"  ready="}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'

# Demo rejection thật (chạy SAU khi đã Enforce) — 3 lệnh này PHẢI bị từ chối
kubectl apply --dry-run=server -f bad-root.yaml
kubectl apply --dry-run=server -f bad-latest-image.yaml
kubectl apply --dry-run=server -f bad-missing-resources.yaml
```

### 6.5. Cosign — verify chữ ký toàn bộ digest first-party đang chạy
```sh
kubectl get pods -n techx-tf3 -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' \
  | grep 'techx-corp@sha256:' | sort -u | while read -r img; do
    cosign verify --certificate-identity-regexp="https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel" \
      --certificate-oidc-issuer="https://token.actions.githubusercontent.com" "$img" >/dev/null 2>&1 \
      && echo "PASS $img" || echo "FAIL $img"
  done
```

### 6.6. PolicyReport — cách lọc đúng, tránh bẫy ReplicaSet cũ (đã gặp phải, ghi lại để không lặp lại)
```sh
kubectl get pods -A -o json > /tmp/allpods.json
kubectl get policyreports -A -o json > /tmp/policyreports.json
python3 - << 'EOF'
import json
pods = json.load(open('/tmp/allpods.json'))
reports = json.load(open('/tmp/policyreports.json'))
live = {(p['metadata']['namespace'], p['metadata']['name']) for p in pods['items']}
for r in reports['items']:
    s = r.get('scope', {})
    if s.get('kind') != 'Pod' or (s.get('namespace'), s.get('name')) not in live:
        continue
    for res in r.get('results', []):
        if res.get('result') == 'fail':
            print(s['namespace'], s['name'], res.get('policy'), res.get('rule'))
EOF
```

---

## 7. Ghi chú dọn dẹp đã làm trong lúc điều tra (18/07)

- Đã xoá pod debug `flagdcheck` (tự tạo hôm 17/07 lúc điều tra flagd/ResolveFloat, dùng ảnh `curlimages/curl:latest`) — pod này đang gây nhiễu số liệu vi phạm (làm tưởng có thêm 1 workload FAIL cả baseline lẫn `disallow-latest-tag`, thật ra chỉ là rác debug của tôi).

---

## 8. [PHÂN TÍCH 19/07] Câu hỏi mở lại của user: 4 policy hiện chỉ áp `techx-tf3` — có nên mở rộng toàn cluster không?

User đặt lại câu hỏi phạm vi: mandate nói "toàn bộ Task Force", không nói chỉ 1 namespace — vậy `custom-baseline-security-context` và `require-resource-requests` có nên áp cho **toàn cluster**, không chỉ `techx-tf3`? Và `disallow-latest-tag`/`require-first-party-image-digest` cũng vậy? Đã quét lại toàn bộ cluster (6 namespace có pod: `techx-tf3`, `kube-system`, `kyverno`, `argocd`, `external-secrets`, `argo-rollouts` — 90 pod, 139 container) để trả lời bằng số liệu thật, không suy đoán.

### 8.1. Trước tiên — 1 chi tiết kỹ thuật quan trọng, quyết định cả câu trả lời

Webhook validate của Kyverno (`kyverno-resource-validating-webhook-cfg`) đã có sẵn `namespaceSelector` loại trừ **`kube-system` và `kyverno`** ở tầng webhook — nghĩa là **dù có sửa `match.resources.namespaces` trong từng `ClusterPolicy` để thêm 2 namespace này, Kyverno cũng sẽ không bao giờ đánh giá resource nào trong đó** (request không tới được webhook). Đây là cơ chế tự bảo vệ chuẩn ngành (tránh Kyverno tự khoá chính nó lúc update, và tránh chặn nhầm add-on lõi của EKS làm sập networking/storage cả cluster) — **nên giữ nguyên**, không nên gỡ.

Vậy câu hỏi "mở rộng toàn cluster" thực chất chỉ có ý nghĩa với 4 namespace còn lại: `techx-tf3` (đã áp), `argocd`, `external-secrets`, `argo-rollouts` — đây là 3 namespace **TF3 tự cài qua GitOps** (`gitops/apps/*.yaml`), không phải add-on EKS quản lý, hoàn toàn sửa được nếu muốn.

### 8.2. Yêu cầu #2 (cấm latest, pin digest) — quét toàn cluster, KHÔNG có vi phạm nào

```sh
kubectl get pods -A -o json | python3 -c "
import json,sys
d=json.load(sys.stdin)
imgs=set()
for p in d['items']:
    for c in p['spec'].get('containers',[])+p['spec'].get('initContainers',[]):
        imgs.add(c['image'])
for i in sorted(imgs): print(i)
" | grep ':latest'
# -> rỗng, 0 ket qua
```

**Danh sách đầy đủ 20 image first-party (ECR `techx-corp`, đều đã pin digest) và 38 image "external" (dùng version từ internet/registry khác) tại thời điểm quét — tất cả đều có tag cố định, không cái nào `:latest`:**

| Loại | Image | Tag/digest hiện tại |
|---|---|---|
| First-party (20 image) | `197826770971.dkr.ecr.../techx-corp@sha256:...` | Tất cả đều `@sha256:` — đạt |
| AIO02 (khác ECR repo, cùng account) | `197826770971.dkr.ecr.../tf-2-ai-engine:IF-v22` | Tag cố định `IF-v22` — đạt yêu cầu "không latest", nhưng **nằm ngoài phạm vi regex của `require-first-party-image-digest`** (chỉ match repo `techx-corp`) nên không bị bắt buộc digest — đúng ý PM-114 đã note trước đó |
| EKS add-on (AWS quản lý, 8 image) | `602401143452.dkr.ecr.../{amazon-k8s-cni,amazon-k8s-cni-init,aws-network-policy-agent,aws-ebs-csi-driver,coredns,csi-attacher,csi-node-driver-registrar,csi-provisioner,csi-resizer,csi-snapshotter,kube-proxy,livenessprobe,metrics-server}` | Tag version cố định kiểu `v1.22.3-eksbuild.1` — đạt |
| Cluster infra khác (10 image) | `aws-load-balancer-controller`, `karpenter/controller` (**đã pin digest luôn**, không chỉ tag), `argo-rollouts`, `argocd`, `dex`, `external-secrets`, `redis` (argocd-redis), `kyverno` ×5 image | Tag cố định hoặc digest — đạt |
| Observability/data (TF3 sở hữu, 9 image) | `flagd`, `jaeger`, `grafana`, `opensearch`, `otel-collector-contrib`, `postgres`, `prometheus`, `k8s-sidecar`, `cloudflared`, `valkey`, `busybox` (2 biến thể, 1 pin digest) | Tag version cố định — đạt |

**Kết luận yêu cầu #2:** dù bật `disallow-latest-tag` cho toàn cluster (trừ `kube-system`/`kyverno` theo mục 8.1), **0 vi phạm thật ngay bây giờ** — an toàn để mở rộng ngay, không cần sửa gì trước. `require-first-party-image-digest` giữ nguyên chỉ nên áp namespace nào có image ECR `techx-corp` thật (hiện chỉ `techx-tf3`) — mở rộng namespace khác cũng không ảnh hưởng gì vì regex tự động không match image không phải `techx-corp`.

### 8.3. Yêu cầu #1 (không root) — quét toàn cluster

| Namespace | Container fail | Ghi chú |
|---|---|---|
| `techx-tf3` | 2 (`aiops-engine`, `kafka`'s `init-kafka-data`) | Đã có exception ghi rõ, không đổi |
| `argocd` | **0** | Toàn bộ container đã đạt `runAsNonRoot`/APE/drop-ALL/seccomp sẵn (chart upstream Argo đã hardening) |
| `external-secrets` | **0** | Tương tự, chart upstream đã hardening sẵn |
| `argo-rollouts` | **0** | Tương tự |
| `kyverno` | **0** (namespace này webhook tự loại trừ, không đánh giá được dù có muốn) | Bản thân Kyverno cũng không chạy root — kiểm tra thủ công cho thấy sạch |
| `kube-system` | **51/53 tổng số fail toàn cluster** | Add-on lõi AWS quản lý (`aws-node`/CNI, `aws-eks-nodeagent`, `kube-proxy`, `ebs-csi-node`) — cần `privileged: true` thật để hoạt động (network namespace, iptables/ipvs, format block device). Đây là ngoại lệ chuẩn ngành cho mọi cluster EKS, không phải gap của TF3. |

**Kết luận yêu cầu #1:** an toàn để mở rộng `custom-baseline-security-context` sang `argocd`/`external-secrets`/`argo-rollouts` **ngay bây giờ, không cần sửa gì** — 0 vi phạm ở cả 3 namespace này. `kube-system` nên tiếp tục loại trừ có chủ đích (ghi vào ADR như exception chuẩn ngành, không phải gap).

### 8.4. Yêu cầu #3 (resource request/limit) — quét toàn cluster, ĐÂY LÀ GAP THẬT nếu mở rộng ngay

Khác 2 mục trên, phần này **có vi phạm thật, cần sửa trước khi mở rộng scope**:

| Namespace | Container fail | Chi tiết thiếu | Sửa được không |
|---|---|---|---|
| `argocd` | **9/9 container** (toàn bộ: `argocd-application-controller`, `argocd-applicationset-controller`, `dex`, `copyutil` ×2, `argocd-notifications-controller`, `redis`, `secret-init`, `argocd-repo-server`, `argocd-server`) | Không khai **bất kỳ field nào** — `resources: {}` hoàn toàn rỗng | ✅ Dễ — TF3 tự quản qua `gitops/apps/argocd-app.yaml` (hoặc tương đương), thêm `resources:` vào values Helm chart ArgoCD |
| `kyverno` | **4/8 container** (4 controller chính: `kyverno-admission-controller`, `kyverno-background-controller`, `kyverno-cleanup-controller`, `kyverno-reports-controller`) | Có `requests.cpu/memory` + `limits.memory`, **thiếu đúng `limits.cpu`** | ✅ Dễ — sửa `gitops/apps/kyverno-app.yaml`, thêm 1 dòng `limits.cpu` mỗi controller |
| `argo-rollouts` | **2/2 container** | Giống Kyverno — có 3/4 field, **thiếu `limits.cpu`** | ✅ Dễ — sửa `gitops/apps/argo-rollouts-app.yaml` |
| `external-secrets` | **0** | Đã đủ 4 field | Không cần sửa |
| `kube-system` | **56 container** (`aws-node`+2 sidecar ×5 node chỉ có `requests.cpu`; `kube-proxy` ×5 chỉ có `requests.cpu`; `coredns` ×2, `ebs-csi-*` ×13 có 3/4 field, thiếu `limits.cpu`; `aws-load-balancer-controller` ×2 rỗng hoàn toàn) | Thiếu 1-4 field tuỳ container | 🟡 Khó hơn — đây là default của EKS managed add-on, sửa qua `aws eks update-addon`/config override riêng, không phải 1 dòng Helm values trong repo này |

**Kết luận yêu cầu #3 — đây là việc thật cần làm nếu muốn mở rộng scope:**
1. **Làm ngay được, ít rủi ro:** thêm `limits.cpu` cho `kyverno` (4 controller) và `argo-rollouts` (1 controller) — chỉ thiếu đúng 1 field, sửa 1 dòng YAML mỗi chỗ.
2. **Cần làm nhưng nhiều hơn 1 chút:** thêm đủ 4 field cho toàn bộ 9 container ArgoCD — trước giờ chưa ai khai gì cả.
3. **Không nên cố sửa qua GitOps repo này:** phần `kube-system` — đây là add-on do EKS quản lý (`aws-node`, `kube-proxy`, `ebs-csi-*`...), sửa sai cách (vd `kubectl edit` trực tiếp DaemonSet) sẽ bị EKS addon-manager tự động ghi đè lại hoặc gây drift ngoài tầm kiểm soát GitOps — nếu muốn siết, phải qua cơ chế `aws eks update-addon --resolve-conflicts` hoặc override chính thức của từng addon, không đơn giản như sửa `values.yaml`. Khuyến nghị: ghi vào ADR như hạng mục riêng (không phải exception vĩnh viễn, mà là "cần làm nhưng khác quy trình", ưu tiên thấp hơn 1-2 vì không ảnh hưởng workload TF3 trực tiếp).

### 8.5. Khuyến nghị tổng hợp

1. **An toàn mở rộng ngay, không cần sửa gì trước:** `custom-baseline-security-context` và `disallow-latest-tag` → thêm `argocd`, `external-secrets`, `argo-rollouts` vào `match.resources.namespaces` — 0 vi phạm thật ở cả 3 namespace này ngay bây giờ.
2. **Cần làm trước khi mở rộng `require-resource-requests`:** thêm `limits.cpu` cho `kyverno`/`argo-rollouts` (nhanh) và đủ 4 field cho toàn bộ ArgoCD (nhiều hơn 1 chút) — rồi mới thêm 3 namespace này vào scope, tránh Enforce xong lại tự chặn ngược chính hạ tầng GitOps/policy-engine của mình.
3. **`kube-system` — giữ nguyên loại trừ ở cả 3 policy trên**, ghi rõ vào ADR 0010 như "exception chuẩn ngành cho add-on lõi EKS", không phải gap của TF3. Riêng phần resource request/limit của `kube-system` có thể ghi thành 1 mục theo dõi riêng (ưu tiên thấp, sửa qua đường EKS addon config, không phải qua policy này).
4. **`require-first-party-image-digest`** không cần đổi gì — bản chất đã tự giới hạn đúng phạm vi qua regex registry/repo, mở namespace nào cũng không ảnh hưởng vì chỉ bắt image thật sự thuộc ECR `techx-corp`.

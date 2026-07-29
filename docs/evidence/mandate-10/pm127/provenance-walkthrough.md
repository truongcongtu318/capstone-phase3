# PM-127 — Truy ngược provenance từ một pod đang chạy

Chứng minh yêu cầu **#3** của Directive #10:

> *"Chỉ vào một pod đang chạy → team truy ngược full provenance"*: image digest → commit → PR reviewer → passing scans → signer → SBOM

Ví dụ dưới đây đi hết chuỗi cho một pod thật, mỗi bước kèm lệnh tự chạy lại được.

---

## Bước 0 — Chọn một pod bất kỳ

```sh
kubectl get pods -n techx-tf3 -l app.kubernetes.io/name=quote \
  -o jsonpath='{range .items[*]}{.metadata.name}{"  "}{.status.containerStatuses[0].imageID}{"\n"}{end}'
```

```
quote-79b77dd947-n6mrq  …/techx-corp@sha256:5035d76864dab66825703705d7c7af5ecccb5842750100bc3b4b0f0fe0bfa696
quote-79b77dd947-zkfmx  …/techx-corp@sha256:5035d76864dab66825703705d7c7af5ecccb5842750100bc3b4b0f0fe0bfa696
```

`image` trong spec và `imageID` thực tế **trùng nhau** — không có tag nào ở giữa để trỏ đi chỗ khác.

---

## Bước 1 — Digest → commit

Commit nằm **trong chính SBOM đã ký**, không phải tra ở nơi khác:

```sh
scripts/ci/get-sbom.sh \
  197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:5035d768… \
  --platform linux/amd64 --metadata | jq -r '.predicate.metadata.properties[]
    | select(.name=="techx.sourceSha") | .value'
```

```
947146d828cf27cee850dd50d3d23a780b396e7a
```

> ⚠️ **Phải dùng Cosign v2.6.2.** Wrapper `get-sbom.sh` tự chặn version sai. Cosign v3 ưu tiên đọc OCI 1.1 referrers do pipeline cũ để lại, chỉ thấy chữ ký cũ ở đó, rồi báo attestation CycloneDX **missing** — dù nó nằm đúng chỗ trong tag legacy mà Kyverno đọc.

```sh
git log -1 947146d828cf27cee850dd50d3d23a780b396e7a
```

```
Merge pull request #500 from tuu-ngo/docs/pm-127-backfill-evidence
author: Vietsory   date: Tue Jul 28 13:23:58 2026 +0700
```

---

## Bước 2 — Commit → PR đã được review

```sh
git log --oneline -S5035d76864dab66825703705d7c7af5ecccb5842750100bc3b4b0f0fe0bfa696 \
  -- 'phase3 - information/deploy/values-prod.yaml'
```

```
edc95cb chore(deploy): bump images from 947146d
```

```sh
gh pr view 502 --json number,title,author,mergedAt,reviews
```

| | |
|---|---|
| PR | **#502** — `chore(deploy): bump quote image to 947146d` |
| Tác giả | `github-actions` (bot, sinh tự động sau build) |
| **Reviewer** | **`ThuyTrang9525`** |
| Merged | 2026-07-28T06:37:53Z |

Digest **không tự vào production được** — phải qua một PR có người duyệt.

---

## Bước 3 — Scan đã pass (chặn, không phải báo cáo suông)

```sh
gh api repos/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30334711133/artifacts
```

| Artifact | Ý nghĩa |
|---|---|
| `trivy-pre-push-30334711133-quote` | Quét **trước khi push** — cổng chặn, HIGH/CRITICAL là dừng |
| `trivy-post-push-30334711133-quote` | Quét lại **trên digest bất biến** đã push, không phải trên tag |
| `signed-release-evidence-30334711133-quote` | Output verify chữ ký + SBOM |
| `approved-image-30334711133-quote` | Manifest digest được duyệt |

Run [`30334711133`](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30334711133) — `success`, 2026-07-28T06:24:38Z. Retention 90 ngày.

---

## Bước 4 — Signer

```sh
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/.github/workflows/build-push-ecr.yml@refs/heads/main' \
  …/techx-corp@sha256:5035d768…
```

| | |
|---|---|
| Issuer | `https://token.actions.githubusercontent.com` |
| Identity | `…/.github/workflows/build-push-ecr.yml@refs/heads/main` |

Keyless — **không có private key nào để rò rỉ**. Chữ ký chỉ tồn tại nếu do đúng workflow đó, chạy trên đúng nhánh `main`, tạo ra. Ký từ laptop cho ra identity khác và **Kyverno từ chối**.

Đây cũng chính là identity mà ClusterPolicy chốt cứng — nên thứ chứng minh ở đây là thứ admission thực sự kiểm.

---

## Bước 5 — SBOM

```sh
scripts/ci/get-sbom.sh …/techx-corp@sha256:5035d768… --platform linux/amd64 --metadata
scripts/ci/get-sbom.sh …/techx-corp@sha256:5035d768… --platform linux/arm64 --metadata
```

| | |
|---|---|
| Format | CycloneDX (`https://cyclonedx.org/bom`) |
| Components | **95** (amd64) — không rỗng |
| Platform | `linux/amd64` và `linux/arm64` đều có SBOM riêng |
| `techx.indexDigest` | khớp digest của pod |
| `techx.subjectDigest` | khớp child digest của platform |
| `techx.sourceSha` | `947146d8…` — khép lại vòng về Bước 1 |

**Một lệnh** cho ra SBOM theo digest — đúng DoD #1.

---

## Chuỗi khép kín

```
pod quote-79b77dd947-n6mrq
  └─ digest  sha256:5035d768…          (imageID, không qua tag)
     └─ commit  947146d8…              (từ SBOM đã ký, không phải tra ngoài)
        └─ PR #502  reviewer ThuyTrang9525
           └─ run 30334711133          Trivy pre-push + post-push pass
              └─ signer  build-push-ecr.yml@refs/heads/main  (keyless)
                 └─ SBOM  CycloneDX, 95 component, 2 platform
```

Mỗi mắt xích **tự kiểm chứng được**, không có bước nào phải tin lời ai.

---

## Điểm cần nói trước khi demo

**Bản backfill ghi `sourceSha` là commit build gốc thật**, không phải commit lúc chạy backfill. Bản đầu tiên ghi sai — nếu để nguyên thì truy vết sẽ dẫn tới một commit **không hề tạo ra image đó**, tức hỏng đúng tiêu chí được chấm. Đã sửa ở PR #498 và truy lại SHA gốc cho cả 20 digest từ các commit promotion (`bump images from <sha>`).

**`quote` là trường hợp duy nhất phải rebuild** thay vì backfill: attestation của nó đã ghi SHA sai và ECR immutable không cho ghi đè `.att` lần hai. Đó là lý do digest hiện tại của nó (`5035d768…`) khác với digest cũ (`445421455…`).

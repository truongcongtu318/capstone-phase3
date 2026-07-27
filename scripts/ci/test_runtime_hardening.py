import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "phase3 - information" / "techx-corp-chart"
VALUES = [
    CHART / "values.yaml",
    REPO / "phase3 - information" / "deploy" / "values-flagd-sync.yaml",
    REPO / "phase3 - information" / "deploy" / "values-prod.yaml",
    REPO / "phase3 - information" / "deploy" / "values-aio-llm.yaml",
]
EXCEPTIONS = REPO / "docs" / "evidence" / "mandate-05" / "exception-register.yaml"
VERIFY = REPO / "scripts" / "ci" / "verify-runtime-hardening.py"


def render_chart_with_dependencies(chart_dir, values):
    with tempfile.TemporaryDirectory() as tmpdir:
        chart_copy = Path(tmpdir) / chart_dir.name
        shutil.copytree(chart_dir, chart_copy)
        subprocess.run(
            ["helm", "dependency", "build", str(chart_copy)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )

        render_result = subprocess.run(
            [
                "helm",
                "template",
                "techx-corp",
                str(chart_copy),
                "--namespace",
                "techx-tf3",
                *sum((["-f", str(path)] for path in values), []),
            ],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
        return render_result.stdout


def test_authoritative_render_is_inventory_clean():
    if shutil.which("helm") is None:
        pytest.skip("helm is required for runtime hardening tests")

    with tempfile.TemporaryDirectory() as tmpdir:
        rendered = Path(tmpdir) / "rendered.yaml"
        inventory = Path(tmpdir) / "inventory.json"

        rendered.write_text(render_chart_with_dependencies(CHART, VALUES), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(VERIFY),
                "--rendered",
                str(rendered),
                "--first-party-repository",
                "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp",
                "--exception-register",
                str(EXCEPTIONS),
                "--mode",
                "inventory",
                "--output",
                str(inventory),
            ],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        data = json.loads(inventory.read_text(encoding="utf-8"))
        assert data["inventoryDelta"] == {"missing": [], "unexpected": []}
        assert data["summary"]["unresolvedFindingCount"] == 0


@pytest.mark.parametrize(
    "image",
    [
        "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp"
        "@sha256:" + "a" * 64,
        "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp"
        ":f5ba80a-30210176908-grafana@sha256:" + "b" * 64,
    ],
)
def test_verifier_accepts_first_party_digest_with_optional_oci_tag(tmp_path, image):
    rendered = tmp_path / "rendered.yaml"
    inventory = tmp_path / "inventory.json"
    rendered.write_text(
        f"""\
apiVersion: v1
kind: Pod
metadata:
  name: grafana-image-reference
  namespace: techx-tf3
  labels:
    app.kubernetes.io/name: grafana
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: grafana
      image: {image}
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: 5m
          memory: 8Mi
        limits:
          cpu: 50m
          memory: 32Mi
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--rendered",
            str(rendered),
            "--mode",
            "inventory",
            "--output",
            str(inventory),
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    data = json.loads(inventory.read_text(encoding="utf-8"))
    assert data["summary"]["unresolvedFindingCount"] == 0


def test_verifier_rejects_first_party_tag_without_digest(tmp_path):
    rendered = tmp_path / "rendered.yaml"
    inventory = tmp_path / "inventory.json"
    rendered.write_text(
        """\
apiVersion: v1
kind: Pod
metadata:
  name: grafana-tag-only
  namespace: techx-tf3
  labels:
    app.kubernetes.io/name: grafana
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: grafana
      image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:mutable
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: 5m
          memory: 8Mi
        limits:
          cpu: 50m
          memory: 32Mi
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--rendered",
            str(rendered),
            "--mode",
            "inventory",
            "--output",
            str(inventory),
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    data = json.loads(inventory.read_text(encoding="utf-8"))
    assert data["summary"]["unresolvedFindingCount"] == 1
    assert data["unresolvedFindings"][0]["rule"] == "require-techx-ecr-sha256-digest"


def test_verifier_honors_container_run_as_non_root_override(tmp_path):
    rendered = tmp_path / "rendered.yaml"
    inventory = tmp_path / "inventory.json"
    rendered.write_text(
        """\
apiVersion: v1
kind: Pod
metadata:
  name: nonroot-container-override
  namespace: techx-tf3
  labels:
    app.kubernetes.io/name: mandate05-test
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: registry.k8s.io/pause:3.10
      securityContext:
        runAsNonRoot: false
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: 5m
          memory: 8Mi
        limits:
          cpu: 50m
          memory: 32Mi
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--rendered",
            str(rendered),
            "--mode",
            "inventory",
            "--output",
            str(inventory),
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    data = json.loads(inventory.read_text(encoding="utf-8"))
    assert data["summary"]["unresolvedFindingCount"] == 1
    assert data["unresolvedFindings"][0]["rule"] == "require-effective-non-root"

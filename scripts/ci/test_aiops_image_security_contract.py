import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRIVYIGNORE = REPO_ROOT / "aiops-engine" / ".trivyignore"
DOCKERFILE = REPO_ROOT / "aiops-engine" / "Dockerfile"
KUBECTL_BUILDER_GO_MOD = REPO_ROOT / "aiops-engine" / "kubectl-builder" / "go.mod"
KUBECTL_BUILDER_MAIN = REPO_ROOT / "aiops-engine" / "kubectl-builder" / "main.go"
DEDICATED_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-push-aiops.yml"
COMMON_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-push-ecr.yml"
COMPOSE_FILE = (
    REPO_ROOT / "phase3 - information" / "techx-corp-platform" / "docker-compose.yml"
)
DOCKERIGNORE = REPO_ROOT / "aiops-engine" / ".dockerignore"


def test_aiops_uses_common_first_party_pipeline_with_raw_manifest_promotion():
    workflow = COMMON_WORKFLOW.read_text()

    assert not DEDICATED_WORKFLOW.exists()
    assert not TRIVYIGNORE.exists()
    assert '- "aiops-engine/**"' in workflow
    assert re.search(r"\bALL_SERVICES:.*?\baiops-engine\b", workflow, re.DOTALL)
    assert len(
        re.findall(
            r'git(?: -C "\$GITHUB_WORKSPACE")? diff --name-only.*?"aiops-engine"',
            workflow,
            re.DOTALL,
        )
    ) == 2
    assert workflow.count('"aiops-engine"|"aiops-engine/"*') == 2
    assert workflow.count("--excluded-service aiops-engine") == 1
    assert '"gitops/aiops-engine/deployment.yaml"' in workflow
    assert '"gitops/aiops-engine/cronjob.yaml"' in workflow
    assert workflow.count(
        'BAKE_ALLOW+=(--allow "fs.read=$GITHUB_WORKSPACE/aiops-engine")'
    ) == 3
    assert (
        "timeout-minutes: "
        "${{ matrix.service == 'aiops-engine' && 90 || 60 }}"
    ) in workflow
    assert "--ignore-unfixed" not in workflow
    assert "--ignorefile" not in workflow
    assert '--severity "$TRIVY_SEVERITIES"' in workflow
    assert "--exit-code 1" in workflow


def test_aiops_bake_target_uses_repository_root_context_and_dockerignore():
    compose = COMPOSE_FILE.read_text()
    assert re.search(
        r"(?ms)^  # AIOps engine\n"
        r"  aiops-engine:\n"
        r"    image: \$\{IMAGE_NAME\}:\$\{DEMO_VERSION\}-aiops-engine\n"
        r"    profiles: \[aiops-build\]\n"
        r"    build:\n"
        r"      context: ../../aiops-engine\n"
        r"      dockerfile: Dockerfile\n"
        r"      cache_from:\n"
        r"        - \$\{IMAGE_NAME\}:\$\{IMAGE_VERSION\}-aiops-engine\n",
        compose,
    )

    ignored = {
        line.strip()
        for line in DOCKERIGNORE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "models/*.joblib" in ignored
    assert "scratch/" in ignored
    assert "venv/" in ignored


def test_dockerfile_builds_patched_stable_kubectl_without_changing_command_surface():
    dockerfile = DOCKERFILE.read_text()
    go_mod = KUBECTL_BUILDER_GO_MOD.read_text()
    builder_main = KUBECTL_BUILDER_MAIN.read_text()

    assert "stable.txt" not in dockerfile
    assert "dl.k8s.io/release" not in dockerfile
    assert re.search(
        r"FROM --platform=\$BUILDPLATFORM "
        r"golang:1\.26\.5@sha256:[0-9a-f]{64} AS kubectl-builder",
        dockerfile,
    )
    assert "ARG TARGETOS TARGETARCH" in dockerfile
    assert 'CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH"' in dockerfile
    assert "GOARCH=amd64" not in dockerfile
    assert "go build -mod=readonly -trimpath" in dockerfile
    assert (
        "COPY --chmod=0755 --from=kubectl-builder "
        "/out/kubectl /usr/local/bin/kubectl"
    ) in dockerfile

    assert "k8s.io/kubectl v0.36.3" in go_mod
    assert "golang.org/x/net v0.57.0" in go_mod
    assert "golang.org/x/text v0.40.0" in go_mod
    assert "go.opentelemetry.io/otel v1.42.0" in go_mod
    assert "k8s.io/component-base/version.gitMajor=1" in dockerfile
    assert "k8s.io/component-base/version.gitMinor=36" in dockerfile
    assert "k8s.io/component-base/version.gitVersion=v1.36.3-aiops.1" in dockerfile
    assert '"k8s.io/kubectl/pkg/cmd"' in builder_main
    assert "cmd.NewDefaultKubectlCommand()" in builder_main


def test_runtime_uses_pinned_alpine_without_python_build_tooling():
    dockerfile = DOCKERFILE.read_text()

    alpine_base = (
        "python:3.10.20-alpine3.23@"
        "sha256:81c5715bb79d8edd45a82de842a29c7d6ef2aff4b7fa88e712f93a93806337df"
    )
    assert f"FROM {alpine_base} AS python-builder" in dockerfile
    assert f"FROM {alpine_base}" in dockerfile
    assert "FROM python:3.10-slim" not in dockerfile
    assert "RUN apk add --no-cache build-base" in dockerfile
    assert "RUN apk add --no-cache libgomp libstdc++" in dockerfile
    assert "RUN python -m pip uninstall -y pip setuptools wheel" in dockerfile
    assert "python -m venv /venv" in dockerfile
    assert "/venv/bin/pip uninstall -y pip setuptools wheel" in dockerfile
    assert "COPY --from=python-builder /venv /venv" in dockerfile
    assert 'ENV PATH="/venv/bin:$PATH"' in dockerfile

import os
import json
import pytest
from pathlib import Path

from ruamel.yaml import YAML

def get_workflows():
    yaml = YAML(typ="safe")
    build = yaml.load(Path(".github/workflows/build-push-ecr.yml").read_text())
    pr = yaml.load(Path(".github/workflows/test-image-bump.yml").read_text())
    return build, pr

def test_t51_actionlint_gate_is_mandatory():
    _, pr = get_workflows()
    steps = pr["jobs"]["validate"]["steps"]

    actionlint_steps = [
        step for step in steps
        if "./actionlint" in step.get("run", "")
    ]

    assert len(actionlint_steps) == 1
    assert "ACTIONLINT_VERSION=1.7.12" in actionlint_steps[0]["run"]
    assert "sha256sum --check --strict" in actionlint_steps[0]["run"]
    assert "./actionlint" in actionlint_steps[0]["run"]

def test_t52_production_service_matrix_jobs():
    build, _ = get_workflows()
    jobs = build.get("jobs", {})
    assert set(jobs.keys()) == {"prepare", "build-scan", "aggregate", "open-image-bump-pr"}
    assert jobs["build-scan"].get("needs") == "prepare"
    assert jobs["aggregate"].get("needs") == ["prepare", "build-scan"]
    assert jobs["open-image-bump-pr"].get("needs") == ["prepare", "aggregate"]
    strategy = jobs["build-scan"]["strategy"]
    assert strategy["fail-fast"] is False
    assert strategy["max-parallel"] == 3
    assert "fromJSON(needs.prepare.outputs.matrix)" in strategy["matrix"]["service"]

def test_t53_permissions_separated():
    build, _ = get_workflows()
    jobs = build.get("jobs", {})
    
    bs_perms = jobs["build-scan"].get("permissions", {})
    assert bs_perms.get("id-token") == "write"
    assert bs_perms.get("contents") == "read"
    assert "pull-requests" not in bs_perms
    
    pr_perms = jobs["open-image-bump-pr"].get("permissions", {})
    assert pr_perms.get("contents") == "write"
    assert pr_perms.get("pull-requests") == "write"
    assert "id-token" not in pr_perms

    aggregate_perms = jobs["aggregate"].get("permissions", {})
    assert aggregate_perms.get("contents") == "read"
    assert "id-token" not in aggregate_perms

def test_t54_artifact_branch_identity():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert "approved-images-${{ github.run_id }}-${{ github.run_attempt }}" in build_raw
    assert "ci/bump-images-${{ github.run_id }}-${{ github.run_attempt }}" in build_raw
    assert "approved-image-${{ github.run_id }}-${{ matrix.service }}" in build_raw
    assert "pattern: approved-image-${{ github.run_id }}-*" in build_raw

def test_t55_publication_fail_closed():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert "git push origin" not in build_raw or "|| true" not in build_raw
    assert "git push --force" not in build_raw
    assert "git commit --amend" not in build_raw
    assert "git push --set-upstream origin \"$BRANCH_NAME\"" in build_raw
    assert "REMOTE_SHA" in build_raw
    assert "gh pr create" in build_raw
    assert "headRefOid" in build_raw

def test_t56_tests_installed_and_run():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert "python -m pip install" in build_raw
    assert "scripts/ci/requirements-image-bump.txt" in build_raw
    assert "python -m pytest" in build_raw

def test_t57_strict_metadata_passed():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert "--expected-source-sha" in build_raw
    assert "--expected-mode" in build_raw
    assert "--expected-registry" in build_raw
    assert "--expected-repository" in build_raw

def test_t58_trivy_contract():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert "v0.72.0" in build_raw
    assert "@${digest}" in build_raw
    build, _ = get_workflows()
    steps = build["jobs"]["build-scan"]["steps"]
    trivy_idx = next((i for i, s in enumerate(steps) if "trivy image" in s.get("run", "")), -1)
    upload_idx = next((i for i, s in enumerate(steps) if "actions/upload-artifact" in s.get("uses", "")), -1)
    assert trivy_idx != -1
    assert upload_idx != -1
    assert trivy_idx < upload_idx

def test_t59_validation_workflow_security():
    _, pr = get_workflows()
    on_block = pr.get("on") or pr.get(True)
    assert on_block.get("pull_request") is not None
    assert pr.get("permissions", {}).get("contents") == "read"
    assert pr.get("permissions", {}).get("id-token") is None

def test_t60_shell_git_safety():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert "set -euo pipefail" in build_raw
    assert "git push -f" not in build_raw
    assert "git rebase" not in build_raw


def test_t61_preserves_all_security_evidence_gates_per_service():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    required_markers = [
        "Smoke build checkout",
        "Build local image candidates for the Trivy gate",
        "Scan local image candidates with Trivy (blocking pre-push gate)",
        "Upload pre-push Trivy reports",
        "Scan pushed immutable images with Trivy (blocking post-push gate)",
        "Upload post-push Trivy reports",
        "Sign and verify approved image digests with keyless Cosign",
        "signed-images.jsonl",
        "Upload signed release evidence",
        "final image tag exceeds 128 characters",
        "invalid media type",
        "manifestMediaType",
        "## Safety checks",
    ]
    for marker in required_markers:
        assert marker in build_raw

    assert "SERVICE: ${{ matrix.service }}" in build_raw
    assert 'docker buildx bake -f docker-compose.yml --push "$SERVICE"' in build_raw
    assert '"${SERVICES[@]}"' not in build_raw
    assert '--set "*.platform=' not in build_raw


def test_t62_aggregate_is_fail_closed_for_exact_expected_services():
    build, _ = get_workflows()
    raw = "\n".join(step.get("run", "") for step in build["jobs"]["aggregate"]["steps"])
    assert "missing or unexpected service evidence" in raw
    assert "duplicate service evidence" in raw
    assert 'test("^sha256:[0-9a-f]{64}$")' in raw
    assert "manifestMediaType" in raw


def test_t63_scoped_canary_and_promotion_evidence_contract():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert 'services:' in build_raw
    assert "INPUT_SERVICES" in build_raw
    assert "unknown production service" in build_raw
    assert "promotion-evidence-${{ github.run_id }}-${{ github.run_attempt }}" in build_raw
    assert "retention-days: 90" in build_raw

def test_t64_grafana_is_registered_as_scoped_production_service():
    build_raw = Path(".github/workflows/build-push-ecr.yml").read_text()
    assert "frontend-proxy grafana image-provider" in build_raw
    assert 'PLATFORM_ROOT="phase3 - information/techx-corp-platform"' in build_raw
    assert 'grep -Fq "# Grafana" <<< "$COMPOSE_DIFF"' in build_raw
    assert "GRAFANA_[A-Za-z0-9_]+=" in build_raw

def test_t65_grafana_dockerfile_is_in_immutable_scope_registry():
    registry = json.loads(Path("scripts/ci/dockerfile-scope.json").read_text())
    entries = [
        item for item in registry["dockerfiles"]
        if item["owner"] == "grafana"
    ]
    assert entries == [{
        "path": "phase3 - information/techx-corp-platform/src/grafana/Dockerfile",
        "classification": "production",
        "owner": "grafana",
        "inScope": True,
        "expectedPlatforms": ["linux/amd64", "linux/arm64"],
    }]

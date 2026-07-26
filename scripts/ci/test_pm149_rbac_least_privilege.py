"""PM-149 render contracts for Grafana RBAC and ServiceAccount token hardening."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "phase3 - information" / "techx-corp-chart"
VALUES = [
    CHART / "values.yaml",
    REPO / "phase3 - information" / "deploy" / "values-flagd-sync.yaml",
    REPO / "phase3 - information" / "deploy" / "values-prod.yaml",
    REPO / "phase3 - information" / "deploy" / "values-aio-llm.yaml",
]
NAMESPACE = "techx-tf3"
SHARED_SERVICE_ACCOUNT = "techx-corp"
COMPONENT_SCOPED_SERVICE_ACCOUNT = "product-reviews-bedrock"
GRAFANA_AUTH_MARKERS = (
    "grafana.ini",
    "auth.anonymous",
    "admin.existingSecret",
    "admin.userKey",
    "admin.passwordKey",
)


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def render_chart_with_dependencies() -> str:
    if shutil.which("helm") is None:
        pytest.skip("helm is required for PM-149 authoritative render tests")

    with tempfile.TemporaryDirectory() as tmpdir:
        chart_copy = Path(tmpdir) / CHART.name
        shutil.copytree(CHART, chart_copy)
        subprocess.run(
            ["helm", "dependency", "build", str(chart_copy)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
        command = [
            "helm",
            "template",
            "techx-corp",
            str(chart_copy),
            "--namespace",
            NAMESPACE,
        ]
        for values_file in VALUES:
            command.extend(["-f", str(values_file)])
        result = subprocess.run(
            command,
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout


def assert_invalid_automount_value_is_rejected() -> None:
    if shutil.which("helm") is None:
        pytest.skip("helm is required for schema validation tests")

    with tempfile.TemporaryDirectory() as tmpdir:
        chart_copy = Path(tmpdir) / CHART.name
        invalid_values = Path(tmpdir) / "invalid.yaml"
        shutil.copytree(CHART, chart_copy)
        invalid_values.write_text(
            "serviceAccount:\n  automountServiceAccountToken: \"false\"\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["helm", "dependency", "build", str(chart_copy)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            [
                "helm",
                "template",
                "techx-corp",
                str(chart_copy),
                "--namespace",
                NAMESPACE,
                "-f",
                str(chart_copy / "values.yaml"),
                "-f",
                str(invalid_values),
            ],
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "automountServiceAccountToken" in (
            result.stdout + result.stderr
        )


def rendered_documents(rendered: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict) and document.get("kind")
    ]


def workload_documents(documents: list[dict]) -> list[dict]:
    return [
        document
        for document in documents
        if isinstance(document.get("spec"), dict)
        and isinstance(document["spec"].get("template"), dict)
        and isinstance(document["spec"]["template"].get("spec"), dict)
    ]


def metadata(document: dict) -> dict:
    return document.get("metadata", {})


def is_grafana_resource(document: dict) -> bool:
    labels = metadata(document).get("labels", {})
    name = metadata(document).get("name", "")
    return (
        labels.get("app.kubernetes.io/name") == "grafana"
        or name.startswith("grafana")
    )


def test_service_account_schema_declares_boolean_automount():
    schema = json.loads(
        (CHART / "values.schema.json").read_text(encoding="utf-8")
    )
    service_account = schema["definitions"]["ServiceAccountConfig"]
    assert service_account["additionalProperties"] is False
    assert service_account["properties"]["automountServiceAccountToken"] == {
        "type": "boolean"
    }


def test_global_values_enable_namespaced_grafana_rbac_and_token_hardening():
    values = load_yaml(CHART / "values.yaml")
    assert values["serviceAccount"]["automountServiceAccountToken"] is False
    assert values["grafana"]["rbac"] == {"create": True, "namespaced": True}


def test_schema_rejects_string_automount_value():
    assert_invalid_automount_value_is_rejected()


def test_templates_guard_component_scoped_service_accounts():
    service_account_template = (
        CHART / "templates" / "serviceaccount.yaml"
    ).read_text(encoding="utf-8")
    objects_template = (CHART / "templates" / "_objects.tpl").read_text(
        encoding="utf-8"
    )
    assert "automountServiceAccountToken" in service_account_template
    assert "automountServiceAccountToken" in objects_template
    assert "not .componentScopedServiceAccount" in objects_template
    assert "serviceAccountName: {{ include" in objects_template


def test_component_scoped_irsa_values_are_preserved():
    aio_values = load_yaml(
        REPO / "phase3 - information" / "deploy" / "values-aio-llm.yaml"
    )
    product_reviews = aio_values["components"]["product-reviews"]
    service_account = product_reviews["serviceAccount"]
    assert service_account["name"] == COMPONENT_SCOPED_SERVICE_ACCOUNT
    assert service_account["annotations"][
        "eks.amazonaws.com/role-arn"
    ].endswith("techx-corp-tf3-product-reviews-bedrock")


def test_authoritative_render_sets_global_service_account_automount():
    documents = rendered_documents(render_chart_with_dependencies())
    service_accounts = [
        document
        for document in documents
        if document.get("kind") == "ServiceAccount"
        and metadata(document).get("name") == SHARED_SERVICE_ACCOUNT
    ]

    assert len(service_accounts) == 1
    assert service_accounts[0]["automountServiceAccountToken"] is False
    assert "automountServiceAccountToken" not in service_accounts[0]["metadata"]


def test_authoritative_render_has_no_shared_sa_workload_without_false():
    documents = rendered_documents(render_chart_with_dependencies())
    targets = []
    failures = []
    for document in workload_documents(documents):
        pod_spec = document["spec"]["template"]["spec"]
        if pod_spec.get("serviceAccountName") != SHARED_SERVICE_ACCOUNT:
            continue
        name = metadata(document).get("name", "<unnamed>")
        targets.append(name)
        if pod_spec.get("automountServiceAccountToken") is not False:
            failures.append((name, pod_spec.get("automountServiceAccountToken")))

    assert targets, "render must contain at least one shared-SA workload"
    assert not failures, f"shared-SA automount violations: {failures}"


def test_authoritative_render_preserves_product_reviews_irsa():
    documents = rendered_documents(render_chart_with_dependencies())
    product_reviews = [
        document
        for document in workload_documents(documents)
        if metadata(document).get("name") == "product-reviews"
    ]
    assert len(product_reviews) == 1
    pod_spec = product_reviews[0]["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == COMPONENT_SCOPED_SERVICE_ACCOUNT

    service_accounts = [
        document
        for document in documents
        if document.get("kind") == "ServiceAccount"
        and metadata(document).get("name") == COMPONENT_SCOPED_SERVICE_ACCOUNT
    ]
    assert len(service_accounts) == 1
    assert (
        service_accounts[0]["metadata"]["annotations"][
            "eks.amazonaws.com/role-arn"
        ].endswith("techx-corp-tf3-product-reviews-bedrock")
    )


def test_authoritative_render_has_namespaced_grafana_rbac_only():
    documents = rendered_documents(render_chart_with_dependencies())
    grafana_roles = [
        document
        for document in documents
        if document.get("kind") in {"Role", "ClusterRole"}
        and is_grafana_resource(document)
    ]
    grafana_bindings = [
        document
        for document in documents
        if document.get("kind") in {"RoleBinding", "ClusterRoleBinding"}
        and is_grafana_resource(document)
    ]

    roles = [document for document in grafana_roles if document["kind"] == "Role"]
    bindings = [
        document for document in grafana_bindings if document["kind"] == "RoleBinding"
    ]
    assert roles, "Grafana must render a namespace-local Role"
    assert bindings, "Grafana must render a namespace-local RoleBinding"
    assert not [
        document
        for document in grafana_roles
        if document["kind"] == "ClusterRole"
    ]
    assert not [
        document
        for document in grafana_bindings
        if document["kind"] == "ClusterRoleBinding"
    ]

    for role in roles:
        assert metadata(role)["namespace"] == NAMESPACE
        for rule in role.get("rules", []):
            assert "*" not in rule.get("resources", [])
            assert "*" not in rule.get("verbs", [])
            assert not rule.get("nonResourceURLs")
            assert set(rule.get("resources", [])) <= {"configmaps", "secrets"}
            assert set(rule.get("verbs", [])) <= {"get", "list", "watch"}

    for binding in bindings:
        assert metadata(binding)["namespace"] == NAMESPACE
        assert binding["roleRef"]["kind"] == "Role"
        assert any(
            subject.get("kind") == "ServiceAccount"
            and subject.get("name") == "grafana"
            and subject.get("namespace") == NAMESPACE
            for subject in binding.get("subjects", [])
        )


def test_pm149_diff_does_not_touch_flagd_or_unrelated_infrastructure():
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "origin/main...HEAD",
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }
    allowed = {
        "phase3 - information/techx-corp-chart/values.yaml",
        "phase3 - information/techx-corp-chart/values.schema.json",
        "phase3 - information/techx-corp-chart/templates/serviceaccount.yaml",
        "phase3 - information/techx-corp-chart/templates/_objects.tpl",
        "scripts/ci/test_pm149_rbac_least_privilege.py",
        "docs/evidence/mandate-17/pm-149-rbac-least-privilege.md",
    }
    # PM-149 content files (excluding the test itself and docs).
    # Only enforce scope guard when the PR is actually a PM-149 content PR.
    # Updating only the test file or CI infra does not constitute a PM-149 PR.
    pm149_content = allowed - {
        "scripts/ci/test_pm149_rbac_least_privilege.py",
    }
    if not (changed & pm149_content):
        pytest.skip("No PM-149 content files changed; scope guard not applicable to this PR")
    assert changed <= allowed
    assert not any("flagd" in path.lower() for path in changed)
    assert not any(
        marker in "\n".join(changed)
        for marker in ("terraform", "network-policy", "secrets/")
    )


def test_pm149_diff_preserves_existing_grafana_auth_markers():
    result = subprocess.run(
        [
            "git",
            "diff",
            "origin/main...HEAD",
            "--",
            "phase3 - information/techx-corp-chart/values.yaml",
            "phase3 - information/deploy/values-prod.yaml",
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    # Skip if neither Grafana values file was touched by this PR.
    if not result.stdout.strip():
        pytest.skip("No changes to Grafana values files; auth marker guard not applicable")
    deleted_lines = [
        line[1:]
        for line in result.stdout.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    for marker in GRAFANA_AUTH_MARKERS:
        assert not any(marker in line for line in deleted_lines)

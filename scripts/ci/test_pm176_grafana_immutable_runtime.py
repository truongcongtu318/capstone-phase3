import re
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
SMOKE = REPO / "scripts" / "pm-176-grafana-smoke.sh"
PLUGIN_PATH = "/opt/grafana/plugins"
PLUGIN_SETTINGS = {
    "preinstall_disabled": True,
    "preinstall_auto_update": False,
    "plugin_admin_enabled": False,
    "plugin_admin_external_manage_enabled": False,
}
IMAGE_RE = re.compile(
    r"^197826770971\.dkr\.ecr\.ap-southeast-1\.amazonaws\.com/"
    r"techx-corp:[A-Za-z0-9_.-]+-grafana@sha256:[0-9a-f]{64}$"
)


def render_production() -> list[dict]:
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
        values = [chart_copy / "values.yaml", *VALUES[1:]]
        result = subprocess.run(
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
        return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def named_document(documents: list[dict], kind: str, name: str) -> dict:
    return next(
        doc
        for doc in documents
        if doc.get("kind") == kind
        and (doc.get("metadata") or {}).get("name") == name
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is required")
def test_pm176_render_uses_baked_plugin_without_runtime_installer():
    documents = render_production()
    deployment = named_document(documents, "Deployment", "grafana")
    pod_spec = deployment["spec"]["template"]["spec"]
    containers = {
        container["name"]: container for container in pod_spec["containers"]
    }
    grafana = containers["grafana"]

    assert IMAGE_RE.fullmatch(grafana["image"])
    plugin_path_env = [
        item for item in grafana["env"] if item["name"] == "GF_PATHS_PLUGINS"
    ]
    assert plugin_path_env == [
        {"name": "GF_PATHS_PLUGINS", "value": PLUGIN_PATH}
    ]
    assert not any(
        item["name"].startswith("GF_PLUGINS_PREINSTALL")
        for item in grafana["env"]
    )

    all_containers = [
        *pod_spec.get("initContainers", []),
        *pod_spec["containers"],
    ]
    startup_text = " ".join(
        str(value)
        for container in all_containers
        for key in ("command", "args")
        for value in container.get(key, [])
    )
    assert "grafana-opensearch-datasource" not in startup_text
    assert "plugins install" not in startup_text

    assert {
        "grafana-sc-alerts",
        "grafana-sc-dashboard",
        "grafana-sc-datasources",
    }.issubset(containers)
    security_context = grafana["securityContext"]
    assert security_context["runAsNonRoot"] is True
    assert security_context["allowPrivilegeEscalation"] is False
    assert security_context["capabilities"]["drop"] == ["ALL"]
    assert security_context["seccompProfile"]["type"] == "RuntimeDefault"

    configmap = named_document(documents, "ConfigMap", "grafana")
    grafana_ini = configmap["data"]["grafana.ini"]
    assert "[paths]" in grafana_ini
    assert f"plugins = {PLUGIN_PATH}" in grafana_ini
    assert "[analytics]" in grafana_ini
    assert "check_for_updates = false" in grafana_ini
    assert "reporting_enabled = false" in grafana_ini
    assert "[plugins]" in grafana_ini
    for key, value in PLUGIN_SETTINGS.items():
        assert f"{key} = {str(value).lower()}" in grafana_ini


def test_pm176_base_values_do_not_declare_runtime_plugins():
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    grafana = values["grafana"]

    assert "plugins" not in grafana
    assert grafana["grafana.ini"]["paths"]["plugins"] == PLUGIN_PATH
    assert grafana["grafana.ini"]["analytics"] == {
        "check_for_updates": False,
        "reporting_enabled": False,
    }
    assert grafana["grafana.ini"]["plugins"] == PLUGIN_SETTINGS


def test_pm176_smoke_script_is_read_only_and_syntax_valid():
    script = SMOKE.read_text(encoding="utf-8")
    assert shutil.which("bash") is not None
    subprocess.run(["bash", "-n", str(SMOKE)], cwd=REPO, check=True)
    for forbidden in ("kubectl apply", "kubectl patch", "kubectl delete", "kubectl rollout"):
        assert forbidden not in script
    for required in (
        "GF_PATHS_PLUGINS",
        "preinstall_disabled = true",
        "failed to install plugin",
        "modified signature",
        "plugin validation failed",
        "grafana-opensearch-datasource/plugin.json",
        "/api/datasources/uid/webstore-logs",
        "EXPECT_EGRESS_BLOCK",
        "kubectl port-forward",
    ):
        assert required in script

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "phase3 - information" / "deploy"
CHART = REPO / "phase3 - information" / "techx-corp-chart"


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_wave_1_remains_in_the_cumulative_migration():
    values = load_yaml(DEPLOY / "values-serviceaccounts.yaml")
    wave_1 = {
        "image-provider",
        "ad",
        "recommendation",
    }
    assert wave_1.issubset(values["components"])


def test_wave_1_service_accounts_are_dedicated_and_tokenless():
    values = load_yaml(DEPLOY / "values-serviceaccounts.yaml")
    for component, config in values["components"].items():
        service_account = config["serviceAccount"]
        assert service_account == {
            "create": True,
            "name": f"techx-{component}",
            "annotations": {},
            "automountServiceAccountToken": False,
        }


def test_no_migrated_component_uses_the_shared_service_account():
    values = load_yaml(DEPLOY / "values-serviceaccounts.yaml")
    for config in values["components"].values():
        assert config["serviceAccount"]["name"] != "techx-corp"


def test_all_migrated_service_account_names_are_unique():
    values = load_yaml(DEPLOY / "values-serviceaccounts.yaml")
    names = [
        config["serviceAccount"]["name"]
        for config in values["components"].values()
    ]
    assert len(names) == len(set(names))


def test_retired_components_and_existing_irsa_are_not_overridden():
    migration = load_yaml(DEPLOY / "values-serviceaccounts.yaml")["components"]
    assert not {"kafka", "postgresql", "valkey-cart"} & set(migration)
    assert "product-reviews" not in migration

    aio = load_yaml(DEPLOY / "values-aio-llm.yaml")
    service_account = aio["components"]["product-reviews"]["serviceAccount"]
    assert service_account["name"] == "product-reviews-bedrock"
    assert service_account["annotations"][
        "eks.amazonaws.com/role-arn"
    ].endswith("techx-corp-tf3-product-reviews-bedrock")


def test_argocd_activates_only_the_cumulative_reviewed_wave_file():
    application = load_yaml(REPO / "gitops" / "apps" / "techx-corp.yaml")
    value_files = application["spec"]["source"]["helm"]["valueFiles"]
    service_account_files = [
        value_file for value_file in value_files if "serviceaccounts" in value_file
    ]
    assert service_account_files == ["../deploy/values-serviceaccounts.yaml"]


def test_cloudflared_has_a_dedicated_tokenless_identity_and_safe_rollout():
    documents = list(
        yaml.safe_load_all(
            (REPO / "gitops" / "infrastructure" / "cloudflared.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    service_account = next(
        document for document in documents if document["kind"] == "ServiceAccount"
    )
    deployment = next(
        document for document in documents if document["kind"] == "Deployment"
    )
    assert service_account["metadata"]["name"] == "cloudflared"
    assert service_account["automountServiceAccountToken"] is False

    pod_spec = deployment["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "cloudflared"
    assert pod_spec["automountServiceAccountToken"] is False
    rolling = deployment["spec"]["strategy"]["rollingUpdate"]
    assert rolling == {"maxUnavailable": 0, "maxSurge": 1}


def test_opensearch_stays_tokenless_without_unnecessary_rbac():
    values = load_yaml(CHART / "values.yaml")["opensearch"]
    assert values["rbac"]["create"] is False
    assert values["rbac"]["automountServiceAccountToken"] is False


def test_checkout_verifier_targets_the_real_rollout_name():
    script = (REPO / "scripts" / "verify-sa-migration.sh").read_text(
        encoding="utf-8"
    )
    assert 'ROLLOUT_NAME="${SERVICE}-rollout"' in script
    assert 'kubectl get rollout "${ROLLOUT_NAME}"' in script
    assert 'patch rollout ${ROLLOUT_NAME}' in script
    assert 'kubectl get rollout "${SERVICE}"' not in script


def test_verifier_captures_authorization_and_denies_representative_privileges():
    script = (REPO / "scripts" / "verify-sa-migration.sh").read_text(
        encoding="utf-8"
    )
    assert 'kubectl auth can-i --list --as="${SA_SUBJECT}"' in script
    for check in (
        '"get pods"',
        '"get secrets"',
        '"list secrets"',
        '"patch deployments.apps"',
        '"create pods/exec"',
    ):
        assert check in script

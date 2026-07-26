from pathlib import Path

import yaml


RBAC_PATH = Path("gitops/infrastructure/rbac-production-access.yaml")


def documents():
    return [doc for doc in yaml.safe_load_all(RBAC_PATH.read_text()) if doc]


def rules_for(role_name, namespace=None, kind="Role"):
    role = next(
        doc
        for doc in documents()
        if doc["kind"] == kind and doc["metadata"]["name"] == role_name
        and (
            namespace is None
            or doc["metadata"].get("namespace") == namespace
        )
    )
    return role["rules"]


def granted(role_name, resource, verb, namespace=None, api_group=None):
    return any(
        resource in rule.get("resources", []) and verb in rule.get("verbs", [])
        and (api_group is None or api_group in rule.get("apiGroups", []))
        for rule in rules_for(role_name, namespace)
    )


def test_operator_excludes_security_sensitive_mutation():
    for resource in (
        "secrets",
        "networkpolicies",
        "persistentvolumeclaims",
        "roles",
        "rolebindings",
        "statefulsets",
    ):
        assert not granted("tf3-production-operator", resource, "create")
        assert not granted("tf3-production-operator", resource, "patch")
        assert not granted("tf3-production-operator", resource, "delete")
    assert not granted("tf3-production-operator", "pods/exec", "create")


def test_namespaced_reader_has_no_mutation_secret_or_exec_access():
    allowed_create_resources = {
        ("", "pods/portforward"),
        ("authorization.k8s.io", "localsubjectaccessreviews"),
    }
    for rule in rules_for("tf3-production-readonly"):
        assert set(rule["verbs"]) <= {"get", "list", "watch", "create"}
        if "create" in rule["verbs"]:
            assert {
                (api_group, resource)
                for api_group in rule["apiGroups"]
                for resource in rule["resources"]
            } <= allowed_create_resources
    assert not granted("tf3-production-readonly", "secrets", "get")
    assert not granted("tf3-production-readonly", "pods/exec", "create")


def test_reader_can_review_grafana_rbac_without_impersonation():
    assert granted(
        "tf3-production-readonly",
        "localsubjectaccessreviews",
        "create",
        namespace="techx-tf3",
        api_group="authorization.k8s.io",
    )
    for resource in ("roles", "rolebindings"):
        assert granted(
            "tf3-production-readonly",
            resource,
            "get",
            namespace="techx-tf3",
            api_group="rbac.authorization.k8s.io",
        )
        assert granted(
            "tf3-production-readonly",
            resource,
            "list",
            namespace="techx-tf3",
            api_group="rbac.authorization.k8s.io",
        )

    cluster_rules = rules_for(
        "tf3-production-readonly-cluster-extensions",
        kind="ClusterRole",
    )
    for resource in ("clusterroles", "clusterrolebindings"):
        assert any(
            rule["apiGroups"] == ["rbac.authorization.k8s.io"]
            and resource in rule["resources"]
            and set(rule["verbs"]) == {"get", "list"}
            for rule in cluster_rules
        )

    argocd_rules = rules_for(
        "tf3-production-readonly-observability",
        namespace="argocd",
    )
    assert not any(
        resource in rule.get("resources", [])
        for rule in argocd_rules
        for resource in (
            "localsubjectaccessreviews",
            "roles",
            "rolebindings",
        )
    )
    assert not any(
        resource in rule.get("resources", [])
        for rule in cluster_rules
        for resource in (
            "localsubjectaccessreviews",
            "roles",
            "rolebindings",
        )
    )


def test_reader_custom_roles_keep_security_boundaries():
    reader_rules = (
        rules_for("tf3-production-readonly", namespace="techx-tf3")
        + rules_for("tf3-production-readonly-observability", namespace="argocd")
        + rules_for(
            "tf3-production-readonly-cluster-extensions",
            kind="ClusterRole",
        )
    )
    assert not any(
        "secrets" in rule.get("resources", [])
        or "pods/exec" in rule.get("resources", [])
        or "impersonate" in rule.get("verbs", [])
        for rule in reader_rules
    )


def test_bindings_target_expected_groups_and_namespace():
    docs = documents()
    assert all(
        doc["metadata"].get("namespace") in {"techx-tf3", "argocd"}
        for doc in docs
        if doc["kind"] in {"Role", "RoleBinding"}
    )
    bindings = {
        (doc["metadata"]["namespace"], doc["metadata"]["name"]): doc
        for doc in docs
        if doc["kind"] == "RoleBinding"
    }
    assert (
        bindings[("techx-tf3", "tf3-production-operator")]["subjects"][0]["name"]
        == "tf3-production-operators"
    )
    assert (
        bindings[("techx-tf3", "tf3-production-readonly")]["subjects"][0]["name"]
        == "tf3-production-readers"
    )
    assert (
        bindings[("argocd", "tf3-production-readonly-observability")]["subjects"][0]["name"]
        == "tf3-production-readers"
    )


def test_reader_has_cluster_view_and_read_only_operational_extensions():
    bindings = {
        doc["metadata"]["name"]: doc
        for doc in documents()
        if doc["kind"] == "ClusterRoleBinding"
    }
    view_binding = bindings["tf3-production-readonly-cluster-view"]
    assert view_binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "view",
    }
    assert view_binding["subjects"][0]["name"] == "tf3-production-readers"

    extension_binding = bindings["tf3-production-readonly-cluster-extensions"]
    assert extension_binding["subjects"][0]["name"] == "tf3-production-readers"
    assert extension_binding["roleRef"]["name"] == "tf3-production-readonly-cluster-extensions"

    rules = rules_for(
        "tf3-production-readonly-cluster-extensions",
        kind="ClusterRole",
    )
    assert all(set(rule["verbs"]) <= {"get", "list", "watch"} for rule in rules)
    assert any(
        rule["apiGroups"] == [""]
        and "nodes" in rule["resources"]
        and "get" in rule["verbs"]
        for rule in rules
    )
    assert any(
        rule["apiGroups"] == ["argoproj.io"]
        and "applications" in rule["resources"]
        and "get" in rule["verbs"]
        for rule in rules
    )
    assert any(
        rule["apiGroups"] == ["networking.k8s.aws"]
        and "policyendpoints" in rule["resources"]
        and "list" in rule["verbs"]
        for rule in rules
    )
    assert not any(
        "secrets" in rule.get("resources", [])
        or "pods/exec" in rule.get("resources", [])
        or "pods/portforward" in rule.get("resources", [])
        for rule in rules
    )


def test_reader_can_port_forward_observability_without_argocd_app_access():
    assert granted(
        "tf3-production-readonly",
        "pods/portforward",
        "create",
        namespace="techx-tf3",
    )
    assert granted(
        "tf3-production-readonly-observability",
        "pods/portforward",
        "create",
        namespace="argocd",
    )
    assert granted("tf3-production-readonly-observability", "services", "get", namespace="argocd")
    # Port-forward remains namespace-scoped; cluster-wide permissions are read-only.
    cluster_rules = rules_for(
        "tf3-production-readonly-cluster-extensions",
        kind="ClusterRole",
    )
    assert not any(
        "pods/portforward" in rule.get("resources", [])
        for rule in cluster_rules
    )


def test_terraform_declares_expected_roles_and_users():
    text = Path("infra/live/production/iam-production-access.tf").read_text()
    for name in ("cdo01-pm", "cdo01-tl", "cdo02-pm", "cdo02-tl", "tf3-members-readonly"):
        assert name in text
    assert 'name = "tf3-production-operator"' in text
    assert 'name = "tf3-production-readonly"' in text
    assert "AmazonEKSClusterAdminPolicy" not in text
    assert "aws_iam_access_key" not in text
    assert "aws:MultiFactorAuthPresent" not in text


def test_eks_group_mapping_keeps_existing_admin_path():
    text = Path("infra/modules/eks-platform/main.tf").read_text()
    assert "var.eks_admin_principal_arns" in text
    assert "var.eks_kubernetes_group_principals" in text
    assert "kubernetes_groups" in text


def test_eks_group_mapping_uses_static_for_each_keys():
    root = Path("infra/live/production/main.tf").read_text()
    assert "operator = {" in root
    assert "readonly = {" in root
    assert "(aws_iam_role.tf3_production_operator.arn)" not in root
    assert "aws_iam_role.tf3_production_operator.arn" in root


def test_ci_workflow_covers_all_access_paths():
    text = Path(".github/workflows/validate-production-access.yml").read_text()
    for path in (
        "scripts/access/**",
        "scripts/ci/test_production_access_contract.py",
        "gitops/infrastructure/rbac-production-access.yaml",
        "infra/live/production/**",
        "infra/modules/eks-platform/**",
    ):
        assert path in text
    assert "terraform validate" in text
    assert "test_production_access_contract.py" in text


def test_runbook_contains_safety_and_recovery_gates():
    text = Path("docs/runbooks/production-access-onboarding.md").read_text()
    for phrase in (
        "197826770971",
        "tf3-production-operator",
        "tf3-production-readonly",
        "one active access key per user",
        "do not remove cdo-2-admin-team",
        "kubectl auth can-i",
        "delete the handoff file",
        "Argo CD",
    ):
        assert phrase.lower() in text.lower()

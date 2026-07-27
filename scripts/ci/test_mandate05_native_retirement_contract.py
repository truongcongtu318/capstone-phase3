from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]


def load_documents(relative_path: str) -> list[dict]:
    with (REPO / relative_path).open(encoding="utf-8") as stream:
        return [document for document in yaml.safe_load_all(stream) if document]


def named_documents(relative_path: str) -> dict[str, dict]:
    return {
        document["metadata"]["name"]: document
        for document in load_documents(relative_path)
    }


def test_native_vap_bindings_remain_deny_and_exclude_only_kube_system():
    documents = named_documents("gitops/policies/native/mandate-05-runtime-policy.yaml")
    expected = {
        "mandate05-native-resource-requirements-techx-tf3",
        "mandate05-native-image-reference-techx-tf3",
    }

    for name in expected:
        binding = documents[name]
        assert binding["kind"] == "ValidatingAdmissionPolicyBinding"
        assert binding["spec"]["validationActions"] == ["Deny"]
        expressions = binding["spec"]["matchResources"]["namespaceSelector"][
            "matchExpressions"
        ]
        assert expressions == [
            {
                "key": "kubernetes.io/metadata.name",
                "operator": "NotIn",
                "values": ["kube-system"],
            }
        ]


def test_first_party_vap_accepts_only_digest_qualified_oci_references():
    documents = named_documents("gitops/policies/native/mandate-05-runtime-policy.yaml")
    policy = documents["mandate05-native-image-reference"]
    first_party_expression = policy["spec"]["validations"][1]["expression"]
    tagged_digest_suffix = (
        "(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
        "@sha256:[0-9a-f]{64}$"
    )

    # The same invariant applies to regular, init, and ephemeral containers.
    assert first_party_expression.count(tagged_digest_suffix) == 3
    assert "techx-corp(:[A-Za-z0-9_]" in first_party_expression
    assert "techx-corp:[^@]+$" not in first_party_expression


def test_psa_enforcement_and_observability_exception_are_explicit():
    techx = load_documents("gitops/infrastructure/namespace-techx-tf3.yaml")[0]
    techx_labels = techx["metadata"]["labels"]
    assert techx_labels["pod-security.kubernetes.io/enforce"] == "restricted"
    assert techx_labels["pod-security.kubernetes.io/enforce-version"] == "v1.35"

    observability = load_documents(
        "gitops/infrastructure/namespace-observability-system.yaml"
    )[0]
    observability_labels = observability["metadata"]["labels"]
    assert "pod-security.kubernetes.io/enforce" not in observability_labels
    assert observability_labels["pod-security.kubernetes.io/warn"] == "baseline"
    assert observability_labels["pod-security.kubernetes.io/audit"] == "baseline"


def test_retired_mandate05_kyverno_policies_stay_absent():
    retired = (
        "baseline-security-context.yaml",
        "disallow-latest-tag.yaml",
        "require-first-party-image-digest.yaml",
        "require-resource-requests.yaml",
    )
    for filename in retired:
        assert not (REPO / "gitops/policies/kyverno" / filename).exists()


def test_argocd_self_uses_server_side_apply():
    application = load_documents("gitops/apps/argocd-self-app.yaml")[0]
    sync_options = application["spec"]["syncPolicy"]["syncOptions"]
    assert "ServerSideApply=true" in sync_options

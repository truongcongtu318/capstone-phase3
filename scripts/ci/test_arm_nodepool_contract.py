from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
SPOT = REPO / "gitops/karpenter/spot-nodepool.yaml"
FALLBACK = REPO / "gitops/karpenter/ondemand-fallback-nodepool.yaml"
TEST_WORKFLOW = REPO / ".github/workflows/test-image-bump.yml"


def documents(path: Path) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if document
    ]


def resource(path: Path, kind: str, name: str) -> dict:
    for document in documents(path):
        if document["kind"] == kind and document["metadata"]["name"] == name:
            return document
    raise AssertionError(f"{kind}/{name} not found in {path}")


def requirements(nodepool: dict) -> dict[str, dict]:
    return {
        requirement["key"]: requirement
        for requirement in nodepool["spec"]["template"]["spec"]["requirements"]
    }


def test_arm_spot_uses_c_m_with_bounded_four_node_capacity():
    nodepool = resource(SPOT, "NodePool", "flash-sale-spot-arm64")
    requirement = requirements(nodepool)
    taint = taints(nodepool)

    assert nodepool["spec"]["weight"] == 100
    assert nodepool["spec"]["template"]["metadata"]["labels"] == {
        "techx.io/capacity": "spot",
        "techx.io/workload": "elastic",
        "techx.io/arch": "arm64",
    }
    assert taint["techx.io/workload"] == {
        "key": "techx.io/workload",
        "value": "elastic",
        "effect": "NoSchedule",
    }
    assert taint["techx.io/arch"] == {
        "key": "techx.io/arch",
        "value": "arm64",
        "effect": "NoSchedule",
    }
    assert requirement["kubernetes.io/arch"]["values"] == ["arm64"]
    assert requirement["kubernetes.io/os"]["values"] == ["linux"]
    assert requirement["karpenter.sh/capacity-type"]["values"] == ["spot"]
    assert requirement["karpenter.k8s.aws/instance-category"]["values"] == [
        "c",
        "m",
    ]
    assert requirement["karpenter.k8s.aws/instance-generation"] == {
        "key": "karpenter.k8s.aws/instance-generation",
        "operator": "Gt",
        "values": ["2"],
    }
    assert requirement["karpenter.k8s.aws/instance-cpu"]["values"] == ["2", "4"]
    assert requirement["karpenter.k8s.aws/instance-memory"] == {
        "key": "karpenter.k8s.aws/instance-memory",
        "operator": "Gt",
        "values": ["3072"],
    }
    assert nodepool["spec"]["limits"] == {
        "cpu": "16",
        "memory": "64Gi",
        "nodes": 4,
    }


def test_existing_amd_spot_cap_stays_at_two_nodes():
    nodepool = resource(SPOT, "NodePool", "flash-sale-spot")
    requirement = requirements(nodepool)

    assert requirement["kubernetes.io/arch"]["values"] == ["amd64"]
    assert requirement["karpenter.sh/capacity-type"]["values"] == ["spot"]
    assert requirement["karpenter.k8s.aws/instance-category"]["values"] == [
        "c",
        "m",
        "r",
        "t",
    ]
    assert nodepool["spec"]["limits"] == {
        "cpu": "12",
        "memory": "48Gi",
        "nodes": 2,
    }


def taints(nodepool: dict) -> dict[str, dict]:
    return {
        taint["key"]: taint
        for taint in nodepool["spec"]["template"]["spec"]["taints"]
    }


def test_arm_ondemand_fallback_matches_arm_scheduling_contract():
    nodepool = resource(
        FALLBACK, "NodePool", "elastic-ondemand-fallback-arm64"
    )
    requirement = requirements(nodepool)
    taint = taints(nodepool)

    assert nodepool["spec"]["weight"] == 10
    assert nodepool["spec"]["template"]["metadata"]["labels"] == {
        "techx.io/capacity": "on-demand-fallback",
        "techx.io/workload": "elastic",
        "techx.io/arch": "arm64",
    }
    assert taint["techx.io/workload"] == {
        "key": "techx.io/workload",
        "value": "elastic",
        "effect": "NoSchedule",
    }
    assert taint["techx.io/arch"] == {
        "key": "techx.io/arch",
        "value": "arm64",
        "effect": "NoSchedule",
    }
    assert requirement["kubernetes.io/arch"]["values"] == ["arm64"]
    assert requirement["kubernetes.io/os"]["values"] == ["linux"]
    assert requirement["karpenter.sh/capacity-type"]["values"] == ["on-demand"]
    assert requirement["karpenter.k8s.aws/instance-category"]["values"] == [
        "c",
        "m",
    ]
    assert requirement["karpenter.k8s.aws/instance-generation"] == {
        "key": "karpenter.k8s.aws/instance-generation",
        "operator": "Gt",
        "values": ["2"],
    }
    assert requirement["karpenter.k8s.aws/instance-cpu"]["values"] == ["2", "4"]
    assert requirement["karpenter.k8s.aws/instance-memory"] == {
        "key": "karpenter.k8s.aws/instance-memory",
        "operator": "Gt",
        "values": ["3072"],
    }
    assert nodepool["spec"]["template"]["spec"]["nodeClassRef"]["name"] == (
        "elastic-ondemand-fallback-arm64"
    )
    assert nodepool["spec"]["limits"] == {
        "cpu": "8",
        "memory": "32Gi",
        "nodes": 2,
    }
    assert nodepool["spec"]["disruption"] == {
        "consolidationPolicy": "WhenEmptyOrUnderutilized",
        "consolidateAfter": "10m",
        "budgets": [{"nodes": "0", "reasons": ["Drifted"]}],
    }


def test_arm_fallback_uses_dedicated_pinned_arm_nodeclass():
    nodeclass = resource(
        FALLBACK, "EC2NodeClass", "elastic-ondemand-fallback-arm64"
    )

    assert nodeclass["spec"]["amiFamily"] == "AL2023"
    assert nodeclass["spec"]["amiSelectorTerms"] == [
        {"id": "ami-038711df7b713297d"}
    ]
    assert nodeclass["spec"]["tags"]["techx.io/capacity"] == (
        "on-demand-fallback"
    )
    assert nodeclass["spec"]["tags"]["techx.io/arch"] == "arm64"


def test_existing_amd_fallback_cap_stays_at_two_nodes():
    nodepool = resource(FALLBACK, "NodePool", "elastic-ondemand-fallback")
    requirement = requirements(nodepool)

    assert requirement["kubernetes.io/arch"]["values"] == ["amd64"]
    assert requirement["karpenter.sh/capacity-type"]["values"] == ["on-demand"]
    assert requirement["karpenter.k8s.aws/instance-category"]["values"] == [
        "c",
        "m",
        "r",
        "t",
    ]
    assert nodepool["spec"]["limits"] == {
        "cpu": "4",
        "memory": "16Gi",
        "nodes": 2,
    }


def test_nodepool_manifest_changes_trigger_contract_suite():
    workflow = yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))
    paths = workflow["on"]["pull_request"]["paths"]

    assert "gitops/karpenter/**" in paths

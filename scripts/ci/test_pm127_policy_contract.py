from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
FIRST_PARTY = "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp"
WORKFLOW_IDENTITY = (
    "https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/"
    ".github/workflows/build-push-ecr.yml@refs/heads/main"
)


def load(path):
    return yaml.safe_load((REPO / path).read_text())


def test_first_party_policy_enforces_and_requires_exact_signature_and_sbom():
    policy = load("gitops/policies/kyverno/verify-first-party-signatures.yaml")
    # Enforce since 2026-07-28. The directive is explicit that reporting-only
    # does not count, so this guards against a silent revert to Audit - a policy
    # that still reads as active while blocking nothing.
    assert policy["spec"]["validationFailureAction"] == "Enforce"
    assert policy["spec"]["background"] is True
    verify = policy["spec"]["rules"][0]["verifyImages"][0]
    # Grafana is first-party but its subchart hardcodes
    # "{{repository}}:{{tag}}@sha256:{{sha}}", so it has to be matched by a
    # second glob or it falls through to the external catalogue it can never
    # be listed in.
    assert verify["imageReferences"] == [
        FIRST_PARTY + "@sha256:*",
        FIRST_PARTY + ":*@sha256:*",
    ]
    assert verify["required"] is True
    assert verify["mutateDigest"] is False
    assert verify["verifyDigest"] is True
    assert verify["imageRegistryCredentials"]["providers"] == ["amazon"]
    keyless = verify["attestors"][0]["entries"][0]["keyless"]
    assert keyless["issuer"] == "https://token.actions.githubusercontent.com"
    assert keyless["subject"] == WORKFLOW_IDENTITY
    attestation = verify["attestations"][0]
    assert attestation["type"] == "https://cyclonedx.org/bom"
    conditions = attestation["conditions"][0]["all"]
    assert {condition["key"] for condition in conditions} == {
        "{{ bomFormat }}",
        "{{ length(components) }}",
        "{{ metadata.properties[?name == 'techx.platform'].value | [0] }}",
        "{{ regex_match('^sha256:[0-9a-f]{64}$', metadata.properties[?name == 'techx.subjectDigest'].value | [0]) }}",
        "{{ metadata.properties[?name == 'techx.indexDigest'].value | [0] }}",
        "{{ regex_match('^[0-9a-f]{40}$', metadata.properties[?name == 'techx.sourceSha'].value | [0]) }}",
    }
    assert conditions[4]["value"] == "{{ image.digest }}"
    attestor = attestation["attestors"][0]["entries"][0]["keyless"]
    assert attestor["issuer"] == "https://token.actions.githubusercontent.com"
    assert attestor["subject"] == WORKFLOW_IDENTITY


def test_external_policy_catalog_is_exactly_the_reviewed_catalog():
    policy = load("gitops/policies/kyverno/allow-approved-external-image-digests.yaml")
    catalog = load("docs/evidence/mandate-10/external-image-allowlist.yaml")
    expected = {entry["image"] for entry in catalog["images"]}
    # Enforce since 2026-07-28. The assertion used to pin Audit to stop an
    # accidental cutover; now it guards the other direction, so a silent revert
    # to reporting-only shows up as a failing test instead of a policy that
    # looks active but blocks nothing.
    assert policy["spec"]["validationFailureAction"] == "Enforce"
    assert policy["spec"]["background"] is True
    foreach = policy["spec"]["rules"][0]["validate"]["foreach"]
    assert len(foreach) == 3
    for loop in foreach:
        assert "request.object.spec." in loop["list"]
        values = set(loop["deny"]["conditions"]["any"][0]["value"])
        assert values == expected
        assert loop["preconditions"]["all"][0]["operator"] == "Equals"
        assert loop["preconditions"]["all"][0]["value"] is False


def test_policy_application_is_gitops_ordered_after_controller():
    controller = load("gitops/apps/kyverno-app.yaml")
    policies = load("gitops/apps/kyverno-policies-app.yaml")
    assert controller["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "10"
    assert policies["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "20"
    assert policies["spec"]["source"]["path"] == "gitops/policies/kyverno"
    assert "ServerSideApply=true" in policies["spec"]["syncPolicy"]["syncOptions"]


def test_external_policy_defers_every_first_party_form_to_the_signature_policy():
    """The two policies must partition the namespace, not overlap or leave gaps.

    Anything under techx-corp is judged by signature and SBOM; anything else is
    judged against the reviewed digest catalogue. A first-party image that slips
    into the external rule would be denied for missing from a catalogue it can
    never be listed in, while an external image that escaped both would run
    unverified.
    """
    import re

    policy = load("gitops/policies/kyverno/allow-approved-external-image-digests.yaml")
    foreach = policy["spec"]["rules"][0]["validate"]["foreach"]
    assert [f["list"] for f in foreach] == [
        "request.object.spec.containers",
        "request.object.spec.initContainers || []",
        "request.object.spec.ephemeralContainers || []",
    ], "ephemeral and init containers must not be a bypass"

    patterns = set()
    for entry in foreach:
        key = entry["preconditions"]["all"][0]["key"]
        patterns.add(re.search(r"regex_match\('([^']+)'", key).group(1))
    assert len(patterns) == 1, "all three container lists must share one rule"

    rx = re.compile(patterns.pop())
    digest = "sha256:" + "a" * 64
    deferred = {
        FIRST_PARTY + "@" + digest: True,
        FIRST_PARTY + ":b44ca10-30240572310-grafana@" + digest: True,
        # A first-party image pinned by tag alone has no digest to verify, so it
        # must stay in the external rule and be denied there.
        FIRST_PARTY + ":latest": False,
        "busybox@" + digest: False,
        "quay.io/prometheus/prometheus:v3.11.3": False,
        "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/tf-2-ai-engine:IF-v63": False,
    }
    for image, is_deferred in deferred.items():
        assert bool(rx.match(image)) is is_deferred, image

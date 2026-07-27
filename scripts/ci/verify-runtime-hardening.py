#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

import yaml


DEFAULT_FIRST_PARTY = (
    "accounting ad cart checkout currency email fraud-detection frontend grafana "
    "frontend-proxy image-provider llm load-generator payment product-catalog "
    "product-reviews quote recommendation shipping"
).split()

DEFAULT_REPOSITORY = "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp"
FIRST_PARTY_DIGEST_RE = re.compile(
    r"^197826770971\.dkr\.ecr\.ap-southeast-1\.amazonaws\.com/techx-corp"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?@sha256:[0-9a-f]{64}$"
)


def load_yaml_documents(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [doc for doc in yaml.safe_load_all(handle) if isinstance(doc, dict)]


def load_exceptions(path):
    if not path:
        return []
    with open(path, "r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}
    exceptions = doc.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise ValueError("exception register must contain an exceptions list")
    return exceptions


def pod_template(doc):
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Rollout", "Job"}:
        return spec.get("template")
    if kind == "CronJob":
        return ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template")
    if kind == "Pod":
        return doc
    return None


def template_identity(doc, template):
    labels = ((template.get("metadata") or {}).get("labels") or {})
    meta = doc.get("metadata") or {}
    return {
        "kind": doc.get("kind"),
        "workload": meta.get("name"),
        "namespace": meta.get("namespace") or "techx-tf3",
        "app": labels.get("app.kubernetes.io/name") or meta.get("name"),
        "labels": labels,
    }


def iter_containers(template):
    spec = template.get("spec") or {}
    for container_type in ("containers", "initContainers"):
        for container in spec.get(container_type) or []:
            yield container_type, container
    for container in spec.get("ephemeralContainers") or []:
        yield "ephemeralContainers", container


def has_fixed_tag_or_digest(image):
    if "@sha256:" in image:
        return bool(re.search(r"@sha256:[0-9a-f]{64}$", image))
    last_segment = image.rsplit("/", 1)[-1]
    return ":" in last_segment and not image.endswith(":latest")


def resource_findings(identity, container_type, container):
    if container_type == "ephemeralContainers":
        return []
    resources = container.get("resources") or {}
    requests = resources.get("requests") or {}
    limits = resources.get("limits") or {}
    missing = []
    for field, data in (
        ("requests.cpu", requests),
        ("requests.memory", requests),
        ("limits.cpu", limits),
        ("limits.memory", limits),
    ):
        key = field.split(".")[1]
        value = data.get(key)
        if value in (None, "", "0", 0):
            missing.append(field)
    if not missing:
        return []
    return [
        {
            **identity,
            "policy": "require-resource-requests",
            "rule": "require-cpu-memory-requests-limits",
            "containerType": container_type,
            "container": container.get("name"),
            "message": "missing resource fields",
            "details": missing,
        }
    ]


def security_findings(identity, template, container_type, container):
    if container_type == "ephemeralContainers":
        return []
    spec = template.get("spec") or {}
    pod_sc = spec.get("securityContext") or {}
    sc = container.get("securityContext") or {}
    findings = []

    def effective_run_as_non_root():
        if "runAsNonRoot" in sc:
            return sc.get("runAsNonRoot")
        return pod_sc.get("runAsNonRoot")

    def add(rule, message, details=None):
        findings.append(
            {
                **identity,
                "policy": "custom-baseline-security-context",
                "rule": rule,
                "containerType": container_type,
                "container": container.get("name"),
                "message": message,
                "details": details or [],
            }
        )

    if effective_run_as_non_root() is not True:
        add("require-effective-non-root", "runAsNonRoot is not effectively true")
    if pod_sc.get("runAsUser") == 0 or sc.get("runAsUser") == 0:
        add("deny-container-run-as-user-zero", "runAsUser is 0")
    if sc.get("privileged") is True:
        add("deny-privileged-containers", "privileged container")
    if sc.get("allowPrivilegeEscalation") is not False:
        add("require-allow-privilege-escalation-false", "allowPrivilegeEscalation is not false")
    if "ALL" not in ((sc.get("capabilities") or {}).get("drop") or []):
        add("drop-all-capabilities", "capabilities.drop does not contain ALL")
    seccomp = (
        (pod_sc.get("seccompProfile") or {}).get("type")
        or (sc.get("seccompProfile") or {}).get("type")
    )
    if seccomp != "RuntimeDefault":
        add("require-seccomp-profile-runtime-default", "RuntimeDefault seccomp is not effective")
    return findings


def image_findings(identity, container_type, container, first_party_repository):
    image = container.get("image") or ""
    findings = []
    if not has_fixed_tag_or_digest(image):
        findings.append(
            {
                **identity,
                "policy": "disallow-latest-tag",
                "rule": "require-explicit-non-latest-image-reference",
                "containerType": container_type,
                "container": container.get("name"),
                "image": image,
                "message": "image uses latest or an implicit latest reference",
            }
        )
    if image.startswith(first_party_repository) and not FIRST_PARTY_DIGEST_RE.match(image):
        findings.append(
            {
                **identity,
                "policy": "require-first-party-image-digest",
                "rule": "require-techx-ecr-sha256-digest",
                "containerType": container_type,
                "container": container.get("name"),
                "image": image,
                "message": "first-party image is not pinned to the exact shared ECR digest form",
            }
        )
    return findings


def exception_matches(finding, exception):
    selector = exception.get("selector") or {}
    labels = selector.get("matchLabels") or {}
    if labels.get("app.kubernetes.io/name") != finding.get("app"):
        return False
    if exception.get("policy") != finding.get("policy"):
        return False
    rules = exception.get("rules") or []
    return finding.get("rule") in rules


def classify_findings(findings, exceptions):
    approved = []
    unresolved = []
    for finding in findings:
        match = next((exc for exc in exceptions if exception_matches(finding, exc)), None)
        if match:
            approved.append({**finding, "exceptionId": match.get("id")})
        else:
            unresolved.append(finding)
    return approved, unresolved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rendered", required=True)
    parser.add_argument("--first-party-repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--first-party-components", nargs="*", default=DEFAULT_FIRST_PARTY)
    parser.add_argument("--exception-register")
    parser.add_argument("--mode", choices=["inventory", "audit", "enforce"], default="audit")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    docs = load_yaml_documents(args.rendered)
    exceptions = load_exceptions(args.exception_register)
    first_party = set(args.first_party_components)

    inventory = []
    findings = []
    for doc in docs:
        template = pod_template(doc)
        if not template:
            continue
        identity = template_identity(doc, template)
        inventory.append(
            {
                "kind": identity["kind"],
                "workload": identity["workload"],
                "namespace": identity["namespace"],
                "app": identity["app"],
                "firstParty": identity["app"] in first_party,
            }
        )
        for container_type, container in iter_containers(template):
            findings.extend(resource_findings(identity, container_type, container))
            findings.extend(security_findings(identity, template, container_type, container))
            findings.extend(image_findings(identity, container_type, container, args.first_party_repository))

    approved, unresolved = classify_findings(findings, exceptions)
    first_party_apps = sorted({item["app"] for item in inventory if item["firstParty"]})
    expected_first_party = sorted(first_party)
    inventory_delta = {
        "missing": sorted(set(expected_first_party) - set(first_party_apps)),
        "unexpected": sorted(set(first_party_apps) - set(expected_first_party)),
    }

    result = {
        "schemaVersion": 1,
        "mode": args.mode,
        "firstPartyRepository": args.first_party_repository,
        "firstPartyComponents": expected_first_party,
        "firstPartyInventory": first_party_apps,
        "inventoryDelta": inventory_delta,
        "workloads": sorted(inventory, key=lambda x: (x["kind"], x["workload"] or "")),
        "approvedExceptions": approved,
        "unresolvedFindings": unresolved,
        "summary": {
            "workloadCount": len(inventory),
            "findingCount": len(findings),
            "approvedExceptionCount": len(approved),
            "unresolvedFindingCount": len(unresolved),
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    should_fail = args.mode in {"audit", "enforce"} and (
        unresolved or inventory_delta["missing"] or inventory_delta["unexpected"]
    )
    if should_fail:
        print(json.dumps(result["summary"], indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import sys
import json
import argparse
from pathlib import Path
from ruamel.yaml import YAML

def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

# Services that render as a named container inside a DIFFERENT workload's Pod
# (a sidecar) rather than owning their own Deployment/StatefulSet/etc. Mapped
# to the pod-identity (opentelemetry.io/name / app.kubernetes.io/name) of the
# workload that hosts them. Must match NESTED_SIDECAR_SERVICES in
# update-image-overrides.py.
NESTED_SIDECAR_SERVICES = {
    "flagd-ui": "flagd",
}

# Grafana is rendered by the vendored Grafana Helm dependency and includes the
# mutable tag before its immutable digest: registry/repository:tag@sha256:...
TAGGED_DIGEST_SERVICES = {
    "grafana",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rendered', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--registry', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--excluded-service', action='append', default=[])
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    rendered_path = Path(args.rendered)
    
    if not manifest_path.is_file():
        fail("Manifest missing")
    if not rendered_path.is_file():
        fail("Rendered YAML missing")
        
    with open(manifest_path, "r") as f:
        manifest = json.load(f)
        
    yaml = YAML(typ='safe')
    with open(rendered_path, "r") as f:
        docs = list(yaml.load_all(f))
        
    expected_digests = {}
    for svc in manifest["services"]:
        if svc["name"] not in args.excluded_service:
            expected_digests[svc["name"]] = svc["digest"]

    # Mapping of service name to list of images found
    found_images = {svc: [] for svc in expected_digests}
    
    for doc in docs:
        if not doc or not isinstance(doc, dict):
            continue
            
        kind = doc.get("kind")
        if kind not in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Rollout"}:
            continue
            
        spec = doc.get("spec", {})
        
        # Traverse to PodSpec
        pod_template = None
        if kind == "CronJob":
            job_template = spec.get("jobTemplate", {})
            pod_template = job_template.get("spec", {}).get("template", {})
        else:
            pod_template = spec.get("template", {})
            
        if not pod_template:
            continue
            
        pod_metadata = pod_template.get("metadata", {})
        pod_labels = pod_metadata.get("labels", {})
        
        doc_metadata = doc.get("metadata", {})
        doc_labels = doc_metadata.get("labels", {})
        doc_name = doc_metadata.get("name")
        
        svc_identity = (
            pod_labels.get("opentelemetry.io/name") or
            pod_labels.get("app.kubernetes.io/component") or
            pod_labels.get("app.kubernetes.io/name") or
            doc_labels.get("opentelemetry.io/name") or
            doc_labels.get("app.kubernetes.io/component") or
            doc_labels.get("app.kubernetes.io/name") or
            doc_name
        )
        
        if not svc_identity:
            continue
            
        pod_spec = pod_template.get("spec", {})
        containers = pod_spec.get("containers", [])

        # Is this one of our expected services?
        if svc_identity in expected_digests:
            for c in containers:
                # We expect the app container to share the service name, or be the first/only one?
                # Usually in our chart, the main container is named after the service or "app".
                image = c.get("image", "")
                if args.repository in image:
                    found_images[svc_identity].append(image)

        # Nested sidecars (e.g. flagd-ui inside the flagd Pod) never match
        # svc_identity above - the Pod's own identity belongs to its main
        # component. Match those by their own container `name` instead, and
        # only within the Pod that actually hosts them, so an unrelated
        # container elsewhere named the same can't be picked up by accident.
        for sidecar_name, parent_identity in NESTED_SIDECAR_SERVICES.items():
            if sidecar_name not in expected_digests or svc_identity != parent_identity:
                continue
            for c in containers:
                if c.get("name") != sidecar_name:
                    continue
                image = c.get("image", "")
                if args.repository in image:
                    found_images[sidecar_name].append(image)

    all_digests_in_manifest = set(expected_digests.values())

    for svc, images in found_images.items():
        if not images:
            fail(f"Expected service workload missing or no relevant images found for {svc}")
            
        expected_digest = expected_digests[svc]
        if svc in TAGGED_DIGEST_SERVICES:
            manifest_service = next(
                item for item in manifest["services"] if item["name"] == svc
            )
            expected_full_image = (
                f"{args.registry}/{args.repository}:"
                f"{manifest_service['tag']}@{expected_digest}"
            )
        else:
            expected_full_image = f"{args.registry}/{args.repository}@{expected_digest}"
        
        for image in images:
            if "@sha256:" not in image:
                fail(f"Mutable tag remains for app image in {svc}: {image}")
                
            if image != expected_full_image:
                found_digest = image.split("@")[-1]
                if found_digest == expected_digest:
                    fail(f"Wrong registry or repository in {svc}. Expected {expected_full_image}, got {image}")
                elif found_digest in all_digests_in_manifest:
                    fail(f"Digest swapped between two services. {svc} is using {found_digest}")
                else:
                    fail(f"Wrong digest in matching service workload {svc}. Expected {expected_digest}, got {found_digest}")

if __name__ == "__main__":
    main()

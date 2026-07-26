#!/usr/bin/env python3
import sys
import json
import re
import argparse
import os
import tempfile
from pathlib import Path
from ruamel.yaml import YAML

ALLOWED_SERVICES = {
    "accounting", "ad", "cart", "checkout", "currency", "email",
    "fraud-detection", "frontend", "frontend-proxy", "image-provider",
    "kafka", "llm", "load-generator", "payment", "product-catalog",
    "product-reviews", "quote", "recommendation", "shipping", "flagd-ui",
    "grafana"
}

# Services that are not their own top-level `components.<name>` entry, but a
# named entry inside another component's `sidecarContainers` list. flagd-ui
# ships as a Phoenix sidecar next to the flagd (flagd core) container, in the
# same Pod - it has no component of its own to key off of.
NESTED_SIDECAR_SERVICES = {
    "flagd-ui": {"component": "flagd", "sidecar_name": "flagd-ui"},
}

# Grafana is a Helm dependency whose image lives under the top-level
# `grafana.image` map instead of `components.<name>.imageOverride`.
TOP_LEVEL_IMAGE_SERVICES = {
    "grafana": "grafana",
}

ALLOWED_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json"
}

def reject_duplicates(ordered_pairs):
    d = {}
    for k, v in ordered_pairs:
        if k in d:
            raise ValueError(f"Duplicate key found: {k}")
        d[k] = v
    return d

def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

def validate_manifest(manifest, args):
    if not isinstance(manifest, dict):
        fail("Manifest is not a JSON object")
    
    if manifest.get("schemaVersion") != 1:
        fail("Invalid schemaVersion")
        
    expected_top_fields = {
        "schemaVersion", "repository", "registry", "sourceSha",
        "sourceShortSha", "workflowRunId", "workflowRunAttempt",
        "mode", "baseTag", "platforms", "services"
    }
    
    if set(manifest.keys()) != expected_top_fields:
        fail(f"Unknown top-level fields or missing required fields. Expected {expected_top_fields}, got {set(manifest.keys())}")
        
    if manifest["mode"] not in {"scoped", "full"}:
        fail("mode must be scoped or full")
        
    if manifest["sourceSha"] != args.expected_source_sha:
        fail("sourceSha mismatch")
    if manifest["sourceShortSha"] != args.expected_source_short_sha:
        fail("sourceShortSha mismatch")
    if manifest["workflowRunId"] != args.expected_run_id:
        fail("workflowRunId mismatch")
    if manifest["workflowRunAttempt"] != args.expected_run_attempt:
        fail("workflowRunAttempt mismatch")
    if manifest["mode"] != args.expected_mode:
        fail("mode mismatch")
    if manifest["registry"] != args.expected_registry:
        fail("registry mismatch")
    if manifest["repository"] != args.expected_repository:
        fail("repository mismatch")
    if manifest["baseTag"] != args.expected_base_tag:
        fail("baseTag mismatch")
        
    # normalize platforms
    expected_platforms = args.expected_platforms.split(",") if args.expected_platforms else []
    expected_platforms = ",".join(sorted(expected_platforms)) if expected_platforms else ""
    manifest_platforms = manifest["platforms"].split(",") if manifest["platforms"] else []
    manifest_platforms = ",".join(sorted(manifest_platforms)) if manifest_platforms else ""
    if manifest_platforms != expected_platforms:
        fail("platforms mismatch")
        
    services = manifest["services"]
    if not isinstance(services, list):
        fail("services must be a list")
    if not services:
        fail("services list is empty")
        
    prev_name = ""
    seen_services = set()
    for s in services:
        if not isinstance(s, dict):
            fail("service entry must be an object")
        
        expected_svc_fields = {"name", "tag", "digest", "manifestMediaType"}
        if set(s.keys()) != expected_svc_fields:
            fail("Unknown or missing fields in service object")
            
        name = s["name"]
        if name not in ALLOWED_SERVICES:
            fail(f"Unknown service name: {name}")
        if name in seen_services:
            fail(f"Duplicate service name: {name}")
        seen_services.add(name)
        
        if name <= prev_name:
            fail("Services list is not deterministically sorted")
        prev_name = name
        
        if not re.match(r"^sha256:[0-9a-f]{64}$", s["digest"]):
            fail(f"Invalid digest format for {name}")
            
        expected_tag = f"{manifest['baseTag']}-{name}"
        if s["tag"] != expected_tag:
            fail(f"tag does not equal <baseTag>-<service> for {name}")
            
        if len(s["tag"]) > 128:
            fail(f"Full tag exceeds 128 characters for {name}")
            
        if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", s["tag"]):
            fail(f"Tag does not match Docker tag convention for {name}")
            
        mt = s["manifestMediaType"]
        if mt not in ALLOWED_MEDIA_TYPES:
            fail(f"Invalid manifestMediaType for {name}")
            
        if "," in manifest_platforms and mt not in {
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json"
        }:
            fail(f"multi-platform with single-manifest media type for {name}")

    expected_set = set(args.expected_services.split()) if args.expected_services else set()
    if seen_services != expected_set:
        fail("Expected service set mismatch")

def parse_yaml_strict(filepath):
    yaml = YAML()
    yaml.preserve_quotes = True
    try:
        with open(filepath, "r") as f:
            doc = yaml.load(f)
    except Exception as e:
        fail(f"Malformed YAML or duplicate keys: {e}")
    if not isinstance(doc, dict):
        fail("YAML root must be a mapping")
    if 'components' not in doc or not isinstance(doc['components'], dict):
        fail("components missing or non-mapping")
    return doc

def find_indent(line):
    return len(line) - len(line.lstrip())

def resolve_target_node(components, name):
    """Return the CommentedMap that owns `imageOverride` for this service -
    either components[name] directly, or (for NESTED_SIDECAR_SERVICES) the
    matching entry inside the parent component's sidecarContainers list.
    Calls fail() and exits if the service can't be located."""
    nested = NESTED_SIDECAR_SERVICES.get(name)
    if nested is None:
        if name not in components:
            fail(f"UNKNOWN_PRODUCTION_COMPONENT: {name}")
        if not isinstance(components[name], dict):
            fail(f"component {name} value is non-mapping")
        return components[name]

    parent_name = nested["component"]
    sidecar_name = nested["sidecar_name"]
    if parent_name not in components:
        fail(f"UNKNOWN_PRODUCTION_COMPONENT: {parent_name}")
    parent = components[parent_name]
    if not isinstance(parent, dict):
        fail(f"component {parent_name} value is non-mapping")
    sidecars = parent.get("sidecarContainers")
    if not isinstance(sidecars, list):
        fail(f"UNKNOWN_PRODUCTION_SIDECAR: {name} ({parent_name}.sidecarContainers is missing or not a list)")
    for item in sidecars:
        if isinstance(item, dict) and item.get("name") == sidecar_name:
            return item
    fail(f"UNKNOWN_PRODUCTION_SIDECAR: {name} (no entry named {sidecar_name} under {parent_name}.sidecarContainers)")

def resolve_top_level_image_node(doc, name):
    key = TOP_LEVEL_IMAGE_SERVICES.get(name)
    if key is None:
        fail(f"UNKNOWN_TOP_LEVEL_IMAGE_SERVICE: {name}")
    target = doc.get(key)
    if not isinstance(target, dict):
        fail(f"top-level image service {name} value is non-mapping")
    return target

def case_d_anchor(components, name, lines):
    """Return (anchor_line_idx, child_indent) for inserting a brand-new
    imageOverride block for `name` that currently has none at all."""
    if name in NESTED_SIDECAR_SERVICES:
        target = resolve_target_node(components, name)
        # ruamel gives each sidecar list-item CommentedMap its own start
        # line/col (the position of its first key, e.g. `name:`) - reuse
        # that directly as the sibling-key indent instead of guessing from
        # the raw line text, since list items may be formatted either as
        # `- name: x` or `-\n    name: x`.
        return target.lc.line, target.lc.col
    line_idx = components.lc.data[name][0]
    indent = find_indent(lines[line_idx]) + 2
    return line_idx, indent

def replace_yaml_scalar_line(line, key, value, force_quote=False):
    pattern = rf'(\b{re.escape(key)}:\s*)("[^"]*"|\'[^\']*\'|\S+)'
    match = re.search(pattern, line)
    if not match:
        fail(f"Unable to replace YAML scalar key: {key}")
    value_text = str(value)
    current = match.group(2)
    if force_quote:
        value_text = f'"{value_text}"'
    elif current.startswith('"') and current.endswith('"'):
        value_text = f'"{value_text}"'
    elif current.startswith("'") and current.endswith("'"):
        value_text = f"'{value_text}'"
    return line[:match.start(2)] + value_text + line[match.end(2):]

def update_top_level_image_service(doc, lines, edits, svc_info, summary):
    name = svc_info["name"]
    target = resolve_top_level_image_node(doc, name)
    new_values = {
        "registry": svc_info["registry"],
        "repository": svc_info["repository"],
        "tag": svc_info["tag"],
        # The Grafana chart expects the digest without the `sha256:` prefix.
        "sha": svc_info["digest"].removeprefix("sha256:"),
    }

    image_node = target.get("image")
    if image_node is None or not isinstance(image_node, dict):
        grafana_line_idx = doc.lc.data[name][0]
        image_block = (
            "  image:\n"
            f"    registry: {new_values['registry']}\n"
            f"    repository: {new_values['repository']}\n"
            f"    tag: {new_values['tag']}\n"
            f"    sha: \"{new_values['sha']}\"\n"
        )
        edits[grafana_line_idx + 0.5] = image_block
        old_values = None
    else:
        old_values = {key: image_node.get(key) for key in new_values}
        image_line_idx = target.lc.data["image"][0]
        for key, value in new_values.items():
            if key in image_node:
                line_idx = image_node.lc.data[key][0]
                edits[line_idx] = replace_yaml_scalar_line(
                    lines[line_idx], key, value, force_quote=(key == "sha")
                )
            else:
                insert_key = image_line_idx + 0.5
                rendered_value = f'"{value}"' if key == "sha" else value
                edits[insert_key] = (
                    edits.get(insert_key, "")
                    + f"    {key}: {rendered_value}\n"
                )

    summary["updated"].append({
        "service": name,
        "oldDigest": (
            f"sha256:{old_values['sha']}" if old_values and old_values.get("sha") else None
        ),
        "newDigest": svc_info["digest"],
        "tagKeyExisted": bool(old_values and "tag" in old_values),
        "oldTag": old_values.get("tag") if old_values else None,
        "newTag": new_values["tag"],
    })

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--values', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--summary-output', required=True)
    parser.add_argument('--expected-source-sha', required=True)
    parser.add_argument('--expected-source-short-sha', required=True)
    parser.add_argument('--expected-run-id', required=True)
    parser.add_argument('--expected-run-attempt', required=True)
    parser.add_argument('--expected-mode', required=True)
    parser.add_argument('--expected-registry', required=True)
    parser.add_argument('--expected-repository', required=True)
    parser.add_argument('--expected-base-tag', required=True)
    parser.add_argument('--expected-platforms', required=True)
    parser.add_argument('--expected-services', required=True)
    parser.add_argument('--excluded-service', action='append', default=[])
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    values_path = Path(args.values)
    
    if not manifest_path.exists() or manifest_path.is_symlink() or not manifest_path.is_file():
        fail("Manifest file missing or invalid type")
        
    if manifest_path.stat().st_size > 1024 * 1024:
        fail("Manifest file larger than 1 MiB")
        
    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f, object_pairs_hook=reject_duplicates)
    except Exception as e:
        fail(f"Manifest JSON parsing failed: {e}")
        
    validate_manifest(manifest, args)
    
    doc = parse_yaml_strict(values_path)
    components = doc['components']
    
    for svc_info in manifest["services"]:
        name = svc_info["name"]
        if name in args.excluded_service:
            continue
        target = (
            resolve_top_level_image_node(doc, name)
            if name in TOP_LEVEL_IMAGE_SERVICES
            else resolve_target_node(components, name)
        )
        if name in TOP_LEVEL_IMAGE_SERVICES:
            io = target.get("image")
            if io is not None and not isinstance(io, dict):
                fail(f"image for {name} is non-mapping")
            continue
        io = target.get('imageOverride')
        # io could be {} or None, but if it exists and is scalar, fail
        if "imageOverride" in target and io is not None and not isinstance(io, dict):
            fail(f"imageOverride for {name} is non-mapping")

    with open(values_path, "rb") as f:
        raw_bytes = f.read()
    raw_text = raw_bytes.decode('utf-8')
    lines = raw_text.splitlines(keepends=True)
    
    edits = {}
    
    summary = {
        "schemaVersion": 1,
        "sourceSha": manifest["sourceSha"],
        "runId": manifest["workflowRunId"],
        "runAttempt": manifest["workflowRunAttempt"],
        "noChanges": False,
        "updated": [],
        "unchanged": [],
        "skipped": []
    }
    
    for svc_info in manifest["services"]:
        name = svc_info["name"]
        if name in args.excluded_service:
            summary["skipped"].append({"service": name, "reason": "excluded-from-production-values"})
            continue
            
        new_digest = svc_info["digest"]
        new_tag = svc_info["tag"]

        if name in TOP_LEVEL_IMAGE_SERVICES:
            svc_info_with_metadata = dict(svc_info)
            svc_info_with_metadata["registry"] = manifest["registry"]
            svc_info_with_metadata["repository"] = manifest["repository"]
            update_top_level_image_service(
                doc, lines, edits, svc_info_with_metadata, summary
            )
            continue

        comp_node = resolve_target_node(components, name)

        if "imageOverride" in comp_node:
            io_node = comp_node.get('imageOverride')
            io_line_idx = comp_node.lc.data['imageOverride'][0]
            
            # Case C: imageOverride exists but is empty or null
            if io_node is None or not io_node:
                # Replace the line with `imageOverride:\n  digest: ...`
                io_line = lines[io_line_idx]
                indent = find_indent(io_line)
                spaces = " " * indent
                insert_line = f"{spaces}imageOverride:\n{spaces}  digest: {new_digest}\n"
                edits[io_line_idx] = insert_line
                summary["updated"].append({
                    "service": name,
                    "oldDigest": None,
                    "newDigest": new_digest,
                    "tagKeyExisted": False,
                    "oldTag": None,
                    "newTag": None
                })
                continue
            
            # Normal Case A and B
            digest_node = io_node.get('digest')
            tag_node = io_node.get('tag')
            
            old_digest = digest_node if digest_node else None
            old_tag = tag_node if tag_node is not None else None
            
            tag_key_existed = 'tag' in io_node
            changed = False
            tag_updated = False
            
            if "digest" in io_node:
                if digest_node != new_digest:
                    line_idx = io_node.lc.data['digest'][0]
                    old_line = lines[line_idx]
                    m = re.search(r'(digest:\s*)("[^"]*"|\'[^\']*\'|\S+)', old_line)
                    if m:
                        val_str = m.group(2)
                        if val_str.startswith('"') and val_str.endswith('"'):
                            new_line = old_line[:m.start(2)] + f'"{new_digest}"' + old_line[m.end(2):]
                        elif val_str.startswith("'") and val_str.endswith("'"):
                            new_line = old_line[:m.start(2)] + f"'{new_digest}'" + old_line[m.end(2):]
                        else:
                            new_line = old_line[:m.start(2)] + new_digest + old_line[m.end(2):]
                    else:
                        new_line = old_line
                    edits[line_idx] = new_line
                    changed = True
            else:
                # Insert digest inside imageOverride
                io_line = lines[io_line_idx]
                indent = find_indent(io_line) + 2
                spaces = " " * indent
                insert_line = f"{spaces}digest: {new_digest}\n"
                if io_line_idx + 0.5 not in edits:
                    edits[io_line_idx + 0.5] = insert_line
                else:
                    fail("Overlap during insertion")
                changed = True
                
            if tag_key_existed and old_tag != new_tag:
                line_idx = io_node.lc.data['tag'][0]
                old_line = lines[line_idx]
                m = re.search(r'(tag:\s*)("[^"]*"|\'[^\']*\'|\S+)', old_line)
                if m:
                    val_str = m.group(2)
                    if val_str.startswith('"') and val_str.endswith('"'):
                        new_line = old_line[:m.start(2)] + f'"{new_tag}"' + old_line[m.end(2):]
                    elif val_str.startswith("'") and val_str.endswith("'"):
                        new_line = old_line[:m.start(2)] + f"'{new_tag}'" + old_line[m.end(2):]
                    else:
                        new_line = old_line[:m.start(2)] + new_tag + old_line[m.end(2):]
                else:
                    new_line = old_line
                edits[line_idx] = new_line
                changed = True
                tag_updated = True
                
            if changed:
                summary["updated"].append({
                    "service": name,
                    "oldDigest": old_digest,
                    "newDigest": new_digest,
                    "tagKeyExisted": tag_key_existed,
                    "oldTag": old_tag,
                    "newTag": new_tag if tag_updated else old_tag
                })
            else:
                summary["unchanged"].append(name)
                
        else:
            # Case D: imageOverride does not exist.
            svc_line_idx, indent = case_d_anchor(components, name, lines)
            spaces = " " * indent

            insert_str = f"{spaces}imageOverride:\n{spaces}  digest: {new_digest}\n"
            edits[svc_line_idx + 0.5] = insert_str
            
            summary["updated"].append({
                "service": name,
                "oldDigest": None,
                "newDigest": new_digest,
                "tagKeyExisted": False,
                "oldTag": None,
                "newTag": None
            })

    if not summary["updated"]:
        summary["noChanges"] = True

    new_lines = []
    for i, line in enumerate(lines):
        if i in edits:
            new_lines.append(edits[i])
        else:
            new_lines.append(line)
        if i + 0.5 in edits:
            new_lines.append(edits[i + 0.5])
            
    new_text = "".join(new_lines)
    new_bytes = new_text.encode('utf-8')
    
    if raw_bytes == new_bytes:
        summary["noChanges"] = True
        
    summary["updated"].sort(key=lambda x: x["service"])
    summary["unchanged"].sort()
    summary["skipped"].sort(key=lambda x: x["service"])

    if not summary["noChanges"]:
        # Verify resulting YAML before replacing
        verify_yaml = YAML(typ="safe")
        try:
            verified_doc = verify_yaml.load(new_text)
        except Exception as e:
            fail(f"Generated YAML is invalid: {e}")
            
        for svc_info in summary["updated"]:
            svc = svc_info["service"]
            try:
                if svc in TOP_LEVEL_IMAGE_SERVICES:
                    image_values = verified_doc[TOP_LEVEL_IMAGE_SERVICES[svc]]["image"]
                    found_digest = f"sha256:{image_values['sha']}"
                else:
                    nested = NESTED_SIDECAR_SERVICES.get(svc)
                    if nested is None:
                        found_digest = verified_doc["components"][svc]["imageOverride"]["digest"]
                    else:
                        parent_sidecars = verified_doc["components"][nested["component"]]["sidecarContainers"]
                        matches = [s for s in parent_sidecars if isinstance(s, dict) and s.get("name") == nested["sidecar_name"]]
                        if not matches:
                            raise KeyError(nested["sidecar_name"])
                        found_digest = matches[0]["imageOverride"]["digest"]
                if found_digest != svc_info["newDigest"]:
                    fail(f"Semantic verification failed for {svc} digest")
            except KeyError:
                fail(f"Semantic verification failed for {svc} structure")
                
        dir_name = os.path.dirname(values_path)
        fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="values-prod-", suffix=".tmp")
        with os.fdopen(fd, 'wb') as f:
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())
        orig_mode = values_path.stat().st_mode
        os.chmod(temp_path, orig_mode)
        os.replace(temp_path, values_path)

    with open(args.summary_output, "w") as f:
        json.dump(summary, f, indent=2)

if __name__ == "__main__":
    main()

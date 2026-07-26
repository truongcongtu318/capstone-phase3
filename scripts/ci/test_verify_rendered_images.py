import os
import json
import subprocess
import pytest
from pathlib import Path

def run_verifier(rendered, manifest, extra_args=[]):
    cmd = [
        "python3", "scripts/ci/verify-rendered-images.py",
        "--rendered", rendered,
        "--manifest", manifest,
        "--registry", "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com",
        "--repository", "techx-corp",
    ] + extra_args
    return subprocess.run(cmd, capture_output=True, text=True)

def setup_env(tmp_path, manifest_data, rendered_data):
    m_path = tmp_path / "approved-images.json"
    r_path = tmp_path / "rendered.yaml"
    m_path.write_text(json.dumps(manifest_data))
    r_path.write_text(rendered_data)
    return str(r_path), str(m_path)

def valid_manifest():
    return {
        "services": [
            {
                "name": "ad",
                "tag": "123-ad",
                "digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            }
        ]
    }

def test_t45_valid_service_mapping(tmp_path):
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:0000000000000000000000000000000000000000000000000000000000000000
"""
    r, m = setup_env(tmp_path, valid_manifest(), rendered)
    assert run_verifier(r, m).returncode == 0

def test_t45a_wrong_registry(tmp_path):
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - image: malicious.example.com/techx-corp@sha256:0000000000000000000000000000000000000000000000000000000000000000
"""
    r, m = setup_env(tmp_path, valid_manifest(), rendered)
    assert run_verifier(r, m).returncode != 0

def test_t45b_wrong_repository(tmp_path):
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp-shadow@sha256:0000000000000000000000000000000000000000000000000000000000000000
"""
    r, m = setup_env(tmp_path, valid_manifest(), rendered)
    assert run_verifier(r, m).returncode != 0

def test_t45c_exact_match(tmp_path):
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:0000000000000000000000000000000000000000000000000000000000000000
"""
    r, m = setup_env(tmp_path, valid_manifest(), rendered)
    assert run_verifier(r, m).returncode == 0

def test_t45d_sidecar_wrong_app_wrong(tmp_path):
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - name: sidecar
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:0000000000000000000000000000000000000000000000000000000000000000
      - name: ad
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:1111111111111111111111111111111111111111111111111111111111111111
"""
    r, m = setup_env(tmp_path, valid_manifest(), rendered)
    # The script looks at all containers that match repository `techx-corp`.
    # Since both match `techx-corp`, both are checked. The second one fails.
    assert run_verifier(r, m).returncode != 0

def test_t46_expected_workload_missing(tmp_path):
    r, m = setup_env(tmp_path, valid_manifest(), "kind: Deployment\n")
    assert run_verifier(r, m).returncode != 0

def test_t47_wrong_digest(tmp_path):
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:1111111111111111111111111111111111111111111111111111111111111111
"""
    r, m = setup_env(tmp_path, valid_manifest(), rendered)
    assert run_verifier(r, m).returncode != 0

def test_t48_swapped_digest(tmp_path):
    man = valid_manifest()
    man["services"].append({"name": "cart", "tag": "123-cart", "digest": "sha256:111"})
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ad
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:111
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cart
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cart
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:0000000000000000000000000000000000000000000000000000000000000000
"""
    r, m = setup_env(tmp_path, man, rendered)
    assert run_verifier(r, m).returncode != 0

def test_t49_mutable_tag(tmp_path):
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:123-ad
"""
    r, m = setup_env(tmp_path, valid_manifest(), rendered)
    assert run_verifier(r, m).returncode != 0

def test_t51_nested_sidecar_flagd_ui_matched(tmp_path):
    man = {
        "services": [
            {"name": "flagd-ui", "tag": "123-flagd-ui", "digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222"}
        ]
    }
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagd
  labels:
    app.kubernetes.io/name: flagd
spec:
  template:
    spec:
      containers:
      - name: flagd
        image: ghcr.io/open-feature/flagd:v0.12.9
      - name: flagd-ui
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:2222222222222222222222222222222222222222222222222222222222222222
"""
    r, m = setup_env(tmp_path, man, rendered)
    res = run_verifier(r, m)
    assert res.returncode == 0, res.stderr

def test_t52_nested_sidecar_flagd_ui_wrong_digest(tmp_path):
    man = {
        "services": [
            {"name": "flagd-ui", "tag": "123-flagd-ui", "digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222"}
        ]
    }
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagd
  labels:
    app.kubernetes.io/name: flagd
spec:
  template:
    spec:
      containers:
      - name: flagd
        image: ghcr.io/open-feature/flagd:v0.12.9
      - name: flagd-ui
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:3333333333333333333333333333333333333333333333333333333333333333
"""
    r, m = setup_env(tmp_path, man, rendered)
    res = run_verifier(r, m)
    assert res.returncode != 0

def test_t53_nested_sidecar_flagd_ui_missing(tmp_path):
    man = {
        "services": [
            {"name": "flagd-ui", "tag": "123-flagd-ui", "digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222"}
        ]
    }
    # flagd Pod exists but has no flagd-ui container at all.
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagd
  labels:
    app.kubernetes.io/name: flagd
spec:
  template:
    spec:
      containers:
      - name: flagd
        image: ghcr.io/open-feature/flagd:v0.12.9
"""
    r, m = setup_env(tmp_path, man, rendered)
    res = run_verifier(r, m)
    assert res.returncode != 0

def test_t54_nested_sidecar_scoped_to_its_own_parent_pod(tmp_path):
    # A container named flagd-ui living in some OTHER, unrelated workload
    # (not the flagd Pod, and not itself an expected service) must be
    # ignored entirely - only the one actually inside the flagd Pod counts.
    man = {
        "services": [
            {"name": "ad", "tag": "123-ad", "digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000"},
            {"name": "flagd-ui", "tag": "123-flagd-ui", "digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222"},
        ]
    }
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - name: ad
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:0000000000000000000000000000000000000000000000000000000000000000
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: some-other-service
  labels:
    app.kubernetes.io/name: some-other-service
spec:
  template:
    spec:
      containers:
      - name: flagd-ui
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:9999999999999999999999999999999999999999999999999999999999999999
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagd
  labels:
    app.kubernetes.io/name: flagd
spec:
  template:
    spec:
      containers:
      - name: flagd
        image: ghcr.io/open-feature/flagd:v0.12.9
      - name: flagd-ui
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:2222222222222222222222222222222222222222222222222222222222222222
"""
    r, m = setup_env(tmp_path, man, rendered)
    res = run_verifier(r, m)
    assert res.returncode == 0, res.stderr

def test_t50_excluded_service(tmp_path):
    man = valid_manifest()
    man["services"].append({"name": "flagd-ui", "tag": "123-flagd-ui", "digest": "sha256:222"})
    rendered = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ad
  labels:
    app.kubernetes.io/name: ad
spec:
  template:
    spec:
      containers:
      - image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp@sha256:0000000000000000000000000000000000000000000000000000000000000000
"""
    # Excluded service flagd-ui missing from rendered is OK.
    r, m = setup_env(tmp_path, man, rendered)
    assert run_verifier(r, m, ["--excluded-service", "flagd-ui"]).returncode == 0

def test_t55_grafana_tagged_digest_exact_match(tmp_path):
    digest = "sha256:4444444444444444444444444444444444444444444444444444444444444444"
    manifest = {
        "services": [{
            "name": "grafana",
            "tag": "123-grafana",
            "digest": digest,
        }]
    }
    rendered = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/name: grafana
    spec:
      containers:
      - name: grafana
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:123-grafana@{digest}
"""
    r, m = setup_env(tmp_path, manifest, rendered)
    assert run_verifier(r, m).returncode == 0

def test_t56_grafana_wrong_tag_is_rejected(tmp_path):
    digest = "sha256:4444444444444444444444444444444444444444444444444444444444444444"
    manifest = {
        "services": [{
            "name": "grafana",
            "tag": "123-grafana",
            "digest": digest,
        }]
    }
    rendered = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/name: grafana
    spec:
      containers:
      - name: grafana
        image: 197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:wrong@{digest}
"""
    r, m = setup_env(tmp_path, manifest, rendered)
    assert run_verifier(r, m).returncode != 0

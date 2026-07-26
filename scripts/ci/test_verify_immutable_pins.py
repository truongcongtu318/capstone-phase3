import importlib.util
import json
import sys
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("verify_immutable_pins", Path(__file__).with_name("verify-immutable-pins.py"))
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_repository_workflows_and_dockerfiles_are_immutable():
    assert MODULE.verify_workflows() == []
    refs, errors = MODULE.parse_dockerfiles()
    assert errors == []
    assert len(MODULE.dockerfile_paths()) == 29
    assert refs
    assert all("@sha256:" in ref.resolved_image for ref in refs)


def test_workflow_tag_and_missing_comment_fail(tmp_path, monkeypatch):
    workflow_root = tmp_path / "workflows"
    workflow_root.mkdir()
    (workflow_root / "bad.yml").write_text(
        "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n"
    )
    monkeypatch.setattr(MODULE, "WORKFLOW_ROOT", workflow_root)
    errors = MODULE.verify_workflows()
    assert any("not a full SHA" in error for error in errors)
    assert any("version comment" in error for error in errors)


def test_scope_file_covers_every_discovered_dockerfile():
    document = json.loads(MODULE.SCOPE_FILE.read_text())
    paths = {entry["path"] for entry in document["dockerfiles"]}
    assert len(paths) == 29
    assert all(entry["inScope"] is True for entry in document["dockerfiles"])


def test_arg_and_stage_resolution():
    path = Path("/tmp/pm129-arg-test.Dockerfile")
    path.write_text(
        "ARG BASE=alpine:3.21@sha256:" + "a" * 64 + "\n"
        "FROM ${BASE} AS builder\n"
        "ARG TARGETARCH\n"
        "FROM builder AS final\n"
        "FROM final-${TARGETARCH} AS selected\n"
    )
    try:
        args = {"BASE": "alpine:3.21@sha256:" + "a" * 64}
        assert MODULE.resolve_vars("${BASE}", args, path=path, line=2).endswith("a" * 64)
    finally:
        path.unlink()

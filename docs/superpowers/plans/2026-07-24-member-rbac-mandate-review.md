# Member RBAC Mandate Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow TF3 read-only members to inspect Grafana RBAC and run namespace-local authorization reviews without granting Secret reads, impersonation, pod exec, or workload mutation.

**Architecture:** Extend the existing `tf3-production-readonly` Role in `techx-tf3` with namespace-scoped review permissions. Extend the existing cluster read-only ClusterRole with RBAC object reads, preserving the current group bindings and GitOps reconciliation path.

**Tech Stack:** Kubernetes RBAC YAML, Python contract tests, Argo CD GitOps.

## Global Constraints

- Grant `create` only for `localsubjectaccessreviews.authorization.k8s.io` in `techx-tf3`.
- Grant `get,list` for Roles and RoleBindings in `techx-tf3`.
- Grant `get,list` for ClusterRoles and ClusterRoleBindings cluster-wide.
- Do not grant Secret reads, impersonation, `pods/exec`, or workload mutation.
- Do not apply or sync production manually; deliver through PR and Argo CD.

---

### Task 1: Extend and verify the member RBAC contract

**Files:**
- Modify: `scripts/ci/test_production_access_contract.py`
- Modify: `gitops/infrastructure/rbac-production-access.yaml`

**Interfaces:**
- Consumes: Kubernetes group `tf3-production-readers`.
- Produces: namespace-scoped review access in `techx-tf3` and cluster-scoped RBAC metadata reads.

- [ ] **Step 1: Write the failing contract assertions**

Add assertions that the namespaced reader receives:

```python
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
```

Add assertions that the extension ClusterRole grants only `get,list` for `clusterroles` and `clusterrolebindings`.

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
pytest -q scripts/ci/test_production_access_contract.py
```

Expected: assertion failure because the three requested RBAC grants are absent.

- [ ] **Step 3: Add the minimal RBAC rules**

Add these rules to the `tf3-production-readonly` Role:

```yaml
- apiGroups: ["authorization.k8s.io"]
  resources: ["localsubjectaccessreviews"]
  verbs: ["create"]
- apiGroups: ["rbac.authorization.k8s.io"]
  resources: ["roles", "rolebindings"]
  verbs: ["get", "list"]
```

Add this rule to `tf3-production-readonly-cluster-extensions`:

```yaml
- apiGroups: ["rbac.authorization.k8s.io"]
  resources: ["clusterroles", "clusterrolebindings"]
  verbs: ["get", "list"]
```

- [ ] **Step 4: Verify GREEN and render validity**

Run:

```bash
pytest -q scripts/ci/test_production_access_contract.py
kubectl create --dry-run=client --validate=false -f gitops/infrastructure/rbac-production-access.yaml
```

Expected: both commands exit `0`.

- [ ] **Step 5: Review the diff and commit**

Run:

```bash
git diff --check
git diff -- scripts/ci/test_production_access_contract.py gitops/infrastructure/rbac-production-access.yaml
git add docs/superpowers/plans/2026-07-24-member-rbac-mandate-review.md scripts/ci/test_production_access_contract.py gitops/infrastructure/rbac-production-access.yaml
git commit -m "feat(access): allow members to review Grafana RBAC"
```

Expected: one atomic commit containing only the plan, contract test, and RBAC manifest.

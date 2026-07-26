# Mandate 17 connectivity test handoff

The automation file is:

~~~text
scripts/network-policy/mandate-17-connectivity-test.sh
~~~

It performs read and pods/exec checks only. It does not apply or modify
Kubernetes objects.

Run the baseline before any policy is promoted:

~~~bash
./scripts/network-policy/mandate-17-connectivity-test.sh baseline
~~~

After one policy is promoted through GitOps and Argo CD is Synced/Healthy:

~~~bash
./scripts/network-policy/mandate-17-connectivity-test.sh policy 12-payment
~~~

Run the full suite only after all allow policies and
90-default-deny-all.yaml are active:

~~~bash
./scripts/network-policy/mandate-17-connectivity-test.sh full
~~~

The manual source-to-destination matrix is:

~~~text
docs/runbooks/mandate-17-network-policy-test-scenarios.md
~~~

For every policy, attach Argo status, pod readiness, events, PolicyEndpoints,
storefront HTTP 200, allowed-flow output, one denied-flow timeout, and the
manual browse -> add-to-cart -> checkout result.

If a pod has no nc or curl, record BLOCKED: tool unavailable. Do not create a
debug pod unless the administrator separately authorizes it.

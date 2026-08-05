# Mandate #19 after-run assessment

> This directory contains two distinct after-run records. The JSON/HTML
> artifact below is the superseded 9→10→11-node attempt. The canonical run
> referenced by the current report is the later operator-confirmed 7-node
> sequence.

## Outcome

The supplied run is preserved as an **invalid/incomplete after attempt**. It
must not be presented as proof that Mandate #19 passed.

What the source does establish:

- load was increased from 100 to 410 concurrent users;
- point-in-time RPS increased from 20.5 to 81.8;
- frontend HPA increased from 2 to 5 replicas;
- frontend-proxy HPA increased from 2 to 3 replicas;
- the final cumulative Locust snapshot shows 7,915 checkout requests, one
  failure and checkout p99 of 490 ms;
- a frontend pod remained Pending for at least 8m49s.

What invalidates the same-infrastructure comparison:

- node count changed from 9 to 10 and then 11;
- node identities also changed between snapshots;
- therefore neither a valid after ceiling nor RPS/node improvement can be
  calculated from this run.

## Before/after comparison

| Measure | Before | After |
|---|---:|---:|
| Highest offered users | 400 observed | 410 observed |
| Peak served RPS holding SLO | Not established | Not established |
| Highest current RPS observed | 76.2 at 400 users | 81.8 at 410 users |

`76.2 RPS` and `81.8 RPS` are point-in-time Locust readings. Neither value may
be presented as a sustained SLO-holding ceiling. The after run also changed
its node set, so the two snapshots cannot support a density-improvement claim.

## Canonical 7-node run (current report)

The operator record states that the later run kept the node count at **7 for
the full stage sequence** (10, 300, 350, 400, 410, 500, 600, 700, 800 and 900
users). HPA replicas increased on those existing nodes; no node was added
during the run. The stage-level observations and screenshots are recorded in
[`docs/../../../mandates/mandate-19/mandate-19-throughput-ceiling-report.md`](../../../mandates/mandate-19/mandate-19-throughput-ceiling-report.md#54-nhật-ký-stage-after).
The checkpoint image
[`node-350-user.jpg`](../../../tests/kyverno/mandate-19/test_slo_after/node-350-user.jpg)
shows `Node count — Mean: 7, Max: 7` for the visible Last-1-hour window. It
directly verifies the 10–400-user screenshot window; later stages remain
operator-record evidence unless a separate node timeline is attached.

This 7-node statement supersedes the invalid 9→10→11-node attempt for the
within-run node-invariance claim. A machine-verifiable 7-node before/after
`kubectl get nodes -o json` pair and matching hash should still be attached if
the mentor requires independently reproducible infrastructure evidence.

## Evidence still required for a strict Directive #19 PASS

Provide the following for a valid rerun:

1. Run identity:
   - Git SHA;
   - frontend and frontend-proxy image digests;
   - exact UTC start/end per stage;
   - Locust version, command and load-profile SHA.
2. Fixed infrastructure:
   - `kubectl get nodes -o json` before and after;
   - node identity hash sampled during the run;
   - Karpenter NodeClaim create/delete events;
   - mark the run invalid immediately if any node joins, leaves or is replaced.
3. Canonical traffic and raw load output:
   - 70% shedable browse (`/` and `/api/products`);
   - 20% cart;
   - 10% protected checkout journey;
   - headless Locust CSV for every stage;
   - load-generator CPU/network to prove the generator is not the bottleneck.
4. Exact-window SLO exports:
   - browse success and p95;
   - cart success;
   - checkout success and approved p99 threshold;
   - unexpected 5xx/timeouts;
   - one-minute samples for every sustained five-minute stage.
5. Saturation evidence:
   - HPA current/desired/Ready replicas and conditions over time;
   - per-pod CPU, memory and CPU-throttling ratio;
   - Pending reason from `kubectl describe pod` and scheduler events;
   - Envoy active/pending/overflow counters;
   - downstream connection-pool/queue-depth metrics.
6. Graceful-degradation run above the new ceiling:
   - enforcement percentage and effective per-proxy token-bucket capacity;
   - browse 429 count/RPS;
   - `x-techx-load-shed: browse`;
   - `x-envoy-ratelimited: true`;
   - Envoy `rate_limited` and `enforced` counter deltas;
   - zero 429 on `/api/cart`, `/api/checkout` and `/api/products/<id>`;
   - checkout success/p99 while browse is shed;
   - no OOM/restart/node change and successful recovery after load drops.

## Required rerun decision

Use the highest five-minute stage that passes every approved SLO in every
one-minute window as the new ceiling. Reproduce that passing stage and the
first failing stage once. Only then calculate:

```text
after_density = after_ceiling_served_rps / fixed_node_count
improvement_percent = ((after_density / before_density) - 1) * 100
```

Intentional browse 429 responses must be reported separately and must not be
counted as successfully served business throughput.

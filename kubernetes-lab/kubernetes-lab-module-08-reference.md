# Kubernetes Lab — Module 8 Reference
## Production Patterns — Resource Management, HPA, PDBs, Rolling Updates, Node Affinity

**Track:** Kubernetes — Comprehensive Coverage
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster (4 nodes)
**Date Completed:** May 1, 2026

---

## Business Context

The e-commerce cluster entered this module with no resource constraints on any workload. Every Pod was `BestEffort` QoS — the database was as expendable as the log collector from the scheduler's perspective. Under memory pressure, postgres would be the first workload evicted. There were no scaling controls, no availability guarantees during maintenance, and no placement constraints preventing both product-catalog replicas from landing on the same node.

Module 8 establishes the production-readiness layer: resource boundaries that give the scheduler real data, autoscaling that responds to real load, availability guarantees during voluntary disruption, and placement rules that enforce fault isolation.

---

## Session Notes — Instruction Quality Issues

Two issues occurred this session that are documented here for transparency and to inform future sessions:

**1. Patch approach failure:** The initial approach to adding resources to postgres used `kubectl patch --patch-file` with a full container spec. Strategic merge patch on StatefulSet containers with `valueFrom` env entries is unreliable — it corrupted the env block and volumeMounts. The correct approach for targeted field changes is `kubectl patch --type=json`, which was used successfully for subsequent workloads. For declarative manifest management, maintain lean authored manifests rather than round-tripping through `kubectl get -o yaml`.

**2. HPA interference in failure scenario:** The Pending Pod failure scenario was designed without accounting for the active HPA, which cleaned up the 4th replica before it could be observed in `Pending` state. The correct procedure is to suspend or pin the HPA before running failure demonstrations that involve replica count manipulation. This is documented in the learning preferences document as a process requirement for future sessions.

---

## Pre-existing Version Mismatch — Discovered This Module

**Issue:** The postgres StatefulSet spec had `image: postgres:15` but the data directory on the PVC was initialized by PostgreSQL 16. This mismatch predates Module 8 — the spec and the running container diverged at some point earlier in the track.

**Discovery:** The patch operation terminated postgres-0 and attempted to start it with postgres:15, which failed immediately:
```
FATAL: database files are incompatible with server
DETAIL: The data directory was initialized by PostgreSQL version 16
```

**Resolution:** Updated StatefulSet image to `postgres:16` to match the data directory. This is the correct fix — downgrading a data directory is not supported by PostgreSQL.

**Version integrity violation:** Per track conventions, the pinned version in the manifest must match the running version. This was not enforced at some earlier point in the track. Going forward, postgres is pinned to `postgres:16`.

---

## [COMPUTE] Resource Requests and Limits

### Concepts

**Request** — the scheduler uses this value for placement decisions. A Pod will only be scheduled on a node that has at least this much unallocated capacity. This is a reservation, not a runtime cap.

**Limit** — enforced at runtime by the container runtime via Linux cgroups. Behavior differs by resource type:

| Resource | At limit behavior | Failure signature |
|---|---|---|
| CPU | Throttled — process continues, gets less CPU time | Silent latency degradation |
| Memory | OOM killed — container terminated and restarted | Pod restarts, loud failure |

CPU is compressible — it can be throttled without termination. Memory is incompressible — exceeding the limit terminates the container.

### Units

**CPU:** Millicores. `1000m` = 1 full CPU core. `250m` = one quarter core. These are standard Linux cgroup units, not Kubernetes-specific — the same values appear in Docker, systemd, and cloud provider instance specs.

**Memory:** Bytes with binary suffixes. Always use `Mi` (mebibytes, 2²⁰ = 1,048,576 bytes) not `M` (megabytes, 1,000,000 bytes). Linux and Kubernetes report memory in mebibytes — using `Mi` ensures the manifest matches what the kernel tracks.

### QoS Classes

Kubernetes derives a QoS class from how requests and limits are configured. The class determines eviction priority under node memory pressure — `BestEffort` Pods are evicted first.

| Class | Condition | Eviction priority |
|---|---|---|
| `Guaranteed` | Every container has requests == limits, both set | Last evicted |
| `Burstable` | Requests set but less than limits, or partial | Middle |
| `BestEffort` | No requests or limits on any container | First evicted |

**Initial state — all workloads BestEffort:**
```
NAME                             QOS
log-collector-*                  BestEffort
postgres-0                       BestEffort
product-catalog-*                BestEffort
```

**Target state — correct class per workload:**
- `postgres` → `Guaranteed`: database must never be unexpectedly throttled or evicted
- `product-catalog` → `Burstable`: needs headroom above baseline to handle traffic spikes
- `log-collector` → `Burstable`: not on critical path, can tolerate throttling

### Eviction Behavior

Eviction is the kubelet protecting the node — it terminates Pods to relieve memory pressure. Eviction and rescheduling are independent operations:

1. kubelet evicts the Pod (no scheduler consultation)
2. The owning controller (Deployment, StatefulSet, DaemonSet) creates a replacement Pod object
3. The scheduler attempts placement on any available node
4. If no node has sufficient resources, the Pod sits `Pending` indefinitely

There is no pre-eviction check for available capacity elsewhere. A `Pending` Pod stays pending until resources free up or a new node joins. This is one of the production arguments for Cluster Autoscaler — it provisions new nodes in response to `Pending` Pods.

### What Was Built

**postgres — Guaranteed QoS:**
```yaml
resources:
  requests:
    cpu: "250m"
    memory: "256Mi"
  limits:
    cpu: "250m"
    memory: "256Mi"
```
Requests equal limits → `Guaranteed`. Applied via `kubectl edit` after patch approach failed.

**product-catalog — Burstable QoS:**
```yaml
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "256Mi"
```
Requests below limits → `Burstable`. Applied via `kubectl patch --type=json`.

**log-collector — Burstable QoS:**
```yaml
resources:
  requests:
    cpu: "50m"
    memory: "32Mi"
  limits:
    cpu: "100m"
    memory: "64Mi"
```
DaemonSet — resource sizing has a 4x multiplier across the cluster (one Pod per node).

**Final QoS state:**
```
NAME                               QOS
log-collector-csks6                Burstable   (control-plane)
log-collector-jtj84                Burstable   (worker)
log-collector-nxkdw                Burstable   (worker2)
log-collector-cmzfz                Burstable   (worker3)
postgres-0                         Guaranteed
product-catalog-586c8594d6-4tpc4   Burstable
product-catalog-586c8594d6-njg47   Burstable
```

### Node Resource Accounting — Before and After

Before (ecommerce-lab-worker3, no requests set):
```
Resource    Requests    Limits
cpu         200m (0%)   100m (0%)   ← monitoring stack only
memory      140Mi (0%)  50Mi (0%)
```

After (ecommerce-lab-worker3, postgres + product-catalog requests applied):
```
Resource    Requests     Limits
cpu         350m (1%)    350m (1%)
memory      506Mi (1%)   306Mi (0%)
```

The scheduler now has real data. `350m` CPU = postgres (`250m`) + product-catalog replica (`100m`) + monitoring components.

---

## [COMPUTE] Horizontal Pod Autoscaler (HPA)

### Business Problem

Static replica counts waste resources at low traffic and fail under spikes. Manual scaling is always reactive. HPA automates replica count adjustment based on observed metrics.

### How It Works

HPA watches a metric, compares it to a target, and adjusts replicas to converge toward the target:

```
desired replicas = ceil(current replicas × (current metric / target metric))
```

`ceil` = ceiling function — rounds up to the nearest whole number. 3.2 replicas → 4. HPA always rounds up, never down.

**Scale-up:** Reacts within ~30 seconds of metric threshold breach.
**Scale-down:** Default 5-minute stabilization window before reducing replicas — prevents flapping when load drops briefly.

### metrics-server

HPA requires metrics-server — a lightweight component that exposes per-Pod CPU and memory usage via the Kubernetes metrics API. Distinct from Prometheus:

| Component | Purpose | Consumer |
|---|---|---|
| metrics-server | Live resource usage, short retention | HPA, `kubectl top` |
| Prometheus | Historical metrics, long retention, alerting | Dashboards, alerts |

**Installation:** Helm chart from `kubernetes-sigs/metrics-server`.

```bash
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm install metrics-server metrics-server/metrics-server \
  -n kube-system \
  -f module-08/metrics-server-override.yaml
```

**kind-specific override** (`module-08/metrics-server-override.yaml`):
```yaml
args:
  - --kubelet-insecure-tls
```

kind kubelets use self-signed certificates that metrics-server rejects by default. `--kubelet-insecure-tls` bypasses this. **This flag is not needed in EKS** — kubelets have valid certificates issued by the cluster CA.

**Node metrics observed:**
```
NAME                          CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)
ecommerce-lab-control-plane   120m         0%       1035Mi          3%
ecommerce-lab-worker          45m          0%       928Mi           2%
ecommerce-lab-worker2         34m          0%       349Mi           1%
ecommerce-lab-worker3         40m          0%       776Mi           2%
```

Control-plane memory higher due to API server, etcd, scheduler, and controller-manager running there.

### What Was Built

**File:** `module-08/product-catalog-hpa.yaml`

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: product-catalog-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: product-catalog
  minReplicas: 2
  maxReplicas: 6
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50
```

`minReplicas: 2` — never scale below 2, availability maintained at all times.
`maxReplicas: 6` — hard ceiling, prevents runaway scaling.
`averageUtilization: 50` — scale up when average CPU across all replicas exceeds 50% of their CPU request.

### Load Test Results

Load generator: `busybox` Pod running continuous `wget` against `product-catalog.default.svc.cluster.local`.

| State | Replicas | CPU |
|---|---|---|
| Idle | 2 | 0% |
| Under load | 3 | 35–40% |
| Load removed (after stabilization window) | 2 | 1% |

HPA scaled from 2 → 3 when CPU exceeded 50% threshold across 2 replicas. CPU stabilized at 35–40% across 3 replicas — below threshold, HPA held at 3. After load removal, 5-minute stabilization window elapsed, then scale-down to 2.

---

## [COMPUTE] Pod Disruption Budgets (PDB)

### Business Problem

Node drain for maintenance evicts all Pods on a node simultaneously. Without a PDB, both product-catalog replicas could be evicted at once if they share a node — checkout goes down during maintenance.

### Voluntary vs Involuntary Disruption

**Voluntary** — node drain, cluster upgrade, manual Pod deletion. PDBs apply — the operation coordinates with the PDB before proceeding.

**Involuntary** — hardware failure, OOM kill, kernel panic. PDBs do not apply — the node is gone, there is no coordination possible.

PDBs are a coordination mechanism, not a fault tolerance mechanism. Fault tolerance requires sufficient replicas distributed across nodes.

### minAvailable vs maxUnavailable

**`minAvailable`** — minimum Pods that must remain available during disruption.
**`maxUnavailable`** — maximum Pods that can be unavailable during disruption.

For a 2-replica Deployment both expressions are equivalent. For larger Deployments they diverge — `maxUnavailable: 25%` scales with replica count, `minAvailable: 1` does not. When HPA is in play, `minAvailable` is the more appropriate expression because `ALLOWED DISRUPTIONS` recalculates dynamically as replica count changes.

**Correct sizing requires knowing the application** — minimum viable replica count under peak load, SLO requirements, and acceptable availability reduction during maintenance windows. These numbers should come from architecture and load testing, not guesswork.

### What Was Built

**File:** `module-08/product-catalog-pdb.yaml`

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: product-catalog-pdb
  namespace: default
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: product-catalog
```

**Observed state:**
```
NAME                  MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
product-catalog-pdb   1               N/A               1
```

`ALLOWED DISRUPTIONS: 1` — computed as current replicas (2) minus minAvailable (1). When HPA scales to 3 replicas, this automatically recalculates to 2.

---

## [COMPUTE] Rolling Update Strategy

### How It Works

A Deployment rolling update creates a new ReplicaSet, incrementally shifts traffic, and terminates the old ReplicaSet. The process is controlled by two fields:

**`maxSurge`** — how many extra Pods above desired replica count can exist during rollout. `maxSurge: 1` on a 2-replica Deployment allows a temporary 3rd Pod before any old Pod is terminated — never drops below desired count, costs extra resources briefly.

**`maxUnavailable`** — how many Pods can be below desired count during rollout. `maxUnavailable: 1` allows one Pod to be terminated before its replacement is ready — briefly under-capacity, no extra resource cost.

### Strategy Tradeoffs

| Configuration | Behavior | Use when |
|---|---|---|
| `maxSurge: 1, maxUnavailable: 0` | Never drops below desired, temporarily N+1 | Strict SLO, resources available |
| `maxSurge: 0, maxUnavailable: 1` | Never exceeds desired, briefly N-1 | Resource-constrained environment |
| `maxSurge: 1, maxUnavailable: 1` | Fastest rollout, simultaneous create and terminate | Lab/dev, no strict SLO |

**SLO relationship:** `maxUnavailable: 1` on a 2-replica Deployment means 50% capacity reduction during rollout. On a 10-replica Deployment the same setting is 10% reduction. Strategy selection must be anchored to SLO requirements and replica count — not set arbitrarily.

Kubernetes default: `maxSurge: 25%`, `maxUnavailable: 25%`.

### What Was Built

**File:** `module-08/product-catalog-deployment.yaml`

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 1
```

Lab environment with no SLO — fastest rollout strategy. Rollout output confirmed expected behavior:
```
Waiting for deployment "product-catalog" rollout to finish: 1 out of 2 new replicas have been updated...
Waiting for deployment "product-catalog" rollout to finish: 1 old replicas are pending termination...
deployment "product-catalog" successfully rolled out
```

---

## [COMPUTE] Node Affinity, Taints, and Tolerations

### Concepts

Two complementary mechanisms for workload placement control:

**Taints and Tolerations** — the node controls who is allowed on it. A taint repels all Pods that don't explicitly tolerate it. Used to reserve nodes for specific workloads or keep workloads off certain nodes.

**Affinity** — the Pod declares where it wants to go. Two flavors:
- `requiredDuringSchedulingIgnoredDuringExecution` — hard requirement, Pod won't schedule if no matching node exists
- `preferredDuringSchedulingIgnoredDuringExecution` — soft preference, scheduler honors if possible but won't block scheduling

**Used together for complete placement guarantees:**
- Taint keeps unwanted workloads off a node
- Affinity ensures the intended workload actively targets that node
- Neither alone is sufficient for hard placement guarantees

### Control-Plane Taint

```
node-role.kubernetes.io/control-plane:NoSchedule
```

All workloads are blocked from the control-plane node by default. `log-collector` requires a toleration to run there as a DaemonSet:

```yaml
tolerations:
- key: "node-role.kubernetes.io/control-plane"
  operator: "Exists"
  effect: "NoSchedule"
```

This was lost when rewriting the log-collector manifest earlier in the module and had to be restored. In EKS, worker nodes do not carry this taint — it is specific to control-plane nodes.

### Pod Anti-Affinity

**Problem:** Without placement constraints, both product-catalog replicas could land on the same node. A node failure would take both replicas simultaneously — the PDB cannot help with involuntary disruption.

**Solution:** Pod anti-affinity prevents a Pod from being scheduled on a node that already runs a Pod matching the selector.

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: product-catalog
      topologyKey: "kubernetes.io/hostname"
```

`topologyKey: kubernetes.io/hostname` — "different location" means different nodes.

**In EKS production:** Use `topology.kubernetes.io/zone` to spread replicas across availability zones instead of just nodes.

**Verified placement:**
```
product-catalog-78789d6fc8-rkfbq   ecommerce-lab-worker3
product-catalog-78789d6fc8-v245l   ecommerce-lab-worker2
```

Two replicas, two different nodes. Anti-affinity enforced.

---

## Failure Scenario — Anti-Affinity Scheduling Conflict

**Production framing:** Anti-affinity added to a Deployment without enough nodes to satisfy the constraint. New Pods sit `Pending` indefinitely. Silent failure — no application error, no crash, no CrashLoopBackOff. The Deployment reports fewer replicas than desired, noticed only if someone is watching Pod counts or has availability alerting.

**What was attempted:** Scaling product-catalog to 4 replicas against 3 available worker nodes (control-plane has untolerated taint).

**Expected scheduler event:**
```
0/4 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: },
3 node(s) didn't match pod anti-affinity rules.
```

**Note:** The Pending Pod was cleaned up by the active HPA before it could be directly observed. The HPA was not suspended before running the failure scenario — a process error. Future failure demonstrations involving replica count must suspend or pin the HPA first.

**Detection commands:**
```bash
kubectl get pods -n default
kubectl get pods -n default --field-selector=status.phase=Pending
kubectl describe pod <pending-pod> -n default  # scheduler event shows reason
```

**Break-it exercise:** Skipped by student preference. The Zenoss → Kubernetes migration project will produce real anti-affinity scenarios with production constraints — a more meaningful context for this failure pattern than a lab exercise.

---

## Manifest Hygiene — Lessons From This Module

**Strategic merge patch is unreliable for StatefulSet containers with complex env blocks.** The `valueFrom` structure (configMapKeyRef, secretKeyRef) does not merge predictably. Use `kubectl patch --type=json` for targeted field changes, or maintain authored manifests applied with `kubectl apply`.

**Do not round-trip through `kubectl get -o yaml` for manifest authoring.** Exported manifests include cluster metadata, status fields, and managed fields that pollute the file and complicate diffs. Maintain lean authored manifests as the source of truth.

**`kubectl patch --type=json` is the correct tool for targeted field changes.** JSON patch operations (`add`, `replace`, `remove`) are unambiguous and do not depend on YAML indentation:

```bash
kubectl patch deployment product-catalog -n default --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/containers/0/resources",
    "value": {
      "requests": {"cpu": "100m", "memory": "128Mi"},
      "limits": {"cpu": "500m", "memory": "256Mi"}
    }
  }
]'
```

---

## Repository State

**Branch:** `module-08`

**Files added:**
```
module-08/
├── metrics-server-override.yaml     # kind-specific kubelet-insecure-tls flag
├── metrics-server-values.yaml       # full default values from helm show values
├── postgres-resources.yaml          # StatefulSet patch (resources only)
├── product-catalog-resources.yaml   # Deployment export with resources added
├── product-catalog-hpa.yaml         # HPA, minReplicas 2, maxReplicas 6, cpu 50%
├── product-catalog-pdb.yaml         # PDB, minAvailable 1
└── product-catalog-deployment.yaml  # Full deployment with strategy + anti-affinity
```

**Commits:**
```
module-08: add resource requests and limits to postgres and product-catalog
module-08: add resource requests and limits to log-collector, restore control-plane toleration
module-08: add HPA for product-catalog, install metrics-server via Helm
module-08: add PDB for product-catalog
module-08: explicit rolling update strategy on product-catalog deployment
module-08: add pod anti-affinity to product-catalog deployment
module-08: complete - resources, HPA, PDB, rolling updates, anti-affinity
```

---

## Diagnostic Command Reference

| Command | Hierarchy | Purpose |
|---|---|---|
| `kubectl get pods -o custom-columns="NAME:.metadata.name,QOS:.status.qosClass"` | COMPUTE | Show QoS class per Pod |
| `kubectl describe node <name> \| grep -A 10 "Allocated resources"` | COMPUTE | Node resource accounting |
| `kubectl top nodes` | COMPUTE | Live node CPU/memory consumption |
| `kubectl top pods -n <ns>` | COMPUTE | Live Pod CPU/memory consumption |
| `kubectl get hpa -n <ns>` | COMPUTE | HPA status, current vs target metric |
| `kubectl get pdb -n <ns>` | LOGICAL | PDB allowed disruptions |
| `kubectl rollout status deployment <name> -n <ns>` | COMPUTE | Rolling update progress |
| `kubectl get pods --field-selector=status.phase=Pending` | COMPUTE | Find stuck Pods |
| `kubectl describe pod <name> \| grep -A 5 "Events:"` | COMPUTE | Scheduling failure reasons |
| `kubectl get pods -o custom-columns="NAME:.metadata.name,NODE:.spec.nodeName"` | COMPUTE | Pod placement per node |

---

## Advanced Topics List

*Carried forward from Modules 1–7, additions from Module 8 marked with **[New]**:*

- Internal mechanics of control plane components
- etcd quorum, split-brain failure modes
- Context management tooling
- CNI plugin comparison, eBPF networking, AWS VPC CNI
- Spot instance node management
- Namespace resource quotas
- GitOps — ArgoCD, Flux
- Kubernetes audit logging
- Container image size best practices
- Cluster event persistence
- Provisioning tools module
- PostgreSQL HA, backup strategy
- Multi-container Pod patterns
- Descheduler, Pod priority classes
- Cluster Autoscaler
- Job and CronJob controllers
- Kubernetes Gateway API, service mesh
- Network access restrictions, port-forward for debugging
- kube-proxy vs Cilium eBPF, NodeLocal DNSCache
- CoreDNS configuration, external DNS
- Helm package manager — advanced usage
- Supply chain security, MetalLB
- Compliance storage patterns, volume snapshots
- EBS CSI driver, storage performance
- Namespace termination failures, CSI drivers
- Sealed Secrets, External Secrets Operator, Vault
- Secret rotation, Reloader operator
- KMS encryption for etcd
- nginx Ingress Controller metrics
- Loki + Grafana Alloy deployment
- Grafana Alloy configuration
- Thanos — long-term metrics storage
- Mimir — horizontally scalable Prometheus-compatible backend
- VictoriaMetrics Operator
- Prometheus federation
- OpenTelemetry instrumentation
- Grafana service graph panel
- Backstage service catalog
- SLO-based alerting with Sloth
- Exemplar-based metric-to-trace linking
- Grafana dashboard provisioning
- Hierarchical Namespace Controller (HNC)
- eBPF-based observability — Pixie, Cilium Hubble
- Datadog, Dynatrace, New Relic Kubernetes integration patterns
- Alert routing and Alertmanager configuration
- OIDC and Kubernetes authentication
- Certificate-based authentication
- OPA Gatekeeper / Kyverno
- PodSecurity admission
- automountServiceAccountToken: false
- audit2rbac
- **[New]** VPA — Vertical Pod Autoscaler, automatic right-sizing of resource requests
- **[New]** HPA on custom metrics — scaling on application-level metrics via Prometheus Adapter
- **[New]** Pod topology spread constraints — finer-grained distribution control beyond anti-affinity
- **[New]** Node affinity for dedicated node pools — taint + affinity pattern for postgres isolation
- **[New]** Graceful termination — preStop hooks, terminationGracePeriodSeconds, SIGTERM handling
- **[New]** PodDisruptionBudget with percentage expressions — maxUnavailable: 25% for large Deployments
- **[New]** Cluster Autoscaler integration with HPA — node provisioning triggered by Pending Pods

---

*Module 9: EKS — multi-node behavior, load balancer provisioning, managed add-ons*

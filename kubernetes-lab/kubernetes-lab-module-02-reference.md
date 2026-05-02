# Kubernetes Lab — Module 2 Reference
## Workloads — Controllers

**Track:** Kubernetes — Comprehensive Coverage
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster (2 nodes)
**Date Completed:** April 23, 2026

---

## Business Context

The e-commerce application's product catalog was running as a naked Pod — no recovery, no replica management, no controlled updates. A single Pod failure meant the product catalog was unavailable to customers until manually restarted. This module promotes all workloads to the appropriate controllers, providing self-healing, replica management, and controlled rollouts.

---

## Version Set (Unchanged from Module 1)

| Component | Version |
|-----------|---------|
| Docker | 29.4.0 |
| kubectl | v1.32.13 |
| kind | v0.27.0 |
| Kubernetes (cluster) | v1.32.3 |
| Node image | kindest/node:v1.32.3 |
| PostgreSQL | 16.3 |
| containerd (worker node) | 2.0.3 |

---

## Cluster Configuration Change

Module 2 introduced a worker node. kind does not support adding nodes to a running cluster — the cluster was recreated.

**Lab deviation from production:** In production, nodes are added dynamically without cluster recreation. On EKS, nodes are added via autoscaling groups. The DaemonSet scheduling behavior observed in this module is identical regardless of how the node was added.

**Multi-node kind config:**

**File:** `~/kubernetes-lab/module-02/kind-config-multinode.yaml`

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ecommerce-lab
nodes:
  - role: control-plane
  - role: worker
```

**Verified nodes:**
```
NAME                          STATUS   ROLES           AGE   VERSION
ecommerce-lab-control-plane   Ready    control-plane   85s   v1.32.3
ecommerce-lab-worker          Ready    <none>          70s   v1.32.3
```

**Worker node ROLES column shows `<none>`** — normal for kind. Production clusters label worker nodes with role or purpose tags to support scheduling decisions.

---

## What is a Pod

A Pod is the smallest deployable unit in Kubernetes. It is not a container — it is a wrapper around one or more containers that share network and storage context.

**What makes up a Pod:**
- **One or more containers** — most Pods run a single container. Multi-container Pods are used for specific patterns.
- **Shared network namespace** — all containers in a Pod share the same IP and port space. They communicate over localhost.
- **Shared storage (volumes)** — containers in a Pod can mount the same volumes.
- **A lifecycle** — Pods are not restarted in place. When a Pod dies the controller creates a new one with a new IP and fresh filesystem.

**Multi-container Pod patterns:**
- **Sidecar** — helper container augmenting the main container. OpenTelemetry collectors are frequently deployed as sidecars.
- **Init container** — runs to completion before the main container starts. Used for setup tasks — waiting for a database, running schema migrations.
- **Ambassador** — proxies traffic on behalf of the main container. Appears in service mesh patterns.

**Pod IP is ephemeral.** Every new Pod gets a new IP. This is why Services exist — covered in Module 3.

---

## Container Runtime

Kubernetes talks to container runtimes through the **Container Runtime Interface (CRI)**. The runtime is pluggable.

**Verified on ecommerce-lab-worker:** `containerd://2.0.3`

**Actual nesting on the lab laptop:**
```
Pop!_OS laptop (host)
  └── Docker container (ecommerce-lab-worker — the "node")
        └── containerd (container runtime inside the node)
              └── container (e.g. postgres — the Pod container)
                    └── application process (e.g. PostgreSQL)
```

**Runtimes encountered in production:**

| Runtime | Usage |
|---------|-------|
| containerd | Current standard. Default in kind, EKS, GKE, AKS. |
| CRI-O | Lightweight, built for Kubernetes. Common in OpenShift. |
| Docker (dockershim) | Removed in Kubernetes 1.24. Docker uses containerd underneath. |
| gVisor | Sandboxed runtime for high-security multi-tenant environments. |
| Kata Containers | Runs containers in lightweight VMs for stronger isolation. |

---

## Controllers Overview

| Controller | Manages | Use Case |
|------------|---------|----------|
| Deployment | ReplicaSet → Pods | Stateless workloads. Standard choice for application services. |
| ReplicaSet | Pods | Replica enforcement. Rarely used directly — Deployments manage them. |
| DaemonSet | Pods (one per node) | Cluster-wide concerns — log collectors, metrics agents, network plugins. |
| StatefulSet | Pods (ordered, stable identity) | Stateful workloads requiring stable identity and persistent storage per Pod. |

**Deployment is built on top of ReplicaSet.** StatefulSet and DaemonSet manage Pods directly — they do not use ReplicaSets underneath.

---

## Deployment — Product Catalog

### Business Context

A naked Pod has no self-healing. If it dies, it stays dead. A Deployment ensures the desired number of replicas are always running and adds controlled rollout capability.

### Demonstrated — Naked Pod Death

The naked Pod from Module 1 was deleted manually:
```bash
k delete pod product-catalog
k get pods
# No resources found in default namespace.
```
No recovery. Product catalog unavailable. This is the problem a Deployment solves.

### Lab Deviation from Production

**Lab:** `hashicorp/http-echo:0.2.3` used as a stand-in for a real product catalog service.
**Production:** A real application image with health checks, resource requests and limits, and liveness/readiness probes defined. Covered in Module 8.

### Manifest

**File:** `~/kubernetes-lab/module-02/product-catalog-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: product-catalog
  labels:
    app: product-catalog
spec:
  replicas: 2
  selector:
    matchLabels:
      app: product-catalog
  template:
    metadata:
      labels:
        app: product-catalog
    spec:
      containers:
        - name: product-catalog
          image: hashicorp/http-echo:0.2.3
          args:
            - "-text=product-catalog service - version 1.0"
          ports:
            - containerPort: 5678
```

**Key fields:**
- `replicas: 2` — desired replica count. ReplicaSet enforces this continuously.
- `selector.matchLabels` — how the Deployment identifies its Pods. Must match `template.metadata.labels` exactly. Mismatch is caught by server-side dry-run validation.
- `template` — the Pod definition. Identical to a naked Pod spec, wrapped in controller management.

### Verified State

```
NAME                                   READY   STATUS    RESTARTS   AGE
product-catalog-8686488fd9-dbwzz       1/1     Running   0          158m
product-catalog-8686488fd9-pttxn       1/1     Running   0          158m
```

**Pod naming convention:** `[deployment-name]-[replicaset-hash]-[pod-id]`
Every Pod name traces back through the ReplicaSet to the Deployment that owns it.

### Self-Healing — Demonstrated

Pod `product-catalog-8686488fd9-lvlz7` was manually deleted. ReplicaSet created replacement `product-catalog-8686488fd9-n7bpw` automatically within seconds. No human intervention. Product catalog remained at 2 replicas throughout.

**ReplicaSet events confirming recovery:**
```
Normal  SuccessfulCreate  replicaset-controller  Created pod: product-catalog-8686488fd9-lvlz7
Normal  SuccessfulCreate  replicaset-controller  Created pod: product-catalog-8686488fd9-w4r7x
Normal  SuccessfulCreate  replicaset-controller  Created pod: product-catalog-8686488fd9-n7bpw
```

### Scaling

**Manual:**
```bash
k scale deployment product-catalog --replicas=4
```
Takes effect immediately. No downtime.

**Automatic — Horizontal Pod Autoscaler (HPA):**
Watches CPU/memory metrics and adjusts replica count automatically. Covered in Module 8. Requires metrics-server.

---

## ReplicaSet

A ReplicaSet has one job: ensure a specified number of Pod replicas are running at all times.

**Rarely used directly.** A Deployment wraps a ReplicaSet and adds rollout management — controlled updates, rollback capability, revision history. There is almost never a reason to create a ReplicaSet directly.

**The ReplicaSet hash changes when the Pod spec changes.** This is how Deployments manage rolling updates — a new ReplicaSet is created for the new spec, the old one is scaled down as the new one scales up.

**Retained ReplicaSets** at zero replicas are kept for rollback capability. Count controlled by `revisionHistoryLimit` (default 10). Covered in Module 8.

**Diagnostic hierarchy:**
- Deployment events → scaling and rollout actions
- ReplicaSet events → individual Pod creation and deletion
- Pod events → scheduling, image pulling, container start/failure

---

## DaemonSet — Log Collector

### Business Context

Log collection must run on every node without exception. A gap in node coverage is a gap in observability. In regulated environments it can be a compliance violation. DaemonSets ensure exactly one Pod per node, automatically scheduling onto new nodes as they join.

### Connection to Observability Track

The Prometheus node exporter is always deployed as a DaemonSet. One instance per node, collecting host-level metrics. This pattern will be used directly in Module 6.

### Existing DaemonSets (kube-system)

```
NAME         DESIRED   CURRENT   READY   NODE SELECTOR
kindnet      1         1         1       kubernetes.io/os=linux
kube-proxy   1         1         1       kubernetes.io/os=linux
```

Both are DaemonSets — observed running since Module 1. `NODE SELECTOR: kubernetes.io/os=linux` prevents scheduling on Windows nodes in mixed OS clusters.

### Taint and Toleration — Control Plane Scheduling

**Problem observed:** Initial DaemonSet deployment produced DESIRED 2, READY 1. The control plane node was not receiving a Pod.

**Cause:** Control plane node carries a taint:
```
Taints: node-role.kubernetes.io/control-plane:NoSchedule
```

A taint repels Pods unless they declare a matching toleration. Regular application workloads should never run on the control plane — this taint enforces that automatically. A log collector however should run on every node including the control plane.

**Resolution:** Added toleration to the DaemonSet manifest.

### Final Manifest

**File:** `~/kubernetes-lab/module-02/log-collector-daemonset.yaml`

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: log-collector
  labels:
    app: log-collector
spec:
  selector:
    matchLabels:
      app: log-collector
  template:
    metadata:
      labels:
        app: log-collector
    spec:
      tolerations:
        - key: "node-role.kubernetes.io/control-plane"
          operator: "Exists"
          effect: "NoSchedule"
      containers:
        - name: log-collector
          image: hashicorp/http-echo:0.2.3
          args:
            - "-text=log-collector running on node"
          ports:
            - containerPort: 5678
```

### Verified State

```
NAME            DESIRED   CURRENT   READY   NODE SELECTOR   AGE
log-collector   2         2         2       <none>          11m
```

```
log-collector-5wbdf   1/1   Running   ecommerce-lab-worker
log-collector-nfj84   1/1   Running   ecommerce-lab-control-plane
```

DESIRED 2, READY 2 — one Pod per node. Full cluster coverage confirmed.

---

## StatefulSet — PostgreSQL Database

### Business Context

The e-commerce application needs a persistent database. Deployment Pods are interchangeable and ephemeral — unsuitable for a database where each instance needs stable identity, ordered startup, and storage that survives Pod restarts.

### Deployment vs StatefulSet — The Practical Test

Ask one question: if this Pod is deleted and replaced, does anything need to be preserved, or does the new Pod start completely fresh?

- Fresh is fine → Deployment
- New Pod must inherit state, identity, or storage → StatefulSet

### StatefulSet Properties

| Property | Deployment | StatefulSet |
|----------|------------|-------------|
| Pod names | Random hash | Stable ordered (`postgres-0`, `postgres-1`) |
| Pod IP | Ephemeral, random | Ephemeral, but DNS name is stable |
| Storage | Shared or none | Dedicated PVC per Pod |
| Startup order | Parallel | Ordered (0, 1, 2) |
| Shutdown order | Parallel | Reverse ordered (2, 1, 0) |

### Replicas in a StatefulSet

Each replica is a separate Pod with its own dedicated storage. Whether replicas form a coordinated HA cluster or operate as independent instances is determined by application configuration — not the StatefulSet itself. PostgreSQL HA requires explicit replication configuration (`postgresql.conf`, `pg_hba.conf`). The StatefulSet provides the stable identity and storage that makes coordination possible.

### Lab Deviation from Production

**Plaintext password in manifest** — `POSTGRES_PASSWORD` is defined as a plaintext value. In production this references a Kubernetes Secret or an external secrets manager (Vault). Fixed in Module 5.

**No resource requests or limits** — QoS class is BestEffort. Fixed in Module 8.

**ReclaimPolicy: Delete** — inherited from the default StorageClass. In production databases, ReclaimPolicy should be `Retain` so accidental PVC deletion does not destroy data.

### Manifest

**File:** `~/kubernetes-lab/module-02/postgres-statefulset.yaml`

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  labels:
    app: postgres
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:16.3
          env:
            - name: POSTGRES_DB
              value: ecommerce
            - name: POSTGRES_USER
              value: appuser
            - name: POSTGRES_PASSWORD
              value: labpassword123
          ports:
            - containerPort: 5432
          volumeMounts:
            - name: postgres-data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: postgres-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 1Gi
```

### Storage Chain — Fully Traced

```
StatefulSet (postgres)
  → Pod postgres-0 (scheduled on ecommerce-lab-worker)
    → volumeClaimTemplate → PVC postgres-data-postgres-0
      → StorageClass standard (rancher.io/local-path)
        → PV pvc-cbfbb1d9-5f30-4696-a49c-104f3dce5239
          → /var/local-path-provisioner/pvc-cbfbb1d9..._default_postgres-data-postgres-0
            → inside ecommerce-lab-worker Docker container
              → mounted into Pod at /var/lib/postgresql/data
```

**Two paths — do not confuse them:**
- `/var/lib/postgresql/data` — mount point inside the Pod container (where PostgreSQL reads/writes)
- `/var/local-path-provisioner/pvc-cbfbb1d9...` — actual path on the worker node (where data physically lives)

**Verified PostgreSQL data files present on worker node:**
```bash
docker exec ecommerce-lab-worker ls /var/local-path-provisioner/pvc-cbfbb1d9-5f30-4696-a49c-104f3dce5239_default_postgres-data-postgres-0
# PG_VERSION, base, global, pg_hba.conf, pg_wal, postgresql.conf, postmaster.pid ...
```

### Storage Concepts

**Access Modes:**

| Mode | Meaning | Use Case |
|------|---------|----------|
| ReadWriteOnce (RWO) | One node mounts for read/write | Databases — exclusive write access |
| ReadOnlyMany (ROX) | Many nodes mount read-only | Shared config, static assets |
| ReadWriteMany (RWX) | Many nodes mount for read/write | Shared upload directories (requires distributed filesystem) |

**RWX has no built-in locking.** Concurrent write safety is the application's responsibility. Databases must never use RWX — they implement their own concurrency control assuming exclusive storage access.

**StorageClass observed:**
```
NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE
standard (default)   rancher.io/local-path   Delete          WaitForFirstConsumer
```

`WaitForFirstConsumer` — storage is not provisioned until a Pod is scheduled, ensuring the volume is created on the same node as the Pod.

**Production StorageClass on EKS:** `ebs.csi.aws.com` provisioner, `Retain` reclaim policy for databases, volume expansion enabled.

### Verified PVC and PV

```
NAME                       STATUS   VOLUME                                     CAPACITY   ACCESS MODES
postgres-data-postgres-0   Bound    pvc-cbfbb1d9-5f30-4696-a49c-104f3dce5239   1Gi        RWO
```

---

## Manifest Validation

**Always validate before applying.**

**Client-side (no cluster required):**
```bash
k apply --dry-run=client -f manifest.yaml
```

**Server-side (preferred — hits API server):**
```bash
k apply --dry-run=server -f manifest.yaml
```

Server-side catches selector/template label mismatches, invalid field values, and policy violations that client-side misses. Use server-side when a cluster is available.

**Common error examples:**
- Missing required field: `ValidationError(Deployment.spec): missing required field "selector"`
- Selector mismatch: `spec.template.metadata.labels: Invalid value: selector does not match template labels`
- Unknown field: `unknown field "replikas"`

---

## kubectl Productivity

**Shell completion:**
```bash
echo 'source <(kubectl completion bash)' >> ~/.bashrc
```

**k alias (standard in production environments):**
```bash
echo 'alias k=kubectl' >> ~/.bashrc
echo 'complete -o default -F __start_kubectl k' >> ~/.bashrc
```

**Global flags (apply to all kubectl commands):**
```bash
k options  # full list
```

`-n / --namespace` — scope command to a specific namespace. Default namespace is used when omitted.

---

## Namespaces

Kubernetes partitions resources within a cluster using namespaces. The same resource name can exist in multiple namespaces without conflict.

**Key namespaces:**
- `default` — where user workloads land when no namespace is specified
- `kube-system` — Kubernetes internal components. Control plane Pods, CoreDNS, kindnet, kube-proxy.

Full namespace coverage — RBAC scoping, resource quotas, multi-tenancy — covered in Module 7.

---

## Failure Scenario — Stalled Rollout (ImagePullBackOff)

**Category:** Failed deployment rollout — new image does not exist.

**What was broken:** Deployment image updated to non-existent tag:
```bash
k set image deployment/product-catalog product-catalog=hashicorp/http-echo:9.9.9
```

**Rolling update behavior observed:**
- Kubernetes created one new Pod with the bad image (`757ff7f8b5` ReplicaSet)
- New Pod entered `ImagePullBackOff`
- Rollout stalled — Kubernetes did not proceed with replacing remaining old Pods
- Old Pods (`8686488fd9` ReplicaSet) remained running throughout — product catalog never went down

**Two ReplicaSets during stalled rollout:**
```
NAME                         DESIRED   CURRENT   READY
product-catalog-757ff7f8b5   1         1         0       ← new, bad image, stalled
product-catalog-8686488fd9   2         2         2       ← old, good image, protecting traffic
```

**Diagnostic path:**
```bash
k rollout status deployment/product-catalog
# Waiting for deployment "product-catalog" rollout to finish: 1 out of 2 new replicas have been updated...

k get replicaset
# New RS at READY 0, old RS holding at READY 2

k get pods
# New Pod in ImagePullBackOff

k describe pod product-catalog-757ff7f8b5-kwc92
# Events confirm: ErrImagePull → ImagePullBackOff
```

**Resolution — rollback:**
```bash
k rollout undo deployment/product-catalog
```

**After rollback:**
```
NAME                         DESIRED   CURRENT   READY
product-catalog-757ff7f8b5   0         0         0       ← scaled to zero, retained for history
product-catalog-8686488fd9   2         2         2       ← restored to full control
```

**Business outcome:** Product catalog served traffic continuously throughout the failed rollout and rollback. Zero customer impact.

### Rollout Commands Reference

```bash
k rollout status deployment/<name>        # current rollout status
k rollout history deployment/<name>       # revision history
k rollout history deployment/<name> --revision=2  # inspect specific revision
k rollout undo deployment/<name>          # roll back to previous revision
k rollout undo deployment/<name> --to-revision=1  # roll back to specific revision
```

### Rollout History Limitations

Revisions are immutable. A failed revision cannot be modified — fixing the issue creates a new revision. Native Kubernetes does not support marking a revision as failed with a reason.

**Production gap:** Change cause annotation requires manual discipline:
```bash
k annotate deployment/<name> kubernetes.io/change-cause="description"
```

For proper deployment audit trails — who deployed what, when, outcome, rollback reason — a GitOps platform (ArgoCD, Flux) is required. Git commit history becomes the deployment audit log.

**Production discipline:** Never use `k set image` in production without also updating the manifest. Imperative commands create drift between the Git repo and the running cluster. The manifest is always the source of truth.

---

## Diagnostic Command Reference

| Command | Purpose |
|---------|---------|
| `k get all` | All resources in current namespace |
| `k get pods -o wide` | Pods with node placement and IP |
| `k get pods -w` | Watch Pod state changes in real time |
| `k get pods --field-selector=status.phase=Failed` | Find failed/terminated Pods |
| `k get replicaset` | ReplicaSet status including desired/ready counts |
| `k get deployment <name>` | Deployment status |
| `k get daemonset` | DaemonSet status |
| `k get statefulset` | StatefulSet status |
| `k get pvc` | PersistentVolumeClaim status and bindings |
| `k get pv` | PersistentVolume details |
| `k get storageclass` | Available StorageClasses |
| `k get events --sort-by='.lastTimestamp'` | All namespace events chronologically |
| `k describe node <name> \| grep -A 10 Taints` | Node taint inspection |
| `k describe node <name> \| grep "Container Runtime"` | Node container runtime version |
| `k rollout status deployment/<name>` | Rollout progress |
| `k rollout history deployment/<name>` | Revision history |
| `k rollout undo deployment/<name>` | Roll back deployment |
| `k scale deployment <name> --replicas=N` | Manual scaling |
| `docker exec <node> ls <path>` | Inspect path inside kind node container |

---

## Advanced Topics List

*Carried forward from Module 1, additions from Module 2 marked with **[New]**:*

- Internal mechanics of each control plane component (etcd Raft consensus, scheduler scoring, controller reconciliation loop internals)
- etcd quorum requirements, odd-number member rule, split-brain failure modes
- Context management tooling: kubectx, kubens, shell prompt integration
- CNI plugin comparison: kindnet vs. Calico vs. Cilium vs. cloud-provider CNI
- Resource requests and limits, QoS classes, eviction order (Module 8)
- RBAC and service account token permissions (Module 7)
- **[New]** Horizontal Pod Autoscaler (HPA) — CPU/memory based autoscaling (Module 8)
- **[New]** Vertical Pod Autoscaler (VPA) — resource right-sizing
- **[New]** revisionHistoryLimit — controlling retained ReplicaSet count (Module 8)
- **[New]** Rolling update strategy configuration — maxSurge, maxUnavailable (Module 8)
- **[New]** Pod graceful termination — SIGTERM, terminationGracePeriodSeconds (Module 8)
- **[New]** Node roles, labels, taints, tolerations, node affinity (Module 8)
- **[New]** Spot instance node management — interruption handling, mixed instance clusters
- **[New]** Namespace resource quotas and LimitRanges (Module 7)
- **[New]** GitOps platforms — ArgoCD, Flux, deployment audit trails
- **[New]** Kubernetes audit logging — API server audit policy, compliance retention
- **[New]** Container image size best practices — impact on Pod startup and recovery time
- **[New]** Cluster event persistence — shipping events to Loki, Elasticsearch, CloudWatch
- **[New]** Provisioning tools module — kind, eksctl, Terraform for cluster provisioning
- **[New]** PostgreSQL HA on Kubernetes — replication configuration, primary/standby promotion
- **[New]** Production StorageClass design — EBS CSI driver, Retain reclaim policy, volume expansion
- **[New]** Multi-container Pod patterns in depth — sidecar, init container, ambassador

---

*Module 3: Networking — Services, DNS, Ingress, and how traffic moves inside the cluster*

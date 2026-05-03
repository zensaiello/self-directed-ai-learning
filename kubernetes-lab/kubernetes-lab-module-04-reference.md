# Kubernetes Lab — Module 4 Reference
## Storage — Volumes, PersistentVolumes, PersistentVolumeClaims, StorageClasses

**Track:** Kubernetes — Comprehensive Coverage
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster (4 nodes)
**Date Completed:** April 27, 2026

---

## Business Context

Storage decisions in Kubernetes are permanent in ways that compute and network decisions are not. A wrong StorageClass choice means data loss when a node goes down. A wrong reclaim policy means losing a production database when someone accidentally deletes a PVC. A StorageClass without volume expansion means an emergency migration when a database fills up. Module 4 establishes the correct storage primitives for each e-commerce workload and demonstrates the consequences of getting them wrong.

---

## The Four Storage Scenarios

| Workload | Data | Survives Pod restart? | Survives Pod deletion? | Storage type |
|----------|------|-----------------------|------------------------|--------------|
| Shopping cart session | Ephemeral session state | Yes | No | emptyDir |
| Product catalog images | Shared read-only assets | Yes | Yes | PVC (ReadOnlyMany) |
| PostgreSQL database | Transactional data | Yes | Yes | PVC (ReadWriteOnce, Retain) |
| Audit logs | Compliance records | Yes | Yes | PVC (write-once, immutable backend) |

Product catalog images and audit logs are flagged for advanced topics — covered in Module 7 (compliance) and beyond.

---

## The Storage Hierarchy — [STORAGE]

```
Physical storage (disk, EBS volume, NFS share, host directory)
  └── StorageClass (provisioner, reclaim policy, expansion policy)
        └── PersistentVolume (actual provisioned storage resource)
              └── PersistentVolumeClaim (workload's request for storage)
                    └── Volume mount (path inside container)
```

**Key principle:** The abstraction exists for portability. A manifest that requests `1Gi ReadWriteOnce` works on a laptop (local directory), on EKS (EBS volume), or on GKE (GCE Persistent Disk) without modification. The StorageClass handles the environment-specific provisioning.

---

## Ephemeral Storage — emptyDir — [STORAGE]

### Business Context

Shopping cart session data does not need to survive Pod deletion. If a user's session is lost on Pod rescheduling, they log back in. Using persistent storage for session data adds cost and complexity for no meaningful benefit.

### What emptyDir Does

- Created on the node when the Pod is scheduled
- Shared between all containers in the Pod
- **Survives container restarts** within the same Pod
- **Deleted permanently** when the Pod is deleted or rescheduled
- No configuration required — no PVC, no StorageClass

### Manifest

**File:** `~/kubernetes-lab/module-04/cart-session-pod.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: cart-session
  labels:
    app: cart-session
spec:
  containers:
    - name: cart
      image: busybox:1.36
      command: ["sh", "-c", "while true; do date >> /session-data/activity.log; sleep 5; done"]
      volumeMounts:
        - name: session-storage
          mountPath: /session-data
  volumes:
    - name: session-storage
      emptyDir: {}
```

### Demonstrated — Data Loss on Pod Deletion

```bash
# Before deletion — 224 lines written
k exec cart-session -- wc -l /session-data/activity.log
# 224 /session-data/activity.log

# Delete and recreate Pod
k delete pod cart-session
k apply -f cart-session-pod.yaml

# After recreation — storage wiped, starts fresh
k exec cart-session -- wc -l /session-data/activity.log
# 4 /session-data/activity.log
```

**[STORAGE] — confirmed:** emptyDir does not survive Pod deletion. New Pod starts with completely empty storage. This is correct behavior for session data.

---

## Persistent Storage — PostgreSQL — [STORAGE]

### Demonstrated — Data Survives Pod Deletion

```bash
# Write data
k exec -it postgres-0 -- psql -U appuser -d ecommerce -c "
  CREATE TABLE products (id SERIAL PRIMARY KEY, name VARCHAR(100), price DECIMAL(10,2));
  INSERT INTO products (name, price) VALUES ('Widget A', 9.99), ('Widget B', 19.99), ('Widget C', 29.99);
"

# Delete Pod
k delete pod postgres-0

# StatefulSet recreates postgres-0, mounts same PVC
# Data survives — PVC was not deleted
k exec -it postgres-0 -- psql -U appuser -d ecommerce -c "SELECT * FROM products;"
# 3 rows returned — data intact
```

**[STORAGE] — why data survived:** The PVC `postgres-data-postgres-0` was not deleted when the Pod was deleted. StatefulSet recreated `postgres-0` and mounted the same PVC. PostgreSQL found its data files intact.

**[STORAGE] — lab limitation:** In kind, the PV is a directory on `ecommerce-lab-worker`. Node loss = data loss despite PVC surviving. On EKS with EBS, the volume exists independently of any node and can reattach to a different node.

---

## StorageClass — [STORAGE]

### Standard StorageClass (kind default)

```
NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION
standard (default)   rancher.io/local-path   Delete          WaitForFirstConsumer   false
```

**Production problems with this StorageClass for a database:**
- `ReclaimPolicy: Delete` — accidental PVC deletion destroys data permanently
- `allowVolumeExpansion: false` — database cannot grow without full storage migration

### Production-Appropriate StorageClass

**File:** `~/kubernetes-lab/module-04/retain-storageclass.yaml`

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: retain-standard
provisioner: rancher.io/local-path
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

```
NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION
retain-standard      rancher.io/local-path   Retain          WaitForFirstConsumer   true
standard (default)   rancher.io/local-path   Delete          WaitForFirstConsumer   false
```

**[STORAGE] — production parallel on EKS:**
```yaml
provisioner: ebs.csi.aws.com
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: gp3
  encrypted: "true"
```

### VolumeBindingMode: WaitForFirstConsumer

Storage is not provisioned when the PVC is created. Provisioning waits until a Pod claims the PVC and is scheduled to a node. Ensures storage is provisioned on the same node the Pod lands on — critical for local storage, also important for availability zone alignment on EBS.

---

## Reclaim Policies — [STORAGE]

### Policy: Delete (default)

```
PVC deleted → PV deleted immediately → data gone → unrecoverable
```

### Policy: Retain

```
PVC deleted → PV status changes to Released → data intact → admin action required
```

**Released status:** PV exists with data intact but cannot be automatically rebound. Previous claim recorded in CLAIM column.

**To reclaim and reuse a Released PV:**
```bash
k patch pv <pv-name> -p '{"spec":{"claimRef":null}}'
# PV returns to Available status, can be bound to new PVC
```

**To permanently delete after confirming data is no longer needed:**
```bash
k delete pv <pv-name>
```

**[STORAGE] — the Retain guarantee:** No data is destroyed without a deliberate human action. The manual intervention step is intentional — it forces a decision before permanent data loss.

### Demonstrated — Delete Policy Risk

```bash
# Create PVC on standard StorageClass (Delete policy)
k apply -f test-pvc.yaml
# Write data, verify it exists

# Delete PVC
k delete pvc test-data

# PV is immediately gone
k get pv
# No resources found
# data is unrecoverable
```

### Demonstrated — Retain Policy Protection

```bash
# Delete PVC on retain-standard StorageClass (Retain policy)
k delete pvc postgres-data-postgres-0

# PV still exists, status changed to Released
k get pv
# STATUS: Released — data intact, admin action required
```

---

## PVC Protection Finalizer — [STORAGE] / [LOGICAL]

Every PVC automatically receives the finalizer `kubernetes.io/pvc-protection` at creation time.

**What it does:** Prevents PVC deletion from completing while a Pod is actively mounting the volume. The PVC enters `Terminating` status and waits for the Pod to release the volume before deletion completes.

**Why it exists:** Protects against data corruption from pulling storage away from a running Pod mid-operation.

**What it does NOT protect against:** Deliberate data deletion once the Pod releases the volume. Once the Pod is gone, the finalizer is removed and the deletion proceeds per the reclaim policy.

**Verified:**
```bash
k get pvc postgres-data-postgres-0 -o jsonpath='{.metadata.finalizers}'
# ["kubernetes.io/pvc-protection"]
```

**Finding objects with pending finalizers:**
```bash
# Objects stuck in Terminating across all namespaces
k get all --all-namespaces | grep Terminating

# Finalizers on a specific object
k get pvc <name> -o jsonpath='{.metadata.finalizers}'
```

**[LOGICAL] — finalizers exist on multiple resource types:**
- PVCs — `kubernetes.io/pvc-protection`
- PVs — `kubernetes.io/pv-protection`
- Namespaces — can get stuck Terminating if resources inside have unresolved finalizers
- Custom resources — operators add their own finalizers for cleanup logic

---

## Volume Expansion — [STORAGE]

### Blocked on standard StorageClass

```bash
k patch pvc test-expansion \
  -p '{"spec":{"resources":{"requests":{"storage":"200Mi"}}}}'

# Error from server (Forbidden): persistentvolumeclaims "test-expansion" is forbidden:
# only dynamically provisioned pvc can be resized and the storageclass
# that provisions the pvc must support resize
```

API server rejects the request outright — does not reach the provisioner.

**[STORAGE] — production consequence:** A database on a non-expandable StorageClass requires a full storage migration when it runs out of space — the same process performed in this module, under time pressure during a production incident.

### Enabled on retain-standard StorageClass

```bash
k patch pvc postgres-data-postgres-0 \
  -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
# persistentvolumeclaim/postgres-data-postgres-0 patched
```

**[STORAGE] — lab limitation:** The local-path provisioner accepts the patch but does not actually resize the volume. On EKS with EBS CSI driver, expansion is fully implemented — the EBS volume is resized and the filesystem is expanded on the next Pod restart.

**[STORAGE] — production workflow:**
```
k patch pvc <name> -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
  → EBS CSI driver resizes underlying EBS volume
    → PVC CAPACITY updates to new size
      → Pod restart triggers filesystem resize if needed
```

---

## StorageClass Migration — [STORAGE]

### When Required

StorageClass is immutable after PVC creation. Moving a workload to a different StorageClass requires a full migration.

### Migration Procedure — PostgreSQL

**Step 1 — Back up data:**
```bash
k exec postgres-0 -- pg_dump -U appuser ecommerce > ~/kubernetes-lab/module-04/ecommerce-backup.sql
```

**Step 2 — Delete StatefulSet, preserve PVC:**
```bash
k delete statefulset postgres --cascade=orphan
```
`--cascade=orphan` deletes the StatefulSet controller but leaves Pods and PVCs intact.

**Step 3 — Delete Pod and old PVC:**
```bash
k delete pod postgres-0
k delete pvc postgres-data-postgres-0
```
With Delete reclaim policy, PV is deleted with PVC.

**Step 4 — Recreate StatefulSet with new StorageClass:**
```bash
k apply -f ~/kubernetes-lab/module-04/postgres-statefulset-v2.yaml
```
New PVC provisioned on `retain-standard` StorageClass automatically.

**Step 5 — Restore data:**
```bash
k exec -i postgres-0 -- psql -U appuser -d ecommerce < ~/kubernetes-lab/module-04/ecommerce-backup.sql
```

**Step 6 — Verify:**
```bash
k exec -it postgres-0 -- psql -U appuser -d ecommerce -c "SELECT * FROM products;"
# 3 rows — data intact
```

**[STORAGE] — production note:** `pg_dump` produces a logical backup — SQL statements recreating schema and data. Portable across PostgreSQL versions. For production, point-in-time recovery (PITR) using WAL archiving is the complete backup strategy.

---

## Updated PostgreSQL StatefulSet — [STORAGE] / [COMPUTE]

**File:** `~/kubernetes-lab/module-04/postgres-statefulset-v2.yaml`

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
        storageClassName: retain-standard
        resources:
          requests:
            storage: 1Gi
```

**Changes from Module 2:**
- `storageClassName: retain-standard` — explicit production-appropriate StorageClass
- ReclaimPolicy: Retain inherited — accidental PVC deletion does not destroy data
- VolumeExpansion: true inherited — database can grow without re-provisioning

**Remaining lab deviations from production:**
- Plaintext password — fixed in Module 5 (Secrets)
- No resource requests/limits — fixed in Module 8
- No liveness/readiness probes — fixed in Module 8
- Single replica — no HA. Production PostgreSQL HA requires replication configuration.

---

## Verified Final State

**PVC:**
```
NAME                       STATUS   VOLUME                       CAPACITY   STORAGECLASS
postgres-data-postgres-0   Bound    pvc-5215cf6e-...             1Gi        retain-standard
```

**PV:**
```
NAME                       CAPACITY   RECLAIM POLICY   STATUS   STORAGECLASS
pvc-5215cf6e-...           1Gi        Retain           Bound    retain-standard
```

**StorageClasses:**
```
NAME              RECLAIMPOLICY   ALLOWVOLUMEEXPANSION
retain-standard   Retain          true
standard          Delete          false
```

---

## Diagnostic Command Reference

| Command | Hierarchy | Purpose |
|---------|-----------|---------|
| `k get pvc` | STORAGE | PVC status, bound volume, StorageClass |
| `k get pv` | STORAGE | PV status, reclaim policy, claim binding |
| `k get storageclass` | STORAGE | Available StorageClasses and their policies |
| `k describe pv <n>` | STORAGE | Full PV detail including source path, node affinity |
| `k get pvc <n> -o jsonpath='{.metadata.finalizers}'` | STORAGE/LOGICAL | Check finalizers on a PVC |
| `k patch pvc <n> -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'` | STORAGE | Expand PVC capacity |
| `k patch pv <n> -p '{"spec":{"claimRef":null}}'` | STORAGE | Release a Retain PV for rebinding |
| `k delete statefulset <n> --cascade=orphan` | COMPUTE | Delete StatefulSet controller, preserve Pods and PVCs |
| `k exec <pod> -- pg_dump -U <user> <db> > backup.sql` | STORAGE | PostgreSQL logical backup |
| `k exec -i <pod> -- psql -U <user> -d <db> < backup.sql` | STORAGE | PostgreSQL restore |
| `k exec <pod> -- cat <path>` | STORAGE | Verify file contents inside a Pod |
| `k exec <pod> -- wc -l <path>` | STORAGE | Count lines in a file inside a Pod |
| `docker exec <node> ls <path>` | STORAGE/COMPUTE | Inspect storage path on kind node |

---

## Advanced Topics List

*Carried forward from Modules 1-3, additions from Module 4 marked with **[New]**:*

- Internal mechanics of control plane components (etcd Raft, scheduler scoring, controller reconciliation)
- etcd quorum, split-brain failure modes
- Context management tooling: kubectx, kubens, shell prompt integration
- CNI plugin comparison and eBPF networking with Cilium
- AWS VPC CNI — native VPC IP assignment, capacity planning
- Resource requests and limits, QoS classes, eviction order (Module 8)
- RBAC and service account token permissions (Module 7)
- Horizontal Pod Autoscaler (Module 8)
- Vertical Pod Autoscaler
- revisionHistoryLimit, rolling update strategy (Module 8)
- Pod graceful termination — SIGTERM, terminationGracePeriodSeconds (Module 8)
- Node roles, labels, taints, tolerations, node affinity (Module 8)
- Spot instance node management
- Namespace resource quotas and LimitRanges (Module 7)
- GitOps platforms — ArgoCD, Flux
- Kubernetes audit logging
- Container image size best practices
- Cluster event persistence
- Provisioning tools module — kind, eksctl, Terraform
- PostgreSQL HA — replication configuration, primary/standby promotion
- Multi-container Pod patterns in depth
- Descheduler configuration, Pod priority classes
- Cluster Autoscaler
- Job and CronJob controllers
- Kubernetes Gateway API
- Service mesh — Istio, Linkerd
- Exposing non-HTTP ports, port-forward for debugging, network access restrictions
- Ingress Controller scaling and performance tuning
- kube-proxy vs Cilium eBPF at scale
- NodeLocal DNSCache
- Cloud load balancer sizing
- CoreDNS configuration, external DNS integration
- Helm package manager
- Supply chain security for Kubernetes manifests
- MetalLB
- **[New]** Compliance storage patterns — write-once storage, ReadOnlyMany access mode, volume snapshot API, audit log retention, immutable storage backends (S3 Object Lock, AWS Backup)
- **[New]** PostgreSQL backup strategy — point-in-time recovery (PITR), WAL archiving, automated backup schedules, backup verification, offsite storage
- **[New]** EBS CSI driver — production StorageClass configuration, gp3 volumes, encryption at rest
- **[New]** Volume snapshots — VolumeSnapshot API, snapshot-based backup and restore
- **[New]** Namespace termination failures — stuck finalizers, force-removing finalizers in emergencies
- **[New]** Static vs dynamic PV provisioning — when each is appropriate
- **[New]** CSI drivers — Container Storage Interface, driver ecosystem, vendor implementations
- **[New]** Storage performance tuning — IOPS, throughput, latency considerations for databases on Kubernetes
- **[New]** Multi-availability-zone storage considerations — EBS zone affinity, cross-zone replication patterns

---

*Module 5: Configuration and Secrets — ConfigMaps, Secrets, environment injection, Vault integration*

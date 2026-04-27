# Kubernetes Lab — Module 5 Reference
## Configuration and Secrets — ConfigMaps, Secrets, Environment Injection

**Track:** Kubernetes — Comprehensive Coverage
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster (4 nodes)
**Date Completed:** April 27, 2026

---

## Business Context

Every application has configuration — database connection strings, API endpoints, feature flags, credentials. How that configuration is managed determines the security posture of the entire application. Prior to Module 5, the PostgreSQL StatefulSet contained plaintext credentials in the manifest — a compliance violation in any regulated environment and a security risk in any environment. Module 5 externalizes all configuration into the correct Kubernetes primitives and establishes the production patterns for secrets management.

---

## The Configuration Problem — Before Module 5

```yaml
# Module 2/3/4 — WRONG. Never do this.
env:
  - name: POSTGRES_PASSWORD
    value: labpassword123
  - name: POSTGRES_USER
    value: appuser
  - name: POSTGRES_DB
    value: ecommerce
```

**[LOGICAL] — why this is wrong:**
- Password stored in plaintext in the manifest
- Password stored in plaintext in Git if manifest is committed
- Password visible to anyone who can run `k describe pod postgres-0`
- Password visible to anyone with read access to the repository
- In a regulated environment: compliance violation
- In any environment: security risk

---

## ConfigMap vs Secret — [LOGICAL]

### Decision Rule

**ConfigMap** — non-sensitive configuration. Safe to expose in logs, dashboards, and to developers without access controls.

**Secret** — sensitive configuration. Exposure causes harm — financial, reputational, regulatory.

| ConfigMap | Secret |
|-----------|--------|
| Database name | Database password |
| Max connections | API keys |
| Log settings | TLS certificates |
| Feature flags | OAuth tokens |
| Service URLs | SSH private keys |
| Application version | Encryption keys |

---

## Secrets — [LOGICAL]

### What Base64 Encoding Is and Is Not

```bash
echo -n "labpassword123" | base64
# bGFicGFzc3dvcmQxMjM=

echo -n "bGFicGFzc3dvcmQxMjM=" | base64 -d
# labpassword123
```

Base64 is trivially reversible. It is encoding, not encryption. Anyone who can read a Secret object gets the plaintext value immediately.

### What Kubernetes Secrets Provide

- **Separation from manifests** — credentials not embedded in application manifests or Git
- **Access control surface** — RBAC restricts who can read Secrets independently of other resources
- **Memory-only delivery** — Secrets mounted as volumes use tmpfs (RAM), not written to disk
- **Audit trail** — API server audit logging captures Secret access separately

### What Kubernetes Secrets Do Not Provide

- **Encryption at rest by default** — etcd stores Secrets base64-encoded. Anyone with direct etcd access reads plaintext.
- **Secret rotation** — no built-in mechanism to rotate credentials and notify applications
- **Fine-grained audit integration** — does not integrate with enterprise SIEM without additional tooling

### Encryption at Rest

- **kind (lab):** Not enabled. Secrets are base64 in etcd.
- **EKS (production):** Enabled by default using AWS KMS. Secrets encrypted in etcd with a KMS key you control.

**[LOGICAL] — honest assessment:** Kubernetes Secrets are a necessary first step, not a complete solution. Significantly better than plaintext in manifests. Not a replacement for a dedicated secrets manager in regulated environments.

### Creating a Secret

**Production method — imperative (no last-applied-configuration annotation):**
```bash
k create secret generic postgres-credentials \
  --from-literal=username=appuser \
  --from-literal=password=labpassword123 \
  --from-literal=database=ecommerce
```

**Lab method — declarative (adds plaintext annotation — do not commit to Git):**

**File:** `~/kubernetes-lab/module-05/postgres-secret.yaml`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-credentials
  labels:
    app: postgres
type: Opaque
stringData:
  username: appuser
  password: labpassword123
  database: ecommerce
```

**[LOGICAL] — `stringData` vs `data`:**
- `stringData` — accepts plaintext, Kubernetes base64-encodes automatically. Preferred for readability.
- `data` — requires pre-encoded base64 values. Error-prone.

**[LOGICAL] — the annotation security concern:**
`k apply` adds `kubectl.kubernetes.io/last-applied-configuration` annotation containing the full original manifest including plaintext `stringData` values. This annotation is readable without base64 decoding. Use `k create` for Secrets in production to avoid this annotation.

**Verified stored state:**
```yaml
data:
  database: ZWNvbW1lcmNl      # ecommerce
  password: bGFicGFzc3dvcmQxMjM=  # labpassword123
  username: YXBwdXNlcg==      # appuser
```

### The Git Problem

Secret manifests containing plaintext values must never be committed to Git. Production patterns:

**Sealed Secrets:** Encrypt the manifest using a cluster-specific key. Encrypted manifest is safe to commit. SealedSecrets controller decrypts on apply.

**External Secrets Operator:** Manifest contains only a reference to Vault or AWS Secrets Manager. Operator fetches the value and creates the Kubernetes Secret. No credential values in Git.

**Vault Agent Injector:** Credentials injected directly into Pods as files at runtime via sidecar. Kubernetes Secrets never created at all. Most secure pattern — credentials exist only in memory inside the Pod.

---

## ConfigMaps — [LOGICAL]

### PostgreSQL Configuration

**File:** `~/kubernetes-lab/module-05/postgres-config.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-config
  labels:
    app: postgres
data:
  POSTGRES_DB: ecommerce
  max_connections: "100"
  shared_buffers: "128MB"
  log_statement: "all"
```

**Lab note:** `POSTGRES_DB` should not be in the ConfigMap — it is already injected as an environment variable from the Secret. Each configuration value should come from exactly one source. This is a lab artifact.

### Product Catalog Configuration

**File:** `~/kubernetes-lab/module-05/product-catalog-config.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: product-catalog-config
  labels:
    app: product-catalog
data:
  SERVICE_VERSION: "1.0"
  DATABASE_HOST: "postgres.default.svc.cluster.local"
  DATABASE_PORT: "5432"
  LOG_LEVEL: "info"
  MAX_RESULTS: "100"
```

**[NETWORK] / [LOGICAL] — `DATABASE_HOST` uses the Service DNS name**, not an IP. If the postgres Service moves, the DNS name stays the same. The ConfigMap value never needs to change. This is the correct pattern for service-to-service configuration in Kubernetes.

---

## Environment Injection Patterns — [LOGICAL]

### Pattern 1 — Specific key from Secret (secretKeyRef)

```yaml
env:
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef:
        name: postgres-credentials
        key: password
```

The container receives the env var with the actual value. The Secret name and key are the reference — never the value itself in the manifest.

**[LOGICAL] — `k describe pod` behavior:** Secret references show as:
```
POSTGRES_PASSWORD: <set to the key 'password' in secret 'postgres-credentials'>
```
Actual values are redacted — not visible in describe output.

### Pattern 2 — Specific key from ConfigMap (configMapKeyRef)

```yaml
env:
  - name: MAX_CONNECTIONS
    valueFrom:
      configMapKeyRef:
        name: postgres-config
        key: max_connections
```

### Pattern 3 — All keys from ConfigMap (envFrom)

```yaml
envFrom:
  - configMapRef:
      name: product-catalog-config
```

Every key in the ConfigMap becomes an environment variable. ConfigMap key = env var name. Convenient but less explicit — new keys added to the ConfigMap automatically appear as env vars on next Pod restart.

**[LOGICAL] — `k describe pod` limitation:** `envFrom` bulk injection does not show individual variables in describe output. `Environment: <none>` is displayed even when envFrom is correctly configured. Verify with:
```bash
k get pod <n> -o jsonpath='{.spec.containers[0].envFrom}'
```

### Pattern 4 — ConfigMap as volume mount

```yaml
volumeMounts:
  - name: postgres-config
    mountPath: /etc/postgresql/conf.d
    readOnly: true
volumes:
  - name: postgres-config
    configMap:
      name: postgres-config
```

Each ConfigMap key becomes a filename. Each ConfigMap value becomes the file contents.

```
ConfigMap key   → filename in mountPath directory
ConfigMap value → file contents
```

**Verified inside container:**
```bash
k exec postgres-0 -- ls /etc/postgresql/conf.d/
# log_statement  max_connections  POSTGRES_DB  shared_buffers

k exec postgres-0 -- cat /etc/postgresql/conf.d/max_connections
# 100
```

### Pattern Comparison

| Pattern | Use case | Granularity | Visibility in describe |
|---------|----------|-------------|----------------------|
| `secretKeyRef` | Specific Secret key as env var | Per key | Shows reference, not value |
| `configMapKeyRef` | Specific ConfigMap key as env var | Per key | Shows value |
| `envFrom configMapRef` | All ConfigMap keys as env vars | Bulk | Not shown |
| `envFrom secretRef` | All Secret keys as env vars | Bulk | Not shown |
| Volume mount | ConfigMap or Secret as files | Bulk | Shows mount path |

**[LOGICAL] — volume mount vs environment variable for Secrets:**
Volume mounted Secrets use tmpfs (RAM) — not written to disk on the node. More secure than environment variables, which are visible in process listings. Use volume mounts for highly sensitive credentials where possible.

---

## Configuration Update Behavior — [LOGICAL]

### ConfigMap Volume Mount Updates

Updates propagate automatically — no Pod restart required.

```
k patch configmap postgres-config --type merge -p '{"data":{"log_statement":"none"}}'
  → API server updates ConfigMap in etcd
    → kubelet detects change (~60 second sync period)
      → File updated in container tmpfs volume
        → Application must reload to pick up change
```

**Verified:**
```bash
# Before patch
k exec postgres-0 -- cat /etc/postgresql/conf.d/log_statement
# all

# After patch (60 second propagation)
k exec postgres-0 -- cat /etc/postgresql/conf.d/log_statement
# none
# Pod never restarted
```

### Environment Variable Updates

Environment variables are set at container startup and never updated. ConfigMap or Secret value changes require a Pod restart to take effect.

### PostgreSQL Parameter Reload Behavior

| Parameter | Reload method | Restart required |
|-----------|---------------|-----------------|
| `log_statement` | `pg_reload_conf()` or automatic | No |
| `work_mem` | `pg_reload_conf()` | No |
| `max_connections` | Cannot reload | Yes — full restart |
| `shared_buffers` | Cannot reload | Yes — full restart |

**[LOGICAL] — production implication:** Operational tunables (log levels, work memory) should use ConfigMap volume mounts — they can change without downtime. Structural parameters (max connections, shared buffers) require planned maintenance windows for Pod restarts.

---

## Updated PostgreSQL StatefulSet — v3 — [COMPUTE] / [LOGICAL]

**File:** `~/kubernetes-lab/module-05/postgres-statefulset-v3.yaml`

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
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: database
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: username
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: password
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          ports:
            - containerPort: 5432
          volumeMounts:
            - name: postgres-data
              mountPath: /var/lib/postgresql/data
            - name: postgres-config
              mountPath: /etc/postgresql/conf.d
              readOnly: true
      volumes:
        - name: postgres-config
          configMap:
            name: postgres-config
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

**Changes from v2 (Module 4):**
- All three credential env vars now use `secretKeyRef` — no plaintext in manifest
- `PGDATA` set to subdirectory to avoid mount point initialization conflict
- `postgres-config` ConfigMap mounted at `/etc/postgresql/conf.d` as read-only volume

**Remaining lab deviations from production:**
- Single replica — no HA
- No resource requests/limits — Module 8
- No liveness/readiness probes — Module 8
- Secret manifest contains plaintext annotation — use `k create` in production
- Secret should use external secrets manager in regulated environments

**Verified working:**
```bash
k exec -it postgres-0 -- psql -U appuser -d ecommerce -c "SELECT current_user, current_database();"
# current_user | current_database
# appuser      | ecommerce
```

---

## Updated Product Catalog Deployment — v2 — [COMPUTE] / [LOGICAL]

**File:** `~/kubernetes-lab/module-05/product-catalog-deployment-v2.yaml`

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
          envFrom:
            - configMapRef:
                name: product-catalog-config
```

**Verified:**
```bash
k get pod product-catalog-64bf995548-rvmc4 \
  -o jsonpath='{.spec.containers[0].envFrom}'
# [{"configMapRef":{"name":"product-catalog-config"}}]
```

---

## Failure Scenario — Missing Secret Key (CreateContainerConfigError) — [LOGICAL]

**Category:** Container fails to start due to unresolvable Secret reference.

**What was broken:** `secretKeyRef` referenced a key that does not exist in the Secret:
```yaml
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: postgres-credentials
      key: wrong-key  # does not exist
```

**Symptoms:**
```
NAME               READY   STATUS                       RESTARTS
postgres-broken-0  0/1     CreateContainerConfigError   0
```

Container never starts — Kubernetes detects the broken reference before launching.

**Diagnostic path:**
```bash
k describe pod postgres-broken-0
# Events:
# Warning  Failed  kubelet  Error: couldn't find key wrong-key in Secret default/postgres-credentials
```

**Why this is better than a runtime failure:** Error surfaces at container creation time. Application never starts with a missing credential that would cause a cryptic error later.

**Related failure — Secret itself missing:**
```
Error: secret "postgres-credentials" not found
```
Occurs when: manifest applied before Secret created, Secret deleted while Deployment still references it, Secret in wrong namespace.

**Diagnostic path:**
```bash
# Step 1
k get pods → CreateContainerConfigError

# Step 2
k describe pod <n> → Events → identify missing Secret or key

# Step 3
k get secret <name> -o yaml → verify Secret exists and check available keys

# Step 4
Fix key reference in manifest → reapply
```

---

## RBAC — Role Based Access Control — [LOGICAL]

Kubernetes authorization system. Controls who can do what to which resources.

**Four components:**
- **Role** — permissions within a namespace
- **ClusterRole** — permissions across the entire cluster
- **RoleBinding** — assigns a Role to a user, group, or service account
- **ClusterRoleBinding** — assigns a ClusterRole cluster-wide

**Why RBAC matters for Secrets:** RBAC rules can restrict which service accounts can read which Secrets. Without Secrets — if credentials were in manifest env vars — there is no access control surface. With Secrets, a developer's service account can be explicitly prevented from reading `postgres-credentials` while the postgres Pod's service account can read it.

Full RBAC coverage in Module 7.

---

## Production Secrets Management — [LOGICAL]

| Concern | Kubernetes Secrets | Production Solution |
|---------|-------------------|---------------------|
| Encryption at rest | Base64 only (unless KMS) | EKS + AWS KMS |
| Secret rotation | Manual, Pod restart required | Vault dynamic secrets |
| Git safety | Plaintext in manifests | Sealed Secrets / External Secrets |
| Audit trail | Basic API audit log | Vault audit + SIEM |
| Cross-cluster sharing | Not supported | Vault / AWS Secrets Manager |
| Expiring credentials | Not supported | Vault dynamic secrets (TTL) |

### SIEM — Security Information and Event Management

Enterprise security platform that collects, correlates, and analyzes security events across infrastructure. Examples: Splunk, IBM QRadar, Microsoft Sentinel, Datadog Security.

In Kubernetes context: ships audit logs (who accessed which Secret, when, from which IP) into the enterprise security platform for anomaly detection, alerting, and incident investigation.

---

## Diagnostic Command Reference

| Command | Hierarchy | Purpose |
|---------|-----------|---------|
| `k get configmaps` | LOGICAL | List ConfigMaps in namespace |
| `k get secrets` | LOGICAL | List Secrets in namespace |
| `k describe configmap <n>` | LOGICAL | Full ConfigMap contents |
| `k get secret <n> -o yaml` | LOGICAL | Secret with base64-encoded values |
| `k get pod <n> -o jsonpath='{.spec.containers[0].envFrom}'` | LOGICAL | Verify envFrom injection |
| `k get pod <n> -o jsonpath='{.spec.containers[0].env}'` | LOGICAL | Verify env injection |
| `k describe pod <n> \| grep -A 10 Environment` | LOGICAL | Environment section (secretKeyRef shows, envFrom does not) |
| `k exec <pod> -- cat /path/to/file` | COMPUTE | Verify ConfigMap volume mount file contents |
| `k exec <pod> -- ls /path/to/dir` | COMPUTE | List ConfigMap volume mount files |
| `k patch configmap <n> --type merge -p '{"data":{"key":"value"}}'` | LOGICAL | Update ConfigMap value |
| `k exec <pod> -- psql -U <user> -d <db> -c "SELECT pg_reload_conf();"` | COMPUTE | Reload PostgreSQL configuration |
| `k exec <pod> -- psql -U <user> -d <db> -c "SHOW <param>;"` | COMPUTE | Check active PostgreSQL parameter value |
| `grep -r "<name>" ~/kubernetes-lab/` | LOGICAL | Find all manifest references to a ConfigMap or Secret |

---

## Advanced Topics List

*Carried forward from Modules 1-4, additions from Module 5 marked with **[New]**:*

- Internal mechanics of control plane components
- etcd quorum, split-brain failure modes
- Context management tooling
- CNI plugin comparison and eBPF networking
- AWS VPC CNI capacity planning
- Resource requests and limits, QoS classes (Module 8)
- RBAC in full — Roles, ClusterRoles, RoleBindings, service account permissions (Module 7)
- Horizontal Pod Autoscaler (Module 8)
- Vertical Pod Autoscaler
- revisionHistoryLimit, rolling update strategy (Module 8)
- Pod graceful termination (Module 8)
- Node affinity, taints, tolerations (Module 8)
- Spot instance node management
- Namespace resource quotas (Module 7)
- GitOps platforms — ArgoCD, Flux
- Kubernetes audit logging
- Container image size best practices
- Cluster event persistence
- Provisioning tools module
- PostgreSQL HA — replication, primary/standby promotion
- Multi-container Pod patterns
- Descheduler, Pod priority classes
- Cluster Autoscaler
- Job and CronJob controllers
- Kubernetes Gateway API
- Service mesh — Istio, Linkerd
- Exposing non-HTTP ports, network access restrictions
- Ingress Controller scaling
- kube-proxy vs Cilium eBPF
- NodeLocal DNSCache
- CoreDNS configuration, external DNS
- Helm package manager
- Supply chain security
- MetalLB
- Compliance storage patterns, volume snapshots
- PostgreSQL backup strategy — PITR, WAL archiving
- EBS CSI driver, storage performance tuning
- Namespace termination failures
- CSI drivers
- Multi-AZ storage considerations
- **[New]** Sealed Secrets — cluster-specific encryption for Secret manifests safe to commit to Git
- **[New]** External Secrets Operator — reference-based Secret management from Vault or AWS Secrets Manager
- **[New]** Vault Agent Injector — runtime credential injection, no Kubernetes Secrets created
- **[New]** Vault dynamic secrets — TTL-based credential rotation, automatic expiry
- **[New]** Secret rotation patterns — sequencing credential changes with Pod restarts under load
- **[New]** Reloader — operator that watches ConfigMaps and Secrets and triggers Pod restarts on change
- **[New]** Resource relationship tracking — Helm release management, dependency ordering in GitOps
- **[New]** KMS encryption for etcd — EKS envelope encryption configuration
- **[New]** PostgreSQL hot-reloadable vs restart-required parameters — operational implications

---

*Module 6: Observability on Kubernetes — Prometheus Operator, scrape configs, log collection, tracing*

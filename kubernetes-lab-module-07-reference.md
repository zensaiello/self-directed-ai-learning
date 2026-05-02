# Kubernetes Lab — Module 7 Reference
## RBAC and Security — ServiceAccounts, Roles, ClusterRoles, Admission Controllers

**Track:** Kubernetes — Comprehensive Coverage
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster (4 nodes)
**Date Completed:** April 29, 2026

---

## Business Context

Every workload in the e-commerce cluster had been running with the `default` ServiceAccount since Module 1. All eight Pods shared one identity with no differentiation — a compromised `cart-session` Pod had the same cluster permissions as the postgres Pod. This is one of the most common findings in Kubernetes security audits. Module 7 establishes least-privilege ServiceAccounts for each workload, scoped to exactly what each requires, and demonstrates the concrete exploit path that over-permissioned accounts enable.

---

## The Designed-In Problem — Shared Identity

### Initial State

All workloads running as `default` ServiceAccount:

```
NAME                               SERVICE_ACCOUNT
cart-session                       default
log-collector-j9z5z                default
log-collector-skrmb                default
log-collector-v4l9w                default
log-collector-vgmtt                default
postgres-0                         default
product-catalog-64bf995548-pd85v   default
product-catalog-64bf995548-rvmc4   default
```

### What the Default ServiceAccount Can Do

```bash
kubectl auth can-i --list --as=system:serviceaccount:default:default -n default
```

No Kubernetes resource permissions in the resource rows. However, all authenticated identities receive cluster-wide GET access to non-resource URLs — the full API discovery surface (`/api/*`, `/apis/*`, `/apis`, `/api`). Any Pod can enumerate every API group, every resource type, and every CRD installed in the cluster using the mounted token.

### The Mounted Token

Every Pod automatically receives a JWT mounted at `/var/run/secrets/kubernetes.io/serviceaccount/token`. Decoded payload from `cart-session`:

```json
{
  "aud": ["https://kubernetes.default.svc.cluster.local"],
  "exp": 1808943925,
  "iat": 1777407925,
  "kubernetes.io": {
    "namespace": "default",
    "node": { "name": "ecommerce-lab-worker2" },
    "pod": { "name": "cart-session" },
    "serviceaccount": { "name": "default" }
  },
  "sub": "system:serviceaccount:default:default"
}
```

**Identity string construction:** The `sub` field encodes the full identity — `system` (Kubernetes prefix) : `serviceaccount` (type) : `default` (namespace) : `default` (ServiceAccount name). The four segments map directly to fields in the JWT payload.

**Token model (Kubernetes 1.24+):** Tokens are generated via the `TokenRequest` API and bound to the Pod's lifetime. They are never stored as Secret objects — the `SECRETS: 0` column on `kubectl get serviceaccounts` is correct and expected. The old pattern of auto-created Secret-based tokens was deprecated because non-expiring tokens stored in etcd are a security risk.

**`aud` field:** Token is scoped to `https://kubernetes.default.svc.cluster.local` only. Cannot be replayed against external services.

---

## [LOGICAL] RBAC — The Four Objects

RBAC answers: WHO can do WHAT on WHICH resources.

```
WHO
 └── defined by ServiceAccount, User, or Group
     bound to permissions via RoleBinding or ClusterRoleBinding

WHAT on WHICH resources
 └── defined by Role or ClusterRole
```

### Object Types

**Role** — namespace-scoped permission set. Only applies within the namespace it is created in.

**ClusterRole** — cluster-scoped permission set. Applies across all namespaces, or to cluster-level resources that have no namespace (Nodes, PersistentVolumes, Namespaces).

**RoleBinding** — attaches a Role (or ClusterRole) to an identity within a specific namespace.

**ClusterRoleBinding** — attaches a ClusterRole to an identity cluster-wide.

### Identity Types

Three types of identity can be bound to a Role:

- **ServiceAccount** — machine identity for a Pod. Created and managed in Kubernetes.
- **User** — human identity. Kubernetes does not manage users — they come from external providers (OIDC, certificates).
- **Group** — a collection of identities. Flat in Kubernetes — no nesting. Group hierarchy lives in the external identity provider (Okta, Azure AD, Google). Kubernetes receives a flattened list of group memberships from the token claims.

### Namespace Scope Rule

| Access needed | Use |
|---|---|
| Resources in one namespace | Role + RoleBinding |
| Resources across all namespaces | ClusterRole + ClusterRoleBinding |
| Cluster-level resources (Nodes, PVs) | ClusterRole + ClusterRoleBinding |

---

## [LOGICAL] Role Rules Structure

```yaml
rules:
- apiGroups: [""]          # Which API group owns this resource?
  resources: ["configmaps"] # Which resource type?
  verbs: ["get", "list"]    # What actions are allowed?
  resourceNames: ["name"]   # Optional: restrict to specific named instances
```

### apiGroups

| apiGroup | Example resources |
|---|---|
| `""` (core) | Pod, Service, ConfigMap, Secret, Node, Namespace |
| `apps` | Deployment, StatefulSet, DaemonSet |
| `rbac.authorization.k8s.io` | Role, ClusterRole, RoleBinding |
| `monitoring.coreos.com` | ServiceMonitor, PrometheusRule |

### Verbs

| Verb | Action |
|---|---|
| `get` | Read a specific named resource |
| `list` | Read all resources of this type |
| `watch` | Stream changes in real time |
| `create` | Create a new resource |
| `update` | Replace an existing resource |
| `patch` | Partially modify an existing resource |
| `delete` | Remove a resource |

`get`, `list`, `watch` are the standard read-only set and are almost always granted together.

### resourceNames — Least-Privilege Pattern

Without `resourceNames`: ServiceAccount can act on all resources of that type in the namespace.

With `resourceNames`: ServiceAccount can only act on the specifically named instance. Every other resource of that type is invisible to it.

```yaml
# Can only GET the Secret named postgres-credentials
# Cannot list Secrets, cannot read any other Secret by name
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
  resourceNames: ["postgres-credentials"]
```

### Secrets — No Field-Level Access Control

There is no RBAC verb that means "use a Secret without reading its value." If a Pod has `get` on a Secret, it can read the full contents. RBAC operates at the resource level, not the field level.

**`list` on Secrets is more dangerous than `get`** — `list` returns all Secrets in the namespace including their full contents. `get` with `resourceNames` requires knowing the name in advance and restricts access to that one instance.

**Production patterns that address this gap:**
- External Secrets Operator / Vault — Secrets never live in etcd. Pod retrieves credentials directly from Vault at runtime.
- Encryption at rest — etcd encrypted with KMS. Limits blast radius if etcd storage is compromised.
- Sealed Secrets — Secrets encrypted in Git, decrypted only inside the cluster by a controller.

---

## What Was Built

### ServiceAccounts

**File:** `module-07/serviceaccounts.yaml`

| ServiceAccount | Purpose |
|---|---|
| `product-catalog-sa` | Dedicated identity for product-catalog Deployment |
| `postgres-sa` | Dedicated identity for postgres StatefulSet |
| `log-collector-sa` | Dedicated identity for log-collector DaemonSet |
| `cart-session-sa` | Zero-permission identity — retained to document the pattern; bare Pod retired after Module 4 |

### Roles

**File:** `module-07/roles.yaml`

```yaml
# product-catalog-role
# Rationale: application may need to read multiple ConfigMaps for configuration
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list", "watch"]

# postgres-role
# Rationale: database needs exactly one credential Secret, nothing else
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
  resourceNames: ["postgres-credentials"]
```

### ClusterRole

**File:** `module-07/clusterrole.yaml`

```yaml
# log-collector-role
# Rationale: DaemonSet runs on every node and must read Pod metadata
# across all namespaces to enrich log entries with Kubernetes context
rules:
- apiGroups: [""]
  resources: ["pods", "namespaces"]
  verbs: ["get", "list", "watch"]
```

No `namespace` field in metadata — this is what makes it a ClusterRole. A Role without a namespace is rejected by the API server.

### Bindings

**File:** `module-07/bindings.yaml`

Two RoleBindings (namespace-scoped) and one ClusterRoleBinding (cluster-scoped):

```
product-catalog-rolebinding   → Role/product-catalog-role   → default/product-catalog-sa
postgres-rolebinding          → Role/postgres-role           → default/postgres-sa
log-collector-clusterrolebinding → ClusterRole/log-collector-role → default/log-collector-sa
```

**Binding structure:**
- `subjects` — the WHO. A list — multiple identities can be bound in one binding.
- `roleRef` — the WHAT. A single reference — one binding connects to exactly one Role or ClusterRole. Multiple roles require multiple bindings.

---

## Permission Verification

### product-catalog-sa

```
Resources     Non-Resource URLs   Resource Names   Verbs
configmaps    []                  []               [get list watch]
```

### postgres-sa

```
Resources   Non-Resource URLs   Resource Names          Verbs
secrets     []                  [postgres-credentials]  [get]
```

`resourceNames` column populated — access restricted to exactly one named Secret.

### log-collector-sa (verified in both `default` and `monitoring` namespaces — identical output)

```
Resources    Non-Resource URLs   Resource Names   Verbs
namespaces   []                  []               [get list watch]
pods         []                  []               [get list watch]
```

Same output in both namespaces confirms ClusterRole is not namespace-scoped.

### cart-session-sa

No resource rows beyond self-subject review entries — zero permissions as intended.

---

## Workload Manifest Updates

**Production pattern:** Prior module manifests are portfolio artifacts — not modified. Versioned copies created in module-07:

| Original | Module 7 version |
|---|---|
| `module-05/product-catalog-deployment-v2.yaml` | `module-07/product-catalog-deployment-v3.yaml` |
| `module-05/postgres-statefulset-v3.yaml` | `module-07/postgres-statefulset-v4.yaml` |
| `module-02/log-collector-daemonset.yaml` | `module-07/log-collector-daemonset-v2.yaml` |

Change in each manifest — single field added to Pod spec:
```yaml
spec:
  serviceAccountName: <dedicated-sa-name>
  containers:
  ...
```

**Bare Pod behavior:** `cart-session` was a bare Pod (no controller). Kubernetes does not allow updating `serviceAccountName` on a running Pod in place — only fields like `image` can be patched. Controllers (Deployments, StatefulSets, DaemonSets) handle this transparently via rollout. Bare Pods require delete and recreate. `cart-session` was retired — it had served its learning purpose in Module 4 and had no production justification for continuation.

**log-collector edit note:** The Python replacement targeted `spec:\n      containers:` but the DaemonSet Pod spec had `tolerations:` before `containers:`. Replacement was adjusted to target `spec:\n      tolerations:` instead. When editing manifests programmatically, inspect the actual spec structure before assuming field order.

### Final State

```
NAME                             SERVICE_ACCOUNT      STATUS
log-collector-5n5rg              log-collector-sa     Running
log-collector-9l4h5              log-collector-sa     Running
log-collector-kw76r              log-collector-sa     Running
log-collector-rqz2l              log-collector-sa     Running
postgres-0                       postgres-sa          Running
product-catalog-875469fb-fsx2r   product-catalog-sa   Running
product-catalog-875469fb-wkncw   product-catalog-sa   Running
```

No `default` ServiceAccount in use by any workload.

---

## [LOGICAL] Admission Controllers

The third gate in the Kubernetes request path — after Authentication and Authorization:

```
kubectl apply
    → Authentication  (who are you?)
    → Authorization   (are you allowed to do this? — RBAC lives here)
    → Admission       (does this resource meet cluster policy?)
    → etcd            (stored)
```

**Validating admission controllers** — inspect and accept or reject. No modifications. Example: reject Pods without resource limits.

**Mutating admission controllers** — modify the resource before storage. Example: inject a sidecar container, or assign the `default` ServiceAccount when none is specified. This is the mechanism that assigned `default` to all Pods before this module.

### PodSecurity Admission

Enforces Pod security standards at the namespace level via namespace labels:

| Level | Restrictions |
|---|---|
| `privileged` | None |
| `baseline` | Blocks known privilege escalation — no hostNetwork, no privileged containers |
| `restricted` | Enforces non-root, read-only root filesystem, drops all capabilities |

```yaml
# Applied as namespace label
pod-security.kubernetes.io/enforce: restricted
```

Pods violating policy are rejected at admission — never reach the scheduler.

**[COMPUTE] — hostNetwork note:** Node Exporter from Module 6 uses `hostNetwork: true` — a legitimate use case for host-level metrics. This would be blocked under `restricted` policy. Production clusters handle this with policy exceptions scoped to the monitoring namespace.

### OPA Gatekeeper / Kyverno

Policy engines extending admission control with custom rules. Examples of enterprise enforcement:

- All images must come from an approved internal registry
- All Pods must have resource limits defined
- No ServiceAccount may use `automountServiceAccountToken: true` without explicit approval
- All Deployments must have at least 2 replicas

**Relationship to RBAC:** RBAC is runtime enforcement — prevents a running Pod from doing unauthorized things. Admission controllers are deploy-time enforcement — prevent misconfigured or policy-violating manifests from being applied. Complementary layers, not alternatives.

---

## Failure Scenario — cluster-admin Binding

**File:** `module-07/overpermissioned-sa.yaml` (retained as documented failure artifact — resources deleted from cluster)

**Category:** Over-permissioned ServiceAccount — common audit finding in enterprise clusters.

**Production framing:** A developer grants their application's ServiceAccount broad permissions to debug a production issue. The change is never reverted. Months later a supply chain compromise of one dependency gives an attacker a token with cluster-wide access.

### What Was Created

```yaml
# ServiceAccount bound to built-in cluster-admin ClusterRole
# cluster-admin = every verb, every resource, every namespace — equivalent to root
subjects:
- kind: ServiceAccount
  name: overpermissioned-sa
  namespace: default
roleRef:
  kind: ClusterRole
  name: cluster-admin
```

### Permission Output

```
Resources   Non-Resource URLs   Resource Names   Verbs
*.*         []                  []               [*]
            [*]                 []               [*]
```

`*.*` with verb `[*]` — unrestricted access to everything.

### Exploit Demonstrated

```bash
# Step 1 — enumerate Secrets across namespaces
kubectl get secrets -n monitoring --as=system:serviceaccount:default:overpermissioned-sa
# Returns: all 11 Secrets in monitoring namespace including grafana-admin-credentials

# Step 2 — extract plaintext credential
kubectl get secret grafana-admin-credentials -n monitoring \
  --as=system:serviceaccount:default:overpermissioned-sa \
  -o jsonpath='{.data.admin-password}' | base64 -d
# Returns: ecommerce-lab-2026
```

Full credential retrieved from a ServiceAccount in `default` namespace reaching into `monitoring` namespace. In production this same pattern reaches database credentials, API keys, TLS certificates, and cloud provider access tokens.

**Escalation risk:** An attacker with `cluster-admin` can create additional ClusterRoleBindings — new backdoor identities. Revoking the original token is insufficient once this happens.

### Resolution

```bash
kubectl delete -f module-07/overpermissioned-sa.yaml
```

**Revocation behavior:** Permissions live in the binding, not the token. Deleting the ClusterRoleBinding is sufficient — token rotation is not required. Subsequent API calls with the same token return `Forbidden` immediately because no binding grants permissions to that identity.

---

## Diagnostic Command Reference

| Command | Hierarchy | Purpose |
|---|---|---|
| `kubectl get serviceaccounts -n <ns>` | LOGICAL | List ServiceAccounts in namespace |
| `kubectl auth can-i --list --as=system:serviceaccount:<ns>:<name> -n <ns>` | LOGICAL | Enumerate all permissions for a ServiceAccount |
| `kubectl auth can-i <verb> <resource> --as=system:serviceaccount:<ns>:<name>` | LOGICAL | Test single permission |
| `kubectl get pods -o custom-columns="NAME:.metadata.name,SA:.spec.serviceAccountName"` | LOGICAL | Show ServiceAccount assignment per Pod |
| `kubectl exec <pod> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token` | COMPUTE | Read mounted JWT |
| `kubectl get rolebindings -n <ns> -o wide` | LOGICAL | List RoleBindings with subjects |
| `kubectl get clusterrolebinding <name> -o wide` | LOGICAL | Inspect ClusterRoleBinding subjects |
| `kubectl get clusterroles` | LOGICAL | List all ClusterRoles including built-ins |

---

## Advanced Topics List

*Carried forward from Modules 1-6, additions from Module 7 marked with **[New]**:*

- Internal mechanics of control plane components
- etcd quorum, split-brain failure modes
- Context management tooling
- CNI plugin comparison, eBPF networking, AWS VPC CNI
- Resource requests and limits, QoS classes (Module 8)
- HPA, VPA (Module 8)
- Rolling update strategy, Pod graceful termination (Module 8)
- Node affinity, taints, tolerations (Module 8)
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
- Helm package manager (introduced Module 6 — advanced usage)
- Supply chain security, MetalLB
- Compliance storage patterns, volume snapshots
- EBS CSI driver, storage performance
- Namespace termination failures, CSI drivers
- Sealed Secrets, External Secrets Operator, Vault
- Secret rotation, Reloader operator
- KMS encryption for etcd
- nginx Ingress Controller metrics — enabling controller.metrics.enabled, ServiceMonitor for ingress-nginx
- Loki + Grafana Alloy deployment — log aggregation when real application logs exist
- Grafana Alloy configuration — pipeline model, log enrichment with Kubernetes metadata
- Thanos — long-term metrics storage, global query across clusters
- Mimir — horizontally scalable Prometheus-compatible metrics backend
- VictoriaMetrics Operator — Prometheus-compatible alternative, lower resource consumption
- Prometheus federation — hierarchical metric aggregation across clusters
- OpenTelemetry instrumentation — SDK usage, semantic conventions, OTLP export
- Grafana service graph panel — dynamic topology discovery from trace data
- Backstage service catalog — static model layer, Grafana integration
- SLO-based alerting with Sloth — business-question framing for alerts
- Exemplar-based metric-to-trace linking — Prometheus exemplars, Tempo integration
- Grafana dashboard provisioning — JSON dashboards in Git, automated deployment
- Hierarchical Namespace Controller (HNC) — parent-child namespace relationships
- Namespace management at scale — naming conventions, GitOps namespace provisioning
- eBPF-based observability — Pixie, Cilium Hubble, no-instrumentation metrics and traces
- Grafana Helm-based nginx deployment — metrics enabled by default in production
- Datadog, Dynatrace, New Relic Kubernetes integration patterns
- Alert routing and Alertmanager configuration — receivers, inhibition, silences
- **[New]** OIDC and Kubernetes authentication — API server configuration, kubeconfig structure, kubectl authentication flow
- **[New]** Certificate-based authentication — kubeconfig client certificates, user identity without OIDC
- **[New]** OPA Gatekeeper / Kyverno — custom admission policy engines, registry enforcement, resource limit enforcement
- **[New]** PodSecurity admission — namespace-level policy enforcement, baseline vs restricted profiles
- **[New]** automountServiceAccountToken: false — disabling token mounting for Pods with no API access requirement
- **[New]** Git branch-based manifest management — replacing file versioning suffixes with branch-per-environment pattern
- **[New]** audit2rbac — tool for generating least-privilege RBAC policies from Kubernetes audit logs

---

*Module 8: Production Patterns — resource limits, HPA, pod disruption budgets, rolling updates, node affinity*

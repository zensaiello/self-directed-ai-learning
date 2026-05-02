# Kubernetes Lab — Module 6 Reference
## Observability on Kubernetes — Prometheus Operator, Metrics, Dashboards

**Track:** Kubernetes — Comprehensive Coverage
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster (4 nodes)
**Date Completed:** April 28, 2026

---

## Business Context

The e-commerce application had no visibility. If the product catalog started returning errors, there were no metrics to show when it started, no logs aggregated centrally, and no traces to identify the cause. An on-call engineer paged at 2am would have nothing to look at. Module 6 deploys a production-grade observability stack that monitors the cluster and application workloads automatically — regardless of what Pods come and go.

---

## The Semantic Layer Problem — [LOGICAL]

Raw telemetry — metrics, logs, traces — is data without meaning. Observability tooling collects and displays data. It does not provide meaning. Meaning must be deliberately encoded by the people who build dashboards and alerts.

**The three layers of observability maturity:**

**Layer 1 — Data collection:** Metrics exist, logs are centralized. Most teams stop here.

**Layer 2 — Dashboards and alerts:** Dashboards built around available data, not around operator questions. Alerts fire on symptoms without context.

**Layer 3 — Operational context:** Dashboards organized around business questions and user journeys. Alerts link to runbooks. Metrics annotated with deployment events. The data tells a story.

**[LOGICAL] — the label-based observability principle:**

Kubernetes Pod names and IPs are ephemeral — they change on every rollout. Dashboards built around Pod names break continuously. The correct approach:

```promql
# WRONG — breaks on every deployment
rate(http_requests_total{pod="product-catalog-8686488fd9-b74dw"}[5m])

# CORRECT — stable across rollouts
sum(rate(http_requests_total{app="product-catalog"}[5m]))
```

Always aggregate by stable labels — `app`, `namespace`, `deployment`. Never by Pod name or IP.

---

## Observability Stack Architecture

### Components Deployed

| Component | Type | Purpose |
|-----------|------|---------|
| Prometheus Operator | Deployment | Manages Prometheus, Alertmanager, and ServiceMonitor CRDs |
| Prometheus | StatefulSet | Metrics collection and storage, 7 day retention |
| Alertmanager | StatefulSet | Alert routing and deduplication |
| Grafana | Deployment | Visualization and dashboards |
| Node Exporter | DaemonSet | Host-level metrics, one Pod per node |
| kube-state-metrics | Deployment | Kubernetes object state as metrics |

### Namespace

All observability components deployed to `monitoring` namespace — separate from application workloads for RBAC clarity, resource isolation, and operational separation.

### Storage

All persistent components use `retain-standard` StorageClass:
- Prometheus: 5Gi — metrics data, 7 day retention
- Grafana: 1Gi — dashboard and configuration persistence
- Alertmanager: 1Gi — alert state persistence

---

## Helm — [LOGICAL]

Helm is the package manager for Kubernetes. It manages installation, configuration, upgrading, and removal of applications.

**Three core concepts:**

**Chart** — a package containing all Kubernetes manifests for an application, with a templating system and default configuration.

**Repository** — a collection of charts. Added with `helm repo add`.

**Release** — a named, versioned deployed instance of a chart in a specific namespace.

**Why Helm for the monitoring stack:** kube-prometheus-stack installs approximately 40 Kubernetes resources in the correct order. Managing this manually adds no learning value and significant operational risk.

**Version installed:** Helm v3.20.2

### Installation

```bash
# Add repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install
helm install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values ~/kubernetes-lab/module-06/kube-prometheus-values.yaml \
  --version 69.3.2
```

### Helm and Secrets — Production Pattern

Never put plaintext credentials in Helm values files. Options:

**Pre-created Secret (used in lab):**
```bash
k create secret generic grafana-admin-credentials \
  --namespace monitoring \
  --from-literal=admin-password=ecommerce-lab-2026 \
  --from-literal=admin-user=admin
```

Reference in values file:
```yaml
grafana:
  admin:
    existingSecret: grafana-admin-credentials
    userKey: admin-user
    passwordKey: admin-password
```

**Production alternatives:** Helm Secrets plugin (SOPS encryption), External Secrets Operator, `--set` flag sourcing from pre-existing Secrets at install time.

### Values File

**File:** `~/kubernetes-lab/module-06/kube-prometheus-values.yaml`

Key configuration decisions:
- `serviceMonitorSelectorNilUsesHelmValues: false` — Prometheus discovers ALL ServiceMonitors cluster-wide, not just those labeled `release: kube-prometheus-stack`. Required for cross-namespace ServiceMonitor discovery.
- `retain-standard` StorageClass on all persistent components
- Grafana exposed via Ingress at `grafana.ecommerce.local`
- `retention: 7d` — sufficient for lab, production typically 15-30 days

---

## Custom Resource Definitions (CRDs) — [LOGICAL]

CRDs allow defining new resource types that the Kubernetes API treats as first-class citizens. The Prometheus Operator installs 10 CRDs:

```
alertmanagerconfigs.monitoring.coreos.com
alertmanagers.monitoring.coreos.com
podmonitors.monitoring.coreos.com
probes.monitoring.coreos.com
prometheusagents.monitoring.coreos.com
prometheuses.monitoring.coreos.com
prometheusrules.monitoring.coreos.com
scrapeconfigs.monitoring.coreos.com
servicemonitors.monitoring.coreos.com
thanosrulers.monitoring.coreos.com
```

**CRDs used in this module:**

`servicemonitors` — defines which Services Prometheus scrapes. Label selector-based discovery. The primary mechanism for adding scrape targets without editing prometheus.yml.

`prometheusrules` — defines alerting and recording rules as Kubernetes resources.

`alertmanagerconfigs` — configures Alertmanager routing.

**The Operator pattern:** Instead of managing Prometheus config files, declare intent in Kubernetes-native YAML. The Operator watches CRDs and translates them into Prometheus configuration automatically.

---

## Node Exporter DaemonSet — [COMPUTE]

Four Node Exporter instances — one per node including control plane:

```
kube-prometheus-stack-prometheus-node-exporter-kqh6j   ecommerce-lab-worker2
kube-prometheus-stack-prometheus-node-exporter-m66nh   ecommerce-lab-worker
kube-prometheus-stack-prometheus-node-exporter-nbrzj   ecommerce-lab-control-plane
kube-prometheus-stack-prometheus-node-exporter-s6bpr   ecommerce-lab-worker3
```

**[COMPUTE] — hostNetwork: true:** Node exporter runs on the host network namespace, not the Pod overlay network. Uses node IP (`172.18.0.x`) not Pod IP (`10.244.x.x`). Required for accurate host network interface metrics. This is a legitimate use of host networking — application Pods should never use it.

DaemonSet pattern from Module 2 confirmed in production monitoring architecture.

---

## ServiceMonitors — [LOGICAL]

### Pre-installed by Helm Chart (13 ServiceMonitors)

Automatically scraping all Kubernetes components:
- kube-apiserver, kube-etcd, kube-controller-manager, kube-scheduler
- kubelet (includes cAdvisor container metrics)
- coredns, kube-proxy, kube-state-metrics
- prometheus, alertmanager, grafana, node-exporter, operator

### Product Catalog ServiceMonitor

**[LOGICAL] — prerequisite:** Service must have named ports. ServiceMonitor references ports by name, not number.

**Updated product catalog Service:**
```yaml
ports:
  - name: http        # name required
    port: 80
    targetPort: 5678
    protocol: TCP
```

**File:** `~/kubernetes-lab/module-06/product-catalog-servicemonitor.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: product-catalog
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  namespaceSelector:
    matchNames:
      - default
  selector:
    matchLabels:
      app: product-catalog
  endpoints:
    - port: http
      interval: 30s
      path: /metrics
```

**Verified targets:**
```
Job: product-catalog  Instance: 10.244.1.13:5678  Health: down
Job: product-catalog  Instance: 10.244.2.14:5678  Health: down
Error: strconv.ParseFloat: parsing "-catalog": invalid syntax
```

ServiceMonitor discovery working correctly. Targets down because `http-echo` does not expose Prometheus metrics — instrumentation gap, not a Prometheus configuration problem.

---

## The Instrumentation Gap — [LOGICAL]

**Critical distinction:** Infrastructure observability vs application observability.

**What the monitoring stack provides automatically:**
- Node CPU, memory, disk, network (Node Exporter)
- Pod CPU and memory consumption (cAdvisor via kubelet)
- Kubernetes object health — replica counts, restart counts, PVC status (kube-state-metrics)
- Deployment generation tracking

**What requires application instrumentation:**
- Request rate per endpoint
- Error rate per endpoint
- Request latency (p50, p95, p99)
- Database query duration
- Cache hit rates
- Business metrics — cart size, checkout conversion rate

Infrastructure metrics tell you something is wrong. Application metrics tell you what and why.

**[NETWORK] — nginx Ingress as a partial substitute:**

The nginx Ingress Controller exposes request rate, latency, and error rate per path when metrics are enabled (`controller.metrics.enabled: true` in Helm values). This provides boundary-level application observability without code instrumentation. Kind-specific nginx manifest does not enable metrics by default — production Helm-based deployments do.

**Production instrumentation options:**
- Prometheus client libraries (Go, Python, Java, Node.js) — direct metric emission
- OpenTelemetry SDK — vendor-neutral instrumentation, multiple backends
- Sidecar exporters — metrics proxy alongside uninstrumented applications
- eBPF-based observability (Pixie, Cilium) — no instrumentation required

---

## Prometheus Targets — Verified State

```
Total active targets: 33
Up: 26
Down: 7
```

**Down targets — all kind-specific limitations:**
- `kube-controller-manager` — binds to 127.0.0.1 inside control plane container
- `kube-scheduler` — same
- `kube-etcd` — same
- `kube-proxy` (x4) — metrics port not exposed in kind configuration

**Production behavior:** On EKS these components are AWS-managed. Some expose metrics via API server proxy, others are disabled in the ServiceMonitor configuration. Not a production concern.

---

## Prometheus Target Diagnostic Path — [LOGICAL]

```
Step 1: k get servicemonitor -n monitoring
        → confirm ServiceMonitor exists

Step 2: Check targets API
        curl http://localhost:9090/api/v1/targets
        → is target discovered?
        → if not: check release label (strict selector mode)
                  check namespaceSelector
                  check Service label selector

Step 3: Check target health and error
        → "connection refused" → wrong port or metrics not exposed
        → "parse error"       → endpoint exists, wrong format
        → "404"               → wrong metrics path
        → "unknown"           → not yet scraped, wait 30s and retry

Step 4: Verify directly
        k run curl-test --image=curlimages/curl:8.6.0 --restart=Never --rm -it -- \
          curl http://<service>.<namespace>.svc.cluster.local/metrics
```

---

## ServiceMonitor Label Selector Behavior — [LOGICAL]

### Strict mode (default — serviceMonitorSelectorNilUsesHelmValues: true)
Prometheus only discovers ServiceMonitors labeled `release: kube-prometheus-stack`. ServiceMonitors without this label are silently ignored. Correct for multi-team environments with strict separation.

### Permissive mode (our configuration — serviceMonitorSelectorNilUsesHelmValues: false)
Prometheus discovers ALL ServiceMonitors cluster-wide regardless of labels. Required when application ServiceMonitors live in different namespaces from the Helm release. Side effect: any ServiceMonitor anywhere gets scraped.

**Production choice:** Depends on organizational model. Single team → permissive. Multiple teams with strict boundaries → strict with documented label requirements.

---

## Observability Monitoring Approaches — [LOGICAL]

| Approach | Model | Data leaves cluster | Instrumentation required | Auto-discovery |
|----------|-------|---------------------|--------------------------|----------------|
| Prometheus Operator + Grafana | Self-hosted | No | Yes (or exporters) | Via ServiceMonitor labels |
| Datadog | SaaS | Yes | Minimal (DaemonSet agent) | Yes |
| Dynatrace | SaaS | Yes | None (OneAgent + AI) | Yes — full topology |
| New Relic + Pixie | SaaS | Yes | None (eBPF) | Yes |
| Elastic ECK | Self-hosted | No | Yes | Partial |
| OpenTelemetry + any backend | Hybrid | Configurable | Yes (OTel SDK) | Via semantic conventions |

**[LOGICAL] — OpenTelemetry convergence:** Industry converging on OTel as the instrumentation standard regardless of backend. Datadog, Dynatrace, New Relic, and Grafana all accept OTLP. Instrument once, switch backends without re-instrumenting.

---

## Grafana — [LOGICAL]

**Access:** `http://grafana.ecommerce.local`
**Credentials:** admin / ecommerce-lab-2026 (from pre-created Secret)
**Ingress:** `grafana.ecommerce.local` → nginx Ingress Controller → Grafana Service

**Hosts file entry required:**
```bash
echo "127.0.0.1 grafana.ecommerce.local" | sudo tee -a /etc/hosts
```

### Pre-built Dashboards (kubernetes-mixin)

Comprehensive cluster monitoring dashboards installed automatically:
- Kubernetes / Compute Resources / Cluster — overall resource utilization
- Kubernetes / Compute Resources / Node (Pods) — per-node Pod consumption
- Node Exporter / Nodes — host-level metrics

**Gaps in pre-built dashboards:**
- No application-scoped filtering — monitoring Pods mixed with application Pods
- No capacity headroom visibility without resource limits defined
- No storage health correlated with StatefulSet health
- No deployment event correlation with metric changes

### E-Commerce Workload Health Dashboard

**File:** `ecommerce-workload-health-dashboard.json`

**Panels:**
- Product Catalog Replica Availability — ratio stat, green/yellow/red thresholds
- Product Catalog Available vs Desired Replicas — stat with both values
- PostgreSQL StatefulSet Ready Replicas — stat, green at 1
- PostgreSQL PVC Bound Status — stat with text mapping (BOUND/NOT BOUND)
- Pod Restart Count Time Series — all containers in default namespace, zero = healthy
- Pod CPU Usage Time Series — per Pod, filtered to default namespace
- Pod Memory Working Set Time Series — per Pod, filtered to default namespace
- Log Collector DaemonSet Coverage — ready vs desired, green at 4

**datasource variable:** Must be set to `Prometheus` after import.

**What this dashboard adds over pre-built dashboards:**
- Scoped entirely to default namespace — no monitoring infrastructure noise
- postgres PVC and StatefulSet health together in one view
- Log collector DaemonSet coverage visibility
- All application workload restarts in one graph

---

## Log Aggregation — Architecture (Not Deployed) — [LOGICAL]

**[LOGICAL] — why not deployed in this module:**

The log-collector DaemonSet from Module 2 echoes text rather than collecting real application logs. Deploying Loki + Grafana Alloy to aggregate meaningless echo output adds operational overhead without observable value. Flagged for implementation when real application logs exist.

### Loki + Grafana Alloy Architecture

```
[COMPUTE] Grafana Alloy DaemonSet (one Pod per node)
  → reads Pod logs via /var/log/pods/ on each node
  → enriches with Kubernetes metadata (namespace, pod, container, labels)
  → ships to Loki

[STORAGE] Loki
  → stores logs indexed by labels
  → queryable via LogQL

[LOGICAL] Grafana
  → Loki datasource
  → Explore view for ad-hoc log queries
  → Dashboard panels combining metrics and logs
```

**[LOGICAL] — why Grafana Alloy over Promtail:**
Alloy is the current Grafana recommendation — replaces Promtail. Unified collector for metrics, logs, traces, and profiles in a single agent. Uses OpenTelemetry Collector as underlying engine. Reduces node overhead vs running separate agents per signal type.

**Deployment pattern:**
```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm install loki grafana/loki-stack \
  --namespace monitoring \
  --set grafana.enabled=false \
  --set promtail.enabled=false \
  --set alloy.enabled=true
```

---

## Failure Scenario — ServiceMonitor Label Mismatch — [LOGICAL]

**Category:** Silent scrape target discovery failure — ServiceMonitor exists but Prometheus ignores it.

**What was broken:** ServiceMonitor missing `release: kube-prometheus-stack` label in strict selector mode.

**Why it is dangerous:** No error is produced. Prometheus simply never discovers the target. Metrics gaps appear silently — an operator may assume a service is being monitored when it is not.

**In our permissive configuration:** The broken ServiceMonitor was discovered because `serviceMonitorSelectorNilUsesHelmValues: false` disables label filtering entirely. Demonstrated that target discovery worked correctly — failure was at the metrics format layer, not the discovery layer.

**Production diagnostic for missing targets in strict mode:**
```bash
# Check ServiceMonitor labels
k get servicemonitor -n monitoring <name> -o yaml | grep labels -A 5

# Verify required label present
k get servicemonitor -n monitoring <name> -o jsonpath='{.metadata.labels}'
# Must include: release: kube-prometheus-stack
```

---

## Diagnostic Command Reference

| Command | Hierarchy | Purpose |
|---------|-----------|---------|
| `helm list -n monitoring` | LOGICAL | List installed Helm releases |
| `helm status kube-prometheus-stack -n monitoring` | LOGICAL | Release status and notes |
| `helm get values kube-prometheus-stack -n monitoring` | LOGICAL | Currently applied values |
| `k get crd \| grep monitoring` | LOGICAL | List Prometheus Operator CRDs |
| `k get servicemonitors -n monitoring` | LOGICAL | List all ServiceMonitors |
| `k get prometheusrules -n monitoring` | LOGICAL | List all alerting rules |
| `k get pods -n monitoring -o wide` | COMPUTE | Monitoring stack Pod placement |
| `k port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090` | NETWORK | Access Prometheus UI |
| `curl http://localhost:9090/api/v1/targets` | NETWORK | Check scrape targets and health |
| `k get ingress -n monitoring` | NETWORK | Grafana Ingress status |

---

## Advanced Topics List

*Carried forward from Modules 1-5, additions from Module 6 marked with **[New]**:*

- Internal mechanics of control plane components
- etcd quorum, split-brain failure modes
- Context management tooling
- CNI plugin comparison, eBPF networking, AWS VPC CNI
- Resource requests and limits, QoS classes (Module 8)
- RBAC in full (Module 7)
- HPA, VPA (Module 8)
- Rolling update strategy, Pod graceful termination (Module 8)
- Node affinity, taints, tolerations (Module 8)
- Spot instance node management
- Namespace resource quotas (Module 7)
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
- Helm package manager (introduced this module — advanced usage)
- Supply chain security, MetalLB
- Compliance storage patterns, volume snapshots
- EBS CSI driver, storage performance
- Namespace termination failures, CSI drivers
- Sealed Secrets, External Secrets Operator, Vault
- Secret rotation, Reloader operator
- KMS encryption for etcd
- **[New]** nginx Ingress Controller metrics — enabling controller.metrics.enabled, ServiceMonitor for ingress-nginx
- **[New]** Loki + Grafana Alloy deployment — log aggregation when real application logs exist
- **[New]** Grafana Alloy configuration — pipeline model, log enrichment with Kubernetes metadata
- **[New]** Thanos — long-term metrics storage, global query across clusters
- **[New]** Mimir — horizontally scalable Prometheus-compatible metrics backend
- **[New]** VictoriaMetrics Operator — Prometheus-compatible alternative, lower resource consumption
- **[New]** Prometheus federation — hierarchical metric aggregation across clusters
- **[New]** OpenTelemetry instrumentation — SDK usage, semantic conventions, OTLP export
- **[New]** Grafana service graph panel — dynamic topology discovery from trace data
- **[New]** Backstage service catalog — static model layer, Grafana integration
- **[New]** SLO-based alerting with Sloth — business-question framing for alerts
- **[New]** Exemplar-based metric-to-trace linking — Prometheus exemplars, Tempo integration
- **[New]** Grafana dashboard provisioning — JSON dashboards in Git, automated deployment
- **[New]** Hierarchical Namespace Controller (HNC) — parent-child namespace relationships
- **[New]** Namespace management at scale — naming conventions, GitOps namespace provisioning
- **[New]** eBPF-based observability — Pixie, Cilium Hubble, no-instrumentation metrics and traces
- **[New]** Grafana Helm-based nginx deployment — metrics enabled by default in production
- **[New]** Datadog, Dynatrace, New Relic Kubernetes integration patterns
- **[New]** Alert routing and Alertmanager configuration — receivers, inhibition, silences

---

*Module 7: RBAC and Security — ServiceAccounts, Roles, ClusterRoles, admission controllers*

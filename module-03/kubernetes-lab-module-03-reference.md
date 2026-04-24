# Kubernetes Lab — Module 3 Reference
## Networking — Services, DNS, and Ingress

**Track:** Kubernetes — Comprehensive Coverage
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster (4 nodes)
**Date Completed:** April 24, 2026

---

## Business Context

The e-commerce application had running workloads but no stable communication between them. Pod IPs are ephemeral — every restart produces a new IP. Direct Pod IP communication is unworkable at scale. External traffic had no entry point into the cluster. Module 3 establishes the networking layer that makes the application functional — stable internal endpoints, DNS-based service discovery, and controlled external access.

---

## Cluster Configuration Change

Module 3 introduced a third worker node and proper port mappings for Ingress. Node labels are now defined in the cluster manifest — no manual labeling required after cluster creation.

**[COMPUTE] / [LOGICAL] — Final cluster config:**

**File:** `~/kubernetes-lab/module-03/kind-config-ingress.yaml`

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ecommerce-lab
nodes:
  - role: control-plane
  - role: worker
    labels:
      node-type: ingress
      ingress-ready: "true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
  - role: worker
    labels:
      node-type: compute
  - role: worker
    labels:
      node-type: compute
```

**[COMPUTE] — Node layout:**

| Node | Role | Labels |
|------|------|--------|
| ecommerce-lab-control-plane | control-plane | system labels only |
| ecommerce-lab-worker | worker | node-type=ingress, ingress-ready=true |
| ecommerce-lab-worker2 | worker | node-type=compute |
| ecommerce-lab-worker3 | worker | node-type=compute |

**[LOGICAL] — production parallel:** On EKS, node group labels are defined in the node group configuration. Every node joining the group inherits those labels automatically. The Ingress Controller node selector targets `ingress-ready=true` — it will only ever land on ingress-designated nodes regardless of how many compute nodes exist.

---

## The Three Kubernetes Hierarchies

Kubernetes has three distinct hierarchies that operate independently and intersect at specific points. Conflating them is the primary source of conceptual confusion.

**[COMPUTE] hierarchy — physical and logical execution:**
```
Data Center / Cloud Region
  └── Node (VM, bare metal, or Docker container in kind)
        └── containerd (container runtime)
              └── Container (actual running process)
                    └── Pod (Kubernetes wrapper around containers)
                          └── Controller (Deployment, StatefulSet, DaemonSet)
```

**[NETWORK] hierarchy — how traffic flows:**
```
External traffic (internet, laptop)
  └── Load Balancer / NodePort (entry point into cluster)
        └── Ingress Controller (HTTP routing rules)
              └── Service (stable virtual IP, load balancing)
                    └── Endpoints (live list of Pod IPs)
                          └── Pod (actual traffic destination)
```

**[STORAGE] hierarchy — how data persists:**
```
Physical storage (disk, EBS volume, NFS share)
  └── StorageClass (provisioner and policy)
        └── PersistentVolume (actual provisioned storage)
              └── PersistentVolumeClaim (request for storage)
                    └── Volume mount (path inside container)
```

**[LOGICAL] / API hierarchy — how Kubernetes organizes resources:**
```
Cluster
  └── Namespace (logical partition — spans all three hierarchies)
        └── Resources (Pods, Services, PVCs, etc.)
```

**Key principle — namespaces are not tied to nodes:**
A namespace is a logical API concept. It has no physical relationship to nodes. Pods within a namespace can be scheduled on any node. A node can run Pods from multiple namespaces simultaneously.

---

## How Services Work

**[NETWORK]** A Service is not a process, container, or Pod. It is a Kubernetes object that defines:

- A stable virtual IP (ClusterIP) — assigned at creation, never changes for the lifetime of the Service
- A label selector — identifies which Pods receive traffic
- An Endpoints object — continuously updated list of healthy Pod IPs matching the selector

**[NETWORK] Traffic flow through a Service:**
```
Client sends traffic to ClusterIP
  → kube-proxy intercepts (iptables or eBPF rules on each node)
    → kube-proxy load balances to one of the Pod IPs in Endpoints
      → traffic reaches the Pod
```

**[NETWORK] Why label selectors are critical:**
A Service finds its Pods entirely by labels. A wrong selector produces an empty Endpoints object and silent traffic failure — no error, just 503s. `k get endpoints <service>` is the first diagnostic command for Service traffic failures.

---

## Kubernetes DNS — [NETWORK]

Kubernetes runs **CoreDNS** as an internal DNS server — completely separate from enterprise DNS. Enterprise DNS never sees in-cluster queries.

**How it works:**
- Every Pod is configured at creation with `/etc/resolv.conf` pointing to the CoreDNS ClusterIP (`10.96.0.10`)
- All in-cluster DNS queries go to CoreDNS, not corporate DNS infrastructure
- Service DNS records have short TTLs (~5 seconds) — changes propagate almost immediately

**Why TTL is not a problem for Services:**
Service DNS resolves to the ClusterIP — a stable virtual IP that never changes, not to ephemeral Pod IPs. Pod IP translation happens at the network layer via kube-proxy, not at the DNS layer.

**[NETWORK] Full DNS name anatomy:**
```
product-catalog . default . svc . cluster.local
[service name]  [namespace] [type] [cluster domain]
```

**Short name resolution:** A Pod in the `default` namespace can reach `product-catalog` by short name — Kubernetes appends the rest via search domains in `/etc/resolv.conf`. A name containing a dot is treated as partially qualified and requires the full FQDN.

**Cross-namespace:** A Pod in a different namespace must use `product-catalog.default` or the full FQDN.

**Verified DNS resolution:**
```
Server:   10.96.0.10
Name:     product-catalog.default.svc.cluster.local
Address:  10.96.146.115
```

CoreDNS ClusterIP: `10.96.0.10`

---

## Service Types

### ClusterIP — [NETWORK]

Internal only. Stable virtual IP reachable from anywhere inside the cluster. Not accessible from outside.

**File:** `~/kubernetes-lab/module-03/product-catalog-service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: product-catalog
  labels:
    app: product-catalog
spec:
  type: ClusterIP
  selector:
    app: product-catalog
  ports:
    - port: 80
      targetPort: 5678
      protocol: TCP
```

**Port separation:** `port: 80` is what clients use. `targetPort: 5678` is the container port. These can differ — allows changing the container port without changing how other services call it.

**Verified state:**
```
NAME              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)
product-catalog   ClusterIP   10.96.146.115   <none>        80/TCP
```

**Verified Endpoints:**
```
NAME              ENDPOINTS
product-catalog   10.244.2.2:5678,10.244.3.2:5678,10.244.1.2:5678
```

**Verified traffic via DNS name:**
```bash
k run curl-test --image=curlimages/curl:8.6.0 --restart=Never --rm -it -- curl http://product-catalog
# product-catalog service - version 1.0
```

---

### Headless Service — [NETWORK]

No ClusterIP assigned. DNS resolves directly to individual Pod IPs. Required by StatefulSets for stable per-Pod DNS names.

**File:** `~/kubernetes-lab/module-03/postgres-service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres
  labels:
    app: postgres
spec:
  type: ClusterIP
  clusterIP: None
  selector:
    app: postgres
  ports:
    - port: 5432
      targetPort: 5432
      protocol: TCP
```

**Per-Pod DNS naming pattern:**
```
postgres-0.postgres.default.svc.cluster.local → Pod IP of postgres-0
postgres-1.postgres.default.svc.cluster.local → Pod IP of postgres-1
```

**Verified DNS resolution:**
```bash
k run dns-test --image=busybox:1.36 --restart=Never --rm -it -- \
  nslookup postgres-0.postgres.default.svc.cluster.local
# Name: postgres-0.postgres.default.svc.cluster.local
# Address: 10.244.2.5  ← actual Pod IP, not a ClusterIP
```

**Verified Pod IP match:**
```
NAME         IP
postgres-0   10.244.2.5  ← confirmed match
```

**[NETWORK] ClusterIP vs Headless contrast:**
- `product-catalog` → ClusterIP `10.96.146.115` → kube-proxy load balances to any healthy Pod
- `postgres-0.postgres...` → Pod IP `10.244.2.5` directly → traffic goes to exactly that Pod

---

### NodePort — [NETWORK] — RETIRED after Module 3

Exposes a Service on a static port on every node. Valid port range: 30000-32767.

**Lab deviation from production:** NodePort exposes a port on every node including the control plane — a security concern. Requires clients to know node IPs and ports directly. Not used for application traffic in production.

**Purpose in lab:** Demonstrated external access via node IP before Ingress was introduced.

**Observed:** `curl http://172.18.0.3:30080` → `product-catalog service - version 1.0`

**File retained for reference:** `~/kubernetes-lab/module-03/product-catalog-nodeport.yaml`

---

### LoadBalancer — [NETWORK] — RETIRED after Module 3

Provisions a cloud load balancer for external traffic. Requires cloud provider integration.

**In kind:** EXTERNAL-IP remains `<pending>` indefinitely — no cloud provider to fulfill the request.

**[NETWORK] On EKS:** Provisions an AWS ELB/NLB automatically. DNS name appears in EXTERNAL-IP column.

**[NETWORK] Underlying architecture:**
```
Internet
  → AWS ELB/NLB
    → NodePort on cluster nodes
      → ClusterIP Service
        → Pods
```

LoadBalancer Services always include a NodePort underneath. The cloud load balancer forwards to the NodePort.

**Lab deviation from production:** MetalLB provides LoadBalancer functionality for on-premise or local clusters without a cloud provider.

**File retained for reference:** `~/kubernetes-lab/module-03/product-catalog-loadbalancer.yaml`

---

## Ingress — [NETWORK]

### Why Ingress Exists

A LoadBalancer Service provisions one cloud load balancer per Service. At scale this is expensive and operationally complex. Ingress puts a single load balancer in front of all Services and routes based on HTTP rules.

```
Internet
  → Single Load Balancer
    → Ingress Controller
      → /products  → product-catalog Service
      → /checkout  → checkout Service (Module 3+)
      → /cart      → cart Service (future)
```

**[NETWORK] Two components:**
- **Ingress resource** — routing rules defined by the user
- **Ingress Controller** — the process that reads rules and implements them. Not installed by default.

**[NETWORK] Ingress is HTTP/HTTPS only** — operates at Layer 7. Cannot route non-HTTP protocols (PostgreSQL, Redis, MQTT, etc.).

### Ingress Controller Installation

**[LOGICAL] — Production note on manifest sourcing:**
Never apply manifests directly from external URLs in production without first downloading, reviewing, and storing them in your own repository. A compromised upstream URL could deliver malicious resources.

**Correct approach:**
```bash
# Download first
curl -o ~/kubernetes-lab/module-03/ingress-nginx.yaml \
  https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/kind/deploy.yaml

# Review, store in Git, then apply from local copy
k apply -f ~/kubernetes-lab/module-03/ingress-nginx.yaml
```

**[COMPUTE] Controller placement:** Ingress Controller scheduled to `ecommerce-lab-worker` via `ingress-ready=true` node selector — defined in the nginx manifest, matched by the label set in the cluster config.

**Verified:**
```
ingress-nginx-controller   1/1   Running   ecommerce-lab-worker
```

**[LOGICAL] Admission Jobs:** Two completed Jobs (`ingress-nginx-admission-create`, `ingress-nginx-admission-patch`) set up the admission webhook that validates Ingress resources at apply time. STATUS: Completed is healthy — not a failure state. Retained for log inspection per default Kubernetes behavior. `ttlSecondsAfterFinished` not set in the nginx manifest — production best practice is to set this on all Jobs to prevent accumulation.

### Ingress Resource

**File:** `~/kubernetes-lab/module-03/product-catalog-ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: product-catalog
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
    - host: ecommerce.local
      http:
        paths:
          - path: /products
            pathType: Prefix
            backend:
              service:
                name: product-catalog
                port:
                  number: 80
```

**Key fields:**
- `ingressClassName: nginx` — routes to the nginx Ingress Controller. Multiple controllers can coexist in one cluster.
- `host: ecommerce.local` — Ingress only responds to requests with this HTTP Host header
- `path: /products` — path-based routing. Other paths return 404.

**Verified routing:**
```bash
curl http://localhost/products -H "Host: ecommerce.local"
# product-catalog service - version 1.0

curl http://localhost/checkout -H "Host: ecommerce.local"
# 404 Not Found
```

**[NETWORK] Full verified traffic chain:**
```
curl on laptop (port 80)
  → extraPortMapping on ecommerce-lab-worker (localhost:80 → containerPort:80)
    → ingress-nginx-controller Pod (node-type=ingress)
      → matched rule: host=ecommerce.local, path=/products
        → product-catalog ClusterIP Service (10.96.146.115:80)
          → Endpoints (Pod IPs on port 5678)
            → product-catalog Pod
              → response returned
```

---

## Non-HTTP External Access — [NETWORK]

Ingress cannot route non-HTTP protocols. Options for exposing TCP/UDP services externally:

**LoadBalancer Service (Layer 4):**
Provisions an AWS NLB on EKS — handles any TCP/UDP protocol. One load balancer per Service. Simple but expensive at scale.

**Gateway API (modern successor to Ingress):**
Supports both HTTP and raw TCP/UDP routing from a single gateway. TCPRoute resource routes non-HTTP traffic by port.

**Service mesh ingress gateway (Istio, Linkerd):**
Handles HTTP and TCP, adds mTLS, circuit breaking, traffic control. Production pattern for complex microservices.

**PostgreSQL specifically — production pattern:**
Never expose a database directly outside the cluster. Options:
- VPN / private network connectivity into the VPC — direct Service IP access without public exposure
- `kubectl port-forward` for temporary admin access — auditable, no permanent exposure:
  ```bash
  kubectl port-forward pod/postgres-0 5432:5432
  ```

**Rule of thumb:**
- HTTP/HTTPS application traffic → Ingress
- TCP/UDP at scale → Gateway API or LoadBalancer Service
- Database access → VPN or port-forward. Never permanent public exposure.

---

## Network Bottlenecks — [NETWORK]

Every layer in the network hierarchy has a throughput ceiling.

**Ingress Controller:**
Single Deployment — all HTTP traffic flows through it. Production mitigations: scale to multiple replicas, size resource requests/limits correctly, monitor nginx metrics (request rate, error rate, latency, active connections).

**kube-proxy (iptables):**
Linear rule matching — every packet walks the full iptables rule chain. At thousands of Services and tens of thousands of Pods, performance degrades measurably. Production solution: Cilium with eBPF — O(1) lookups replace linear traversal.

**CoreDNS:**
High Pod density with high DNS query rates creates bottleneck. Mitigations: scale CoreDNS replicas, enable NodeLocal DNSCache (runs DNS cache on every node), use FQDNs in applications to avoid search domain expansion overhead.

**Cloud load balancer:**
AWS NLB supports millions of requests per second — rarely the bottleneck. Connection limits per target node are real and must be sized for high-traffic applications.

---

## Scheduler Behavior — [COMPUTE]

The scheduler makes a one-time placement decision when a Pod is created. It does not continuously rebalance running Pods.

**Scoring criteria:**
- Available CPU/memory vs Pod resource requests
- Node selectors and affinity rules
- Taints and tolerations
- Spreading constraints (spread replicas across nodes/zones)

**The Descheduler:** Optional component that performs periodic rebalancing — evicts suboptimally placed Pods for the scheduler to replace. Not installed by default. Requires careful configuration with PodDisruptionBudgets.

**Node pressure eviction:** kubelet monitors actual resource consumption. Under critical memory or disk pressure, evicts Pods in order: BestEffort first, then Burstable, then Guaranteed.

**[COMPUTE] Cluster Autoscaler:** Watches for Pending Pods due to insufficient node capacity. Triggers cloud provider to add nodes. Works in combination with HPA — HPA scales Pods, Cluster Autoscaler scales nodes.

---

## Failure Scenario — Service Selector Mismatch

**Category:** Silent traffic failure — Service exists, Pods are running, traffic fails.

**What was broken:** Service selector changed to non-matching value:
```yaml
selector:
  app: product-catalog-wrong  # does not match any Pod labels
```

**Symptoms:**
- All Pods running and healthy
- Service exists with ClusterIP assigned
- Ingress rule unchanged
- Customer sees: `503 Service Unavailable`
- No errors in cluster events

**Why it is dangerous:** Nothing in the infrastructure throws an error. The failure is visible only to traffic — and only after it reaches the Service.

**Diagnostic path:**
```bash
# Step 1 — check Endpoints — gap appears here
k get endpoints product-catalog
# NAME              ENDPOINTS
# product-catalog   <none>

# Step 2 — compare selector to Pod labels
k describe service product-catalog | grep Selector
# Selector: app=product-catalog-wrong

k get pods --show-labels
# Labels: app=product-catalog  ← mismatch identified
```

**Resolution:** Correct the selector in the manifest and reapply.

**Post-restoration propagation:** After Endpoints are restored, kube-proxy updates iptables rules on each node. Sub-second in healthy clusters, a few seconds under load. Traffic resumes after propagation completes.

**Production discipline:** `k get endpoints` is the first command to run when a Service returns 503. Empty Endpoints always means selector mismatch or all matching Pods unhealthy.

---

## Active Workload Inventory

| Resource | Type | Namespace | Purpose |
|----------|------|-----------|---------|
| product-catalog | Deployment | default | Product catalog service, 2 replicas |
| postgres | StatefulSet | default | E-commerce database |
| log-collector | DaemonSet | default | Log collection, one Pod per node |
| product-catalog | Service (ClusterIP) | default | Stable internal endpoint |
| postgres | Service (Headless) | default | Per-Pod DNS for StatefulSet |
| product-catalog | Ingress | default | HTTP routing /products → product-catalog |
| ingress-nginx-controller | Deployment | ingress-nginx | nginx Ingress Controller |

**Retired after Module 3 (manifests retained for reference):**
- Naked Pod (`module-01/product-catalog.yaml`) — replaced by Deployment
- NodePort Service — replaced by Ingress
- LoadBalancer Service — replaced by Ingress

---

## Diagnostic Command Reference

| Command | Hierarchy | Purpose |
|---------|-----------|---------|
| `k get services` | NETWORK | List all Services and their types/IPs |
| `k get endpoints <n>` | NETWORK | Verify Pods are registered to a Service |
| `k describe service <n>` | NETWORK | Full Service detail including selector |
| `k get ingress` | NETWORK | Ingress rules and address assignment |
| `k describe ingress <n>` | NETWORK | Full Ingress detail including rules |
| `k get pods -n ingress-nginx` | COMPUTE | Ingress Controller Pod status |
| `k run dns-test --image=busybox:1.36 --restart=Never --rm -it -- nslookup <name>` | NETWORK | In-cluster DNS resolution test |
| `k run curl-test --image=curlimages/curl:8.6.0 --restart=Never --rm -it -- curl <url>` | NETWORK | In-cluster HTTP traffic test |
| `k get nodes --show-labels` | COMPUTE/LOGICAL | Node labels for scheduling verification |
| `k label node <n> <key>=<value>` | LOGICAL | Apply label to node manually |
| `k get pods -o wide` | COMPUTE | Pod placement across nodes |
| `kubectl port-forward pod/<n> <local>:<remote>` | NETWORK | Temporary external access for debugging |

---

## Advanced Topics List

*Carried forward from Modules 1-2, additions from Module 3 marked with **[New]**:*

- Internal mechanics of each control plane component (etcd Raft consensus, scheduler scoring, controller reconciliation loop internals)
- etcd quorum requirements, odd-number member rule, split-brain failure modes
- Context management tooling: kubectx, kubens, shell prompt integration
- CNI plugin comparison: kindnet vs. Calico vs. Cilium vs. AWS VPC CNI
- **[New]** CNI in depth — overlay networks, cross-node Pod routing, eBPF networking with Cilium
- **[New]** AWS VPC CNI — native VPC IP assignment, capacity planning implications
- Resource requests and limits, QoS classes, eviction order (Module 8)
- RBAC and service account token permissions (Module 7)
- Horizontal Pod Autoscaler (HPA) — CPU/memory based autoscaling (Module 8)
- Vertical Pod Autoscaler (VPA) — resource right-sizing
- revisionHistoryLimit — controlling retained ReplicaSet count (Module 8)
- Rolling update strategy — maxSurge, maxUnavailable (Module 8)
- Pod graceful termination — SIGTERM, terminationGracePeriodSeconds (Module 8)
- Node roles, labels, taints, tolerations, node affinity (Module 8)
- Spot instance node management — interruption handling, mixed instance clusters
- Namespace resource quotas and LimitRanges (Module 7)
- GitOps platforms — ArgoCD, Flux, deployment audit trails
- Kubernetes audit logging — API server audit policy, compliance retention
- Container image size best practices — impact on Pod startup and recovery time
- Cluster event persistence — shipping to Loki, Elasticsearch, CloudWatch
- Provisioning tools module — kind, eksctl, Terraform for cluster provisioning
- PostgreSQL HA on Kubernetes — replication configuration, primary/standby promotion
- Production StorageClass design — EBS CSI driver, Retain reclaim policy, volume expansion
- Multi-container Pod patterns in depth — sidecar, init container, ambassador
- Descheduler configuration, eviction policies, Pod priority classes
- Cluster Autoscaler — node group sizing, scale-down safety rules
- Job and CronJob controllers — `ttlSecondsAfterFinished`, cleanup policies
- **[New]** Kubernetes Gateway API — TCP/UDP routing, successor to Ingress
- **[New]** Service mesh — Istio, Linkerd, ingress gateway, mTLS, traffic control
- **[New]** Exposing non-HTTP ports externally — Gateway API, LoadBalancer Services for TCP/UDP
- **[New]** Temporary port exposure for debugging — kubectl port-forward, access scoping, audit trail
- **[New]** Network access restrictions — loadBalancerSourceRanges IP allowlisting, NetworkPolicies, cloud security group integration on EKS
- **[New]** Ingress Controller scaling and performance tuning
- **[New]** kube-proxy vs Cilium eBPF at scale — iptables linear traversal vs O(1) eBPF lookups
- **[New]** NodeLocal DNSCache — per-node DNS caching, reducing CoreDNS load
- **[New]** Cloud load balancer sizing and connection limits
- **[New]** CoreDNS configuration — stub zones, external DNS forwarding, enterprise DNS integration
- **[New]** external-dns project — automating enterprise DNS records for Kubernetes Services
- **[New]** Helm package manager — third-party component installation, version management
- **[New]** Supply chain security for Kubernetes manifests
- **[New]** MetalLB — LoadBalancer support for on-premise and local clusters

---

*Module 4: Storage — Volumes, PersistentVolumes, PersistentVolumeClaims, StorageClasses in depth*

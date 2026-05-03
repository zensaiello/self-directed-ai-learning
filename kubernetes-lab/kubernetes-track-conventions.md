# Kubernetes Track Conventions
## Steven Aiello — Kubernetes Lab Reference

This document captures track-specific decisions, conventions, and context for the Kubernetes learning track. Upload this alongside the learning preferences document and the most recent module reference document at the start of each new module session.

---

## Track Overview

**Goal:** Comprehensive Kubernetes coverage from fundamentals through production patterns, culminating in EKS-ready knowledge applicable to senior-level technical conversations.

**Lab environment:** Pop!_OS (Ubuntu jammy base), local kind cluster.

**Repository:** Private GitHub repo — `kubernetes-lab/`

---

## Lab Environment — Pinned Versions

| Component | Version |
|---|---|
| kind | Current stable (no package manager distribution — binary install acceptable) |
| kubectl | Installed via official Kubernetes apt repository, pinned to minor version |
| Kubernetes | v1.32.3 |
| Helm | v3.20.2 |
| Docker | Current stable |

---

## Cluster Configuration

**Cluster name:** `ecommerce-lab`

**Node layout:**
```
ecommerce-lab-control-plane
ecommerce-lab-worker
ecommerce-lab-worker2
ecommerce-lab-worker3
```

**Namespace convention:**
- `default` — application workloads
- `monitoring` — observability stack

**kubectl alias:** `k` is aliased to `kubectl` throughout all lab sessions.

---

## The E-Commerce Workload

The persistent workload running across all modules. Every infrastructure concept is taught in the context of what this application requires.

**Services:**
- `product-catalog` — Deployment, 2 replicas, serves product data
- `postgres` — StatefulSet, backing database
- `cart-session` — bare Pod, retired after Module 4 (served storage lab purpose)
- `log-collector` — DaemonSet, one Pod per node

**Access:**
- Product catalog: `http://product-catalog.ecommerce.local`
- Grafana: `http://grafana.ecommerce.local` (admin / ecommerce-lab-2026)

**Hosts file entries required:**
```bash
echo "127.0.0.1 product-catalog.ecommerce.local" | sudo tee -a /etc/hosts
echo "127.0.0.1 grafana.ecommerce.local" | sudo tee -a /etc/hosts
```

---

## Repository Structure Convention

**Manifest management uses Git branches, not filename version suffixes.**

Each module is a branch. Changes to manifests are tracked as commits within that branch. The branch history is the versioning mechanism — no `v2`, `v3` filename suffixes.

```
main          — stable, production-equivalent state after each module
module-01     — branch for Module 1 work
module-02     — branch for Module 2 work
...
module-N      — branch for current module work
```

Prior module manifests are portfolio artifacts. Merging to main after each module preserves the complete history.

**Note:** Modules 1–7 were completed before this convention was established and use the subdirectory + filename versioning pattern. The branch convention applies to Module 8 onwards and to all new tracks.

**Directory layout (Modules 1–7, legacy):**
```
kubernetes-lab/
├── module-01/
├── module-02/
├── module-03/
├── module-04/
├── module-05/
├── module-06/
├── module-07/
└── README.md
```

---

## Observability Stack

Deployed in Module 6 via Helm. Installed in `monitoring` namespace.

**Helm release:** `kube-prometheus-stack` v69.3.2 from `prometheus-community`

**Components:**
- Prometheus — metrics, 7d retention, 5Gi storage
- Grafana — dashboards, 1Gi storage
- Alertmanager — alert routing, 1Gi storage
- Node Exporter — DaemonSet, host metrics
- kube-state-metrics — Kubernetes object state metrics

**StorageClass:** `retain-standard` — used for all persistent components.

**Key values file decision:** `serviceMonitorSelectorNilUsesHelmValues: false` — Prometheus discovers all ServiceMonitors cluster-wide, not just those labeled for the Helm release.

---

## RBAC State (Post Module 7)

Dedicated ServiceAccounts in `default` namespace:

| ServiceAccount | Permissions |
|---|---|
| `product-catalog-sa` | get/list/watch ConfigMaps in default |
| `postgres-sa` | get Secret `postgres-credentials` in default only |
| `log-collector-sa` | get/list/watch Pods and Namespaces cluster-wide |
| `cart-session-sa` | none — zero-permission pattern, workload retired |

---

## Module Sequence

| Module | Topic | Status |
|---|---|---|
| 1 | Cluster setup, first Pod, Prometheus + Grafana basics | Complete |
| 2 | Multi-node cluster, DaemonSets, StatefulSets, storage basics | Complete |
| 3 | Networking — Services, Ingress, nginx Ingress Controller | Complete |
| 4 | Storage — PVs, PVCs, StorageClasses, retain policy | Complete |
| 5 | Configuration and Secrets — ConfigMaps, Secrets, injection patterns | Complete |
| 6 | Observability — Prometheus Operator, Helm, ServiceMonitors, dashboards | Complete |
| 7 | RBAC and Security — ServiceAccounts, Roles, ClusterRoles, admission controllers | Complete |
| 8 | Production Patterns — resource limits, HPA, PDBs, rolling updates, node affinity | Next |
| Cloud | EKS — multi-node behavior, load balancer provisioning, managed add-ons | Pending |

---

## Session Procedure

1. Start a fresh chat for each module
2. Upload at session start:
   - `steven-aiello-learning-preferences.md`
   - `kubernetes-track-conventions.md` (this document)
   - Most recent module reference document
3. Confirm cluster state before any lab work begins
4. Produce module reference document at session end
5. Commit reference document to GitHub repo before closing chat

---

## Decisions Log

Significant architectural or workflow decisions made during the track — recorded here so they don't need to be re-established.

| Module | Decision | Rationale |
|---|---|---|
| 1 | kind over EKS for Modules 1–7 | No cloud cost, runs on existing Docker install, sufficient for foundational concepts |
| 2 | E-commerce workload as persistent lab vehicle | Abstract Kubernetes teaching without a real workload produces knowledge that doesn't transfer |
| 4 | `retain-standard` StorageClass with Retain reclaim policy | Demonstrates production data safety — PVs survive PVC deletion |
| 5 | Pre-created Secrets over plaintext in manifests | Establishes correct secret hygiene from first use |
| 6 | `serviceMonitorSelectorNilUsesHelmValues: false` | Enables cross-namespace ServiceMonitor discovery without label management overhead |
| 6 | Loki + Alloy deferred | log-collector echoes text — deploying log aggregation for meaningless output adds overhead without observable value |
| 7 | Git branches over filename versioning for future tracks | Branches are the production pattern — filename suffixes are a workaround with no real equivalent in production workflows |
| 7 | cart-session bare Pod retired | Served its Module 4 storage lab purpose — bare Pods have no production justification and add noise |

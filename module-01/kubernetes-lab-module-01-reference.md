# Kubernetes Lab — Module 1 Reference
## Cluster Fundamentals

**Track:** Kubernetes — Comprehensive Coverage  
**Lab Environment:** Pop!_OS (Ubuntu jammy base), local kind cluster  
**Date Completed:** April 21, 2026

---

## Business Context

Our company runs a microservices e-commerce application currently on bare VMs. Deployments are manual, failure recovery is manual, and scaling requires provisioning new machines. We are migrating to Kubernetes to achieve automated recovery, declarative configuration, and a consistent deployment platform. Module 1 establishes the cluster that everything else in this track builds on.

---

## Version Set (Pinned)

| Component | Version |
|-----------|---------|
| Docker | 29.4.0 |
| kubectl | v1.32.13 |
| Kustomize | v5.5.0 (bundled with kubectl) |
| kind | v0.27.0 |
| Kubernetes (cluster) | v1.32.3 |
| Node image | kindest/node:v1.32.3 |

**kubectl installation method:** Official Kubernetes apt repository, pinned to v1.32 stable channel. Managed via apt — upgrades are explicit, not automatic.

```bash
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update && sudo apt-get install -y kubectl
```

**kind installation method:** Official binary release. No apt package exists for kind — binary install is the correct and official method.

---

## What Kubernetes Solves

Kubernetes exists because running containerized applications at scale on bare VMs produces operational problems that cannot be solved manually:

- **Manual recovery:** A VM or container failure requires human intervention to restart workloads. At scale this is not viable.
- **Manual scaling:** Adding capacity requires provisioning and configuring new machines. Demand spikes cannot be responded to in time.
- **Inconsistent deployments:** Without a declarative platform, deployment procedures vary between teams and environments. Drift is inevitable.

Kubernetes solves these by providing a declarative API — you describe the desired state, and Kubernetes continuously works to make reality match that description. This is the reconciliation model.

---

## Cluster Architecture

### Lab Deviation from Production

**Lab:** Single-node kind cluster. One Docker container acts as both control plane and worker node.

**Production:** Control plane and worker nodes are always separate. Application workloads are never scheduled on control plane nodes. Production control planes run multiple nodes (typically 3) for high availability, backed by a replicated etcd cluster.

### How kind Works

kind (Kubernetes IN Docker) runs each Kubernetes node as a Docker container on the host machine. This allows a real Kubernetes cluster to run locally without VMs or cloud infrastructure. Sufficient for Modules 1–5 and parts of 6–7. Cloud cluster (EKS) will be introduced when multi-node behavior and managed services are required.

### Cluster Configuration

**File:** `~/kubernetes-lab/module-01/kind-config.yaml`

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ecommerce-lab
nodes:
  - role: control-plane
```

**Create cluster:**
```bash
kind create cluster --config kind-config.yaml --image kindest/node:v1.32.3
```

**Verified output:**
```
Creating cluster "ecommerce-lab" ...
✓ Ensuring node image (kindest/node:v1.32.3)
✓ Preparing nodes
✓ Writing configuration
✓ Starting control-plane
✓ Installing CNI
✓ Installing StorageClass
Set kubectl context to "kind-ecommerce-lab"
```

---

## Control Plane Components

**Verified with:** `kubectl get pods -n kube-system`

**Observed output:**
```
NAME                                                  READY   STATUS    RESTARTS   AGE
coredns-668d6bf9bc-pczl7                              1/1     Running   0          4m2s
coredns-668d6bf9bc-pvgs4                              1/1     Running   0          4m2s
etcd-ecommerce-lab-control-plane                      1/1     Running   0          4m10s
kindnet-67c4j                                         1/1     Running   0          4m2s
kube-apiserver-ecommerce-lab-control-plane            1/1     Running   0          4m10s
kube-controller-manager-ecommerce-lab-control-plane   1/1     Running   0          4m9s
kube-proxy-x4zt9                                      1/1     Running   0          4m2s
kube-scheduler-ecommerce-lab-control-plane            1/1     Running   0          4m9s
```

### Component Reference

| Component | Role |
|-----------|------|
| etcd | Cluster state database. Every workload, config, and secret lives here. Loss without backup means loss of cluster. Production runs 3 or 5 etcd members for quorum. |
| kube-apiserver | Front door for all cluster communication. Every kubectl command hits this endpoint. Stateless — HA is achieved by running multiple instances. |
| kube-controller-manager | Reconciliation engine. Watches desired vs. actual state and acts to close the gap. If a pod dies and 3 replicas were requested, this component notices and creates a replacement. |
| kube-scheduler | Assigns new pods to nodes based on available resources, constraints, and rules. In a single-node cluster always picks the only node. |
| coredns (x2) | In-cluster DNS. Services find each other by name rather than IP. Two instances for redundancy. |
| kindnet | CNI plugin. Handles pod-to-pod networking. kind-specific — production uses Calico, Cilium, or cloud-provider CNI. |
| kube-proxy | Manages network rules on each node so traffic to a Service reaches the correct pods. |

---

## kubectl Context Management

Every kind cluster registers a context in `~/.kube/config`. kubectl sends commands to whichever context is currently active.

**List contexts:**
```bash
kubectl config get-contexts
```

**Set active context:**
```bash
kubectl config use-context kind-ecommerce-lab
```

**Active context is marked with `*` in the CURRENT column.**

**Production discipline:** Sending a command to the wrong context is a real incident category. In production environments, engineers use tools like `kubectx` for fast context switching and configure their shell prompt to display the active context at all times. Never run a destructive command without verifying your active context first.

---

## First Workload — Product Catalog Service

### Business Context

The product catalog service is the first component of our e-commerce application. It serves product data to other services. In this module it is deployed as a naked Pod — no Deployment, no Service. This is intentional: understanding a raw Pod before introducing the abstractions that manage Pods makes every higher-level construct legible.

### Lab Deviation from Production

**Lab:** Naked Pod deployed directly. No Deployment, no replica management, no resource limits.

**Production:** Pods are never deployed directly. They are managed by a controller — typically a Deployment. A naked Pod that dies is not replaced. A Deployment-managed Pod is. Resource requests and limits are always defined.

### Pod Manifest

**File:** `~/kubernetes-lab/module-01/product-catalog.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: product-catalog
  labels:
    app: product-catalog
    track: kubernetes-lab
spec:
  containers:
    - name: product-catalog
      image: hashicorp/http-echo:0.2.3
      args:
        - "-text=product-catalog service - version 1.0"
      ports:
        - containerPort: 5678
```

**Apply:**
```bash
kubectl apply -f product-catalog.yaml
```

### Verified State

**kubectl get pod product-catalog:**
```
NAME              READY   STATUS    RESTARTS   AGE
product-catalog   1/1     Running   0          43s
```

**Pod IP observed:** 10.244.0.5

**Traffic verified:**
```bash
kubectl port-forward pod/product-catalog 8080:5678 &
curl http://localhost:8080
# Response: product-catalog service - version 1.0
```

### Key Observations from kubectl describe

- **Pod IP is ephemeral.** If the Pod is deleted and recreated it receives a different IP. This is why Services exist — stable endpoint in front of ephemeral Pod IPs. Covered in Module 3.
- **QoS Class: BestEffort.** No resource requests or limits defined. First to be evicted under node resource pressure. Production deviation — covered in Module 8.
- **Auto-mounted service account token.** Every Pod receives one by default. Default permissions are broader than they should be in production. Covered in Module 7.
- **Events section** is the primary diagnostic tool for Pod failures. Healthy sequence: Scheduled → Pulling → Pulled → Created → Started.

---

## Failure Scenarios

### Failure 1 — Silent Unexpected Behavior (Duplicate Control Plane Nodes)

**Category:** Misconfiguration that succeeds without error but produces unintended state.

**What was broken:** kind cluster config specified two control-plane nodes instead of one.

```yaml
nodes:
  - role: control-plane
  - role: control-plane
```

**Symptoms:** Cluster creation succeeded. Output included additional lines not present in a single-node create:
- `Configuring the external load balancer` — a load balancer container was provisioned in front of two API servers
- `Joining more control-plane nodes` — second control plane node joined the first
- kubectl context was silently switched to the new cluster

**Why this is dangerous:** No error was produced. The cluster appeared healthy. The unintended result was a multi-control-plane HA cluster with a load balancer, running under the same name as the intended single-node cluster. Silent unexpected behavior is harder to catch than loud failures.

**Diagnostic path:** Compare `kind create cluster` output against expected output for the config. Additional lines indicate unintended topology. Verify with `kubectl get nodes` and `kubectl config get-contexts`.

**Resolution:** `kind delete cluster --name ecommerce-broken`

**Deleted nodes observed:**
```
ecommerce-broken-external-load-balancer
ecommerce-broken-control-plane
ecommerce-broken-control-plane2
```

---

### Failure 2 — ImagePullBackOff (Non-Existent Image Version)

**Category:** Pod stuck in retry loop due to image not found at registry.

**What was broken:** Pod manifest referenced `hashicorp/http-echo:9.9.9` — a version that does not exist.

**Symptoms:**
```
NAME              READY   STATUS             RESTARTS   AGE
product-catalog   0/1     ImagePullBackOff   0          20s
```

**Events observed:**
```
Warning  Failed   kubelet  Failed to pull image "hashicorp/http-echo:9.9.9": 
         rpc error: code = NotFound desc = failed to pull and unpack image 
         "docker.io/hashicorp/http-echo:9.9.9": not found
Warning  Failed   kubelet  Error: ErrImagePull
Normal   BackOff  kubelet  Back-off pulling image "hashicorp/http-echo:9.9.9"
```

**Diagnostic path:** `kubectl describe pod <name>` — Events section shows exact registry error and retry state.

**Production relevance:** This failure appears when a deployment references an image tag that was never pushed, was deleted from the registry, or contains a typo. The Pod sits in ImagePullBackOff indefinitely — it does not crash, does not restart the container, just retries at increasing intervals forever. It will not self-heal because Kubernetes is working correctly — the image simply does not exist.

**Resolution:** Delete the broken Pod, apply the corrected manifest with a valid image version.

---

## Diagnostic Command Reference

| Command | Purpose |
|---------|---------|
| `kubectl cluster-info` | Verify API server and CoreDNS endpoints |
| `kubectl get nodes` | Node status and Kubernetes version |
| `kubectl get pods -n kube-system` | Control plane component health |
| `kubectl get pod <name>` | Pod status at a glance |
| `kubectl describe pod <name>` | Full Pod detail including Events — primary failure diagnostic |
| `kubectl config get-contexts` | List all contexts, identify active context |
| `kubectl config use-context <name>` | Switch active context |
| `kubectl port-forward pod/<name> <local>:<remote>` | Forward local port to Pod for testing |
| `kubectl apply -f <file>` | Apply manifest to cluster |
| `kubectl delete pod <name>` | Delete a Pod |

---

## Advanced Topics List

Topics identified in this module but not yet covered. Carried forward to subsequent modules.

- Internal mechanics of each control plane component (etcd Raft consensus algorithm, scheduler node scoring, controller reconciliation loop internals)
- etcd quorum requirements, odd-number member rule, split-brain failure modes and prevention
- Context management tooling: kubectx, kubens, shell prompt integration for active context display
- CNI plugin comparison: kindnet vs. Calico vs. Cilium vs. cloud-provider CNI — tradeoffs and use cases
- Resource requests and limits, QoS classes, eviction order under node pressure (Module 8)
- RBAC and service account token permissions, principle of least privilege for Pods (Module 7)
- Deployment controller, ReplicaSet, replica management — why naked Pods are never used in production (Module 2)
- Services and stable endpoints in front of ephemeral Pod IPs (Module 3)

---

*Module 2: Workloads — Deployments, ReplicaSets, DaemonSets, StatefulSets*

# Architecture Principles

## Purpose

This document defines the design goals and engineering principles that apply
to every tier of the Zenoss Core Kubernetes migration. All manifest decisions
should be evaluated against these principles. When a decision deviates from
a principle, the reason must be documented in the tier completion report.

---

## Design Goals

### 1. Scalability Without Over-Provisioning
Design every resource to scale up without requiring structural changes.
Deploy at the minimum viable replica count for the current environment.

In practice this means:
- StatefulSets for all stateful services, regardless of current replica count
- Anti-affinity rules on every pod spec - no effect at 1 replica, automatic
  spreading when scaled
- Headless services for all StatefulSets - works correctly at any replica count
- No hardcoded instance counts in config files where avoidable
- Resource requests sized to actual needs, limits set generously

Never make a configuration decision that requires rearchitecting to scale.
A replica count change should be the only action needed to scale a service.

### 2. Production-Grade From Day One
Every manifest is written as if it will run in production.
No shortcuts that require rework later.

In practice this means:
- PodDisruptionBudgets on every StatefulSet and Deployment
- RollingUpdate strategy on every StatefulSet
- Resource requests and limits on every container
- Readiness and liveness probes on every container
- terminationGracePeriodSeconds appropriate for each service
- Anti-affinity rules to prevent co-location of replicas

### 3. Standard Kubernetes Primitives
Use only standard Kubernetes resources. No custom operators, no Helm charts,
no external controllers. Raw manifests that any Kubernetes cluster can apply.

This ensures the migration knowledge is transferable to any Kubernetes
distribution or cloud provider without additional tooling dependencies.

### 4. Version Controlled Configuration
Every configuration decision lives in git. Nothing is configured manually
inside running containers.

The only exception is initial cluster bootstrapping (kubectl apply of
namespace and initial resources). After that, all changes go through:
  1. Edit the manifest file
  2. kubectl apply
  3. git commit

---

## Workload Type Decisions

### Use StatefulSet when:
- Service needs persistent storage that survives pod restarts
- Service requires stable network identity (hostname)
- Service is part of a cluster that uses peer discovery by hostname
- Service startup/shutdown order matters

Examples: MariaDB, Redis, RabbitMQ, Solr, ZooKeeper, HMaster, RegionServer

### Use Deployment when:
- Service is stateless or treats storage as ephemeral
- Any replica is interchangeable with any other
- No stable hostname required

Examples: Memcached, Memcached-Session, application daemons

### PVC Required when:
- Data must survive pod restarts (databases, message queues, search indexes)
- Log data must persist for audit or debugging purposes

### emptyDir appropriate when:
- Data is ephemeral by design (caches, temp files, pid files)
- Sharing data between initContainer and main container
- ControlCenter used tmp volume type

---

## Networking Principles

### Every exported service gets a ClusterIP Service
A pod's IP address changes on restart. Other pods must never connect
directly to pod IPs. Every service that accepts connections from other
pods gets a named ClusterIP Service.

DNS pattern: <service-name>.zenoss.svc.cluster.local:<port>

### Every StatefulSet gets a Headless Service
The headless service (clusterIP: None) provides stable per-pod DNS:
  <pod-name>.<headless-service-name>.zenoss.svc.cluster.local

Required for: ZooKeeper clustering, HBase inter-node, RabbitMQ Erlang clustering

### No hardcoded IPs anywhere
All inter-service references use ClusterDNS names from the zenoss-config
ConfigMap. The 127.0.0.1 addresses from ControlCenter's Context block
are replaced with real DNS names in global.conf and service configs.

### The controlplane_consumer endpoint is omitted
ControlCenter injected a serviced-controller agent into every container
that communicated on port 8444 for internal metrics. This is CC-specific
and has no Kubernetes equivalent. Services will log connection errors
for this endpoint but will continue to function normally.

---

## Image Selection Principles

### Prefer zenoss/core_6.3 when:
- Service contains Zenoss-specific Python code or ZenPacks
- Service reads from /opt/zenoss or requires ZENHOME environment
- No suitable official image exists for the service

### Prefer official Docker Hub image when:
- Service has no Zenoss-specific code (pure infrastructure)
- zenoss/core_6.3 image has PID 1 issues for this service
- Official image provides a cleaner, more maintainable solution

### Document every image deviation
When the official image is used instead of zenoss/core_6.3, document:
- Which service and why
- What was tried with the zenoss image
- What the specific failure mode was
- Why the official image resolves it

---

## Configuration Principles

### ConfigMap for non-sensitive configuration
All service endpoints, hostnames, ports, and rendered config files
live in the zenoss-config ConfigMap. 59 keys covering all services.

### Secrets for credentials
All passwords, tokens, and credentials live in zenoss-secrets.
Secrets are never committed to git (secrets.yaml is gitignored).
On cluster rebuild, apply secrets.yaml manually before any other resource.

### Config injection replaces ControlCenter templating
ControlCenter rendered config files at container startup using Go templates.
In Kubernetes this becomes one of:
1. Pre-rendered values in the ConfigMap (for static configs)
2. initContainer that writes config files to an emptyDir volume
3. Direct ConfigMap subPath mount at the config file path

### Changes take effect via rolling restart
After editing a ConfigMap:
  kubectl apply -f configmap.yaml
  kubectl rollout restart statefulset/<name> -n zenoss

---

## Startup Ordering Principles

### initContainers implement all prereqs
Every ControlCenter Prereq becomes a Kubernetes initContainer.
The main container does not start until all initContainers succeed.

### Dependency chain must be explicit
Each service's initContainers check actual service health, not just
DNS resolution. A service being DNS-resolvable does not mean it is ready.

Standard health check patterns:
- MariaDB: mysql -u root -h host -e 'select 1'
- Redis: redis-cli -h host ping
- ZooKeeper: echo stats | nc host 2181 | grep Zookeeper
- RabbitMQ: rabbitmq-diagnostics check_port_connectivity
- HMaster: wget http://hmaster:61000/status/cluster

### Never assume a service is ready based on pod status
A pod showing 1/1 Running means its readiness probe passed.
Use the readiness probe as the signal, not pod status alone.

---

## Observability Principles

### Log to stdout/stderr
All containers must log to stdout/stderr so kubectl logs works.
Services that log to files should either:
1. Be configured to log to /dev/stdout
2. Have a sidecar or supervisord configured to tail files to stdout

### Readiness probes gate traffic
No service receives traffic until its readiness probe passes.
The readiness probe uses the same check as the ControlCenter health check
where possible, ensuring behavioral equivalence.

### Liveness probes restart truly broken services
Liveness probe timing is more generous than readiness.
initialDelaySeconds for liveness is always >= initialDelaySeconds for readiness.
failureThreshold for liveness is always <= failureThreshold for readiness.

---

## ControlCenter to Kubernetes Translation Reference

| ControlCenter Concept | Kubernetes Equivalent |
|---|---|
| Services[] hierarchy | Deployments/StatefulSets in namespace |
| ImageID | spec.containers[].image |
| Command | spec.containers[].command |
| RunAs | spec.securityContext.runAsUser |
| Endpoints (export) | Service (ClusterIP) |
| Endpoints (import) | ClusterDNS reference |
| Volumes (persistent) | volumeClaimTemplates |
| Volumes (tmp) | emptyDir |
| ConfigFiles | ConfigMap subPath mount |
| Context variables | ConfigMap keys |
| Prereqs | initContainers |
| HealthChecks | readinessProbe + livenessProbe |
| RAMCommitment | resources.requests.memory |
| CPUCommitment | resources.requests.cpu |
| Instances.Min/Max | replicas + HPA |
| StartLevel | initContainer ordering |
| Launch: manual | replicas: 0 |
| controlplane_consumer | Omitted (CC-specific) |

# Handoff Document — Tier 02: Data Tier

## Cluster Access

ssh root@195.201.43.82
kubectl get pods -n zenoss

Note: SSH from Anthropic/Claude infrastructure times out — Hetzner blocks
those IP ranges. SSH works normally from your laptop.

## Repository

cd ~/self-directed-ai-learning/zenoss-k8s
git log --oneline -5

## Current Cluster State

All Tier 01 infrastructure is healthy:

| Pod | Status | Image |
|---|---|---|
| mariadb-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 |
| redis-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 |
| rabbitmq-0 | 1/1 Running | rabbitmq:3-management |
| memcached-* | 1/1 Running | memcached:1.6-alpine |
| memcached-session-* | 1/1 Running | memcached:1.6-alpine |
| solr-0 | 1/1 Running | solr:8.6 |

---

## Architectural Decision: HBase Stack Replaced by VictoriaMetrics

### What the original Tier 02 plan was
The ControlCenter manifest included a full HBase stack for time series storage:
ZooKeeper → HMaster → RegionServer → OpenTSDB

### Why we abandoned it
During implementation we hit a fundamental architectural mismatch:
- CC ran HMaster and RegionServer on the same host sharing `/var/hbase` via
  the local filesystem (or NFS in multi-node deployments)
- In Kubernetes, each StatefulSet pod gets its own PVC — there is no shared
  local filesystem between pods
- k3s local-path-provisioner only supports ReadWriteOnce, not ReadWriteMany
- HBase requires shared storage between HMaster and RegionServer

More broadly: the entire ZooKeeper + HBase + OpenTSDB stack is a 2013-era
solution to time series storage. It exists solely to store and query metrics.
Maintaining this stack in Kubernetes would require either NFS infrastructure
or a more complex storage solution, all to replicate functionality that modern
purpose-built time series databases provide in a single container.

### The modern replacement: VictoriaMetrics
VictoriaMetrics is a single-binary time series database that:
- Speaks the OpenTSDB ingestion protocol natively (port 4242)
- Zenoss's metric-consumer writes to `opentsdb-writer.zenoss.svc.cluster.local:4242`
  — we put VictoriaMetrics behind that DNS name. Zero application code changes.
- Has a native Grafana datasource plugin
- Runs as a single StatefulSet with a standard PVC — no coordination layer needed
- Handles the same write throughput as the HBase stack with a fraction of
  the infrastructure

### Grafana addition
Zenoss's built-in dashboarding was historically weak. Since VictoriaMetrics has
native Grafana support, we add Grafana as a Deployment in this tier. This gives
us a modern dashboarding layer on top of the existing Zenoss monitoring data.

### What Zenoss sees
- Metrics flow: Zenoss collectors → metric-consumer → opentsdb-writer:4242
  → VictoriaMetrics (unchanged from Zenoss perspective)
- Metric reads: central-query → opentsdb-reader:4242 → VictoriaMetrics
- Grafana queries VictoriaMetrics directly via its datasource plugin
- No Zenoss application code changes required

---

## What To Build — Tier 02: Data

### 1. VictoriaMetrics
Image: victoriametrics/victoria-metrics:latest (or pin to stable tag)
Purpose: Time series database replacing the entire HBase + OpenTSDB stack
Ports: 8428 (HTTP API), 4242 (OpenTSDB ingestion)
Storage: Persistent - /storage
Key facts:
- StatefulSet, single replica
- OpenTSDB ingestion endpoint at :4242 — Zenoss writes here unchanged
- Two ClusterIP Services needed:
  - opentsdb-writer (port 4242) — metric-consumer writes to this
  - opentsdb-reader (port 4242) — central-query reads from this
  - Both point to the same VictoriaMetrics pod (same as original OpenTSDB setup)
- HTTP API at :8428 — Grafana datasource points here
- No initContainers needed — single binary, no coordination
- Data directory: /storage (configure via -storageDataPath flag)
- Retention: configurable via -retentionPeriod flag (default 1 month)

### 2. Grafana
Image: grafana/grafana:latest (or pin to stable tag)
Purpose: Modern dashboarding layer for Zenoss metrics
Ports: 3000 (HTTP)
Storage: Persistent - /var/lib/grafana (dashboards, datasources, users)
Key facts:
- Deployment (stateless application, persistent data on PVC)
- VictoriaMetrics datasource provisioned via ConfigMap at startup
- Exposed via NodePort or LoadBalancer for browser access
- Default credentials: admin/admin (change on first login)
- No dependency on any other Tier 02 service

---

## Key Patterns from Tier 01 (Apply to All Future Tiers)

### 1. Image Inspection First
Always inspect before writing manifests:
```bash
kubectl run debug --image=<image> --restart=Never -n zenoss --command -- sleep 3600
kubectl exec debug -n zenoss -- bash -c '...'
kubectl delete pod debug -n zenoss
```

### 2. Official Images for Pure Infrastructure
`zenoss/core_6.3` is only for services with Zenoss Python code.
Pure infrastructure services use official images — this was proven by
RabbitMQ, Memcached, and Solr all requiring official images.

### 3. enableServiceLinks: false
Always set `enableServiceLinks: false` on pods when the service name matches
a known environment variable used by the application (e.g. SOLR_PORT, REDIS_PORT).
Kubernetes auto-injects `<SERVICENAME>_PORT=tcp://clusterIP:port` which breaks
applications that expect a plain integer port number.

### 4. Duplicate env: blocks
YAML allows multiple `env:` keys in the same mapping — Kubernetes only reads
the last one. Always verify env vars are applied:
```bash
kubectl get statefulset <name> -n zenoss \
  -o jsonpath='{.spec.template.spec.containers[0].env}'
```

### 5. PVC Ownership Pattern
When a service runs as a non-root user and uses a PVC:
- PVCs are created owned by root
- Add a `fix-permissions` initContainer (runAsUser: 0) to chown the PVC
  to the correct uid before the main container starts
- This is idempotent — safe on every restart

### 6. ConfigMap subPath vs emptyDir
For single config file injection, prefer ConfigMap subPath mount:
```yaml
volumeMounts:
  - name: config
    mountPath: /etc/service/config.conf
    subPath: config.conf
```
This mounts only the specific file, leaving the rest of the directory
untouched. An emptyDir mount shadows the entire directory and wipes
any files the image already has there.

### 7. kubectl diff Before Apply
Always run `kubectl diff -f <file>` before `kubectl apply` to verify
exactly what will change. This caught a patch file that would have
wiped the entire ConfigMap.

### 8. imagePullPolicy: Never for Locally Loaded Images
Any image loaded via `k3s ctr images import` must have:
```yaml
imagePullPolicy: Never
```

---

## Directory Structure

zenoss-k8s/
  README.md
  ARCHITECTURE-PRINCIPLES.md
  TIER-01-INFRASTRUCTURE-COMPLETE.md   <- updated this session
  HANDOFF-TIER-02-DATA.md              <- this file
  configmap.yaml
  secrets.yaml (gitignored)
  01-infrastructure/
    mariadb.yaml
    redis.yaml
    rabbitmq.yaml
    memcached.yaml
    solr.yaml                          <- updated: now uses solr:8.6
  02-data/                             <- build this next
    victoriametrics.yaml               <- to be created
    grafana.yaml                       <- to be created
  03-resmgr/
  04-collector/
  05-frontend/

---

## Source Material

ControlCenter manifest: zenoss-core-6_3_2_1.json (in ~/ZenossCore/ on VM)
The CC manifest is still useful for Tier 03+ (Zenoss application services)
to extract startup commands, config files, and health checks.

Images on VM (~/ZenossCore/):
  zenoss/core_6.3:6.3.2_1   — loaded, pulls from Docker Hub fine
  zenoss/hbase:24.0.8        — loaded via .run file (manifest v1, won't pull)
  zenoss/opentsdb:24.0.8     — loaded via .run file (manifest v1, won't pull)

Note: zenoss/hbase and zenoss/opentsdb are no longer needed since we replaced
the HBase stack with VictoriaMetrics. They can be removed from containerd
to free up space if desired:
  k3s ctr images rm docker.io/zenoss/hbase:24.0.8
  k3s ctr images rm docker.io/zenoss/opentsdb:24.0.8

---

## To Start the Next Session

1. SSH to server: ssh root@195.201.43.82
2. Check cluster state: kubectl get pods -n zenoss
3. Read ARCHITECTURE-PRINCIPLES.md
4. Read TIER-01-INFRASTRUCTURE-COMPLETE.md
5. Read this file (HANDOFF-TIER-02-DATA.md)
6. Build VictoriaMetrics manifest first, then Grafana

No CC manifest attachment needed for Tier 02 — VictoriaMetrics and Grafana
are entirely new services with no CC equivalent.

---

## Claude Access Setup

SSH from Claude's infrastructure times out due to Hetzner IP blocking.
Workaround options:
- Tailscale on the VM (recommended for future sessions)
- Jump host
- Continue with copy-paste workflow (current approach)

Server: 195.201.43.82
User: claude-access
Key: ~/.ssh/claude_zenoss (on your laptop)
Public key fingerprint: AAAAC3NzaC1lZDI1NTE5AAAAIKQI1tmK2Kp82ygW0UFEgsnkmYHcfvvp7w5GdwJl2GH5

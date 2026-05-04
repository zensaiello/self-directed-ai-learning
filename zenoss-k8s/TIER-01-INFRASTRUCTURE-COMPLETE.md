# Tier 01 — Infrastructure: Completion Report

## Services Completed

| Service | K8s Type | Image Used | Status |
|---|---|---|---|
| MariaDB | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| Redis | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| RabbitMQ | StatefulSet | rabbitmq:3-management | Running 1/1 |
| Memcached | Deployment | memcached:1.6-alpine | Running 1/1 |
| Memcached-Session | Deployment | memcached:1.6-alpine | Running 1/1 |
| ZooKeeper | StatefulSet | zookeeper:3.8 | Running 1/1 |
| Solr | StatefulSet | solr:6.6 | Running 1/1 |

---

## Key Discoveries and Decisions

### MariaDB
- Startup: `/usr/bin/mysqld_safe --user=mysql --console`
- Pre-initialized databases in image: zenoss_zep, zodb, zodb_session
- Root user has NO password, localhost only
- zenoss user password: zenoss, accessible from any host (%)
- initContainer bootstraps PVC from image data on first start

### Redis
- Startup: `redis-server /etc/redis.conf`
- Default config binds to 127.0.0.1 — MUST override to 0.0.0.0
- No authentication in original deployment

### RabbitMQ
- zenoss/core_6.3 RabbitMQ 3.3.5 has mnesia data tied to rabbit@rbt0
- Solution: Use official rabbitmq:3-management image
- RABBITMQ_DEFAULT_VHOST=/zenoss creates the vhost automatically
- postStart lifecycle hook sets permissions via rabbitmqctl
- Probes use rabbitmq-diagnostics — curl NOT available in official image

### Memcached
- zenoss/core_6.3 memcached 1.4.15 PID 1 zombie process issue
- Solution: Use official memcached:1.6-alpine image
- Both instances (memcached + memcached-session) in single memcached.yaml

### ZooKeeper (new service — not in original CC deployment)
- Added to support Solr in SolrCloud mode
- Official zookeeper:3.8 image
- Single node sufficient; scale to 3 for HA
- ZOO_MY_ID and ZOO_SERVERS set via env vars
- ZOO_4LW_COMMANDS_WHITELIST must include ruok for health checks

### Solr
Solr required the most iteration of any service. Key findings:

**zenoss/core_6.3 image problems:**
- supervisor.conf doesn't exist in image — CC injected it at runtime
- Solr 6.5 with missing Jetty ZooKeeper module — `-DzkRun` is a no-op
- Embedded ZK never starts

**official solr:8.x problems:**
- Embedded ZK removed from Docker image in 8.x
- `/solr/zookeeper` endpoint moved to `/solr/admin/zookeeper` in 8.x
- `solrcloudpy` doesn't follow the 301 redirect — breaks Zenoss

**Root cause:** `solrcloudpy` was written for Solr 6.x. It requires the
`/solr/zookeeper` endpoint that existed in that era.

**Solution: solr:6.6 + external ZooKeeper (zookeeper:3.8)**
- `solr:6.6` has the `/solr/zookeeper` endpoint solrcloudpy needs
- External ZooKeeper provides SolrCloud coordination
- `zenoss_model` configset (schema.xml + solrconfig.xml) extracted from
  `zenoss/core_6.3` and uploaded to ZooKeeper via `solr zk upconfig`
- Collection creation automated via `ensure-solr-collection` initContainer
  on Zope — no manual job needed
- `enableServiceLinks: false` prevents SOLR_PORT injection

**Solr initContainer sequence (4 steps):**
1. `fix-permissions` (busybox:1.36, runAsUser: 0): creates /var/solr/data
   and /var/solr/logs, chowns to uid 8983
2. `copy-configset` (zenoss/core_6.3): copies schema.xml + solrconfig.xml
   to shared emptyDir
3. `wait-for-zookeeper` (solr:6.6): waits for ZK ruok
4. `upload-configset` (solr:6.6): runs `solr zk upconfig`

---

## Persistent Storage

| PVC | Size | Mount | Service |
|---|---|---|---|
| data-mariadb-0 | 20Gi | /var/lib/mysql | MariaDB |
| data-redis-0 | 5Gi | /var/lib/redis | Redis |
| data-rabbitmq-0 | 10Gi | /var/lib/rabbitmq | RabbitMQ |
| data-solr-0 | 10Gi | /var/solr | Solr |
| data-zookeeper-0 | 5Gi | /data | ZooKeeper |
| datalog-zookeeper-0 | 5Gi | /datalog | ZooKeeper |

---

## Services Using Official Images

| Service | Reason |
|---|---|
| RabbitMQ | mnesia tied to CC hostname |
| Memcached | PID 1 zombie issue, no Zenoss code |
| ZooKeeper | New service, no CC equivalent |
| Solr | solrcloudpy API compatibility requires 6.6 |

**Principle:** `zenoss/core_6.3` only for services with Zenoss Python code.

---

## Image Loading for Cluster Rebuilds

k3s containerd v2.1 dropped Docker manifest v1 support. Load legacy images:
```bash
SKIP=$(awk '/^__DOCKERFILE_FOLLOWS__/ { print NR + 1; exit 0; }' <file>.run)
tail -n +$SKIP <file>.run | gunzip -c | k3s ctr images import -
```

`zenoss/core_6.3:6.3.2_1` pulls from Docker Hub fine (manifest v2).
`zenoss/hbase` and `zenoss/opentsdb` are no longer needed (HBase replaced).

Any locally imported image needs `imagePullPolicy: Never`.

---

## Key Patterns Established

- **enableServiceLinks: false** — prevents Kubernetes injecting `<SVC>_PORT`
  env vars that break applications expecting plain integer port numbers
- **kubectl diff before apply** — always verify what will change
- **Controller revision cleanup** — when pod stubbornly uses old spec:
  ```bash
  kubectl delete controllerrevision -n zenoss \
    $(kubectl get controllerrevision -n zenoss | grep <name> | awk '{print $1}')
  ```
- **PVC ownership** — always add `fix-permissions` initContainer (runAsUser: 0)
  for services running as non-root users

---

## Verification Commands

```bash
kubectl get pods -n zenoss -L tier

# ZooKeeper
kubectl exec zookeeper-0 -n zenoss -- sh -c "echo ruok | nc localhost 2181"
# Expected: imok

# Solr
kubectl exec solr-0 -n zenoss -- curl -sf \
  "http://localhost:8983/solr/admin/collections?action=LIST"
# Expected: {"collections":["zenoss_model"]}
```

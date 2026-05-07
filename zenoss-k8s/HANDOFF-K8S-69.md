# Handoff — Zenoss 6.9.0 Kubernetes Migration

## Context

This is a continuation of the Zenoss Core CC-to-Kubernetes migration effort,
now targeting Zenoss 6.9.0 images built by the xeenose project. The 6.3.2
migration (on `main` branch) is the reference implementation — patterns,
lessons learned, and tier completion reports from that effort apply here.

This work is on branch `zenoss-6.9.0` of the `zenoss-k8s` repo.

---

## Cluster Access

```
SSH: root@195.201.43.82
Repo: ~/self-directed-ai-learning/zenoss-k8s
Branch: zenoss-6.9.0
Namespace: zenoss
```

---

## Repository Structure

Work goes under `core/` in the repo:

```
core/
  infrastructure/     # mariadb-model, mariadb-events, redis, rabbitmq, zodb
  platform/           # zep, zenhub, zenhubworkers, zeneventd, zenactiond, zenjobs, zope
  collector/          # zenping, zenperfsnmp, zenprocess, zenstatus,
                      # zenmodeler, zensyslog, zentrap
configmap.yaml        # already written, applied
secrets.yaml          # already written, applied, gitignored
```

---

## Images Available in k3s

All images are already imported into k3s containerd:

```
docker.io/zenoss-local/zenoss-core:6.9.0          393MB
docker.io/zenoss-local/zenoss-product-base:6.9.0  365MB
docker.io/zenoss-local/zenoss-zep:6.9.0            98MB
```

All manifests using these images must set `imagePullPolicy: Never`.

Official images (mariadb, rabbitmq, redis) pull from Docker Hub normally.

---

## Source Material

All of the following are available in the repo or on the VM:

- `~/xeenose/zenoss-core/service.json` — 6.9.0 CC service definitions (authoritative)
- `~/xeenose/zenoss-core/etc/global.conf.tpl` — global.conf template
- `~/xeenose/zenoss-core/etc/zope.conf.tpl` — zope.conf template
- `ARCHITECTURE-PRINCIPLES.md` — K8s design principles (apply to all manifests)
- `TIER-01-INFRASTRUCTURE-COMPLETE.md` — 6.3.2 infrastructure patterns
- `TIER-03-RESMGR-COMPLETE.md` — 6.3.2 platform patterns and known gotchas

---

## Architecture Decisions Made

### 6.9.0 vs 6.3.2 key differences

| Component | 6.3.2 | 6.9.0 |
|---|---|---|
| ZODB backend | RelStorage (MariaDB) | ZEO server (:8100) |
| MariaDB | 1 instance | 2: mariadb-model + mariadb-events |
| Solr | Required | Gone |
| ZooKeeper | Required | Gone |
| Memcached | 2 instances | Gone |
| HBase/OpenTSDB | Required | Gone |
| zproxy | Root service (:8080) | Gone |
| Zope port | 9080 (behind zproxy) | 8080 (direct) |
| ZenHub port | 8789 | 9988 |
| ZenHub global.conf key | hubhost | zhhost |
| Redis global.conf keys | redis-host/redis-port | redishost/redisport |
| Entry point | daemon-specific | /entrypoint.sh <daemon> |
| Config rendering | CC Go templates | envsubst via configure-zenoss.sh |

### Session storage
Zope session storage is in-memory (`<temporarystorage>`). Single Zope
instance only. Known gap — shared session storage needed for multiple
replicas. Deferred until Zope scaling is required.

### configure-zenoss.sh
Every Zenoss container runs `/entrypoint.sh <daemon>`. The entrypoint
sources env vars and execs the daemon. `configure-zenoss.sh` is called
by supervisord configs before daemons start (for supervisord-managed
services) or must be called explicitly in the container command.

Key behavior:
- Renders `global.conf` from `global.conf.tpl` using `envsubst`
- First-run init: runs `zenbuild`, sets admin password, runs `zenmigrate`,
  installs ZenPacks
- First-run flag: `${ZENHOME}/var/.configured` — must survive pod restarts
- `/opt/zenoss/var` needs a PVC on Zope (owns the first-run flag)

### zope.conf
Pre-rendered and mounted via ConfigMap at `/opt/zenoss/etc/zope.conf`.
Already written in `configmap.yaml`. Uses ZEO client, port 8080, 
in-memory temporary storage.

---

## Environment Variables

All pods source env vars from the `zenoss-config` ConfigMap and
`zenoss-secrets` Secret. The following env vars map to `global.conf.tpl`
substitutions:

| Env Var | Maps to global.conf key | Value |
|---|---|---|
| `ZODB_HOST` | `zodb-host` | `zodb.zenoss.svc.cluster.local` |
| `ZODB_PORT` | `zodb-port` | `8100` |
| `ZEP_DB_HOST` | `zep-db-host` | `mariadb-events.zenoss.svc.cluster.local` |
| `ZEP_DB_PORT` | `zep-db-port` | `3306` |
| `ZEP_DB_PASSWORD` | `zep-db-password` | from secret |
| `ZEP_DB_ADMIN_PASSWORD` | `zep-db-admin-password` | from secret |
| `AMQP_HOST` | `amqphost` | `rabbitmq.zenoss.svc.cluster.local` |
| `AMQP_PORT` | `amqpport` | `5672` |
| `AMQP_PASSWORD` | `amqppassword` | from secret |
| `REDIS_HOST` | `redishost` | `redis.zenoss.svc.cluster.local` |
| `REDIS_PORT` | `redisport` | `6379` |
| `ZENHUB_HOST` | `zhhost` | `zenhub.zenoss.svc.cluster.local` |
| `ZENHUB_PORT` | `zhport` | `9988` |
| `ZENOSS_ADMIN_PASSWORD` | `zpasswd` | from secret |
| `TZ` | `timezone` | `UTC` |

---

## Infrastructure Tier Service Specs

### mariadb-model
- **Type**: StatefulSet
- **Image**: `mariadb:10.6`
- **Port**: 3306
- **PVC**: 20Gi at `/var/lib/mysql`
- **Purpose**: ZODB model catalog database
- **Init env vars**:
  - `MYSQL_DATABASE=zodb`
  - `MYSQL_USER=zenoss`
  - `MYSQL_PASSWORD` from secret `MARIADB_MODEL_PASSWORD`
  - `MYSQL_ROOT_PASSWORD` from secret `MARIADB_MODEL_ROOT_PASSWORD`
- **Health check**: `mysqladmin ping -h localhost`
- **Pattern**: Same as 6.3.2 mariadb.yaml — see TIER-01 report

### mariadb-events
- **Type**: StatefulSet
- **Image**: `mariadb:10.6`
- **Port**: 3306
- **PVC**: 20Gi at `/var/lib/mysql`
- **Purpose**: ZEP events database
- **Init env vars**:
  - `MYSQL_DATABASE=zep`
  - `MYSQL_USER=zenoss`
  - `MYSQL_PASSWORD` from secret `MARIADB_EVENTS_PASSWORD` (ZEP_DB_PASSWORD)
  - `MYSQL_ROOT_PASSWORD` from secret `MARIADB_EVENTS_ROOT_PASSWORD`
- **Extra MariaDB config needed**:
  - `log_bin_trust_function_creators = 1` — required for ZEP schema migrations
  - Pattern: ConfigMap-mounted `/etc/mysql/conf.d/zenoss.cnf`
- **Health check**: `mysqladmin ping -h localhost`

### redis
- **Type**: StatefulSet
- **Image**: `redis:7.0-alpine`
- **Port**: 6379
- **PVC**: none (ephemeral acceptable — Redis is a cache in this deployment)
- **Config**: must bind to `0.0.0.0` not `127.0.0.1`
  - Pattern: `redis-server --bind 0.0.0.0 --save ""`  
- **Health check**: `redis-cli ping`
- **Note**: No auth in original deployment

### rabbitmq
- **Type**: StatefulSet
- **Image**: `rabbitmq:3.11-management`
- **Ports**: 5672 (AMQP), 15672 (management)
- **PVC**: 10Gi at `/var/lib/rabbitmq`
- **Env vars**:
  - `RABBITMQ_DEFAULT_USER=zenoss`
  - `RABBITMQ_DEFAULT_PASS` from secret
  - `RABBITMQ_DEFAULT_VHOST=/zenoss`
- **Health check**: `nc -z localhost 5672` (busybox pattern from 6.3.2)
- **Pattern**: Same as 6.3.2 rabbitmq.yaml — see TIER-01 report
- **Known gotcha**: Do NOT use `rabbitmq-diagnostics` for remote health checks

### zodb (ZEO server)
- **Type**: StatefulSet
- **Image**: `docker.io/zenoss-local/zenoss-product-base:6.9.0`
- **imagePullPolicy**: Never
- **Port**: 8100 (TCP)
- **PVC**: 20Gi at `/zodb-data`
- **Command**: `/opt/zenoss/bin/runzeo -f /zodb-data/zodb.fs -a 0.0.0.0:8100`
- **Health check**: TCP socket check on port 8100
  - `zeo_answering` is the health check name in service.json
  - Pattern: `nc -z localhost 8100`
- **RunAs**: `runAsUser: 1337, runAsGroup: 1206` (zenoss uid/gid)
- **No configure-zenoss.sh** — ZEO server needs no Zenoss config, just runzeo
- **No env vars from configmap needed** — standalone service

---

## Workflow Instructions

### Per-tier process
1. Write manifests for the tier under `core/<tier>/`
2. Apply with `kubectl apply -f core/<tier>/`
3. Watch pods: `kubectl get pods -n zenoss -w`
4. Debug failures by reading logs: `kubectl logs -n zenoss <pod>`
5. Fix and reapply iteratively
6. When all pods in tier are `1/1 Running` and health checks pass:
   - Commit with descriptive message
   - Write a tier completion report (`INFRASTRUCTURE-COMPLETE.md` etc.)
   - Commit the completion report

### Commit message pattern
```
feat(infrastructure): add mariadb-model StatefulSet

- mariadb:10.6, 20Gi PVC, zodb database
- log_bin_trust_function_creators=1 for ZEP schema migrations
- ConfigMap-mounted zenoss.cnf for MariaDB overrides
```

### Validation before moving to next tier
Infrastructure tier is complete when:
- `kubectl get pods -n zenoss` shows all infrastructure pods `1/1 Running`
- MariaDB model: `kubectl exec -n zenoss mariadb-model-0 -- mysqladmin ping`
- MariaDB events: `kubectl exec -n zenoss mariadb-events-0 -- mysqladmin ping`
- Redis: `kubectl exec -n zenoss redis-0 -- redis-cli ping` → `PONG`
- RabbitMQ: `kubectl exec -n zenoss rabbitmq-0 -- nc -z localhost 5672`
- ZEO: `kubectl exec -n zenoss zodb-0 -- nc -z localhost 8100`

---

## Known Unknowns to Investigate

These require inspection inside the running images before manifests can
be finalized for the platform tier. Investigate after infrastructure is up:

1. **zenhub startup command** — service.json may have the command. Verify
   what `zenhub` actually does when invoked via `/entrypoint.sh zenhub`
2. **zenhubworker pool names** — service.json shows `zenhubworker_default`
   and `zenhubworker_adminsvc`. Verify the actual CLI flags for pool selection
3. **configure-zenoss.sh invocation** — which services call it and when.
   For supervisord-managed services inspect the supervisor.conf in the image
4. **ZEP startup** — `zenoss-zep` image has its own `start-zep.sh`.
   Verify it reads env vars correctly for `mariadb-events` connection
5. **Metrics** — no metrics pipeline in service.json. Confirm daemons
   don't fail hard on missing metric endpoint (port 22350 from CC is gone)

---

## Reference: 6.3.2 Known Gotchas That Still Apply

From TIER-03-RESMGR-COMPLETE.md:
- `runAsUser: 1337, runAsGroup: 1206` — NOT 1337 for group
- `enableServiceLinks: false` — prevents K8s injecting `<SVC>_PORT` env vars
- zenhubworker `--workerid` must be integer extracted from pod name:
  `${MY_POD_NAME##*-}`
- wait-for-rabbitmq: use `busybox:1.36` with `nc -z host 5672`
- `fix-permissions` initContainer (runAsUser: 0) for non-root services
  with PVCs

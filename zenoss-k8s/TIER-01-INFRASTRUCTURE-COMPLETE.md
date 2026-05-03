# Tier 01 — Infrastructure: Completion Report

## Services Completed

| Service | K8s Type | Image Used | Status |
|---|---|---|---|
| MariaDB | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| Redis | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| RabbitMQ | StatefulSet | rabbitmq:3-management | Running 1/1 |
| Memcached | Deployment | memcached:1.6-alpine | Running 1/1 |
| Memcached-Session | Deployment | memcached:1.6-alpine | Running 1/1 |
| Solr | StatefulSet | zenoss/core_6.3:6.3.2_1 | Init:0/2 (waiting for ZooKeeper) |

---

## Key Discoveries and Decisions

### Image Inspection Approach
Before writing any manifest, inspect the image from a debug pod:
```bash
kubectl run debug-svc \
  --image=<image> \
  --restart=Never \
  --namespace=zenoss \
  --command -- sleep 3600
kubectl exec debug-svc -n zenoss -- bash -c '...'
kubectl delete pod debug-svc -n zenoss
```
This revealed correct startup commands, pre-baked data, user requirements,
and config file locations that the ControlCenter manifest abstracted away.

### The PID 1 Problem
Several services in zenoss/core_6.3 cannot run as PID 1 in Kubernetes:
- memcached 1.4.15 — accepts connections but returns no data when PID 1
- RabbitMQ 3.3.5 — mnesia data tied to old node identity (rabbit@rbt0)

**Pattern discovered:** When a service was designed to run under ControlCenter's
serviced-controller as PID 1, it may not function correctly as Kubernetes PID 1.
Use supervisord (available in the image) or the official Docker Hub image.

### MariaDB
- Startup: `/usr/bin/mysqld_safe --user=mysql --console`
- NOT `mysqld` directly — executable not in PATH
- Pre-initialized databases in image: zenoss_zep, zodb, zodb_session
- Root user has NO password, localhost only
- zenoss user password: zenoss, accessible from any host (%)
- initContainer bootstraps PVC from image data on first start
- `/etc/my.cnf` is production-tuned in image — preserve it in ConfigMap

### Redis
- Startup: `redis-server /etc/redis.conf`
- Default config binds to 127.0.0.1 — MUST override to 0.0.0.0
- No authentication in original deployment
- RDB persistence configured — 5Gi PVC sufficient

### RabbitMQ
- zenoss/core_6.3 image RabbitMQ 3.3.5 has mnesia data tied to rabbit@rbt0
- Renaming the mnesia directory is insufficient — internal topology references
  old node name and boot fails with "failed_to_cluster_with [rabbit@rbt0]"
- Solution: Use official rabbitmq:3-management image
- RABBITMQ_DEFAULT_VHOST=/zenoss creates the vhost automatically
- postStart lifecycle hook sets permissions: rabbitmqctl set_permissions
- Probes use rabbitmq-diagnostics — curl NOT available in official image
- /zenoss vhost and zenoss user confirmed working

### Memcached
- zenoss/core_6.3 memcached 1.4.15 accepts connections but returns no data
- Confirmed not a network issue — TCP connections succeed, zero bytes returned
- Binary identical between /bin/memcached and /usr/bin/memcached
- Running as PID 1 causes zombie process accumulation
- Solution: Use official memcached:1.6-alpine image
- memcached has zero Zenoss-specific code — official image is correct choice
- Both instances (memcached + memcached-session) use same image, different -m flag
- Health check: echo stats | nc 127.0.0.1 11211 | grep -q uptime

### Solr
- Startup: /bin/supervisord -n -c /opt/solr/zenoss/etc/supervisor.conf
- supervisord config already in image — correct approach from ControlCenter manifest
- solr.in.sh injected by ControlCenter template — we inject via config-init initContainer
- ZK_HOST=zookeeper.zenoss.svc.cluster.local:2181/solr
- Two PVCs: /var/solr/data (10Gi) and /opt/solr/server/logs (5Gi)
- Currently waiting in Init:0/2 for ZooKeeper — correct behavior
- Health check: curl http://localhost:8983/solr/zenoss_model/admin/ping?wt=json

---

## Persistent Storage Summary

| PVC | Size | Mount | Service |
|---|---|---|---|
| data-mariadb-0 | 20Gi | /var/lib/mysql | MariaDB |
| data-redis-0 | 5Gi | /var/lib/redis | Redis |
| data-rabbitmq-0 | 10Gi | /var/lib/rabbitmq | RabbitMQ |
| data-solr-0 | 10Gi | /var/solr/data | Solr |
| logs-solr-0 | 5Gi | /opt/solr/server/logs | Solr |

All PVCs use k3s local-path-provisioner (default StorageClass).
To migrate to cloud storage add storageClassName to volumeClaimTemplates.

---

## Services Using Official Images Instead of zenoss/core_6.3

| Service | Reason |
|---|---|
| RabbitMQ | mnesia node identity tied to ControlCenter hostname (rabbit@rbt0) |
| Memcached | PID 1 zombie process issue, no Zenoss-specific code |

This pattern may apply to other infrastructure services. When a service has
no Zenoss-specific code and has PID 1 issues, prefer the official image.

---

## ConfigMap and Secrets

**zenoss-config** (59 keys) — All service DNS endpoints and rendered config files:
- global.conf — pre-rendered with real ClusterDNS names
- zookeeper.cfg — scale-ready with all 3 potential pod entries
- hbase-site.xml — ZooKeeper quorum via headless service DNS
- opentsdb.conf — stable table prefix (zenoss-tsdb)
- rabbitmq-env.conf / rabbitmq.config — not used (official image)
- solr.in.sh — ZK_HOST with /solr chroot
- metricshipper.yaml — collector Redis and MetricConsumer endpoints
- central-query-configuration.yaml — OpenTSDB reader endpoint
- metric-consumer-configuration.yaml — OpenTSDB writer endpoint

**zenoss-secrets** (12 keys) — Credentials:
- amqppassword: zenoss
- zodb-password: zenoss
- zep-password: zenoss
- zauth-password: MY_PASSWORD
- mariadb-root-password: "" (root has no password in image)
- mariadb-zenoss-password: zenoss
- redis-password: "" (no auth in original deployment)
- rabbitmq-user/password: zenoss/zenoss

Note: secrets.yaml is gitignored. Re-apply from local file if cluster is rebuilt.

---

## Verification Commands

```bash
# Check all infrastructure pods
kubectl get pods -n zenoss -l tier=infrastructure

# Verify MariaDB
kubectl exec -it mariadb-0 -n zenoss -- mysql -u zenoss -pzenoss -e "show databases;"

# Verify Redis
kubectl run test --image=redis:alpine --restart=Never --rm -it \
  --command -- redis-cli -h redis.zenoss.svc.cluster.local ping

# Verify RabbitMQ
kubectl exec rabbitmq-0 -n zenoss -- rabbitmqctl list_vhosts

# Verify Memcached
kubectl run test --image=memcached:1.6-alpine --restart=Never --rm -it \
  --command -- sh -c "echo stats | nc memcached.zenoss.svc.cluster.local 11211 | grep uptime"
```

# Tier 01 — Infrastructure: Completion Report

## Services Completed

| Service | K8s Type | Image Used | Status |
|---|---|---|---|
| MariaDB | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| Redis | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| RabbitMQ | StatefulSet | rabbitmq:3-management | Running 1/1 |
| Memcached | Deployment | memcached:1.6-alpine | Running 1/1 |
| Memcached-Session | Deployment | memcached:1.6-alpine | Running 1/1 |
| Solr | StatefulSet | solr:8.6 | Running 1/1 |

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
Solr required the most iteration of any Tier 01 service. Full discovery log:

**What we tried with zenoss/core_6.3:**
1. CC manifest showed supervisord as the startup command, but
   `/opt/solr/zenoss/etc/supervisor.conf` does not exist in the image —
   CC injected it at runtime via ConfigFiles. Without it, Solr fails immediately.
2. The real startup script is `/opt/solr/zenoss/bin/start-solr` which calls
   `/opt/solr/bin/solr -DzkRun -f`. However the zenoss image ships a stripped
   Solr 6.5 installation missing the Jetty ZooKeeper module. `-DzkRun` has no
   effect — the embedded ZooKeeper never starts.
3. Solr requires ZooKeeper to load `solr.xml` from. Without embedded ZK starting,
   Solr times out after 30 seconds and crashes.
4. The original manifest pointed `ZK_HOST` at the external ZooKeeper
   (zookeeper.zenoss.svc.cluster.local) which was the HBase ZooKeeper — Solr
   never needed it. Solr has its own embedded ZooKeeper.

**Root causes identified:**
- zenoss/core_6.3 Solr is missing the Jetty http/zookeeper module jars
- The `wait-for-zookeeper` initContainer was pointing at the wrong ZooKeeper
- `solr.in.sh` was mounted via emptyDir that shadowed the entire
  `/opt/solr/zenoss/etc/` directory, wiping out other files in that path
- Kubernetes auto-injects `SOLR_PORT=tcp://clusterIP:8983` for every service
  named `solr` in the namespace — the Solr startup script does arithmetic on
  this value and crashes with `expr: non-integer argument`

**Solution: official solr:8.6 image**
- No Zenoss-specific code in Solr — official image is the correct choice
- The only Zenoss artifact needed is the `zenoss_model` configset (2 files:
  schema.xml and solrconfig.xml) extracted from zenoss/core_6.3
- `solr-precreate zenoss_model` creates the collection on first start cleanly
- `enableServiceLinks: false` prevents Kubernetes from injecting `SOLR_PORT`
- `SOLR_PORT: "8983"` set explicitly as env var
- `fix-permissions` initContainer (busybox, runAsUser: 0) sets PVC ownership
  to uid 8983 (solr user in official image) before main container starts
- `copy-configset` initContainer copies zenoss_model from zenoss/core_6.3
  into an emptyDir mounted at the official image's configsets directory
- Health check: curl http://localhost:8983/solr/zenoss_model/admin/ping?wt=json
  returns `"status":"OK"`

---

## Persistent Storage Summary

| PVC | Size | Mount | Service |
|---|---|---|---|
| data-mariadb-0 | 20Gi | /var/lib/mysql | MariaDB |
| data-redis-0 | 5Gi | /var/lib/redis | Redis |
| data-rabbitmq-0 | 10Gi | /var/lib/rabbitmq | RabbitMQ |
| data-solr-0 | 10Gi | /var/solr | Solr |

All PVCs use k3s local-path-provisioner (default StorageClass).
To migrate to cloud storage add storageClassName to volumeClaimTemplates.

Note: Solr previously had two PVCs (data + logs). Consolidated to one under
the official image — logs live under /var/solr/logs on the same PVC.

---

## Services Using Official Images Instead of zenoss/core_6.3

| Service | Reason |
|---|---|
| RabbitMQ | mnesia node identity tied to ControlCenter hostname (rabbit@rbt0) |
| Memcached | PID 1 zombie process issue, no Zenoss-specific code |
| Solr | Missing Jetty ZK module in zenoss image, no Zenoss-specific code |

**Principle established:** `zenoss/core_6.3` is only used for services with
actual Zenoss Python code. Pure infrastructure services use official images.

---

## Image Loading — Critical Note for Cluster Rebuilds

### containerd v2.1 Compatibility Issue
k3s ships with containerd v2.1 which dropped support for Docker manifest v1
image format (`application/vnd.docker.distribution.manifest.v1+prettyjws`).
Some older images on Docker Hub (including zenoss/hbase and zenoss/opentsdb)
use this format and cannot be pulled directly by k3s.

**Symptom:**
```
failed to pull and unpack image: not implemented: media type
"application/vnd.docker.distribution.manifest.v1+prettyjws" is no longer
supported since containerd v2.1
```

**Solution:** Load images manually from the `.run` installer files:
```bash
# The .run files are self-extracting shell scripts containing a gzipped
# Docker image tarball. Extract and pipe directly into k3s containerd:
SKIP=$(awk '/^__DOCKERFILE_FOLLOWS__/ { print NR + 1; exit 0; }' <file>.run)
tail -n +$SKIP <file>.run | gunzip -c | k3s ctr images import -

# Verify import
crictl images | grep <imagename>
```

**Images available in ~/ZenossCore/ on the VM:**
```
install-zenoss-core_6.3_6.3.2_1.run   -> zenoss/core_6.3:6.3.2_1
install-zenoss-hbase_24.0.8.run        -> zenoss/hbase:24.0.8
install-zenoss-opentsdb_24.0.8.run     -> zenoss/opentsdb:24.0.8
```

Note: zenoss/hbase:24.0.8 and zenoss/opentsdb:24.0.8 share the same IMAGE ID —
they are the same image with two different tags.

Note: zenoss/core_6.3:6.3.2_1 pulls successfully from Docker Hub (manifest v2).
The hbase and opentsdb images do not. Load them from .run files on cluster rebuild.

### imagePullPolicy for Locally Loaded Images
Any manifest using images loaded via k3s ctr import must set:
```yaml
imagePullPolicy: Never
```
Without this, k3s will attempt a Docker Hub pull on pod restart and fail
with the manifest v1 error above.

---

## ConfigMap and Secrets

**zenoss-config** — All service DNS endpoints and rendered config files.
Keys added across Tier 01:
- global.conf — pre-rendered with real ClusterDNS names
- solr.in.sh — ZK_HOST=localhost:9983 (embedded ZK, NOT external)
- rabbitmq-env.conf / rabbitmq.config — present but not used (official image)
- metricshipper.yaml — collector Redis and MetricConsumer endpoints
- central-query-configuration.yaml — OpenTSDB reader endpoint
- metric-consumer-configuration.yaml — OpenTSDB writer endpoint
- hbase-env.sh — HBASE_MANAGES_ZK=false, HBASE_HEAPSIZE=921
- opentsdb-logback.xml — stdout-only logging (FILE appender removed)
- (plus all individual endpoint keys: redis-host, solr-host, etc.)

Note: solr.in.sh ZK_HOST was changed from the external ZooKeeper DNS to
`localhost:9983` when we switched to the official Solr image with embedded ZK.
The hbase-env.sh and opentsdb-logback.xml keys were added for Tier 02 HBase
work that was subsequently abandoned in favor of VictoriaMetrics.

**zenoss-secrets** (gitignored) — Credentials:
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
kubectl get pods -n zenoss

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

# Verify Solr
kubectl exec solr-0 -n zenoss -- curl -s \
  "http://localhost:8983/solr/zenoss_model/admin/ping?wt=json" | grep status
# Expected: "status":"OK"
```

# Tier 03 — Resource Manager: Completion Report

## Services Completed

| Service | K8s Type | Image | Status |
|---|---|---|---|
| zeneventserver | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| zeneventd | Deployment | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| zenhub | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| zenhubworker | StatefulSet | zenoss/core_6.3:6.3.2_1 | Running 2/2 |
| zenjobs | Deployment | zenoss/core_6.3:6.3.2_1 | Running 1/1 |
| zenactiond | Deployment | zenoss/core_6.3:6.3.2_1 | Running 1/1 |

Note: zenhubworker and zenactiond were initially missed from the CC manifest
review. Always do a full service tree dump before writing manifests.

---

## Verification

- All 6 services reached ready state
- Events created in UI appear in event console
- `zenmodeler run -d localhost --now` completes successfully from Zope pod
- zenhub workers registered: `Worker 0 reporting for work`, `Worker 1 reporting for work`
- All Zenoss toolbox checks pass (see Toolbox section below)

---

## Key Discoveries and Fixes

### 1. `zep-host` in global.conf must be the MariaDB host
`zeneventserver-functions.sh` reads `zep-host` and passes it as `--dbhost`
to `zeneventserver-create-db`. It must point to MariaDB, not the ZEP API.
- `zep-host` → `mariadb.zenoss.svc.cluster.local` (DB connection)
- `zep-uri` → `http://zeneventserver.zenoss.svc.cluster.local:8084` (API)

### 2. ZEP reads Redis host from JVM property, not global.conf
Pass `-Dzep.redis.host=redis.zenoss.svc.cluster.local` in `DEFAULT_ZEP_JVM_ARGS`.
ZEP's Spring config has Redis hardcoded to `localhost` — global.conf `redis-host`
is ignored by zeneventserver.

### 3. `amqppassword` was missing from global.conf
ZEP connects to RabbitMQ as `amqp://zenoss@.../zenoss` with no password,
which RabbitMQ rejects. Added `amqppassword zenoss` to global.conf.

### 4. `log_bin_trust_function_creators = 1` required in MariaDB
ZEP schema migrations run `DROP TRIGGER IF EXISTS pt_osc_...` which requires
this setting when binary logging is enabled. Already present in mariadb.yaml
but was not applied to the running pod until MariaDB was restarted.

### 5. `rabbitmq-diagnostics check_port_connectivity` cannot target remote hosts
Use `busybox:1.36` with `nc -z host 5672` for all RabbitMQ readiness checks.
The `rabbitmq:3-management` image's diagnostics command uses Erlang node
resolution, not DNS, and does not accept `--hostname` flags.

### 6. zenhubworker was missed in initial service review
`zenhubworker` is a separate CC service (not spawned by zenhub). Without it,
zenhub's worker list is empty and all modeling/collection hangs on
"Modeling has not started pending configuration pull from ZenHub."

Always dump the full CC service tree before writing manifests:
```python
def print_tree(node, depth=0):
    print('  ' * depth + node.get('Name',''))
    for c in node.get('Services',[]): print_tree(c, depth+1)
```

### 7. zenhubworker requires integer --workerid
CC used `$CONTROLPLANE_INSTANCE_ID`. In Kubernetes, use a StatefulSet and
extract the index from the stable pod name: `${MY_POD_NAME##*-}`
(`zenhubworker-0` → `0`, `zenhubworker-1` → `1`).

### 8. zenactiond does not connect to zenhub
Despite being in the same CC service group, zenactiond only imports a metric
publisher module from ZenHub. It connects to RabbitMQ and MariaDB only.
Remove `--hubhost` from zenactiond command.

### 9. runAsGroup must be 1206, not 1337
zenoss uid=1337, gid=1206. Using `runAsGroup: 1337` causes
`/usr/bin/id: cannot find name for group ID 1337` on every shell exec.
All manifests with zenoss workloads must use `runAsGroup: 1206`.

### 10. hubhost missing from global.conf
Daemons default to `localhost:8789` for zenhub. In Kubernetes each daemon
is its own pod. Add `hubhost zenhub.zenoss.svc.cluster.local` to global.conf.
Key name is `hubhost` (not `zenhub-host`) — that's what PBDaemon.py reads.

### 11. Multiple configmap keys missing from global.conf block
Keys present in ConfigMap data section but missing from global.conf block:
- `amqppassword zenoss` — ZEP RabbitMQ auth
- `mysqluser zenoss` — zodbscan, legacy toolbox
- `mysqlpasswd zenoss` — zodbscan, legacy toolbox
- `mysqldb zodb` — zodbscan, legacy toolbox
- `zodb-password zenoss` — zenossdbpack
- `hubhost zenhub.zenoss.svc.cluster.local` — all hub-connected daemons

Always verify keys appear in BOTH the data section AND the global.conf block.

---

## Toolbox Health (run from Zope pod after deployment)

All toolbox checks must pass before running zencatalog:

```bash
findposkeyerror -f      # 0 errors
zenrelationscan -f      # 0 errors
zencatalogscan -f       # 0 errors
zodbscan                # requires mysqluser/mysqlpasswd in global.conf
zenossdbpack            # requires zodb-password in global.conf
```

### Solr reindex required on first boot
After fresh deployment, Solr is empty. The UI will show empty template/device
lists. Run from inside the Zope pod:

```bash
zencatalog run --createcatalog --forceindex --workers 2
```

**IMPORTANT:** Use `--workers 2`, not the default 8. 8 workers OOMKills the
Zope pod (2Gi memory limit). 2 workers completes in ~80 seconds safely.

Run toolbox checks first. The catalog reindex is a one-time operator action —
do not automate it, as running on a non-fresh deployment could corrupt data.

### zodbscan unreachable objects warning
After first deployment zodbscan reports ~35% unreachable objects. This is
normal — run `zenossdbpack` to clean up. Requires `zodb-password` in global.conf.

---

## Workload Type Decisions

| Service | Type | Reason |
|---|---|---|
| zeneventserver | StatefulSet | PVC for Lucene index |
| zeneventd | Deployment | Stateless consumer |
| zenhub | StatefulSet | Stable identity, CC locks to 1 instance |
| zenhubworker | StatefulSet | Stable pod names for integer workerid extraction |
| zenjobs | Deployment | Stateless worker |
| zenactiond | Deployment | Stateless, single instance |

---

## Persistent Storage

| PVC | Size | Mount | Service |
|---|---|---|---|
| zeneventserver-data-zeneventserver-0 | 10Gi | /opt/zenoss/var/zeneventserver | Lucene index |

---

## File Location

Manifest: `03-resmgr.yaml` (repo root, no subdirectory)

---

## Cluster State After Tier 03

| Pod | Status | Tier |
|---|---|---|
| mariadb-0 | 1/1 Running | infrastructure |
| redis-0 | 1/1 Running | infrastructure |
| rabbitmq-0 | 1/1 Running | infrastructure |
| memcached-* | 1/1 Running | infrastructure |
| memcached-session-* | 1/1 Running | infrastructure |
| zookeeper-0 | 1/1 Running | infrastructure |
| solr-0 | 1/1 Running | infrastructure |
| victoriametrics-0 | 1/1 Running | data |
| grafana-* | 1/1 Running | data |
| zeneventserver-0 | 1/1 Running | resmgr |
| zeneventd-* | 1/1 Running | resmgr |
| zenhub-0 | 1/1 Running | resmgr |
| zenhubworker-0 | 1/1 Running | resmgr |
| zenhubworker-1 | 1/1 Running | resmgr |
| zenjobs-* | 1/1 Running | resmgr |
| zenactiond-* | 1/1 Running | resmgr |
| zope-* | 1/1 Running | frontend |

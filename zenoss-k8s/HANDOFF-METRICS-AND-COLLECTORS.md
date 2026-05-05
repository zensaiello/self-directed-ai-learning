# Handoff Document — Metrics Tier + Tier 04 Collectors

## Cluster Access

ssh root@195.201.43.82
kubectl get pods -n zenoss -L tier

Note: SSH from Claude/Anthropic infrastructure times out — Hetzner blocks
those IP ranges. SSH works normally from your laptop.

## Repository

cd ~/self-directed-ai-learning/zenoss-k8s
git log --oneline -5

## Current Cluster State

All Tiers 01, 02, 03, and Zope (05-frontend) are healthy:

| Pod | Status | Image | Tier |
|---|---|---|---|
| mariadb-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 | infrastructure |
| redis-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 | infrastructure |
| rabbitmq-0 | 1/1 Running | rabbitmq:3-management | infrastructure |
| memcached-* | 1/1 Running | memcached:1.6-alpine | infrastructure |
| memcached-session-* | 1/1 Running | memcached:1.6-alpine | infrastructure |
| zookeeper-0 | 1/1 Running | zookeeper:3.8 | infrastructure |
| solr-0 | 1/1 Running | solr:6.6 | infrastructure |
| victoriametrics-0 | 1/1 Running | victoriametrics/victoria-metrics:v1.101.0 | data |
| grafana-* | 1/1 Running | grafana/grafana:10.4.3 | data |
| zeneventserver-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 | resmgr |
| zeneventd-* | 1/1 Running | zenoss/core_6.3:6.3.2_1 | resmgr |
| zenhub-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 | resmgr |
| zenhubworker-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 | resmgr |
| zenhubworker-1 | 1/1 Running | zenoss/core_6.3:6.3.2_1 | resmgr |
| zenjobs-* | 1/1 Running | zenoss/core_6.3:6.3.2_1 | resmgr |
| zenactiond-* | 1/1 Running | zenoss/core_6.3:6.3.2_1 | resmgr |
| zope-* | 1/1 Running | zenoss/core_6.3:6.3.2_1 | frontend |

## UI Status

Zope: http://195.201.43.82:30980 (admin/zenoss)
- Login works
- Events work end to end (create in UI → appears in console)
- Monitoring Templates visible
- `zenmodeler run -d localhost --now` works from Zope pod
- `Unable to load the visualization library` on device graph pages
  → caused by missing CentralQuery service (serves visualization.js)

---

## Directory Structure

zenoss-k8s/
  configmap.yaml
  secrets.yaml          (gitignored — present on VM, apply manually on rebuild)
  03-resmgr.yaml        (resmgr services — no subdirectory)
  01-infrastructure/
    mariadb.yaml
    redis.yaml
    rabbitmq.yaml
    memcached.yaml
    zookeeper.yaml
    solr.yaml
  02-data/
    victoriametrics.yaml
    grafana.yaml
  04-collector/         <- collector services go here
  05-frontend/
    zope.yaml

---

## What To Build Next

### Priority 1 — Metrics Tier (build before collectors)

The metrics pipeline is foundational. Collectors ship metrics through it.
The UI graph rendering depends on CentralQuery.

From the CC service tree (under `Metrics` group):

**CentralQuery**
- CC Command: `supervisord -n -c etc/central-query/supervisor.conf`
- Purpose: Serves performance query API to UI + proxies to TSDB
- Port: 8888 (HTTP)
- Key: Serves `/static/performance/query/visualization.js` — fixes
  "Unable to load the visualization library" in device graph pages
- Also serves `/api/performance/query` — needed for graph rendering

**MetricConsumer**
- CC Command: `supervisord -n -c etc/metric-consumer-app/supervisor.conf`
- Purpose: Receives metrics from daemons via RabbitMQ, writes to TSDB
- Port: 8549 (HTTP receiver)
- Key: Daemons post metrics to `localhost:22350` (CC) which was proxied
  to MetricConsumer. In Kubernetes, daemons need to post directly to
  MetricConsumer's endpoint.

**MetricShipper**
- CC Command: `supervisord -n -c etc/metricshipper/supervisor.conf`
- Purpose: Ships metrics from MetricConsumer to VictoriaMetrics/OpenTSDB
- Config: `/opt/zenoss/etc/metricshipper/` — needs TSDB endpoint configured

**Important:** All three are supervisord-managed Java/Go services inside
the zenoss/core_6.3 image, not Python daemons. Inspect carefully:
```bash
cat /opt/zenoss/etc/central-query/supervisor.conf
cat /opt/zenoss/etc/metric-consumer-app/supervisor.conf
cat /opt/zenoss/etc/metricshipper/supervisor.conf
```

**MetricShipper → VictoriaMetrics translation**
CC shipped to OpenTSDB. VictoriaMetrics has an OpenTSDB-compatible endpoint
at port 4242 (TCP line protocol) and HTTP at `/api/put`. MetricShipper
config needs to point to `victoriametrics.zenoss.svc.cluster.local`.

**Daemon metric posting**
Currently all daemons fail with:
`HTTPConnectionPool(host='localhost', port=22350): Connection refused`
Port 22350 was the CC controlplane_consumer (CC-specific, omitted).
Daemons need to post to MetricConsumer instead. This likely requires
a config key in global.conf pointing to MetricConsumer's endpoint.
Investigate `MetricReporter.py` to find what config key controls the endpoint.

### Priority 2 — Tier 04 Collectors (after metrics)

Start minimal — zenping and zminion only. Add others once those work.

From CC service tree (all under `localhost` collection node):

| Service | Launch | Purpose |
|---|---|---|
| zenping | auto | ICMP ping availability |
| zminion | auto | Zenoss minion worker (task dispatcher) |
| zenperfsnmp | auto | SNMP performance collection |
| zenprocess | auto | Process monitoring |
| zenpython | auto | Python-based datasource collection |
| zencommand | auto | Command-based collection |
| zenstatus | auto | TCP port status |
| zentrap | auto | SNMP trap receiver |
| zensyslog | auto | Syslog receiver |
| zenmodeler | auto | Device modeling (can run manually from Zope) |
| MetricShipper | auto | Per-collector metric shipping (also in Metrics tier) |
| collectorredis | auto | Per-collector Redis instance |
| zenmail | manual | Email action handler |
| zenpop3 | manual | POP3 collection |

**Note on zenmail:** zenactiond replacement — in later Zenoss versions the
notification framework ZenPack replaced zenactiond. In 6.3 zenactiond is
still active. zenmail is a separate optional service for email notifications.

**collectorredis** — each collector has its own Redis instance in CC.
In our architecture this maps to the existing redis StatefulSet. The
per-collector Redis was a CC artifact of isolated container networking.

**zminion** — uses supervisord internally, similar to CentralQuery/MetricConsumer.
Inspect supervisor.conf before writing manifest.

---

## Key Patterns — Do Not Repeat These Mistakes

### Always dump the full CC service tree first
```python
python3 -c "
import json
data = json.load(open('zenoss-core-6_3_2_1.json'))
def print_tree(node, depth=0):
    name = node.get('Name','')
    launch = node.get('Launch','auto')
    instances = node.get('Instances',{})
    print('  '*depth + f'{name} | launch={launch} | instances={instances}')
    for c in node.get('Services',[]): print_tree(c, depth+1)
print_tree(data)
"
```

### runAsUser / runAsGroup for zenoss workloads
- `runAsUser: 1337` (zenoss uid)
- `runAsGroup: 1206` (zenoss gid — NOT 1337)

### hubhost in global.conf
Key name is `hubhost` (not `zenhub-host`). Already set in configmap.yaml.
All collector daemons read this via PBDaemon.py.

### wait-for-rabbitmq pattern
Use `busybox:1.36` with `nc -z rabbitmq.zenoss.svc.cluster.local 5672`.
Never use `rabbitmq:3-management` with `rabbitmq-diagnostics` for remote checks.

### Daemon conf files
Each daemon reads `/opt/zenoss/etc/<daemon>.conf` for CLI option overrides.
Generate a sample with `<daemon> genxmlconfigs` or inspect existing ones
like `/opt/zenoss/etc/zenpython.conf`. Mount via ConfigMap subPath if needed.

### supervisord-based services
CentralQuery, MetricConsumer, MetricShipper, zminion all run under supervisord.
The main process is `/bin/supervisord -n -c <path>/supervisor.conf`.
Always inspect the supervisor.conf to understand what actually runs inside.

### ZENOSS_DAEMON=1 redirects logs to file
Logs go to `/opt/zenoss/log/<daemon>.log` not stdout.
Access via `kubectl exec -- tail -f /opt/zenoss/log/<daemon>.log`.

---

## Important global.conf Keys (current state)

```
amqphost rabbitmq.zenoss.svc.cluster.local
amqpport 5672
amqpuser zenoss
amqppassword zenoss
amqpvhost /zenoss
zep-host mariadb.zenoss.svc.cluster.local      ← DB host for ZEP internal use
zep-uri http://zeneventserver.zenoss.svc.cluster.local:8084
zodb-host mariadb.zenoss.svc.cluster.local
zodb-password zenoss
mysqluser zenoss
mysqlpasswd zenoss
mysqldb zodb
hubhost zenhub.zenoss.svc.cluster.local
redis-host redis.zenoss.svc.cluster.local
solr-servers solr.zenoss.svc.cluster.local:8983
```

Still needed (add when building metrics tier):
- MetricConsumer endpoint (replaces localhost:22350)
- CentralQuery endpoint (for UI graph queries)

---

## Post-Deployment Steps (rebuild from scratch)

After applying all manifests and pods reach Running:

1. Run toolbox checks from Zope pod:
   ```bash
   kubectl exec -n zenoss deployments/zope -it -- /bin/bash
   findposkeyerror -f
   zenrelationscan -f
   zencatalogscan -f
   zodbscan
   zenossdbpack
   ```

2. Reindex Solr (one-time, operator action):
   ```bash
   zencatalog run --createcatalog --forceindex --workers 2
   ```

3. Verify events work: create event in UI, confirm it appears in console

4. Verify modeling works:
   ```bash
   zenmodeler run -d localhost --now
   ```

---

## Rebuild From Scratch Sequence (validated)

```bash
kubectl delete namespace zenoss
kubectl create namespace zenoss
kubectl apply -f configmap.yaml
kubectl apply -f secrets.yaml

# Tier 01
kubectl apply -f 01-infrastructure/mariadb.yaml
kubectl apply -f 01-infrastructure/redis.yaml
kubectl apply -f 01-infrastructure/rabbitmq.yaml
kubectl apply -f 01-infrastructure/memcached.yaml
kubectl apply -f 01-infrastructure/zookeeper.yaml
kubectl apply -f 01-infrastructure/solr.yaml

# Tier 02
kubectl apply -f 02-data/victoriametrics.yaml
kubectl apply -f 02-data/grafana.yaml

# Tier 03
kubectl apply -f 03-resmgr.yaml

# Tier 05 (Zope)
kubectl apply -f 05-frontend/zope.yaml
```

Wait for all pods to reach 1/1 Running. Then run post-deployment steps above.

Note: zeneventserver may restart once on first boot while Liquibase runs
DB migrations. This is expected.

---

## Source Material

ControlCenter manifest: ~/ZenossCore/zenoss-core-6_3_2_1.json
Reference: https://github.com/zenoss/zenoss-prodbin

## To Start the Next Session

1. SSH to server: ssh root@195.201.43.82
2. Check cluster: kubectl get pods -n zenoss -L tier
3. Read ARCHITECTURE-PRINCIPLES.md
4. Read TIER-01-INFRASTRUCTURE-COMPLETE.md
5. Read TIER-03-RESMGR-COMPLETE.md
6. Read this file
7. Attach zenoss-core-6_3_2_1.json to the conversation
8. Start by inspecting CentralQuery supervisor.conf from inside the image

# Handoff Document — Tier 03: Resource Manager

## Cluster Access

ssh root@195.201.43.82
kubectl get pods -n zenoss -L tier

Note: SSH from Claude/Anthropic infrastructure times out — Hetzner blocks
those IP ranges. SSH works normally from your laptop.

## Repository

cd ~/self-directed-ai-learning/zenoss-k8s
git log --oneline -5

## Current Cluster State

All Tiers 01, 02, and Zope (05-frontend) are healthy:

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
| zope-* | 1/1 Running | zenoss/core_6.3:6.3.2_1 | frontend |

## Zope Status

Zope is running and accessible at http://195.201.43.82:30980
Login: admin / zenoss

The UI loads and login works. Errors visible in the UI are from missing
downstream services — all expected at this stage:
- ZepConnectionError — zeneventserver not running yet
- getTrees failures — zenhub not running yet

---

## Directory Structure

zenoss-k8s/
  configmap.yaml
  secrets.yaml (gitignored — present on VM, apply manually on rebuild)
  01-infrastructure/
    mariadb.yaml
    redis.yaml
    rabbitmq.yaml
    memcached.yaml       (contains both memcached + memcached-session)
    zookeeper.yaml
    solr.yaml
  02-data/
    victoriametrics.yaml
    grafana.yaml
  03-resmgr/             <- BUILD THIS NEXT
  04-collector/
  05-frontend/
    zope.yaml

---

## What To Build — Tier 03: Resource Manager

Build in this order — each service depends on the previous:

### 1. zeneventserver (ZEP — Zenoss Event Processor)
Image: zenoss/core_6.3:6.3.2_1
Purpose: Event storage and processing (MariaDB backend)
Ports: 8084 (HTTP API), 3306 (internal DB port — NOT exposed)
Database: zenoss_zep (pre-exists in MariaDB image)
Depends on: MariaDB
Key facts:
- CC Command: su - zenoss -c "zeneventserver start"
- Health: curl http://localhost:8084/zeneventserver/heartbeat
- Prereq: MariaDB zep database accessible
- This is what Zope connects to for event display
- Once running, the ZepConnectionError in Zope disappears

### 2. zeneventd
Image: zenoss/core_6.3:6.3.2_1
Purpose: Event processing daemon — transforms and routes events
Ports: None exported (connects outbound to ZEP + RabbitMQ)
Depends on: zeneventserver, RabbitMQ
Key facts:
- CC Command: su - zenoss -c "zeneventd run --logfileonly"
- Consumes events from RabbitMQ, processes through ZEP

### 3. zenhub
Image: zenoss/core_6.3:6.3.2_1
Purpose: Central hub — all collectors and Zope connect through zenhub
Ports: 8789 (PB protocol), 8081 (XML-RPC)
Depends on: MariaDB, Redis, ZEP
Key facts:
- CC Command: su - zenoss -c "zenhub start"
- This is the most critical application service
- Zope imports zenhub on 8789 — UI device management needs this
- Collectors connect to zenhub to report data
- Health: nc localhost 8789

### 4. zenjobs
Image: zenoss/core_6.3:6.3.2_1
Purpose: Background job scheduler
Ports: None exported
Depends on: zenhub, MariaDB
Key facts:
- CC Command: su - zenoss -c "zenjobs run --logfileonly"
- Runs scheduled maintenance tasks

---

## Key Patterns from Previous Tiers

### Always inspect the image first
```bash
kubectl run debug --image=zenoss/core_6.3:6.3.2_1 \
  --restart=Never -n zenoss --command -- sleep 3600
kubectl exec debug -n zenoss -- bash
kubectl delete pod debug -n zenoss
```

### zenoss/core_6.3 startup pattern
All Zenoss application services follow this pattern:
- CC Command: `su - zenoss -c "<daemon> start"` or `<daemon> run --logfileonly`
- In Kubernetes: set `runAsUser: 1337` (zenoss uid) and call the daemon directly
- Config files in /opt/zenoss/etc/ — global.conf already has all endpoints
- Logs go to /opt/zenoss/log/ — mount as emptyDir for kubectl logs

### Check the CC manifest for each service
Extract Command, RunAs, Volumes, ConfigFiles, HealthChecks, Prereqs:
```bash
python3 -c "
import json
data = json.load(open('zenoss-core-6_3_2_1.json'))
def find(node, name):
    if node.get('Name') == name:
        for k in ['Command','RunAs','Volumes','ConfigFiles','HealthChecks','Prereqs','Endpoints']:
            if k in node: print(k, json.dumps(node[k], indent=2))
    for c in node.get('Services',[]): find(c, name)
find(data, 'SERVICE_NAME_HERE')
"
```

### enableServiceLinks: false
Set on all pods — prevents Kubernetes injecting service env vars that
conflict with application-level env var names.

### Config injection
All services read from /opt/zenoss/etc/global.conf which is already
pre-rendered in the zenoss-config ConfigMap with all ClusterDNS names.
Mount it via subPath. Most services need no other config injection.

---

## Important global.conf Keys

These are already in the ConfigMap and will be read by all zenoss services:
- amqphost: rabbitmq.zenoss.svc.cluster.local
- redis-host: redis.zenoss.svc.cluster.local
- redis-url: redis://redis.zenoss.svc.cluster.local:6379/0
- zep-host: zeneventserver.zenoss.svc.cluster.local
- zep-uri: http://zeneventserver.zenoss.svc.cluster.local:8084
- solr-servers: solr.zenoss.svc.cluster.local:8983
- zodb-host: mariadb.zenoss.svc.cluster.local

---

## Source Material

ControlCenter manifest: ~/ZenossCore/zenoss-core-6_3_2_1.json
Reference: https://github.com/zenoss/zenoss-prodbin

---

## To Start the Next Session

1. SSH to server: ssh root@195.201.43.82
2. Check cluster: kubectl get pods -n zenoss -L tier
3. Read ARCHITECTURE-PRINCIPLES.md
4. Read TIER-01-INFRASTRUCTURE-COMPLETE.md
5. Read this file
6. Attach zenoss-core-6_3_2_1.json to the conversation
7. Start with zeneventserver inspection and manifest

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

# Tier 05 (Zope — creates Solr collection automatically via initContainer)
kubectl apply -f 05-frontend/zope.yaml
```

Wait for all pods to reach 1/1 Running. No manual steps required.
Zope UI: http://<server-ip>:30980 (admin/zenoss)
Grafana: http://<server-ip>:30300 (admin/<changed password>)

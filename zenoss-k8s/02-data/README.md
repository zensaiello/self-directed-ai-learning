# Tier 02: Data — Apply Guide

## Overview

Builds ZooKeeper, HMaster, RegionServer, and OpenTSDB.
Solr (already in Init:0/2) will automatically proceed once ZooKeeper is running.

## Pre-checks

```bash
# Confirm Tier 01 is healthy
kubectl get pods -n zenoss -l tier=infrastructure
# Expected: mariadb-0, redis-0, rabbitmq-0, memcached-*, memcached-session-* all 1/1 Running
# solr-0 should be Init:0/2 (waiting for ZooKeeper — expected)
```

---

## Step 1: Patch the ConfigMap

Adds zookeeper.cfg, hbase-site.xml, hbase-env.sh, opentsdb.conf, opentsdb-logback.xml.

```bash
cd ~/self-directed-ai-learning/zenoss-k8s

# The patch file adds only the new keys — apply it on top of the existing ConfigMap.
# If your configmap.yaml is a full replacement, add these keys to it first.
kubectl apply -f 02-data/configmap-tier02-patch.yaml

# Verify the new keys exist
kubectl get configmap zenoss-config -n zenoss -o jsonpath='{.data}' | python3 -c \
  "import json,sys; d=json.load(sys.stdin); [print(k) for k in sorted(d.keys())]"
```

Expected new keys: `hbase-env.sh`, `hbase-site.xml`, `opentsdb-logback.xml`, `opentsdb.conf`, `zookeeper.cfg`

---

## Step 2: ZooKeeper

```bash
kubectl apply -f 02-data/zookeeper.yaml

# Watch it come up
kubectl get pods -n zenoss -w -l app=zookeeper
# Expected: Init:0/2 -> Init:1/2 -> Init:2/2 -> Running (1/1)
# Two initContainers: config-init, myid-init

# Once Running, verify health
kubectl exec zookeeper-0 -n zenoss -- sh -c "echo stats | nc 127.0.0.1 2181 | grep Zookeeper"
# Expected: Zookeeper version: ...

# Verify myid was written correctly
kubectl exec zookeeper-0 -n zenoss -- cat /var/lib/zookeeper/myid
# Expected: 1

# Check solr-0 — it should now advance from Init:0/2 to Init:1/2 or Running
kubectl get pods -n zenoss -l app=solr
```

---

## Step 3: HMaster

```bash
kubectl apply -f 02-data/hmaster.yaml

kubectl get pods -n zenoss -w -l app=hmaster
# Expected: Init:0/2 -> Init:1/2 -> Init:2/2 -> Running (1/1)
# initContainers: wait-for-zookeeper, config-init

# Once Running, verify REST API
kubectl exec hmaster-0 -n zenoss -- curl -s http://127.0.0.1:61000/status/cluster
# Expected: JSON with "liveServers":[] (no region servers yet — that's correct)

# Check readiness probe passed
kubectl describe pod hmaster-0 -n zenoss | grep -A5 "Conditions:"
```

---

## Step 4: RegionServer

```bash
kubectl apply -f 02-data/regionserver.yaml

kubectl get pods -n zenoss -w -l app=regionserver
# Expected: Init:0/3 -> ... -> Running (1/1)
# initContainers: wait-for-zookeeper, wait-for-hmaster, config-init

# Once Running, verify it registered with HMaster
kubectl exec hmaster-0 -n zenoss -- \
  curl -s http://127.0.0.1:61000/status/cluster | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('Live servers:', d.get('LiveServerNumber', d))"
# Expected: Live servers: 1

# Verify port connectivity
kubectl exec regionserver-0 -n zenoss -- sh -c "echo | nc 127.0.0.1 60200 && echo 'port ok'"
```

---

## Step 5: OpenTSDB

```bash
kubectl apply -f 02-data/opentsdb.yaml

kubectl get pods -n zenoss -w -l app=opentsdb
# Expected: Init:0/4 -> ... -> Running (1/1)
# initContainers: wait-for-zookeeper, wait-for-hmaster, wait-for-regionserver, config-init
# NOTE: readinessProbe has initialDelaySeconds=60 — first start may take longer
#       due to CREATE_TABLES=1 running mkmetrics.sh to create HBase tables.

# Watch logs during first start (table creation is verbose)
kubectl logs -f opentsdb-0 -n zenoss

# Once Running, verify API
kubectl exec opentsdb-0 -n zenoss -- \
  wget --timeout=5 -q -O - http://localhost:4242/api/version
# Expected: JSON with "version" field

# Verify both Services resolve
kubectl run test --image=busybox --restart=Never --rm -it -n zenoss -- \
  sh -c "nslookup opentsdb-reader.zenoss.svc.cluster.local && nslookup opentsdb-writer.zenoss.svc.cluster.local"
```

---

## Full Tier 02 Health Check

```bash
# All Tier 02 pods should be 1/1 Running
kubectl get pods -n zenoss -l tier=data

# ZooKeeper responding
kubectl exec zookeeper-0 -n zenoss -- sh -c "echo ruok | nc 127.0.0.1 2181"
# Expected: imok

# HMaster REST showing 1 live server
kubectl exec hmaster-0 -n zenoss -- \
  wget -q -O - http://localhost:61000/status/cluster | grep -o '"LiveServerNumber":[0-9]*'
# Expected: "LiveServerNumber":1

# OpenTSDB API
kubectl exec opentsdb-0 -n zenoss -- \
  wget --timeout=5 -q -O - http://localhost:4242/api/stats | head -1
# Expected: valid JSON array

# Solr should now be Running (was waiting for ZooKeeper in Tier 01)
kubectl get pods -n zenoss -l app=solr
# Expected: 1/1 Running
```

---

## Troubleshooting

### ZooKeeper not starting
```bash
kubectl logs zookeeper-0 -n zenoss -c config-init
kubectl logs zookeeper-0 -n zenoss -c myid-init
kubectl logs zookeeper-0 -n zenoss
# Check /var/lib/zookeeper/myid exists and contains "1"
kubectl exec zookeeper-0 -n zenoss -- ls -la /var/lib/zookeeper/
```

### HMaster crash-looping
```bash
kubectl logs hmaster-0 -n zenoss --previous
# Common issue: ZooKeeper not ready when HMaster starts
# The wait-for-zookeeper initContainer should prevent this; check its logs:
kubectl logs hmaster-0 -n zenoss -c wait-for-zookeeper
# If hbase-site.xml is wrong:
kubectl exec hmaster-0 -n zenoss -- cat /etc/hbase-site.xml
```

### RegionServer not registering
```bash
kubectl logs regionserver-0 -n zenoss
# Check what instance ID was passed:
kubectl logs regionserver-0 -n zenoss -c config-init | grep ordinal
# Verify HMaster was ready when RS started:
kubectl logs regionserver-0 -n zenoss -c wait-for-hmaster
```

### OpenTSDB table creation failing
```bash
kubectl logs opentsdb-0 -n zenoss
# Table creation requires HBase to be healthy and the RegionServer to have regions assigned.
# If "ERROR" about table creation: wait 2-3 minutes and restart:
kubectl rollout restart statefulset/opentsdb -n zenoss
# First start often needs a restart after tables are created — this is normal.
```

### Solr still in Init after ZooKeeper is Running
```bash
kubectl logs solr-0 -n zenoss -c wait-for-zookeeper
# If ZooKeeper is up but Solr initContainer is still failing:
kubectl exec -it debug-pod -n zenoss -- sh -c \
  "echo stats | nc zookeeper.zenoss.svc.cluster.local 2181 | grep Zookeeper"
```

---

## Git Commit

```bash
cd ~/self-directed-ai-learning/zenoss-k8s
git add 02-data/ configmap.yaml   # (after merging tier02 patch keys into configmap.yaml)
git commit -m "tier02: add ZooKeeper, HMaster, RegionServer, OpenTSDB"
```

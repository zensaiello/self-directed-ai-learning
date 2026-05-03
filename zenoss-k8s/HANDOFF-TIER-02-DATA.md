# Handoff Document — Tier 02: Data Tier

## Cluster Access

ssh root@195.201.43.82
kubectl get pods -n zenoss

## Repository

cd ~/self-directed-ai-learning/zenoss-k8s
git log --oneline -5

## Current Cluster State

### Running Services

| Pod | Status | Image |
|---|---|---|
| mariadb-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 |
| redis-0 | 1/1 Running | zenoss/core_6.3:6.3.2_1 |
| rabbitmq-0 | 1/1 Running | rabbitmq:3-management |
| memcached-* | 1/1 Running | memcached:1.6-alpine |
| memcached-session-* | 1/1 Running | memcached:1.6-alpine |
| solr-0 | Init:0/2 | zenoss/core_6.3:6.3.2_1 |

### Solr is waiting

solr-0 is blocked in wait-for-zookeeper initContainer.
It will automatically proceed once ZooKeeper is running.
No action needed - just build ZooKeeper first.

---

## What To Build - Tier 02: Data

Build in this exact order - each service depends on the previous:

### 1. ZooKeeper
Image: zenoss/hbase:24.0.8
Purpose: Distributed coordination for HBase and Solr
Ports: 2181 (client), 2888 (peer), 3888 (leader election)
Storage: Persistent - /var/lib/zookeeper
Key facts:
- StatefulSet, headless service required for peer DNS
- myid file must match pod ordinal (zookeeper-0 = myid 1)
- zoo.cfg already prepared in zenoss-config ConfigMap
- When ZooKeeper starts, Solr will automatically proceed from Init:0/2

### 2. HMaster
Image: zenoss/hbase:24.0.8
Purpose: HBase master - manages region assignments
Ports: 60000 (master), 60010 (web UI), 61000 (REST API)
Depends on: ZooKeeper
Key facts:
- hbase-site.xml in zenoss-config ConfigMap points to ZooKeeper
- REST API at :61000 used by OpenTSDB prereq health check
- initContainer must wait for ZooKeeper

### 3. RegionServer
Image: zenoss/hbase:24.0.8
Purpose: HBase region server - stores and serves data
Ports: 60200 (region server), 60300 (web UI)
Depends on: ZooKeeper + HMaster
Key facts:
- initContainer must wait for HMaster REST API to report live servers
- OpenTSDB prereq checks: wget http://hmaster:61000/status/cluster

### 4. OpenTSDB
Image: zenoss/opentsdb:24.0.8
Purpose: Time series database for Zenoss metrics
Ports: 4242 (read+write)
Depends on: ZooKeeper + HMaster + RegionServer
Key facts:
- Two Services needed: opentsdb-reader and opentsdb-writer (both port 4242)
- Table prefix: zenoss (creates zenoss-tsdb, zenoss-tsdb-uid, etc.)
- opentsdb.conf in zenoss-config ConfigMap already configured
- Tables must be created on first start via mkmetrics.sh or similar
- initContainer waits for RegionServer via HMaster REST API

---

## Key Patterns Established (Apply to All Future Tiers)

### 1. Image Inspection First
Always inspect before writing manifests.
Run a debug pod, exec into it, check binaries, configs, data directories.
Delete the debug pod when done.

### 2. Check the ControlCenter Manifest
Extract Command, RunAs, Volumes, ConfigFiles, HealthChecks, Prereqs
before writing any manifest. The JSON is the source of truth.

### 3. PID 1 Decision Tree
- Does the service have no Zenoss-specific code? Use official image.
- Does ControlCenter manifest show supervisord in Command? Use supervisord.
- Does the service run in foreground by default? Use directly as command.

### 4. Pre-baked Data Pattern (MariaDB model)
If image has pre-initialized data directory:
- initContainer copies image data to PVC on first start
- Check if PVC is empty before copying (idempotent)

### 5. ZooKeeper Dependency Pattern
Services that depend on ZooKeeper use this initContainer check:
  until nc zookeeper.zenoss.svc.cluster.local 2181 returns Zookeeper; do sleep 5; done

### 6. Config Injection Pattern
ControlCenter template injection becomes Kubernetes initContainer:
- initContainer writes config files to emptyDir volume
- Main container mounts same emptyDir and reads configs
- Alternatively mount ConfigMap directly via subPath for static configs

---

## Directory Structure

zenoss-k8s/
  README.md
  ARCHITECTURE-PRINCIPLES.md
  TIER-01-INFRASTRUCTURE-COMPLETE.md
  HANDOFF-TIER-02-DATA.md
  configmap.yaml
  secrets.yaml (gitignored - apply manually on rebuild)
  01-infrastructure/
    mariadb.yaml
    redis.yaml
    rabbitmq.yaml
    memcached.yaml
    solr.yaml
  02-data/          <- next tier to build
  03-resmgr/
  04-collector/
  05-frontend/

---

## Source Material

ControlCenter manifest: /mnt/user-data/uploads/zenoss-core-6_3_2_1.json
Reference repos:
  https://github.com/zenoss/zenoss-prodbin (bin/ scripts, healthchecks)
  https://github.com/zenoss/zendev (development environment reference)
Docker Hub images:
  zenoss/core_6.3:6.3.2_1 (main application image)
  zenoss/hbase:24.0.8 (ZooKeeper, HMaster, RegionServer)
  zenoss/opentsdb:24.0.8 (OpenTSDB)

---

## To Start the Next Session

1. SSH to server: ssh root@195.201.43.82
2. Check cluster state: kubectl get pods -n zenoss
3. Read ARCHITECTURE-PRINCIPLES.md
4. Read TIER-01-INFRASTRUCTURE-COMPLETE.md
5. Attach the ControlCenter JSON manifest to the new conversation
6. Start with ZooKeeper inspection and manifest

---

## Claude Access Setup

SSH access is configured for read/inspect operations.

Server: 195.201.43.82
User: claude-access
Key: ~/.ssh/claude_zenoss (on your laptop)

At the start of the next session paste the private key content so Claude
can SSH in to read pod status, logs, and files directly without copy-paste.

Private key is at: ~/.ssh/claude_zenoss on your laptop
Public key fingerprint: AAAAC3NzaC1lZDI1NTE5AAAAIKQI1tmK2Kp82ygW0UFEgsnkmYHcfvvp7w5GdwJl2GH5

Access model:
- Claude SSHes in to READ: logs, pod status, manifest files, inspection output
- You RUN all kubectl apply/delete/patch commands
- You RUN all git commits and pushes
- Claude WRITES manifest files directly to /opt/self-directed-ai-learning/zenoss-k8s/

Project directory: /opt/self-directed-ai-learning/zenoss-k8s/
Claude has write access to zenoss-k8s/ only via zenoss-project group.

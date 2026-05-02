# Zenoss Core 6.3 — Kubernetes Migration

## Project Goal

Migrate Zenoss Community Edition (Core) 6.3.2 from its native Control Center
orchestrator to Kubernetes (k3s). This is a real-world translation exercise
converting a proprietary orchestration manifest into standard Kubernetes primitives.

## Source Material

- ControlCenter manifest: `zenoss-core-6_3_2_1.json`
- ControlCenter version: 1.6.3
- Zenoss Core version: 6.3.2_1
- Original project: https://sourceforge.net/projects/zenoss/

## Cluster

- Distribution: k3s v1.35.4
- Node: Hetzner CPX42 (8 vCPU, 16GB RAM, 320GB SSD)
- OS: Ubuntu 22.04 LTS
- Namespace: zenoss

## Architecture

Five tiers deployed in dependency order:

| Tier | Services |
|---|---|
| infrastructure | MariaDB, Redis, RabbitMQ, Solr, Memcached, memcached-session |
| data | ZooKeeper, HMaster, RegionServer, OpenTSDB |
| resmgr | zenhub, zenhubworker, ZEP, Zope, CentralQuery, MetricConsumer, zeneventd, zenactiond, zenjobs |
| collector | zentrap, zensyslog, zenperfsnmp, zenping, zenprocess, zencommand, zenpython, zenstatus, zenmodeler, zminion, collectorredis, MetricShipper |
| frontend | zproxy, Traefik ingress |

## Directory Structure
zenoss-k8s/
├── README.md
├── namespace.yaml
├── configmap.yaml
├── secrets.yaml
├── 01-infrastructure/
│   ├── mariadb.yaml
│   ├── redis.yaml
│   ├── rabbitmq.yaml
│   ├── solr.yaml
│   ├── memcached.yaml
│   └── memcached-session.yaml
├── 02-data/
│   ├── zookeeper.yaml
│   ├── hmaster.yaml
│   ├── regionserver.yaml
│   └── opentsdb.yaml
├── 03-resmgr/
│   ├── zenhub.yaml
│   ├── zenhubworker.yaml
│   ├── zeneventserver.yaml
│   ├── zope.yaml
│   ├── centralquery.yaml
│   ├── metricconsumer.yaml
│   ├── zeneventd.yaml
│   ├── zenactiond.yaml
│   └── zenjobs.yaml
├── 04-collector/
│   ├── collectorredis.yaml
│   ├── metricshipper.yaml
│   ├── zentrap.yaml
│   ├── zensyslog.yaml
│   ├── zenperfsnmp.yaml
│   ├── zenping.yaml
│   ├── zenprocess.yaml
│   ├── zencommand.yaml
│   ├── zenpython.yaml
│   ├── zenstatus.yaml
│   ├── zenmodeler.yaml
│   └── zminion.yaml
└── 05-frontend/
└── zproxy.yaml

## Key Translation Decisions

- ControlCenter `Context` variables → Kubernetes ConfigMap (`zenoss-config`)
- ControlCenter `Volumes` (persistent) → StatefulSet `volumeClaimTemplates`
- ControlCenter `Volumes` (tmp) → `emptyDir`
- ControlCenter `Prereqs` → `initContainers`
- ControlCenter `HealthChecks` → `livenessProbe` / `readinessProbe`
- ControlCenter `Endpoints` (export) → Kubernetes `Service`
- ControlCenter `Endpoints` (import) → DNS reference via `Service` name
- ControlCenter `Launch: manual` → `replicas: 0`
- ControlCenter `controlplane_consumer` `:8444` → stubbed out (CC-specific, no K8s equivalent)

## Label Strategy

Every resource carries:

```yaml
labels:
  app.kubernetes.io/part-of: zenoss
  app.kubernetes.io/name: <service-name>
  tier: <infrastructure|data|resmgr|collector|frontend>
```


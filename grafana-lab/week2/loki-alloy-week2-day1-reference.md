# Loki + Grafana Alloy — Week 2 Day 1 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand Loki's role in the stack at a level sufficient for enterprise architecture conversations
- Understand Grafana Alloy's role as the telemetry collector and what it replaced
- Understand the push vs pull architectural distinction and why it matters
- Extend the Week 1 stack with Loki and Alloy
- Verify end-to-end log pipeline from containers to Grafana
- Introduce foundational LogQL concepts

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- All scaling claims quantified where possible
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Table of Contents

1. [What Loki Is and How It Fits in the Stack](#1-what-loki-is-and-how-it-fits-in-the-stack)
2. [What Grafana Alloy Is](#2-what-grafana-alloy-is)
3. [Push vs Pull — The Architectural Shift](#3-push-vs-pull--the-architectural-shift)
4. [Stack Setup](#4-stack-setup)
5. [LogQL Introduction — Line Filter Operators](#5-logql-introduction--line-filter-operators)
6. [Questions and Answers](#6-questions-and-answers)
7. [Advanced Topics](#7-advanced-topics)
8. [Reference Material](#8-reference-material)

---

## 1. What Loki Is and How It Fits in the Stack

### Loki's Role

Loki is a log aggregation system built by Grafana Labs. It ingests, stores, and makes logs queryable. In the LGTM stack it is the **L** — the log layer that sits alongside Prometheus metrics, Tempo traces, and Mimir long-term storage.

**The single most important design decision in Loki:**

> Loki does not index the content of log lines. It only indexes the labels attached to log streams.

This drives every architectural and operational decision downstream.

---

### How Loki Differs From Traditional Log Management

The dominant alternative in enterprise log management is the **Elastic Stack** (ELK — Elasticsearch, Logstash, Kibana). Understanding the difference is essential for customer conversations.

| | Elasticsearch | Loki |
|---|---|---|
| Full-text search speed | Fast — pre-indexed | Slower — scans compressed data |
| Storage cost | High | Low |
| Ingest cost (CPU) | High | Low |
| Schema requirement | Yes | No |
| Operational complexity | High | Lower |
| Best fit | Unknown log formats, ad-hoc search | Known log sources, label-based filtering |

**Enterprise implication:** Loki is not a replacement for Elasticsearch in all scenarios. It is the right choice when you know your log sources, can attach meaningful labels at collection time, and want to keep storage costs low. It is the wrong choice when you need fast full-text search across arbitrary log fields without knowing the structure in advance.

---

### The Loki Data Model

Loki organizes logs into **streams**. A stream is a set of log lines that share the same label set — exactly analogous to a Prometheus time series.

```
{job="prometheus", container="prometheus"} → log lines from the Prometheus container
{job="node-exporter", container="node-exporter"} → log lines from node-exporter
{job="grafana", container="grafana"} → log lines from Grafana
```

Each unique combination of label key-value pairs is a separate stream. Log lines within a stream are stored in time order.

**The cardinality principle from Week 1 applies directly:**
- High-cardinality labels create too many streams
- Same anti-patterns apply — never use user IDs, request IDs, IP addresses as labels
- Labels should be dimensions you filter or aggregate by — `job`, `container`, `environment`, `level`
- High-cardinality identifiers belong in the log line content, not in the labels

---

### Where Loki Fits Relative to Prometheus

Prometheus and Loki answer different questions about the same system:

| Question | Tool |
|---|---|
| How many errors per second? | Prometheus — metric |
| Which specific requests errored and why? | Loki — log |
| Is CPU above 80%? | Prometheus — metric |
| What was the application doing when CPU spiked? | Loki — log |
| What is the p99 latency? | Prometheus — histogram |
| What did the slow requests look like? | Loki — log |

Metrics tell you something is wrong and how bad it is. Logs tell you what specifically happened. The Grafana Explore split view — metrics on the left, logs on the right — makes this correlation practical during an incident.

**Enterprise relevance:** A monitoring platform with only metrics can tell you an alert fired. A platform with metrics and logs can tell you why. This is the answer to "what does adding Loki to a Prometheus environment get you?"

---

### Loki Enterprise Fit and Limitations

| Scenario | Loki Fit | Notes |
|---|---|---|
| Container and Kubernetes log collection | Excellent | Native label model maps well to K8s metadata |
| Known log sources with structured labels | Excellent | Low cost, low operational overhead |
| High-volume log ingestion at scale | Good with distributed mode | Single-node Loki has ingest limits |
| Ad-hoc full-text search across unknown log formats | Poor | Elasticsearch is better suited |
| Long-term log retention for compliance | Good | Object storage backend — same model as Mimir |
| Real-time log alerting | Good | Loki supports alerting rules similar to Prometheus |

---

## 2. What Grafana Alloy Is

Grafana Alloy is the **telemetry collector** for the Grafana stack. It runs as an agent, collects telemetry data — logs, metrics, and traces — and forwards it to the appropriate backends.

### What Alloy Replaced

| Component | Role | Status |
|---|---|---|
| Promtail | Log collection agent for Loki only | Deprecated — replaced by Alloy |
| Grafana Agent | Broader collector for metrics, logs, traces | Deprecated — replaced by Alloy |
| Grafana Alloy | Unified collector for all telemetry types | Current path |

**Enterprise implication:** Customers running Promtail today are running a deprecated component. Part of the Grafana Labs value proposition is helping customers migrate to Alloy. Knowing the migration path is relevant to the role.

---

### The Alloy Pipeline Model

Alloy uses a **component-based pipeline** architecture. Each component does one thing and passes data to the next — the same mental model as a Unix pipe.

A simple log collection pipeline:

```
[discover containers] → [read log files] → [add labels] → [send to Loki]
```

**Lab configuration — three components:**

```hcl
// Component 1 — discover running Docker containers
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// Component 2 — collect logs from discovered containers
loki.source.docker "container_logs" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.containers.targets
  forward_to = [loki.write.local.receiver]
  relabel_rules = loki.relabel.container_labels.rules
}

// Component 3 — write logs to Loki
loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

**Relabel rules — extracting useful labels from Docker metadata:**

```hcl
loki.relabel "container_labels" {
  forward_to = []

  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }

  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
    target_label  = "service"
  }
}
```

**Why the pipeline model matters at enterprise scale:** It makes collection composable and auditable. You can see exactly what data is being collected, what transformations are applied, and where it is going. Complex routing requirements — multiple log sources, multiple backends, different labels per source — are expressed as additional pipeline components rather than monolithic configuration.

---

### Alloy Web UI

Alloy exposes a web UI at `http://localhost:12345` showing all pipeline components and their health status. In the lab all four components show healthy — discovery, source, relabel, and write.

---

## 3. Push vs Pull — The Architectural Shift

| | Prometheus (metrics) | Loki (logs) |
|---|---|---|
| Model | Pull — Prometheus reaches out to targets | Push — Alloy ships logs to Loki |
| Collection trigger | Scheduled interval | Event-driven — as log lines are written |
| Agent requirement | No agent needed on target | Agent (Alloy) required on or near log source |
| Network requirement | Prometheus must reach targets | Agent must reach Loki |

**Why logs must be pushed:**

A metric has a current value retrievable at any time. A log line exists at a specific moment — if you do not capture it when it happens you lose it. An agent running close to the log source captures lines as they are written and forwards them immediately. Polling would introduce latency and risk missing lines between poll intervals.

**Connection to Zenoss background:** The same architectural tension that led to building PS.DataIngest as a push-based framework at Zenoss. Poll-based collection works for state (current CPU value) but not for events (what just happened). Logs are events. Alloy's push model is the correct architectural response.

---

## 4. Stack Setup

### Week 2 Directory Structure

```
~/grafana-lab/week2/
├── docker-compose.yml
├── loki-config.yml
└── alloy-config.alloy
```

### Loki Configuration

```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  instance_addr: 127.0.0.1
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

query_range:
  results_cache:
    cache:
      embedded_cache:
        enabled: true
        max_size_mb: 100

schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093
```

### Docker Compose

Five services — Prometheus, Grafana, Node Exporter carried forward from Week 1, plus Loki and Alloy:

```yaml
networks:
  monitoring:
    driver: bridge

volumes:
  prometheus_data:
  grafana_data:
  loki_data:

services:

  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ../week1/prometheus.yml:/etc/prometheus/prometheus.yml
      - ../week1/recording_rules.yml:/etc/prometheus/recording_rules.yml
      - ../week1/alerting_rules.yml:/etc/prometheus/alerting_rules.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.enable-lifecycle'
    ports:
      - "9090:9090"
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=grafana
    ports:
      - "3000:3000"
    networks:
      - monitoring
    depends_on:
      - prometheus
      - loki

  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    restart: unless-stopped
    ports:
      - "9100:9100"
    networks:
      - monitoring
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/host/root:ro,rslave
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/host/root'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'

  loki:
    image: grafana/loki:latest
    container_name: loki
    restart: unless-stopped
    volumes:
      - ./loki-config.yml:/etc/loki/local-config.yaml
      - loki_data:/loki
    command:
      - '--config.file=/etc/loki/local-config.yaml'
    ports:
      - "3100:3100"
    networks:
      - monitoring

  alloy:
    image: grafana/alloy:latest
    container_name: alloy
    restart: unless-stopped
    volumes:
      - ./alloy-config.alloy:/etc/alloy/config.alloy
      - /var/run/docker.sock:/var/run/docker.sock
    command:
      - 'run'
      - '--server.http.listen-addr=0.0.0.0:12345'
      - '/etc/alloy/config.alloy'
    ports:
      - "12345:12345"
    networks:
      - monitoring
    depends_on:
      - loki
```

### Startup Sequence

```bash
# Bring down Week 1 stack first to avoid port conflicts
cd ~/grafana-lab/week1
docker compose down

# Start Week 2 stack
cd ~/grafana-lab/week2
docker compose up -d
```

### Grafana Data Sources — Fresh Instance

Week 2 Grafana starts with no data sources configured. Both must be added manually:

**Prometheus:**

| Field | Value |
|---|---|
| URL | `http://prometheus:9090` |
| Scrape interval | 15s |
| HTTP method | POST |

**Loki:**

| Field | Value |
|---|---|
| URL | `http://loki:3100` |

### Verification Endpoints

| Endpoint | What it confirms |
|---|---|
| `http://localhost:3100/ready` | Loki is healthy and ready |
| `http://localhost:12345` | Alloy UI — pipeline component health |
| `http://localhost:9090/targets` | Prometheus scrape targets UP |

### Lab Verification Results

All five containers confirmed running:

```
container=alloy        service=alloy
container=grafana      service=grafana
container=loki         service=loki
container=node-exporter  service=node-exporter
container=prometheus   service=prometheus
```

Log line counts over 5 minutes — Loki generates significantly more log output than other containers due to self-logging of ingest operations:

- loki: highest volume — logs its own ingest, index writes, compaction
- prometheus: low volume — stable scrape cycle generates minimal log output
- alloy, grafana, node-exporter: moderate volume

---

## 5. LogQL Introduction — Line Filter Operators

### Stream Selection

All LogQL queries begin with a **stream selector** — a label matcher that identifies which log streams to query:

```logql
{container="prometheus"}           # exact match — one container
{container=~".+"}                  # regex match — all containers
{container="prometheus", service="prometheus"}  # multiple labels
```

This is the index lookup — fast regardless of data volume.

---

### The Log Pipeline

After selecting streams, **pipeline stages** filter or transform the log lines within those streams. Pipeline stages are chained using the `|` character.

---

### Line Filter Operators

Line filter operators scan log line content — the expensive operation that runs after stream selection.

| Operator | Meaning | Example |
|---|---|---|
| `\|=` | Line contains string | `\|= "error"` |
| `!=` | Line does not contain string | `!= "debug"` |
| `\|~` | Line matches regex | `\|~ "error\|warn"` |
| `!~` | Line does not match regex | `!~ "health.*check"` |

**Parallel to PromQL label matchers:**

| PromQL | LogQL equivalent |
|---|---|
| `{mode="idle"}` | `\|= "text"` |
| `{mode!="idle"}` | `!= "text"` |
| `{mode=~"user\|system"}` | `\|~ "regex"` |
| `{mode!~"idle\|iowait"}` | `!~ "regex"` |

**Chaining pipeline stages:**

```logql
# Lines containing "scrape" but not "success"
{container="prometheus"} |= "scrape" != "success"

# Error lines across all containers excluding 404s
{container=~".+"} |= "error" != "404"
```

---

### Metric Queries — count_over_time()

LogQL supports converting log stream data into numeric metrics:

```logql
# Count log lines per container over last 5 minutes
sum by (container) (count_over_time({container=~".+"}[5m]))
```

`count_over_time()` is analogous to PromQL's `rate()` — it converts event data into a numeric value over a time window. The `sum by (container)` aggregation is identical in syntax to PromQL.

---

### Performance — Label Selectors vs Line Filters

This is the most important operational concept in LogQL query design.

| Operation | Layer | Cost |
|---|---|---|
| Label selector `{container="prometheus"}` | Index lookup | Cheap — fast regardless of data volume |
| Line filter `\|= "error"` | Compressed log scan | Expensive — scales with data volume |

**The rule:** Use label selectors to narrow the stream set as much as possible before applying line filters. The more specific your label selector, the less data Loki must decompress and scan.

**Performance comparison at scale (10GB/hour ingest, 500 services):**

| Query | Data scanned | Performance |
|---|---|---|
| `{service=~".+"} \|= "error"` | All 10GB | Slow — full scan |
| `{service="api-gateway"} \|= "error"` | ~20MB | Fast — narrow stream |
| `{service="api-gateway", detected_level="error"}` | ~2MB | Fastest — index filters |

**The design implication:** If a filter dimension can be expressed as a bounded label — log level, environment, service tier — extract it as a label at collection time. This moves filtering from the expensive scan layer to the cheap index layer.

```logql
# Slower — line scan for level
{container="prometheus"} |= "error"

# Faster — index lookup for level (requires detect_level label from Alloy)
{container="prometheus", detected_level="error"}
```

Alloy's built-in `detect_level` feature automatically extracts log level as a label — enabling the faster index-based filtering without manual parsing configuration.

---

### Lab Queries Run

```logql
# All streams
{container=~".+"}

# Single container
{container="prometheus"}
{container="loki"}

# Line content filter
{container="prometheus"} |= "error"   # returned no results — healthy baseline

# Metric aggregation
sum by (container) (count_over_time({container=~".+"}[5m]))
```

---

## 6. Questions and Answers

### Q1: How does Loki differ from Elasticsearch for log management?

**Summary:** Loki indexes only labels — not log line content. Elasticsearch indexes everything. Loki is cheaper to operate and store but slower for full-text search. Elasticsearch is better for ad-hoc search across unknown log formats. Loki is the right choice for known log sources with structured labels where storage cost matters.

---

### Q2: What did Grafana Alloy replace?

**Summary:** Alloy replaced two deprecated components — Promtail (log-only collection agent for Loki) and the Grafana Agent (broader but inconsistent collector). Alloy unifies log, metric, and trace collection in a single component with a consistent pipeline model. Customers running Promtail are running a deprecated component — migration to Alloy is the current path.

---

### Q3: Why must logs be pushed rather than pulled?

**Summary:** A metric has a current value retrievable at any point in time. A log line exists at a specific moment — polling would risk missing lines between intervals. An agent running close to the log source captures lines as they are written and pushes them immediately. Pull-based log collection would introduce latency and data loss.

---

### Q4: What is the performance concern with line filter operators?

**Summary:** Line filters operate against compressed log data — not the index. After stream selection via labels, Loki must decompress and scan actual log content to apply line filters. Cost scales with the volume of data in the selected streams. Mitigation: use label selectors to narrow the stream set as much as possible before applying line filters. If a filter dimension can be expressed as a bounded label, extract it at collection time so it can be filtered via the index instead.

---

## 7. Advanced Topics

Topics identified during Week 2 Day 1 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, and native histograms | Histograms are a significant cardinality source. Native histograms change the storage model and reduce series count overhead substantially. | Week 1 Day 2 |
| **Recording rules** — advanced design and performance impact at scale | Enterprise scale introduces rule evaluation performance, rule dependencies, and federation of recorded metrics. | Week 1 Day 2 |
| **SNMP exporter configuration** — Counter32 vs Counter64 OID selection | Operational gap when customers migrate from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing and inhibition | Full Alertmanager deployment, routing trees, and inhibition rules. Week 4 topic. | Week 1 Day 3 |
| **Prometheus CI/CD integration** — promtool in pipelines | Metric instrumentation validation before deployment. | Week 1 Day 3 |
| **Grafana Enterprise features** — advanced caching, RBAC, reporting | Relevant to large organization deployments. | Week 1 Day 4 |
| **Loki distributed mode** — scaling beyond single node | Single-node Loki has ingest and query limits. Distributed mode splits components for horizontal scaling. | Week 2 Day 1 — enterprise fit discussion |
| **LogQL parsing stages** — extracting structured fields from log lines | Beyond line filters, LogQL supports parsing log content into structured fields for aggregation. Foundation for log-derived metrics. | Week 2 Day 1 — pipeline stages introduction |
| **Promtail to Alloy migration** — customer migration path | Customers running Promtail need a migration path. Understanding what changes and what carries forward is directly relevant to the role. | Week 2 Day 1 — Alloy introduction |

---

## 8. Reference Material

### Loki

| Resource | URL | Notes |
|---|---|---|
| Loki documentation | https://grafana.com/docs/loki/latest/ | Authoritative — covers LogQL, label design, storage |
| Loki labels best practices | https://grafana.com/docs/loki/latest/get-started/labels/best-practices/ | Cardinality guidance specific to Loki |
| Loki vs Elasticsearch | https://grafana.com/docs/loki/latest/get-started/overview/ | Grafana's own comparison |
| Loki storage configuration | https://grafana.com/docs/loki/latest/configure/storage/ | Filesystem vs object storage backends |
| Loki distributed mode | https://grafana.com/docs/loki/latest/get-started/deployment-modes/ | Scaling beyond single node |

### Grafana Alloy

| Resource | URL | Notes |
|---|---|---|
| Grafana Alloy documentation | https://grafana.com/docs/alloy/latest/ | Component reference and pipeline configuration |
| Alloy component reference | https://grafana.com/docs/alloy/latest/reference/components/ | All available pipeline components |
| Promtail to Alloy migration | https://grafana.com/docs/alloy/latest/tasks/migrate/from-promtail/ | Migration path for customers on Promtail |
| Alloy workshops | https://grafana.com/workshops/ | Free hands-on pipeline building workshops |

### LogQL

| Resource | URL | Notes |
|---|---|---|
| LogQL documentation | https://grafana.com/docs/loki/latest/query/ | Query language reference |
| LogQL log queries | https://grafana.com/docs/loki/latest/query/log_queries/ | Stream selectors, pipeline stages, line filters |
| LogQL metric queries | https://grafana.com/docs/loki/latest/query/metric_queries/ | count_over_time() and other metric aggregations |
| LogQL query best practices | https://grafana.com/docs/loki/latest/query/bp-query/ | Performance guidance including label vs line filter tradeoffs |

### Architecture and Competitive Landscape

| Resource | URL | Notes |
|---|---|---|
| Grafana LGTM stack overview | https://grafana.com/about/press/2022/06/09/announcing-the-lgtm-stack-grafana-loki-tempo-and-mimir/ | How the four components fit together |
| Loki architecture | https://grafana.com/docs/loki/latest/get-started/architecture/ | Component breakdown including distributor, ingester, querier |
| Elasticsearch vs Loki | https://grafana.com/blog/2020/08/19/how-loki-compares-to-other-log-storage-solutions/ | Grafana's detailed comparison |

---

*Week 2 Day 1 complete. Day 2: LogQL depth — filtering, parsing, metric queries, and log-to-metric correlation in Grafana Explore split view.*

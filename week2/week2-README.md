# Week 2 Lab — Loki + Grafana Alloy Stack
## Grafana Observability Lab — Log Ingestion & Correlation Guide

---

## Overview

This lab extends the Week 1 Prometheus + Grafana stack by adding log ingestion and correlation capabilities:

- **Loki** — log aggregation and storage
- **Grafana Alloy** — telemetry collector, collects container logs and ships them to Loki

By the end of this lab you will have a working log pipeline collecting logs from all running containers, a unified dashboard combining Prometheus metrics and Loki log panels, and two Loki alerting rules monitoring for log-based conditions.

> **Prerequisite:** The Week 1 stack configuration files are required. The Week 2 `docker-compose.yml` references `../week1/prometheus.yml`, `../week1/recording_rules.yml`, and `../week1/alerting_rules.yml` via relative paths. Both the `week1/` and `week2/` directories must be present.

---

## Architecture

```
Docker containers (all 5)
        ↓ stdout logs
Grafana Alloy
  - Discovers containers via Docker socket
  - Reads log output
  - Extracts container and service labels
  - Pushes labeled log streams to Loki
        ↓ push (HTTP)
Loki
  - Receives and indexes log streams by label
  - Stores compressed log data
  - Evaluates alerting rules via built-in ruler
  - Serves LogQL queries
        ↓ query
Grafana
  - Loki data source alongside existing Prometheus data source
  - Explore split view — metrics left, logs right
  - Unified dashboard with both metric and log panels
```

---

## Week 2 Directory Structure

```
week2/
├── docker-compose.yml          ← Full stack including Loki and Alloy
├── loki-config.yml             ← Loki server configuration
├── alloy-config.alloy          ← Grafana Alloy pipeline configuration
├── loki-rules/
│   └── log_alerts.yml          ← Loki alerting rules
├── loki-alloy-week2-day1-reference.md
├── loki-alloy-week2-day2-reference.md
└── loki-alloy-week2-day3-reference.md
```

---

## Setup

### Bring Down Week 1 Stack

Week 1 and Week 2 use the same ports. Bring down Week 1 before starting Week 2:

```bash
cd ~/grafana-lab/week1
docker compose down

cd ~/grafana-lab/week2
docker compose up -d
```

### Verify All Containers Running

```bash
docker compose ps
```

Five containers should be running — prometheus, grafana, node-exporter, loki, alloy.

### Check Loki Is Ready

```
http://localhost:3100/ready
```

Should return `ready`.

### Check Alloy Pipeline

```
http://localhost:12345
```

Alloy web UI — all four pipeline components should show healthy status.

---

## Configuration Files

### docker-compose.yml

Five services — Prometheus, Grafana, and Node Exporter carried forward from Week 1 via relative path references, plus Loki and Alloy:

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
      - ./loki-rules:/loki/rules/fake
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

---

### loki-config.yml

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
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /loki/rules-temp
  enable_api: true
```

> **Note on ruler alertmanager_url:** `http://localhost:9093` will produce a connection refused error because Alertmanager is not deployed in Week 2. Inside a Docker container `localhost` resolves to the container itself, not the host or other containers. When Alertmanager is deployed in Week 4 this should be changed to `http://alertmanager:9093`.

---

### alloy-config.alloy

```hcl
// Discover all Docker containers running on the host
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// Collect logs from discovered containers and forward to Loki
loki.source.docker "container_logs" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.containers.targets
  forward_to = [loki.write.local.receiver]

  relabel_rules = loki.relabel.container_labels.rules
}

// Relabel rules — extract useful labels from Docker container metadata
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

// Write logs to local Loki instance
loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

---

### loki-rules/log_alerts.yml

```yaml
groups:
  - name: log_alerts
    rules:
      - alert: HighLogErrorRate
        expr: |
          sum by (container) (
            rate({container=~".+"} |= "error" [5m])
          ) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate in logs for {{ $labels.container }}"
          description: "Log error rate is {{ $value | humanize }} errors/sec in {{ $labels.container }}"

      - alert: FatalLogEvent
        expr: |
          sum by (container) (
            count_over_time(
              {container=~".+"} |~ "fatal|panic|FATAL|PANIC" !~ "caller=metrics.go|caller=evaluator"
              [5m]
            )
          ) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Fatal event detected in {{ $labels.container }}"
          description: "A fatal or panic log event was detected in {{ $labels.container }}"
```

> **Note on FatalLogEvent exclusion pattern:** The `!~ "caller=metrics.go|caller=evaluator"` exclusion prevents the alert from matching Loki's own ruler evaluation log lines, which contain the word "panic" as part of the query string. Without this exclusion the alert self-triggers — a false positive caused by the monitoring system logging its own query expressions.

> **Note on loki-rules/fake directory:** The `fake` subdirectory is required by Loki's single-tenant mode. Loki uses `fake` as the default org_id in single-tenant deployments. Rules must be placed in a directory matching the org_id.

---

## Grafana Configuration

### Add Prometheus Data Source

Week 2 Grafana starts with no data sources — both must be added.

Connections → Data sources → Add data source → Prometheus

| Field | Value |
|---|---|
| URL | `http://prometheus:9090` |
| Scrape interval | 15s |
| HTTP method | POST |

### Add Loki Data Source

Connections → Data sources → Add data source → Loki

| Field | Value |
|---|---|
| URL | `http://loki:3100` |

---

## Verify Log Pipeline

In Grafana Explore with Loki selected, run:

```logql
{container=~".+"}
```

All five containers should return log lines. Confirm with:

```logql
sum by (container) (count_over_time({container=~".+"}[5m]))
```

All five containers should appear in the results.

---

## Verify Alerting Rules

```
http://localhost:3100/loki/api/v1/rules
```

Both rules should be listed. Check ruler evaluation logs:

```bash
docker logs loki 2>&1 | grep -i "HighLogErrorRate\|FatalLogEvent" | tail -5
```

Key fields to verify:
- `msg="evaluating rule"` — rule is being evaluated on schedule
- `total_entries=0` — expression returning no results, alert inactive
- No `total_entries=1` on FatalLogEvent — false positive eliminated

---

## Loki Diagnostic Endpoints

| Endpoint | What it shows |
|---|---|
| `http://localhost:3100/ready` | Loki health status |
| `http://localhost:3100/loki/api/v1/labels` | All indexed stream labels |
| `http://localhost:3100/loki/api/v1/label/container/values` | All values for a specific label |
| `http://localhost:3100/loki/api/v1/rules` | Loaded alerting rules |
| `http://localhost:12345` | Alloy pipeline component health |

---

## Stack Observability Dashboard

A unified dashboard combining Prometheus metrics and Loki log panels.

### Panels

| Panel | Data source | Visualization | Query |
|---|---|---|---|
| Log Ingestion Rate | Loki | Time series | `sum by (container) (rate({container=~"$container"}[5m]))` |
| Log Error Rate | Loki | Time series | `sum by (container) (rate({container=~"$container"} \|= "error" [5m]))` |
| Warnings and Errors | Loki | **Logs** | `{container=~"$container"} \|~ "warn\|error\|WARN\|ERROR"` |
| CPU Utilization | Prometheus | Time series | `instance:node_cpu_utilization:avg_rate5m` |
| Total Errors (1h) | Loki | Stat | `sum(count_over_time({container=~"$container"} \|= "error" [1h]))` |

> **Critical:** The Warnings and Errors panel must use the **Logs** visualization type — not Time series. Log stream queries return raw log lines, not numeric data. Setting this panel to Time series produces "Data is missing a number field".

### Container Variable

Dashboard settings → Variables → Add variable:

| Field | Value |
|---|---|
| Name | `container` |
| Type | Query |
| Data source | Loki |
| Query | `label_values(container)` |
| Include All option | On |
| Custom all value | `.+` |

Selecting a specific container scopes all Loki panels simultaneously. The Prometheus CPU panel is not scoped to the variable — it shows infrastructure metrics regardless of container selection.

---

## Key Concepts Covered

### Loki data model
- Logs are organized into streams — each unique label set is a separate stream
- Only labels are indexed — log line content is not indexed, only compressed and stored
- The same cardinality principles apply as Prometheus — bounded labels, no unbounded unique values as labels

### Stream labels vs structured metadata
- Stream labels are indexed and queryable in stream selectors — `{container="prometheus"}`
- Structured metadata is visible in log line detail but not indexed — cannot be used in stream selectors
- `detected_level` in this lab is structured metadata, not an indexed stream label
- Verify what is indexed: `http://localhost:3100/loki/api/v1/labels`

### LogQL fundamentals
- Stream selector `{container="prometheus"}` — index lookup, cheap
- Line filter `|= "error"` — log content scan, expensive, scales with data volume
- Always narrow stream selection before applying line filters
- `rate()` and `count_over_time()` convert log streams to numeric metrics
- LogQL field comparisons are case sensitive — `level="INFO"` not `level="info"` for Prometheus logs

### Grafana Alloy pipeline
- Component-based pipeline — discover, collect, relabel, write
- Alloy's `detect_level` attaches log level as structured metadata automatically
- Edge filtering via `stage.drop` removes noise before it reaches Loki
- Label promotion via `stage.labels` makes extracted fields into indexed stream labels

### Push vs pull
- Prometheus pulls metrics on a schedule — appropriate for current state
- Alloy pushes logs to Loki as they are generated — appropriate for events
- Logs are event-driven — polling would risk missing lines between intervals

### Loki alerting rules
- Same YAML syntax as Prometheus alerting rules
- LogQL metric expressions used as alert conditions
- Loki ruler evaluates rules and sends firing alerts to Alertmanager
- `localhost` inside a Docker container resolves to the container itself — use service names

### Alert design lessons
- Self-triggering false positives occur when the monitoring system logs its own query strings
- Always run alert expressions in Explore first — examine what they actually match
- Surgical exclusion patterns (`!~`) are preferable to broad container exclusions
- Rule hot reload works via volume-mounted files — confirmed by query hash change in ruler logs

### Operational lessons
- Loki generates the highest log volume of any container due to self-logging of ingest operations
- Loki's ~50 minute error count cycle is compaction — expected, not a fault
- The Logs visualization type is required for raw log line panels — Time series will error

---

## Next Steps (Week 3)

- Add Tempo for distributed tracing
- Instrument a Python application with OpenTelemetry
- Correlate traces with metrics and logs in Grafana
- Understand exemplars — the link between metrics and traces

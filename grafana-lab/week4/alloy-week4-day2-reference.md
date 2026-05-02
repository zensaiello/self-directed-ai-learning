# Alloy-Only Tracing + Meta-Observability — Week 4 Day 2 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand meta-observability — the platform monitoring itself
- Add LGTM component metrics endpoints as Prometheus scrape targets
- Discover correct metric names through exploration rather than assumption
- Build a 13-panel LGTM Stack Health dashboard with verified queries
- Apply production dashboard design principles

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- Real-world examples over theory
- Dashboard design principles applied throughout

---

## Table of Contents

1. [What Meta-Observability Is](#1-what-meta-observability-is)
2. [Component Metrics Endpoints](#2-component-metrics-endpoints)
3. [Adding Scrape Targets](#3-adding-scrape-targets)
4. [Metric Discovery — The Correct Approach](#4-metric-discovery--the-correct-approach)
5. [Key Metrics Per Component](#5-key-metrics-per-component)
6. [LGTM Stack Health Dashboard](#6-lgtm-stack-health-dashboard)
7. [Dashboard Design Principles](#7-dashboard-design-principles)
8. [Questions and Answers](#8-questions-and-answers)
9. [Advanced Topics](#9-advanced-topics)
10. [Reference Material](#10-reference-material)

---

## 1. What Meta-Observability Is

Every component in the LGTM stack exposes its own Prometheus metrics. Meta-observability uses those metrics to monitor the health of the observability platform itself — the same tools used to monitor applications monitor the monitoring infrastructure.

**Why it matters operationally:** If your log pipeline goes down you lose the ability to investigate incidents. Knowing Loki is healthy before an incident occurs — not discovering it is broken during one — is a real operational requirement.

**Why it matters for customer demonstrations:** Showing a customer that the observability platform monitors itself builds confidence in the platform. It also gives them a concrete template — the same patterns used to instrument the LGTM stack apply directly to their own modular applications.

**The meta-observability pattern:**
```
LGTM components (Loki, Tempo, Alloy, Prometheus)
    ↓ expose /metrics endpoints
Prometheus scrapes all component endpoints
    ↓
Grafana dashboard showing platform health
    ↓
Alerts when pipeline degrades
```

---

## 2. Component Metrics Endpoints

Every LGTM stack component exposes Prometheus-format metrics:

| Component | Metrics endpoint | Key signal categories |
|---|---|---|
| Prometheus | `http://localhost:9090/metrics` | TSDB health, scrape duration, rule evaluation |
| Loki | `http://localhost:3100/metrics` | Ingest rate, chunk compression, WAL health |
| Tempo | `http://localhost:3200/metrics` | Span ingest rate, push duration, ingester health |
| Alloy | `http://localhost:12345/metrics` | Component health, pipeline throughput, memory usage |

All endpoints return standard Prometheus exposition format with `# HELP` and `# TYPE` lines.

---

## 3. Adding Scrape Targets

Updated `~/grafana-lab/week1/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "recording_rules.yml"
  - "alerting_rules.yml"

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['prometheus:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'order-api'
    static_configs:
      - targets: ['order-api:5000']

  - job_name: 'loki'
    static_configs:
      - targets: ['loki:3100']

  - job_name: 'tempo'
    static_configs:
      - targets: ['tempo:3200']

  - job_name: 'alloy'
    static_configs:
      - targets: ['alloy:12345']
```

Hot reload:
```bash
curl -X POST http://localhost:9090/-/reload
```

Verify all targets UP: `http://localhost:9090/targets`

---

## 4. Metric Discovery — The Correct Approach

**Never assume metric names.** Metric names change between versions. Always discover what is actually being scraped before building panels.

### Discovery Query Pattern

```promql
# All metrics from a specific job
{job="loki"}

# Find metrics matching a pattern
{__name__=~"loki_ingester.*", job="loki"}

# Find metrics matching a pattern for Alloy
{__name__=~"alloy.*", job="alloy"}

# Find otelcol pipeline metrics from Alloy
{__name__=~"otelcol.*", job="alloy"}

# Find Tempo distributor metrics
{__name__=~"tempo_distributor.*", job="tempo"}
```

### Metrics That Did Not Exist

| Expected metric | Reality |
|---|---|
| `loki_ingester_active_streams` | Does not exist — use `loki_ingester_memory_streams` |
| `loki_query_frontend_query_range_duration_seconds_bucket` | Not populated in single-node Loki — query frontend not active |
| `avg(loki_ingester_chunk_compression_ratio)` | It is a histogram not a gauge — use `histogram_quantile()` |
| `loki_process_read_lines_total` | Promtail metric — does not exist in Alloy |

**The lesson:** The diagnostic pattern of running `{__name__=~"component.*", job="component"}` and reading what actually exists is more reliable than any documentation or example that may reference an older version.

---

## 5. Key Metrics Per Component

### Loki — Confirmed Available Metrics

```promql
# Log ingestion rate
sum(rate(loki_distributor_lines_received_total[5m]))

# Active streams in memory
sum(loki_ingester_memory_streams)

# Chunk compression ratio (histogram)
histogram_quantile(0.50,
  sum by (le) (
    rate(loki_ingester_chunk_compression_ratio_bucket[5m])
  )
)

# Push request duration p99
histogram_quantile(0.99,
  sum by (le) (
    rate(loki_ingester_client_request_duration_seconds_bucket{
      job="loki",
      operation="/logproto.Pusher/Push"
    }[5m])
  )
)

# Chunk flush failures — should always be 0
sum(loki_ingester_chunks_flush_failures_total)

# WAL disk usage percent
loki_ingester_wal_disk_usage_percent
```

**Lab values observed:**
- Active streams: 5 (one per container)
- WAL disk usage: 0.17%
- Duplicate entries discarded: 56 — normal, caused by Alloy retry behavior

### Alloy — Confirmed Available Metrics

```promql
# Healthy component count — should equal total components
alloy_component_controller_running_components{job="alloy", health_type="healthy"}

# Component evaluation duration p99
histogram_quantile(0.99,
  sum by (le) (
    rate(alloy_component_evaluation_seconds_bucket{job="alloy"}[5m])
  )
)

# Config load failures — should always be 0
alloy_config_load_failures_total

# Process memory
alloy_resources_process_resident_memory_bytes

# Spans received by OTLP receiver
rate(otelcol_receiver_accepted_spans_total{job="alloy"}[5m])

# Spans exported to Tempo
rate(otelcol_exporter_sent_spans_total{job="alloy"}[5m])

# Failed spans — should always be 0
rate(otelcol_receiver_failed_spans_total{job="alloy"}[5m])

# Export queue fill ratio
otelcol_exporter_queue_size{job="alloy", data_type="traces"}
/
otelcol_exporter_queue_capacity{job="alloy", data_type="traces"}
```

**Lab values observed:**
- Healthy components: 7/7
- Memory: ~273MB
- Spans received = spans exported: 3,277,821 — 100% success rate
- Failed spans: 0
- Queue fill: 0/1000

### Tempo — Confirmed Available Metrics

```promql
# Span ingestion rate
rate(tempo_distributor_spans_received_total{job="tempo"}[5m])

# Push duration p99 from Alloy
histogram_quantile(0.99,
  sum by (le) (
    rate(tempo_distributor_push_duration_seconds_bucket{job="tempo"}[5m])
  )
)

# Bytes received total
tempo_distributor_bytes_received_total{job="tempo"}

# Ingester clients connected
tempo_distributor_ingester_clients{job="tempo"}
```

**Lab values observed:**
- Push duration p99: 0.005s (5ms) — extremely fast
- Spans received: 3,279,507
- Ingester clients: 1 (single-node)
- Bytes received: ~707MB total

### Pipeline Health Cross-Check

Comparing Alloy and Tempo span counts confirms end-to-end delivery:

| Metric | Value | Notes |
|---|---|---|
| `otelcol_receiver_accepted_spans_total` (Alloy) | 3,277,821 | Spans received from order-api |
| `tempo_distributor_spans_received_total` (Tempo) | 3,279,507 | Spans received by Tempo |
| Difference | ~1,686 | Spans in batch processor at query time |
| Failed spans | 0 | 100% delivery rate |

---

## 6. LGTM Stack Health Dashboard

### Dashboard: LGTM Stack Health

13 panels covering platform health and application performance.

---

### Panel 1 — Component Health (Current)

```promql
up{job=~"loki|tempo|alloy|prometheus|node-exporter|order-api"}
```

- Visualization: **Stat**
- Color scheme: Fixed — Red base, Green at threshold 1
- Display name: `${__field.labels.job}`
- Shows: Current up/down state per component — 1 = up, 0 = down
- Lab result: All 6 components showing 1 (green)

---

### Panel 2 — Component Availability % (Period)

```promql
avg_over_time(up{job=~"loki|tempo|alloy|prometheus|node-exporter|order-api"}[$__range]) * 100
```

- Visualization: **Stat**
- Unit: Percent (0-100)
- Thresholds: Base red, 99 yellow, 99.9 green
- Display name: `${__field.labels.job}`
- Shows: Uptime percentage over dashboard time range — SLO reporting
- `$__range` resolves to current dashboard time window automatically

> **Design note:** Use `avg_over_time` for availability/uptime — the average is the correct measure. Use `max_over_time` for queue fill and error rates — worst case is more operationally meaningful than average.

---

### Panel 3 — Loki Log Ingestion Rate

```promql
sum(rate(loki_distributor_lines_received_total[5m]))
```

- Visualization: **Time series**
- Color: Orange (`"fixedColor": "orange"`)
- Min: 0, Legend: Hidden
- Lab result: ~4.21 lines/sec

---

### Panel 4 — Alloy Spans Received Rate

```promql
rate(otelcol_receiver_accepted_spans_total{job="alloy"}[5m])
```

- Visualization: **Time series**
- Color: Blue (`"fixedColor": "blue"`)
- Min: 0, Legend: Hidden
- Lab result: ~21.1 spans/sec

---

### Panel 5 — Tempo Spans Received Rate

```promql
rate(tempo_distributor_spans_received_total{job="tempo"}[5m])
```

- Visualization: **Time series**
- Color: Purple (`"fixedColor": "purple"`)
- Min: 0, Legend: Hidden
- Lab result: ~21.1 spans/sec — matches Alloy, confirming 100% delivery

---

### Panel 6 — Alloy Export Failures

```promql
rate(otelcol_receiver_failed_spans_total{job="alloy"}[5m])
```

- Visualization: **Time series**
- Color: Red (`"fixedColor": "red"`)
- Min: 0, Legend: Hidden
- Should always flatline at 0 — any non-zero value indicates pipeline failure
- Lab result: 0

---

### Panel 7 — Alloy Healthy Components

```promql
alloy_component_controller_running_components{job="alloy", health_type="healthy"}
```

- Visualization: **Stat**
- Thresholds: Base red, 7 green
- Display name: `components`
- Lab result: 7

---

### Panel 8 — Tempo Push Duration p99

```promql
histogram_quantile(0.99,
  sum by (le) (
    rate(tempo_distributor_push_duration_seconds_bucket{job="tempo"}[5m])
  )
)
```

- Visualization: **Time series**
- Color: Purple
- Min: 0, Legend: Hidden
- Lab result: 0.005s (5ms) — extremely healthy

---

### Panel 9 — Alloy Queue Max Fill (Period)

```promql
max_over_time(otelcol_exporter_queue_size{job="alloy", data_type="traces"}[$__range])
/
max_over_time(otelcol_exporter_queue_capacity{job="alloy", data_type="traces"}[$__range])
```

- Visualization: **Stat**
- Unit: Percent (0.0-1.0)
- Thresholds: Base green, 0.5 yellow, 0.8 red
- Display name: `queue fill`
- Shows worst-case queue pressure during the dashboard time range
- Lab result: 0 — no backpressure observed

> **Note:** `max_over_time` cannot wrap an expression — each metric must be queried separately and divided afterward. Division of two instant vectors is valid.

---

### Panel 10 — Alloy Memory Usage

```promql
alloy_resources_process_resident_memory_bytes{job="alloy"}
```

- Visualization: **Stat**
- Unit: bytes (SI) — auto-formats as MB/GB
- Thresholds: Base green, 500000000 (500MB) yellow, 1000000000 (1GB) red
- Display name: `memory`
- Lab result: 273MB

---

### Panel 11 — Loki Active Streams

```promql
sum(loki_ingester_memory_streams)
```

- Visualization: **Stat**
- Thresholds: Base green, 50 yellow, 100 red
- Display name: `streams`
- Lab result: 5 (one per container)

---

### Panel 12 — order-api Request Rate by Endpoint

```promql
sum by (endpoint) (
  rate(flask_http_request_duration_seconds_count{job="order-api"}[5m])
)
```

- Visualization: **Time series**
- Min: 0, Legend: Visible
- Legend field: `{{endpoint}}`
- Lab result: Three lines — checkout, list_orders, get_order

> **Note:** Use `flask_http_request_duration_seconds_count` not `flask_http_request_total` for per-endpoint breakdown. `flask_http_request_total` only has `method` and `status` labels — no `endpoint` label. The duration histogram metric carries the `endpoint` label from `group_by='endpoint'` configuration.

---

### Panel 13 — order-api p99 Latency by Endpoint

```promql
histogram_quantile(0.99,
  sum by (le, endpoint) (
    rate(flask_http_request_duration_seconds_bucket{job="order-api"}[5m])
  )
)
```

- Visualization: **Time series**
- Min: 0, Legend: Visible
- Legend field: `{{endpoint}}`
- Lab result: checkout p99 higher than list_orders — correct, checkout has 6 spans vs 1

---

## 7. Dashboard Design Principles

Principles applied throughout the dashboard build:

**Zero baseline on time series panels**
Set `min: 0` on all rate and duration panels. Auto-scaling makes small fluctuations look dramatic. A rate varying between 4.1 and 4.3 looks like noise on a zero-based graph — correct. On auto-scaled it looks like a significant swing — misleading.

**Exception:** When values are always large and variance matters (e.g. CPU never below 60%), auto-scaling can be more useful.

**Hide legends on single-series panels**
The panel title carries the context. Legend visibility off keeps panels clean.

**Keep legends on multi-series panels**
Panels showing multiple endpoints or components need the legend to distinguish lines.

**Color coding by signal type**
| Signal | Color |
|---|---|
| Loki | Orange |
| Alloy | Blue |
| Tempo | Purple |
| Errors/failures | Red |
| Application metrics | Green (default) |

**Setting color in JSON**
The UI sometimes leaves `"mode": "palette-classic"` in `fieldConfig.defaults.color` which overrides the fixed color setting. Fix directly in panel JSON:
```json
"color": {
  "mode": "fixed",
  "fixedColor": "purple"
}
```

**avg_over_time vs max_over_time**
- `avg_over_time` — use for availability and uptime. Average is the correct SLO measure.
- `max_over_time` — use for queue fill and error rates. Worst case is more operationally meaningful.

**Stat panels for current state**
Point-in-time health indicators — component count, memory, active streams.

**Time series panels for trends**
Rate metrics, latency, throughput — anything where the shape over time matters.

**Two-panel availability pattern**
| Panel | Query | Answers |
|---|---|---|
| Current status | `up{...}` | Is it broken right now? |
| Availability % | `avg_over_time(up{...}[$__range]) * 100` | How reliable has it been? |

---

## 8. Questions and Answers

### Q1: Why did some expected metric names not exist?

**Summary:** Metric names change between component versions. `loki_ingester_active_streams` was renamed to `loki_ingester_memory_streams`. `loki_process_read_lines_total` is a Promtail metric that does not exist in Alloy. Always discover actual metric names using the pattern `{__name__=~"component.*", job="component"}` before building panels. Never assume names from documentation or examples that may reference older versions.

---

### Q2: Why use flask_http_request_duration_seconds_count instead of flask_http_request_total for per-endpoint breakdown?

**Summary:** `flask_http_request_total` only carries `method` and `status` labels — no `endpoint` label. The `endpoint` label from `group_by='endpoint'` is only present on the histogram metrics (`flask_http_request_duration_seconds_*`). Using `_count` from the histogram gives the same request count with the endpoint dimension available.

---

### Q3: Why does max_over_time not work wrapping a division expression?

**Summary:** `max_over_time` is a range function that operates on a single metric selector — it cannot wrap an arithmetic expression. The fix is to apply `max_over_time` to each metric individually and divide the resulting instant vectors:

```promql
# Wrong — range functions cannot wrap expressions
max_over_time((metric_a / metric_b)[$__range])

# Correct — apply to each metric separately
max_over_time(metric_a[$__range]) / max_over_time(metric_b[$__range])
```

---

### Q4: How do you fix a color setting that does not apply in Grafana?

**Summary:** The UI sometimes writes the fixed color to the override section while leaving `"mode": "palette-classic"` in `fieldConfig.defaults.color` — and defaults override overrides for color mode. Fix directly in panel JSON by changing `fieldConfig.defaults.color` to `{"mode": "fixed", "fixedColor": "purple"}`. The JSON editor is more reliable than the UI for color settings.

---

## 9. Advanced Topics

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — native histograms | Significant cardinality source. Native histograms change storage model. | Week 1 Day 2 |
| **Recording rules** — advanced design at scale | Rule evaluation performance and dependencies. | Week 1 Day 2 |
| **SNMP exporter** — Counter32 vs Counter64 | Migration gap from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing | Full deployment, routing trees, inhibition. Week 5 topic. | Week 1 Day 3 |
| **Loki distributed mode** | Single-node has ingest and query limits. | Week 2 Day 1 |
| **Tempo v2.10 Kafka ingest architecture** | New default ingest for high-volume production. | Week 3 Day 1 |
| **Tail sampling** | Keep errors and slow traces, drop normal traffic. | Week 3 Day 2 |
| **Tempo metrics generator** | Derives RED metrics from traces. | Week 3 Day 1 |
| **Exemplars** — metrics to traces link | Direct link from Prometheus metric to specific trace ID. | Week 3 Day 3 |
| **TraceQL advanced patterns** | Service graph queries, span set operations. | Week 3 Day 3 |
| **OpenTelemetry deep dive** | OTel as its own topic. Week 6. | Week 3 Day 2 |
| **Kubernetes + LGTM on K8s** | CKA track + deploying full stack. Week 7. | Lab planning |
| **Grafana dashboard variables for stack health** | Making the LGTM Stack Health dashboard dynamic — select which component to drill into. | Week 4 Day 2 |
| **Alert rules for pipeline health** | Alerting when Alloy export failures > 0, queue fill > 80%, component count drops. Week 5 topic. | Week 4 Day 2 |
| **Status history visualization** | Shows up/down state over time as a color band — more informative than current-value Stat panels for availability tracking. | Week 4 Day 2 |

---

## 10. Reference Material

### Meta-Observability

| Resource | URL | Notes |
|---|---|---|
| Alloy self-monitoring | https://grafana.com/docs/alloy/latest/monitor/ | Alloy metrics and pipeline observability |
| Grafana dashboards for LGTM | https://grafana.com/grafana/dashboards/ | Community dashboards — import by ID |
| Loki operational dashboard | https://grafana.com/grafana/dashboards/14055 | Official Loki monitoring dashboard |
| Tempo operational dashboard | https://grafana.com/grafana/dashboards/16310 | Official Tempo monitoring dashboard |

### Prometheus Functions Used

| Resource | URL | Notes |
|---|---|---|
| avg_over_time | https://prometheus.io/docs/prometheus/latest/querying/functions/#aggregation_over_time | Time-range aggregation functions |
| max_over_time | https://prometheus.io/docs/prometheus/latest/querying/functions/#aggregation_over_time | Worst-case value over time range |
| histogram_quantile | https://prometheus.io/docs/prometheus/latest/querying/functions/#histogram_quantile | Quantile calculation from histograms |

### Grafana Dashboard Design

| Resource | URL | Notes |
|---|---|---|
| Grafana panel JSON model | https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/view-dashboard-json-model/ | Direct JSON editing reference |
| Grafana visualization types | https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/ | All panel types including Status history |
| Grafana $__range variable | https://grafana.com/docs/grafana/latest/dashboards/variables/add-template-variables/#__range | Built-in time range variable |

---

*Week 4 Day 2 complete. Day 3: Alloy pipeline traces — Alloy emitting its own OTel traces for internal pipeline operations, visible in Tempo alongside Flask app traces.*

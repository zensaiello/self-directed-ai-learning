# Tempo + OpenTelemetry — Week 3 Day 3 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand TraceQL — Tempo's query language for searching and filtering traces
- Add Prometheus metrics to the Flask application for three-signal coverage
- Understand and fix a real cardinality anti-pattern in application instrumentation
- Use Grafana Explore split view for three-pillar correlation
- Understand Tempo attribute cardinality vs Prometheus/Loki label cardinality
- Understand Tempo trace retention and its operational implications

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- Lab deviations from production best practice noted explicitly
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Lab Architecture Note

The current lab runs both Grafana Alloy and the OTel Collector simultaneously. This is not the standard production Grafana Labs pattern. Production best practice is Alloy as the single collector for all telemetry signals including traces.

**Follow-on labs planned:**
- Alloy-only tracing lab — rebuilds the trace pipeline using only Alloy, includes meta-observability (Alloy self-metrics and pipeline traces)
- OpenTelemetry deep dive track — OTel as its own topic alongside the Kubernetes track

---

## Table of Contents

1. [TraceQL](#1-traceql)
2. [Adding Prometheus Metrics to the Flask App](#2-adding-prometheus-metrics-to-the-flask-app)
3. [Three-Pillar Correlation](#3-three-pillar-correlation)
4. [Tempo Retention](#4-tempo-retention)
5. [Tempo Attribute Cardinality](#5-tempo-attribute-cardinality)
6. [Stack Self-Observability](#6-stack-self-observability)
7. [Questions and Answers](#7-questions-and-answers)
8. [Advanced Topics](#8-advanced-topics)
9. [Reference Material](#9-reference-material)

---

## 1. TraceQL

TraceQL is to Tempo what PromQL is to Prometheus and LogQL is to Loki. It searches for traces based on span attributes, duration, status, and service name.

---

### Basic Syntax

```
{attribute condition}
```

The simplest query — all traces from order-api:

```
{resource.service.name="order-api"}
```

---

### Span Attribute Types

**Resource attributes** — describe the service that produced the span. Set at the TracerProvider level via the Resource object. Prefixed with `resource.`:

```
{resource.service.name="order-api"}
{resource.deployment.environment="lab"}
```

**Span attributes** — describe the specific operation. Set via `span.set_attribute()`. Prefixed with `span.`:

```
{span.db.system="postgresql"}
{span.peer.service="tax-service"}
{span.checkout.success=true}
{span.slow_call=true}
```

**Intrinsic attributes** — built-in span properties, no prefix required:

```
{name="checkout"}
{status=error}
{duration>500ms}
```

---

### Filtering by Duration

```
# All slow traces from order-api
{resource.service.name="order-api" && duration>500ms}

# Slow checkout requests specifically
{name="POST /orders/checkout" && duration>500ms}

# Traces where tax service span took over 200ms
{span.peer.service="tax-service" && duration>200ms}
```

---

### Filtering by Span Attributes

```
# Traces that triggered the slow tax service call
{span.slow_call=true}

# Traces involving the tax service
{span.peer.service="tax-service"}

# Traces with database operations
{span.db.system="postgresql"}
```

---

### Filtering by Status

```
# Traces containing errors
{status=error}

# Errors on a specific span
{name="external.tax-service" && status=error}
```

---

### TraceQL Pipeline Syntax

The `|` operator chains trace-level aggregations after the span selector:

```
{resource.service.name="order-api"} | avg(duration) > 100ms
```

**Span-level filter `{}`** — evaluates conditions per span. Finds traces containing at least one span matching the condition.

**Trace-level pipeline `|`** — aggregates across all spans in a trace. Evaluates the aggregated result.

```
# Span-level — any span over 500ms
{resource.service.name="order-api" && duration>500ms}

# Trace-level — average span duration over 100ms
{resource.service.name="order-api"} | avg(duration) > 100ms

# Trace-level — traces with more than 5 spans
{resource.service.name="order-api"} | count() > 5

# Trace-level — sum of all span durations over 2 seconds
{resource.service.name="order-api"} | sum(duration) > 2s
```

**When to use each:**
- Span-level for root cause analysis — "find traces where the tax service was slow"
- Trace-level for characterizing overall behavior — "find broadly slow traces across all operations"

---

### Tempo Search Table — UI Limitations

The Tempo search table shows a **flattened preview** of spans per trace — not the full hierarchy. Rendering all spans for every trace in a results list would be expensive. The table is for triage and selection.

To see full span counts without manual expansion:

```
# Filter to complex traces (more than 5 spans)
{resource.service.name="order-api"} | count() > 5
```

For aggregate span analysis across a result set, use the Tempo HTTP API or a Grafana dashboard table panel. The search UI does not surface aggregate span counts across results — a UI limitation worth knowing.

---

### Lab TraceQL Results

| Query | Results | Notes |
|---|---|---|
| `{resource.service.name="order-api"}` | All traces | Full service coverage |
| `{resource.service.name="order-api" && duration>500ms}` | Slow traces | Tax service slow calls visible |
| `{span.slow_call=true}` | ~4 per 20 requests | ~20% — higher than 10% probability due to small sample variance |
| `{span.peer.service="tax-service" && duration>200ms}` | 12 across two bursts | Isolates deliberate slow path from pricing service variance |

---

## 2. Adding Prometheus Metrics to the Flask App

### The Cardinality Problem — path Label

`prometheus-flask-exporter` uses the raw URL path as a label by default:

```
flask_http_request_duration_seconds_bucket{path="/orders/1", ...}
flask_http_request_duration_seconds_bucket{path="/orders/2", ...}
flask_http_request_duration_seconds_bucket{path="/orders/47291", ...}
```

Each unique order ID creates a new histogram series with 15 bucket entries. In production with millions of orders this causes cardinality explosion — a new time series per unique path value.

**This is the same anti-pattern as Prometheus label design** — unbounded unique values as labels. The fix is to group by the Flask route template instead of the raw path.

---

### The Fix — group_by='endpoint'

```python
metrics = PrometheusMetrics(app, group_by='endpoint')
```

Label values become Flask endpoint function names — `checkout`, `list_orders`, `get_order` — regardless of the specific URL path requested. Bounded by the number of routes, not by URL parameter values.

**Before fix:**
```
{path="/orders/1", method="GET", status="200"}
{path="/orders/2", method="GET", status="200"}
{path="/orders/3", method="GET", status="200"}
```

**After fix:**
```
{endpoint="get_order", method="GET", status="200"}
```

---

### Updated requirements.txt

```
flask==3.0.3
opentelemetry-api==1.25.0
opentelemetry-sdk==1.25.0
opentelemetry-instrumentation-flask==0.46b0
opentelemetry-exporter-otlp-proto-http==1.25.0
requests==2.32.3
prometheus-flask-exporter==0.23.1
```

### Updated app.py — PrometheusMetrics Addition

```python
from prometheus_flask_exporter import PrometheusMetrics

# After Flask app creation
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
metrics = PrometheusMetrics(app, group_by='endpoint')
metrics.info("order_api_info", "Order API information", version="1.0.0")
```

### Rebuild After Changes

```bash
docker compose up -d --build order-api
```

---

### Metrics Available at /metrics

| Metric | Type | What it measures |
|---|---|---|
| `flask_http_request_duration_seconds` | Histogram | Request latency by endpoint, method, status |
| `flask_http_request_total` | Counter | Request count by method, status |
| `flask_http_request_exceptions_total` | Counter | Unhandled exceptions |
| `order_api_info` | Gauge | Service version metadata |
| `python_gc_*` | Counter | Python garbage collection |
| `process_*` | Gauge | Process memory, CPU, file descriptors |

---

### Lab Histogram Results — Performance Characteristics

**checkout (30 requests):**
- Most complete between 250ms–500ms
- Some requests up to 2.5s (tax service slow calls)
- Average: 523ms (`sum 15.71s / 30`)

**list_orders (20 requests):**
- All complete within 75ms
- Average: 42ms — fast, single DB query, no external calls

**get_order (20 requests):**
- Range 75ms–750ms
- Average: 178ms — moderate variance from pricing service call

The histogram distribution alone reveals the application structure — `list_orders` is simple and fast, `get_order` has one external dependency, `checkout` has multiple dependencies with a slow tail.

---

### Adding order-api as a Prometheus Scrape Target

Update `~/grafana-lab/week1/prometheus.yml`:

```yaml
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
```

Hot reload:
```bash
curl -X POST http://localhost:9090/-/reload
```

Verify: `http://localhost:9090/targets` — order-api should show State: UP.

---

### PromQL for Flask Metrics

```promql
# p99 request latency by endpoint
histogram_quantile(0.99,
  sum by (le, endpoint) (
    rate(flask_http_request_duration_seconds_bucket{job="order-api"}[5m])
  )
)

# Request rate by endpoint
sum by (endpoint) (rate(flask_http_request_total{job="order-api"}[5m]))

# Error rate
rate(flask_http_request_total{job="order-api", status=~"5.."}[5m])
```

---

## 3. Three-Pillar Correlation

### The Correlation Workflow

```
1. Alert fires — p99 checkout latency > 800ms
        ↓
2. Prometheus (left panel) — p99 latency query
   Observation: latency spike, started 10 minutes ago
        ↓
3. Loki (right panel) — application log query
   Query: {container="order-api"} !~ "GET /metrics"
   Observation: no error lines — not an application error
        ↓
4. Tempo — slow trace query
   Query: {resource.service.name="order-api" && duration>500ms}
   Observation: slow traces all show external.tax-service or
                external.pricing-service as longest span
        ↓
5. Click into slow trace — waterfall view
   Observation: specific service call duration identified
        ↓
6. Finding: external dependency is bottleneck, not application code
   Action: investigate downstream service health
```

**Metrics detect. Logs rule out. Traces identify.**

---

### Split View Configuration

Left panel — Prometheus:
```promql
histogram_quantile(0.99,
  sum by (le) (
    rate(flask_http_request_duration_seconds_bucket{job="order-api"}[5m])
  )
)
```

Right panel — Loki:
```logql
{container="order-api"} !~ "GET /metrics"
```

The `!~ "GET /metrics"` exclusion removes Prometheus scrape noise from the log view — the same edge filtering principle from Week 2 applied at query time.

---

### Why the p99 Appears Flat in the Lab

The histogram quantile appears as a constant value (~2.05s) when traffic is generated in bursts and then stops. The rate settles and the p99 stabilizes at the recent high-water mark.

In production with continuous traffic the line moves — latency spikes when slow calls trigger, dropping back when they resolve. To see movement in the lab, run a traffic burst while watching the graph:

```bash
for i in {1..10}; do curl -s -X POST http://localhost:5000/orders/checkout > /dev/null; done
```

---

### Real-World vs Lab Correlation Value

**In the lab:** Value is limited because you know exactly what the application does, there are no surprises, and traffic patterns are artificial.

**In production:** Value becomes real during incidents — an alert fires, you do not know why, the split view lets you rule out or confirm causes without switching tools. The Loki panel confirms whether errors are appearing at the same time as the metric spike. The Tempo panel shows which specific operation is slow.

---

### Bottleneck Variability — A Realistic Finding

TraceQL identified both `external.tax-service` and `external.pricing-service` as bottlenecks across different traces. This is correct and realistic — in production bottlenecks vary across requests:

- `tax-service` has a deliberate 10% slow path (500ms delay)
- `pricing-service` has natural latency variance (20-80ms range)
- On any given request either could be the longest span

This is why trace data across many requests is more valuable than a single trace — the distribution of bottlenecks tells you where to focus optimization effort.

---

## 4. Tempo Retention

### Lab Configuration

```yaml
compactor:
  compaction:
    block_retention: 24h
```

Initially set to **1 hour** — traces expired before Day 3 queries could run. Extended to **24 hours** for the lab.

### Production Retention Guidelines

| Environment | Typical retention | Notes |
|---|---|---|
| Development | 1-24 hours | Low value in keeping old dev traces |
| Staging | 3-7 days | Enough for debugging release cycles |
| Production | 7-30 days | Standard operational window |
| Compliance | 90+ days | Regulated industries |

**Tempo default if not configured:** 336 hours (14 days)

### Operational Lesson

Trace retention must be set to match your investigation window. If you receive an alert about a slow request from 2 hours ago and your retention is 1 hour, the trace is gone. Retention configuration is an operational decision, not just a storage cost decision.

---

## 5. Tempo Attribute Cardinality

### Tempo vs Prometheus vs Loki

| | Prometheus | Loki | Tempo |
|---|---|---|---|
| Indexed unit | Label set | Stream label set | Tag index |
| Cardinality failure mode | Memory exhaustion from series count | Memory exhaustion from stream count | Query performance degradation |
| High cardinality tolerance | Low | Low | Higher |
| Unique IDs as labels/attributes | Never — series explosion | Never — stream explosion | Acceptable — but query performance degrades |

### Why Tempo Is More Forgiving

Prometheus and Loki index their label sets — cardinality directly drives memory usage. Each unique label combination is a new time series or stream.

Tempo stores traces as blobs and builds a tag index for searching. High-cardinality span attributes like request IDs or user IDs do not create series explosion — the trace is stored once. The tag index grows with unique values but the failure mode is slow search queries, not memory exhaustion.

### Where Cardinality Still Matters in Tempo

**Resource attributes** — `service.name`, `deployment.environment`, `service.version`. Used heavily in search and should be bounded.

**TraceQL on high-cardinality attributes** — querying `{span.user.id="12345"}` against millions of traces with unique user IDs requires scanning a large index. Query will be slow.

**Tempo metrics generator** — derives Prometheus metrics from trace data. These derived metrics ARE subject to full Prometheus cardinality constraints. If you generate metrics from high-cardinality span attributes the resulting series count can explode. This is the most common real-world Tempo cardinality trap.

### Practical Guidance

| Attribute type | Cardinality tolerance | Reason |
|---|---|---|
| Span attributes (request ID, user ID, order ID) | Higher — acceptable | Trace stored once, index grows but does not explode |
| Resource attributes (service.name, environment) | Keep bounded | Drive search performance and metrics generation |
| Metrics generator dimensions | Must be bounded | Full Prometheus cardinality constraints apply |

---

## 6. Stack Self-Observability

Every LGTM stack component exposes its own telemetry — the platform is observable using the same tools used to observe applications.

| Component | Metrics endpoint | Key signals |
|---|---|---|
| Prometheus | `http://localhost:9090/metrics` | TSDB health, scrape duration, rule evaluation |
| Loki | `http://localhost:3100/metrics` | Ingest rate, query duration, ingester memory |
| Grafana Alloy | `http://localhost:12345/metrics` | Pipeline component health, throughput, export success/failure |
| Tempo | `http://localhost:3200/metrics` | Trace ingest rate, block write duration, query latency |
| OTel Collector | `http://localhost:8888/metrics` | Pipeline throughput, dropped spans, export failures |

**Alloy additional self-observability:**
- Built-in UI at `http://localhost:12345` — component health status
- Alloy can emit its own traces via OTel for internal pipeline operations — if a pipeline component is slow the bottleneck is visible in the trace waterfall

**Meta-observability pattern:**
```
Alloy pipeline
    ↓ metrics about pipeline health
Prometheus (scraping Alloy's /metrics)
    ↓
Grafana dashboard showing pipeline health
    ↓
Alerts when pipeline degrades
```

**Planned follow-on lab:** Alloy-only tracing with meta-observability — Alloy self-metrics scraped by Prometheus, Alloy pipeline traces, and Flask app traces all flowing through a single Alloy collector. A clean demonstration of the platform monitoring itself.

Community-maintained dashboards for monitoring the LGTM stack are available on Grafana.com — importable by dashboard ID. These are standard practice in production Grafana deployments.

---

## 7. Questions and Answers

### Q1: Why is the TraceQL pipeline operator | outside the curly braces?

**Summary:** The `{}` selector filters at the span level — finding traces containing spans that match the condition. The `|` pipeline operator applies trace-level aggregations across all spans in a matching trace. They operate at different levels. `{duration>500ms}` finds traces with any span over 500ms. `{} | avg(duration) > 100ms` finds traces where the average across all spans exceeds 100ms. Both are valid but answer different questions.

---

### Q2: Doesn't the path label in prometheus-flask-exporter cause cardinality problems?

**Summary:** Yes — confirmed and fixed in the lab. The default `path` label uses the raw URL path, creating one histogram series per unique URL. For endpoints with path parameters like `/orders/<id>` this creates unbounded cardinality — one series per unique order ID. Fix with `group_by='endpoint'` which uses the Flask route function name instead. Bounded by the number of routes, not URL parameter values.

This is the same cardinality anti-pattern as Prometheus label design — the consequence is identical: memory exhaustion and series explosion. The fix must be applied before the application reaches production.

---

### Q3: Why does the p99 histogram appear flat in the lab?

**Summary:** Traffic was generated in bursts and stopped. With no new requests the rate settles and the p99 stabilizes. In production with continuous traffic the line moves with application behavior. To see movement in the lab, run a traffic burst while watching the graph. The metric is working correctly — flat just means stable recent latency, not a broken query.

---

### Q4: Are Tempo attributes subject to cardinality concerns like Prometheus labels?

**Summary:** Yes, but the failure mode is different. Prometheus and Loki cardinality causes memory exhaustion — each unique label combination is a new time series or stream. Tempo cardinality causes query performance degradation — the tag index grows but traces are stored as blobs, not per unique attribute value. High-cardinality span attributes are tolerable in Tempo. The important exception is the metrics generator — derived trace metrics are full Prometheus metrics and subject to the same cardinality constraints. Keep metrics generator dimensions bounded.

---

### Q5: What is the correct Tempo trace retention for production?

**Summary:** Depends on operational requirements. Development: 1-24 hours. Staging: 3-7 days. Production: 7-30 days. Compliance: 90+ days. Tempo default if unconfigured: 336 hours (14 days). The lab was initially set to 1 hour — too short for investigation across a Day 3 session. Extended to 24 hours. Retention must match the investigation window — if an alert fires about a trace from 2 hours ago and retention is 1 hour, the trace is gone.

---

## 8. Advanced Topics

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — native histograms | Significant cardinality source. Native histograms change storage model. | Week 1 Day 2 |
| **Recording rules** — advanced design at scale | Rule evaluation performance and dependencies. | Week 1 Day 2 |
| **SNMP exporter** — Counter32 vs Counter64 | Migration gap from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing | Full deployment, routing trees, inhibition. Week 4 topic. | Week 1 Day 3 |
| **Loki distributed mode** | Single-node has ingest and query limits. | Week 2 Day 1 |
| **Loki recording rules** | Pre-computing log-derived metrics. | Week 2 Day 2 |
| **Self-triggering alert patterns** | Monitoring systems matching own query strings. | Week 2 Day 3 |
| **Tempo v2.10 Kafka ingest architecture** | New default ingest for high-volume production. | Week 3 Day 1 |
| **Tail sampling in OTel Collector** | Keep errors and slow traces, drop normal traffic. | Week 3 Day 2 |
| **OTel Collector as full telemetry pipeline** | Metrics, logs, and traces in one agent. | Week 3 Day 2 |
| **Alloy-only tracing lab** | Production Grafana best practice. Planned follow-on. | Week 3 Day 2 |
| **OpenTelemetry deep dive track** | OTel as its own topic. Planned separate lab track. | Week 3 Day 2 |
| **Tempo metrics generator** | Derives RED metrics from traces. Full Prometheus cardinality constraints apply to derived metrics. | Week 3 Day 1, Day 3 |
| **Exemplars** — metrics to traces link | Direct link from a Prometheus metric data point to a specific trace ID. Enables one-click navigation from a latency spike to the responsible trace. | Week 3 Day 3 — correlation workflow |
| **Meta-observability lab** | Alloy self-metrics, pipeline traces, and app traces in one environment. Planned for Alloy-only tracing lab. | Week 3 Day 3 |
| **TraceQL advanced patterns** | Service graph queries, span set operations, metrics from traces. | Week 3 Day 3 — TraceQL depth |
| **prometheus-flask-exporter cardinality** — path vs endpoint grouping | Real instrumentation anti-pattern found and fixed in lab. CI/CD promtool linting would catch this pre-production. | Week 3 Day 3 |

---

## 9. Reference Material

### TraceQL

| Resource | URL | Notes |
|---|---|---|
| TraceQL documentation | https://grafana.com/docs/tempo/latest/traceql/ | Full query language reference |
| TraceQL metrics | https://grafana.com/docs/tempo/latest/traceql/metrics-queries/ | Deriving metrics from trace data |
| TraceQL tutorial | https://grafana.com/docs/tempo/latest/getting-started/tempo-in-grafana/ | Hands-on query examples |

### Prometheus Flask Integration

| Resource | URL | Notes |
|---|---|---|
| prometheus-flask-exporter | https://github.com/rycus86/prometheus_flask_exporter | group_by configuration and cardinality options |
| Flask metrics best practices | https://prometheus.io/docs/practices/instrumentation/ | General instrumentation guidance applicable to Flask |

### Tempo Configuration

| Resource | URL | Notes |
|---|---|---|
| Tempo compactor configuration | https://grafana.com/docs/tempo/latest/configuration/#compactor | block_retention and compaction settings |
| Tempo storage backends | https://grafana.com/docs/tempo/latest/configuration/storage/ | Local vs object storage for production |
| Tempo cardinality | https://grafana.com/docs/tempo/latest/operations/tempo_cli/ | Tools for analyzing trace data at scale |

### Stack Self-Observability

| Resource | URL | Notes |
|---|---|---|
| Grafana dashboards for LGTM | https://grafana.com/grafana/dashboards/ | Community dashboards for Loki, Tempo, Mimir, Alloy |
| Alloy self-observability | https://grafana.com/docs/alloy/latest/monitor/ | Alloy metrics and tracing for its own pipeline |
| Loki operational dashboards | https://grafana.com/grafana/dashboards/14055 | Official Loki monitoring dashboard |

### Correlation and Exemplars

| Resource | URL | Notes |
|---|---|---|
| Grafana Explore documentation | https://grafana.com/docs/grafana/latest/explore/ | Split view and correlation workflows |
| Exemplars in Prometheus | https://prometheus.io/docs/prometheus/latest/exemplars/ | Metrics to traces link |
| Grafana exemplar support | https://grafana.com/docs/grafana/latest/fundamentals/exemplars/ | Using exemplars in Grafana dashboards |

---

*Week 3 Day 3 complete. Day 4: Week 3 consolidation — GitHub repository update, Week 3 review, screening questions scoped to tracing and OpenTelemetry, and Week 4 scope.*

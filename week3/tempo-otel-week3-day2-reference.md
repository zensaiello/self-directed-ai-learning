# Tempo + OpenTelemetry — Week 3 Day 2 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand OpenTelemetry instrumentation concepts — resource attributes, auto vs manual instrumentation, exporters
- Build and instrument a Python Flask application with OpenTelemetry
- Send traces through the OTel Collector pipeline to Tempo
- Explore traces in Grafana and understand the trace detail view
- Understand the Tempo search table view vs trace detail view
- Generate a realistic trace dataset with observable latency variance

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- Lab deviations from production best practice noted explicitly
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Lab Architecture Note — Deviation From Production Best Practice

The current lab runs both Grafana Alloy and the OTel Collector simultaneously. This is not the standard production Grafana Labs pattern.

**Production best practice:** Use Grafana Alloy as the single collector for all telemetry signals including traces. Alloy can receive OTLP traces and forward to Tempo without a separate OTel Collector.

**Why the lab uses both:** The OTel Collector is widely deployed in enterprise environments independent of Grafana. Understanding its pipeline model is independently valuable for a Senior Observability Architect role. The lab deliberately includes it for learning breadth.

**Follow-on lab planned:** An Alloy-only tracing lab will rebuild this pipeline using only Alloy as the collector — the production Grafana pattern. This will be a separate lab after Week 3 completes.

---

## Table of Contents

1. [OpenTelemetry Instrumentation Concepts](#1-opentelemetry-instrumentation-concepts)
2. [The Python Flask Application](#2-the-python-flask-application)
3. [Trace Exploration in Grafana](#3-trace-exploration-in-grafana)
4. [Lab Results](#4-lab-results)
5. [Questions and Answers](#5-questions-and-answers)
6. [Advanced Topics](#6-advanced-topics)
7. [Reference Material](#7-reference-material)

---

## 1. OpenTelemetry Instrumentation Concepts

### The Trace Pipeline

The application does not send traces directly to Tempo. It sends via OTLP to the OTel Collector which forwards to Tempo:

```
Flask app
    ↓ OTLP/HTTP to localhost:4319
OTel Collector (port 4319 on host → 4318 inside container)
    ↓ OTLP/gRPC to tempo:4317
Tempo
```

This separation means the application only needs to know how to speak OTLP. Where traces ultimately go is the Collector's concern — changing backends requires only Collector reconfiguration, not application changes.

---

### Resource Attributes

Every trace carries **resource attributes** — metadata identifying what produced the trace. The most important is `service.name` — how Grafana and Tempo identify which service a trace came from.

```python
resource = Resource(attributes={
    "service.name": "order-api",
    "service.version": "1.0.0",
    "deployment.environment": "lab"
})
```

Resource attributes are the trace equivalent of Prometheus job labels and Loki container labels. Consistent naming across all three signals enables correlation — `service.name="order-api"` in Tempo should correspond to matching labels in Prometheus and Loki.

---

### Auto-Instrumentation

Instruments Flask automatically — every HTTP request gets a span created without writing span code. The OTel Flask instrumentation library handles this:

```python
from opentelemetry.instrumentation.flask import FlaskInstrumentor
FlaskInstrumentor().instrument_app(app)
```

Produces spans for every HTTP request with attributes including HTTP method, route, status code, and duration. No further code needed for HTTP-level visibility.

---

### Manual Spans

Explicitly created spans for operations auto-instrumentation cannot see — database queries, business logic, external API calls:

```python
with tracer.start_as_current_span("process-order") as span:
    span.set_attribute("order.id", order_id)
    span.set_attribute("order.total", total)
    # work happens here
    # span ends automatically when the with block exits
```

The `with` block starts the span on entry and ends it on exit — duration is measured automatically. Attributes provide context for investigation.

---

### BatchSpanProcessor vs SimpleSpanProcessor

**BatchSpanProcessor** — aggregates spans and sends them in bulk on a background thread. Does not block request handling. Correct for production use.

**SimpleSpanProcessor** — sends each span synchronously, blocking until the export completes. Adds measurable latency to every request. Never use in production.

```python
# Correct
provider.add_span_processor(BatchSpanProcessor(exporter))

# Never use in production
provider.add_span_processor(SimpleSpanProcessor(exporter))
```

---

### Span Kind

The `Kind` attribute on a span indicates the role of the operation:

| Kind | Meaning |
|---|---|
| `server` | Handling an inbound request — set by Flask auto-instrumentation |
| `client` | Making an outbound call — set by HTTP client auto-instrumentation |
| `internal` | Internal operation — set by manual `start_as_current_span()` |
| `producer` | Sending to a message queue |
| `consumer` | Receiving from a message queue |

In the lab the manual spans show `Kind: internal` because they simulate external calls rather than making real HTTP requests. In a production application using the OTel requests instrumentation, actual outbound HTTP calls would show `Kind: client` with `http.url`, `http.method`, and `http.status_code` attributes added automatically.

---

## 2. The Python Flask Application

### Application Structure

```
~/grafana-lab/week3/app/
├── app.py
├── requirements.txt
└── Dockerfile
```

### requirements.txt

```
flask==3.0.3
opentelemetry-api==1.25.0
opentelemetry-sdk==1.25.0
opentelemetry-instrumentation-flask==0.46b0
opentelemetry-exporter-otlp-proto-http==1.25.0
requests==2.32.3
```

### app.py

```python
import time
import random
import requests
from flask import Flask, jsonify

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# --- OpenTelemetry Setup ---

resource = Resource(attributes={
    "service.name": "order-api",
    "service.version": "1.0.0",
    "deployment.environment": "lab"
})

exporter = OTLPSpanExporter(
    endpoint="http://otel-collector:4318/v1/traces"
)

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("order-api")

# --- Flask App ---

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


def simulate_db_query(query_name, min_ms=10, max_ms=50):
    with tracer.start_as_current_span(f"db.query.{query_name}") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.operation", query_name)
        duration = random.uniform(min_ms, max_ms) / 1000
        time.sleep(duration)
        span.set_attribute("db.rows_returned", random.randint(1, 100))


def simulate_external_call(service_name, min_ms=20, max_ms=200):
    with tracer.start_as_current_span(f"external.{service_name}") as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("peer.service", service_name)
        duration = random.uniform(min_ms, max_ms) / 1000
        time.sleep(duration)
        if random.random() < 0.1:
            time.sleep(0.5)
            span.set_attribute("slow_call", True)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/orders", methods=["GET"])
def list_orders():
    with tracer.start_as_current_span("list-orders") as span:
        span.set_attribute("endpoint", "/orders")
        simulate_db_query("select_orders", min_ms=15, max_ms=60)
        orders = [{"id": i, "status": "complete"} for i in range(1, 6)]
        span.set_attribute("orders.count", len(orders))
        return jsonify(orders)


@app.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    with tracer.start_as_current_span("get-order") as span:
        span.set_attribute("order.id", order_id)
        simulate_db_query("select_order_by_id", min_ms=10, max_ms=40)
        simulate_db_query("select_inventory", min_ms=5, max_ms=25)
        simulate_external_call("pricing-service", min_ms=30, max_ms=100)
        order = {
            "id": order_id,
            "status": "complete",
            "items": random.randint(1, 5),
            "total": round(random.uniform(10.0, 500.0), 2)
        }
        span.set_attribute("order.total", order["total"])
        span.set_attribute("order.items", order["items"])
        return jsonify(order)


@app.route("/orders/checkout", methods=["POST"])
def checkout():
    with tracer.start_as_current_span("checkout") as span:
        simulate_db_query("select_cart", min_ms=10, max_ms=30)
        simulate_db_query("select_inventory_check", min_ms=15, max_ms=50)
        simulate_external_call("pricing-service", min_ms=20, max_ms=80)
        simulate_external_call("tax-service", min_ms=15, max_ms=300)
        simulate_external_call("payment-service", min_ms=50, max_ms=150)
        simulate_db_query("insert_order", min_ms=20, max_ms=60)
        total = round(random.uniform(10.0, 500.0), 2)
        span.set_attribute("checkout.total", total)
        span.set_attribute("checkout.success", True)
        return jsonify({"status": "success", "total": total})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

CMD ["python", "app.py"]
```

### docker-compose.yml Addition

```yaml
  order-api:
    build:
      context: ./app
    container_name: order-api
    restart: unless-stopped
    ports:
      - "5000:5000"
    networks:
      - monitoring
    depends_on:
      - otel-collector
```

### Build and Start

```bash
cd ~/grafana-lab/week3
docker compose up -d --build order-api
```

### Application Endpoints

| Endpoint | Method | Spans generated | Notes |
|---|---|---|---|
| `/health` | GET | 1 | Minimal — health check only |
| `/orders` | GET | 2 | Root + 1 DB query |
| `/orders/<id>` | GET | 4 | Root + 2 DB queries + pricing call |
| `/orders/checkout` | POST | 8 | Root + 2 DB queries + 3 external calls + 1 DB write |

### Generating Test Traces

```bash
# Basic endpoint coverage
curl http://localhost:5000/health
curl http://localhost:5000/orders
curl http://localhost:5000/orders/1
curl -X POST http://localhost:5000/orders/checkout

# Generate volume for latency analysis
for i in {1..10}; do curl -s -X POST http://localhost:5000/orders/checkout > /dev/null; done
```

---

## 3. Trace Exploration in Grafana

### Tempo Search — Table View vs Trace Detail

**Table view** — the search results list. Shows a preview per trace:
- Trace ID, start time, service, root span name, duration
- Nested rows show a **subset** of spans — not the full hierarchy
- Designed for triage — scan and select, not investigate
- Column customization is limited in this view

**Trace detail view** — opened by clicking a trace ID:
- Full span hierarchy rendered as a waterfall diagram
- All spans with correct parent-child relationships
- Span attributes visible on click
- Duration bars show relative time within the trace
- This is the investigation view — use this for root cause analysis

**The workflow:**
```
Search results (table) → scan durations → click slow trace → detail view → find bottleneck span
```

### Trace Detail Span Attributes

Each span in the detail view shows:
- **Service** — which service created the span
- **Duration** — how long the span took
- **Start Time** — offset from trace start in ms
- **Kind** — server, client, or internal
- **Status** — unset (no error), ok, or error
- **Library Name** — which instrumentation library created the span
- Custom attributes set via `span.set_attribute()`

### Customizing the Trace View

The Tempo search table nested span columns are fixed — no column picker available. Options for custom trace views:

- **TraceQL tab in Explore** — query language with more result control (Day 3)
- **Grafana dashboard panels** — Table visualization gives column control
- **Tempo data source settings** — configure search filter tags (does not add columns)

---

## 4. Lab Results

### OTel Collector Verification

```
"spans": 39   ← batch containing all curl request spans
"spans": 4    ← subsequent batch
```

39 spans received and forwarded confirms the full pipeline is working. The BatchSpanProcessor aggregates spans and sends in bulk — hence the batched counts rather than one span per request.

### Trace Dataset

- **Service name:** `order-api`
- **Total traces generated:** 20+
- **Checkout duration range:** 287ms — 951ms
- **Consistent bottleneck:** `external.tax-service` longest span in majority of traces

### Checkout Trace Span Structure (8 spans)

```
POST /orders/checkout          ~519ms  ← Flask auto-instrumentation (server)
└── checkout                           ← manual span (internal)
    ├── db.query.select_cart
    ├── db.query.select_inventory_check
    ├── external.pricing-service
    ├── external.tax-service       292ms  ← bottleneck — 10% slow call
    ├── external.payment-service
    └── db.query.insert_order
```

### The Finding

The tax service call accounts for the majority of checkout latency variance:
- Fast traces (~287ms): tax service completes in normal range
- Slow traces (~951ms): tax service triggers 500ms artificial delay

This is the distributed tracing value proposition demonstrated: without tracing, checkout p99 ~950ms with no obvious cause in metrics. With tracing, one query identifies `external.tax-service` as the bottleneck in under 30 seconds of investigation.

---

## 5. Questions and Answers

### Q1: Are there API libraries to expose a /metrics endpoint from Flask?

**Summary:** Yes — `prometheus-flask-exporter` adds Prometheus metrics to Flask in two lines. It automatically instruments every route and exposes `/metrics` with request duration histograms, request counts by endpoint/method/status, and exception counts. Adding this to the order-api creates the full three-pillar setup — Prometheus metrics, Tempo traces, and Loki logs from one application. This is the foundation for the Day 3 correlation workflow and will be added then.

```python
from prometheus_flask_exporter import PrometheusMetrics
metrics = PrometheusMetrics(app)
```

The OTel approach to metrics (using the OTel metrics SDK and exporting via Collector) is an alternative — covered in the planned OpenTelemetry deep dive lab track.

---

### Q2: Other ways to send traces to Tempo without the OTel Collector?

**Summary:** Three options. Direct OTLP from the application to Tempo — simple but couples the app to Tempo specifically. Via Grafana Alloy — the recommended production Grafana Labs pattern, Alloy receives OTLP and forwards to Tempo. Legacy formats (Jaeger, Zipkin) sent directly to Tempo — useful for existing instrumentation without migration.

The lab uses the OTel Collector specifically to learn its pipeline model. Production Grafana deployments use Alloy.

---

### Q3: Can the OTel Collector handle metrics and logs in addition to traces?

**Summary:** Yes — the OTel Collector is a full telemetry pipeline supporting all three signal types simultaneously. It has receivers for Prometheus scraping, file log reading, and OTLP metrics/logs in addition to traces. It can export to Loki, Prometheus, Tempo, or any OTLP-compatible backend. All three pipelines run in one Collector instance.

---

### Q4: Grafana Alloy vs OTel Collector — complementary or conflicting?

**Summary:** Complementary with overlap that requires a deliberate architectural choice. In a pure Grafana Labs environment Alloy is preferred — purpose-built for LGTM stack with tighter integration. In mixed environments requiring vendor neutrality the OTel Collector is better. Many production environments run both — OTel Collector near the application for instrumentation, Alloy for infrastructure-level collection — handing off to each other. The honest answer to customers is "it depends on your existing environment and vendor neutrality requirements."

---

### Q5: Does OTel have broad auto-instrumentation library coverage?

**Summary:** Yes — extensive coverage for Python including Flask, Django, FastAPI, requests, httpx, SQLAlchemy, psycopg2, pymongo, redis, Celery, boto3, and more. Java has the most mature ecosystem. Go requires more manual instrumentation due to language characteristics. Auto-instrumentation handles infrastructure-level spans; manual instrumentation is used for business logic.

Reference: https://opentelemetry-python-contrib.readthedocs.io/en/latest/

---

### Q6: Does tracing add significant application overhead? How is it mitigated?

**Summary:** Overhead is real but manageable with correct configuration. The primary mitigation is sampling — only record a percentage of traces rather than every request.

**Head sampling** — decision made at trace start, before any spans are created:
```python
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
sampler = TraceIdRatioBased(0.1)  # 10% of traces
```

**Tail sampling** — decision made after full trace is assembled, allows keeping errors and slow traces while dropping fast successful ones. Configured in the OTel Collector. More powerful but adds Collector memory overhead.

**BatchSpanProcessor is critical** — sends spans in bulk on a background thread. Never use SimpleSpanProcessor in production — it blocks request handling on every span export.

With BatchSpanProcessor and 10% head sampling, overhead is typically under 1ms per request. At enterprise scale (100,000 req/sec), 100% sampling generates 100,000 traces/sec — significant storage cost. A well-designed sampling strategy keeps errors, slow requests, and a representative sample of normal traffic.

---

### Q7: Why does the Tempo search table show only 3 spans while the trace detail shows 8?

**Summary:** The search table shows a flattened preview subset of spans — designed for triage scanning, not investigation. Rendering the full span tree for every trace in a list would be expensive. The trace detail view fetches the complete trace by ID from Tempo and renders the full hierarchy as a waterfall. The detail view is the authoritative investigation interface. The table is for selecting which trace to investigate.

---

## 6. Advanced Topics

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
| **TraceQL depth** — advanced query patterns | Covered in Day 3. | Week 3 Day 1 |
| **Exemplars** — metrics to traces correlation | Covered in Day 3. | Week 3 Day 1 |
| **Tempo metrics generator** | Derives RED metrics from traces, pushes to Prometheus. | Week 3 Day 1 |
| **Tail sampling in OTel Collector** | Keep errors and slow traces, drop normal traffic. More powerful than head sampling but adds Collector memory overhead. | Week 3 Day 2 — sampling discussion |
| **OTel Collector as full telemetry pipeline** | Metrics, logs, and traces in one agent. Customer environments commonly deploy it. | Week 3 Day 2 — Q3 |
| **Alloy-only tracing lab** | Production Grafana best practice — replace OTel Collector with Alloy for trace collection. Planned follow-on lab after Week 3. | Week 3 Day 2 — architecture note |
| **OpenTelemetry deep dive track** | OTel as its own topic — instrumentation across languages, sampling strategies, Collector in depth. Planned separate lab track alongside Kubernetes. | Week 3 Day 2 — lab planning |

---

## 7. Reference Material

### OpenTelemetry Python

| Resource | URL | Notes |
|---|---|---|
| OpenTelemetry Python SDK | https://opentelemetry.io/docs/languages/python/ | Auto and manual instrumentation |
| OTel Python contrib libraries | https://opentelemetry-python-contrib.readthedocs.io/en/latest/ | Full auto-instrumentation library list |
| OTel Python getting started | https://opentelemetry.io/docs/languages/python/getting-started/ | Flask instrumentation walkthrough |
| BatchSpanProcessor docs | https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.export.html | Processor configuration options |

### Sampling

| Resource | URL | Notes |
|---|---|---|
| OTel sampling documentation | https://opentelemetry.io/docs/concepts/sampling/ | Head vs tail sampling concepts |
| OTel Collector tail sampling processor | https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor | Configuration reference |
| TraceIdRatioBased sampler | https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.sampling.html | Python SDK sampler options |

### Tempo and Grafana

| Resource | URL | Notes |
|---|---|---|
| Tempo search documentation | https://grafana.com/docs/tempo/latest/getting-started/tempo-in-grafana/ | Search tab and trace exploration |
| TraceQL documentation | https://grafana.com/docs/tempo/latest/traceql/ | Query language — covered in Day 3 |
| Grafana Tempo data source | https://grafana.com/docs/grafana/latest/datasources/tempo/ | Configuration and search tag settings |

### Prometheus Flask Integration

| Resource | URL | Notes |
|---|---|---|
| prometheus-flask-exporter | https://github.com/rycus86/prometheus_flask_exporter | Two-line Prometheus metrics for Flask |

---

*Week 3 Day 2 complete. Day 3: TraceQL queries, adding Prometheus metrics to the Flask app, exemplars, and the three-pillar correlation workflow in Grafana Explore.*

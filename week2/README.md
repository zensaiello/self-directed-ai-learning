# Week 3 Lab — Tempo + OpenTelemetry
## Grafana Observability Lab — Distributed Tracing Guide

---

## Overview

This lab extends the Week 1 and Week 2 stack by adding distributed tracing:

- **Tempo** — distributed trace storage and querying (the T in LGTM)
- **OpenTelemetry Collector** — vendor-neutral telemetry collection pipeline
- **order-api** — a Python Flask application instrumented with OpenTelemetry

By the end of this lab you will have a working trace pipeline collecting spans from a multi-endpoint Flask application, queryable via TraceQL in Grafana, with Prometheus metrics and Loki logs from the same application enabling three-pillar correlation.

---

## Lab Architecture Note — Deviation From Production Best Practice

This lab runs both Grafana Alloy (from Week 2) and the OpenTelemetry Collector simultaneously. **This is not the standard production Grafana Labs pattern.**

**Production best practice:** Use Grafana Alloy as the single collector for all telemetry signals including traces. Alloy can receive OTLP traces and forward to Tempo without a separate OTel Collector.

**Why the lab uses both:** The OTel Collector is widely deployed in enterprise environments independent of Grafana. Understanding its pipeline model is independently valuable for a Senior Observability Architect role.

**Follow-on labs planned:**
- Alloy-only tracing lab — rebuilds this pipeline using only Alloy, includes meta-observability (Alloy self-metrics and pipeline traces)
- OpenTelemetry deep dive track — OTel as its own topic alongside the Kubernetes track

---

## Architecture

```
order-api (Flask + OTel SDK)
        ↓ OTLP/HTTP port 4319
OTel Collector
        ↓ OTLP/gRPC to tempo:4317
Tempo
        ↓ query
Grafana (Tempo data source)

order-api (/metrics endpoint)
        ↓ scrape
Prometheus
        ↓ query
Grafana (Prometheus data source)

order-api (stdout logs)
        ↓ collect
Grafana Alloy
        ↓ push
Loki
        ↓ query
Grafana (Loki data source)
```

---

## Week 3 Directory Structure

```
week3/
├── docker-compose.yml           ← Full stack — references week1 and week2 configs
├── tempo-config.yml             ← Tempo server configuration
├── otel-collector-config.yml    ← OTel Collector pipeline configuration
├── app/
│   ├── app.py                   ← Flask application with OTel instrumentation
│   ├── requirements.txt         ← Python dependencies
│   └── Dockerfile               ← Container build definition
├── tempo-otel-week3-day1-reference.md
├── tempo-otel-week3-day2-reference.md
└── tempo-otel-week3-day3-reference.md
```

---

## Prerequisites

- Week 1 directory must be present — `week3/docker-compose.yml` references `../week1/prometheus.yml` and rule files
- Week 2 directory must be present — `week3/docker-compose.yml` references `../week2/loki-config.yml` and `../week2/alloy-config.alloy`

---

## Setup

### Bring Down Previous Stack

```bash
cd ~/grafana-lab/week2
docker compose down

cd ~/grafana-lab/week3
docker compose up -d --build
```

### Verify All Containers Running

```bash
docker compose ps
```

Eight containers should be running — prometheus, grafana, node-exporter, loki, alloy, tempo, otel-collector, order-api.

### Check Tempo Is Ready

```
http://localhost:3200/ready
```

> **Note:** Tempo ingester requires approximately 15 seconds to warm up. The `/ready` endpoint returns "not ready" during this window — expected behavior, not an error.

---

## Configuration Files

### tempo-config.yml

```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

ingester:
  max_block_duration: 5m

compactor:
  compaction:
    block_retention: 24h

storage:
  trace:
    backend: local
    local:
      path: /var/tempo/blocks
    wal:
      path: /var/tempo/wal
```

> **Version note:** Tempo is pinned to `grafana/tempo:2.6.1` — not `latest`. Tempo v2.10 changed the default ingest architecture to require Kafka, which is unsuitable for this lab setup. v2.6.1 uses the classic ingest path.

> **Retention note:** `block_retention: 24h` — set to 24 hours for the lab. Production deployments typically use 7-30 days. Retention must match your investigation window — traces older than the retention period are permanently deleted.

---

### otel-collector-config.yml

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  otlp:
    endpoint: tempo:4317
    tls:
      insecure: true
  debug:
    verbosity: basic

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp, debug]
```

> **Note on debug exporter:** The `logging` exporter was deprecated and removed in recent OTel Collector contrib versions. Use `debug` instead.

---

### app/requirements.txt

```
flask==3.0.3
opentelemetry-api==1.25.0
opentelemetry-sdk==1.25.0
opentelemetry-instrumentation-flask==0.46b0
opentelemetry-exporter-otlp-proto-http==1.25.0
requests==2.32.3
prometheus-flask-exporter==0.23.1
```

---

### app/app.py

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
from prometheus_flask_exporter import PrometheusMetrics

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
metrics = PrometheusMetrics(app, group_by='endpoint')
metrics.info("order_api_info", "Order API information", version="1.0.0")


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

---

## Grafana Configuration

### Data Sources Required

All three must be configured — Grafana starts fresh in Week 3:

| Data source | URL |
|---|---|
| Prometheus | `http://prometheus:9090` |
| Loki | `http://loki:3100` |
| Tempo | `http://tempo:3200` |

---

## Prometheus Scrape Target

Add order-api to `~/grafana-lab/week1/prometheus.yml`:

```yaml
  - job_name: 'order-api'
    static_configs:
      - targets: ['order-api:5000']
```

Hot reload:
```bash
curl -X POST http://localhost:9090/-/reload
```

---

## Port Reference

| Service | Port | Purpose |
|---|---|---|
| Grafana | 3000 | UI — admin/grafana |
| Prometheus | 9090 | Metrics UI and API |
| Loki | 3100 | Log API |
| Tempo | 3200 | Trace API and UI |
| Tempo OTLP gRPC | 4317 | Direct trace ingest |
| Tempo OTLP HTTP | 4318 | Direct trace ingest |
| OTel Collector HTTP | 4319 | Application trace ingest |
| OTel Collector gRPC | 4320 | Application trace ingest |
| Alloy | 12345 | Pipeline UI and metrics |
| Node Exporter | 9100 | Host metrics |
| order-api | 5000 | Application endpoints and /metrics |

---

## Generating Test Traces

```bash
# Basic coverage
curl http://localhost:5000/health
curl http://localhost:5000/orders
curl http://localhost:5000/orders/1
curl -X POST http://localhost:5000/orders/checkout

# Volume for analysis
for i in {1..20}; do
  curl -s http://localhost:5000/orders > /dev/null
  curl -s http://localhost:5000/orders/$((RANDOM % 5 + 1)) > /dev/null
  curl -s -X POST http://localhost:5000/orders/checkout > /dev/null
done
```

---

## Key TraceQL Queries

```
# All traces from order-api
{resource.service.name="order-api"}

# Slow traces
{resource.service.name="order-api" && duration>500ms}

# Traces where slow call triggered
{span.slow_call=true}

# Traces where tax service was slow
{span.peer.service="tax-service" && duration>200ms}

# Traces containing errors
{status=error}

# Complex traces
{resource.service.name="order-api"} | count() > 5
```

---

## Key Concepts Covered

### Distributed tracing
- Traces track a single request across all services it touches
- Spans are individual units of work — name, start time, duration, attributes, status
- Context propagation passes the trace ID through request headers between services
- The trace waterfall view shows where time was spent in a request

### OpenTelemetry instrumentation
- Resource attributes identify the service — `service.name` is the most important
- Auto-instrumentation instruments Flask automatically via `FlaskInstrumentor`
- Manual spans created with `tracer.start_as_current_span()` for business logic
- `BatchSpanProcessor` sends spans in bulk on a background thread — never use `SimpleSpanProcessor` in production
- Span Kind — `server` for inbound, `client` for outbound, `internal` for manual spans

### TraceQL
- `{}` selects spans matching conditions — span-level filter
- `|` pipeline applies trace-level aggregations
- Resource attributes prefixed with `resource.`, span attributes with `span.`, intrinsic attributes have no prefix
- Duration filters find slow traces — `{duration>500ms}`
- Attribute filters find specific conditions — `{span.slow_call=true}`

### Prometheus metrics on Flask
- `prometheus-flask-exporter` adds `/metrics` endpoint in two lines
- **Critical:** Use `group_by='endpoint'` to avoid path label cardinality explosion
- Default `path` label uses raw URL — `/orders/1`, `/orders/2` etc. creates one series per unique URL
- `endpoint` label uses Flask route function name — bounded by number of routes

### Tempo retention
- Default `block_retention` in lab: 24h — set explicitly to avoid traces expiring during investigation
- Production: 7-30 days standard, 90+ days for compliance
- Retention must match investigation window — expired traces cannot be recovered

### Tempo attribute cardinality
- More tolerant than Prometheus/Loki — traces stored as blobs, not per unique attribute value
- High-cardinality span attributes acceptable — request IDs, user IDs
- Resource attributes should be bounded — drive search performance
- Metrics generator reintroduces full Prometheus cardinality constraints for derived metrics

### Three-pillar correlation
- Metrics detect problems — p99 latency spike
- Logs rule out application errors — no error lines means not a code bug
- Traces identify root cause — specific slow span in the waterfall
- Grafana Explore split view enables this workflow in one interface

### Operational lessons
- Tempo v2.10 requires Kafka — pin to v2.6.1 for simple deployments
- Tempo ingester has 15-second warm-up — `/ready` returns not ready during this window
- OTel Collector `logging` exporter deprecated — use `debug` exporter
- Trace retention must be set before investigation — expired traces are gone

---

## Next Steps (Week 4)

- Deploy Alertmanager — complete the alerting pipeline from Weeks 1 and 2
- Configure alert routing, grouping, inhibition, and silencing
- Deploy Grafana Mimir for long-term metrics storage
- Connect the full LGTM stack with production-representative architecture

# Tempo + OpenTelemetry — Week 3 Day 1 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand distributed tracing and why it exists as the third pillar of observability
- Understand the trace data model — spans, traces, context propagation
- Understand Tempo's role in the LGTM stack and how it differs from Loki and Prometheus
- Understand OpenTelemetry as the vendor-neutral instrumentation standard
- Extend the stack with Tempo and the OTel Collector
- Verify the full trace pipeline infrastructure is ready to receive traces

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- All scaling claims quantified where possible
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Table of Contents

1. [What Distributed Tracing Is and Why It Exists](#1-what-distributed-tracing-is-and-why-it-exists)
2. [The Trace Data Model](#2-the-trace-data-model)
3. [Tempo — Role and Architecture](#3-tempo--role-and-architecture)
4. [OpenTelemetry](#4-opentelemetry)
5. [Stack Setup](#5-stack-setup)
6. [Operational Lessons — Version Compatibility](#6-operational-lessons--version-compatibility)
7. [Questions and Answers](#7-questions-and-answers)
8. [Advanced Topics](#8-advanced-topics)
9. [Reference Material](#9-reference-material)

---

## 1. What Distributed Tracing Is and Why It Exists

### The Blind Spot in Metrics and Logs

Metrics and logs both describe individual components in isolation. When a user request touches multiple services before returning a response, neither metrics nor logs alone can tell you the full story of that specific request.

**The scenario:**
A user reports their checkout is slow. Metrics show all services healthy — CPU, memory, error rates all normal. Logs show no errors. The request is still slow. Why?

The checkout service calls inventory, which calls pricing, which calls an external tax API. Each service looks healthy individually. But the tax API call is taking 2 seconds on every request. Without tracing you cannot see this — you only see each service independently.

**What distributed tracing adds:**
Tracks a single request as it flows through every service it touches. Produces a timeline showing exactly how long each step took and where time was spent.

---

### The Three Pillars — What Each Answers

| Pillar | Tool | Primary question |
|---|---|---|
| Metrics | Prometheus | How much / how fast? Is something wrong? |
| Logs | Loki | What happened? What were the details? |
| Traces | Tempo | Where did time go? Which service caused the slowness? |

All three are complementary. Metrics detect the problem. Logs provide event-level detail. Traces show the request path and identify the specific bottleneck.

---

## 2. The Trace Data Model

### Three Core Concepts

**Span** — a single unit of work. Contains:
- Name — what operation was performed
- Start time and duration
- Attributes — key/value metadata about the operation
- Status — success or error
- Optionally, log events attached to the span

**Trace** — a collection of spans representing a complete request journey. All spans in a trace share the same **trace ID**.

**Context propagation** — the mechanism by which the trace ID travels from service to service. When service A calls service B, it passes the trace ID in the request headers. Service B reads the trace ID and creates its own span as a child of the calling span. This is how a distributed trace is assembled across service boundaries.

---

### A Trace Visualized

```
Trace ID: abc-123
│
├── [span] checkout-service.process_order     0ms → 450ms
│   ├── [span] inventory-service.check_stock  5ms → 45ms
│   ├── [span] pricing-service.get_price      50ms → 120ms
│   │   └── [span] tax-api.calculate_tax      55ms → 2100ms  ← the problem
│   └── [span] payment-service.charge_card    2110ms → 2380ms
```

This waterfall view immediately identifies `tax-api.calculate_tax` taking 2045ms as the root cause of the slow checkout. Without tracing you would need to correlate logs across four services manually to find this.

---

### Enterprise Relevance

SLO conversations move to traces at the service level. "Our p99 checkout latency is 2.4 seconds" is a Prometheus metric. "The tax API call accounts for 85% of that latency" is a trace finding. Both are needed — the metric triggers the investigation, the trace identifies the cause.

---

## 3. Tempo — Role and Architecture

### What Tempo Is

Tempo is Grafana Labs' trace storage backend — the **T** in LGTM. It receives traces, stores them efficiently, and makes them queryable via **TraceQL**.

**How it differs from Loki and Prometheus:**

| | Prometheus | Loki | Tempo |
|---|---|---|---|
| Data type | Metrics — numeric time series | Logs — text streams | Traces — request spans |
| Query language | PromQL | LogQL | TraceQL |
| Collection model | Pull (scrape) | Push (Alloy) | Push (OTel Collector or Alloy) |
| Primary question | How much / how fast? | What happened? | Where did time go? |
| Storage model | Local TSDB or Mimir | Compressed streams or object storage | Object storage |

**What Tempo is not:**
- Not a metrics backend
- Not a log backend
- Not an instrumentation library — it does not instrument your application

### Tempo Storage Model

Tempo stores traces in object storage — S3, GCS, Azure Blob — the same model as Mimir for metrics and Loki for logs at scale. For local development filesystem storage is used. This makes Tempo cost-effective at enterprise scale — object storage is cheap and highly durable.

### Trace Formats Supported

Tempo accepts traces in multiple formats — vendor-neutral by design:
- OpenTelemetry (OTLP) — the current standard, preferred
- Jaeger — widely deployed legacy format
- Zipkin — older distributed tracing format

This means customers can send traces from existing Jaeger or Zipkin instrumentation to Tempo without re-instrumenting their applications.

---

## 4. OpenTelemetry

### What OpenTelemetry Is

OpenTelemetry (OTel) is a vendor-neutral open standard for telemetry instrumentation governed by the CNCF. It provides:

- **SDKs** for instrumenting applications in any language — Python, Go, Java, JavaScript, and more
- **APIs** for creating spans, recording attributes, and propagating context
- **The OpenTelemetry Collector** — a standalone agent that receives telemetry, processes it, and exports to backends

### Why It Matters

Before OpenTelemetry, every observability vendor had their own instrumentation library. Switching backends meant re-instrumenting the application. OpenTelemetry decouples instrumentation from the backend — instrument once using the OTel SDK, route telemetry to any compatible backend by changing collector configuration, not application code.

**Enterprise relevance:** This is directly relevant to the Grafana Labs role. OpenTelemetry is the instrumentation standard Grafana recommends and supports. Customers ask about it constantly. Being able to explain the vendor-neutrality value proposition clearly is a core competency.

### The OTel Collector

Sits between the application and the backends:

```
Application (OTel SDK)
        ↓ OTLP (OpenTelemetry Protocol)
OTel Collector
  - Receives telemetry
  - Processes/batches
  - Exports to backends
        ↓ OTLP
Tempo
```

The Collector has three pipeline stages:
- **Receivers** — accept telemetry in various formats (OTLP, Jaeger, Zipkin)
- **Processors** — transform, batch, filter, or enrich telemetry
- **Exporters** — send telemetry to backends

This separation means you can change backends without touching application code — just update the Collector's exporter configuration.

### Auto-Instrumentation vs Manual Instrumentation

**Auto-instrumentation** — the OTel SDK automatically instruments common libraries and frameworks (HTTP clients, database drivers, message queues) without code changes. The application imports the instrumentation package and spans are created automatically.

**Manual instrumentation** — developers explicitly create spans and add attributes in application code. More precise control, more work. Used for business logic that auto-instrumentation cannot capture.

In practice both are used together — auto-instrumentation for infrastructure-level spans, manual instrumentation for business-critical operations.

---

## 5. Stack Setup

### Week 3 Directory Structure

```
~/grafana-lab/week3/
├── docker-compose.yml
├── tempo-config.yml
├── otel-collector-config.yml
└── app/                    ← Python application (Day 2)
```

### tempo-config.yml (v2.6.1 compatible)

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
    block_retention: 1h

storage:
  trace:
    backend: local
    local:
      path: /var/tempo/blocks
    wal:
      path: /var/tempo/wal
```

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

> **Note on debug exporter:** The `logging` exporter was deprecated and removed in recent OTel Collector contrib versions. The replacement is `debug`. Using `logging` in the current image produces a fatal startup error.

### docker-compose.yml — Key Additions

Seven services total. New services compared to Week 2:

```yaml
  tempo:
    image: grafana/tempo:2.6.1
    container_name: tempo
    restart: unless-stopped
    user: root
    volumes:
      - ./tempo-config.yml:/etc/tempo/config.yml
      - tempo_data:/var/tempo
    command:
      - '--config.file=/etc/tempo/config.yml'
    ports:
      - "3200:3200"
      - "4317:4317"
      - "4318:4318"
    networks:
      - monitoring

  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    container_name: otel-collector
    restart: unless-stopped
    volumes:
      - ./otel-collector-config.yml:/etc/otelcol-contrib/config.yaml
    ports:
      - "4319:4318"
      - "4320:4317"
    networks:
      - monitoring
    depends_on:
      - tempo
```

**Prometheus addition — remote write receiver:**
```yaml
command:
  - '--web.enable-remote-write-receiver'
```

Required for Tempo's metrics generator to push derived metrics to Prometheus.

**Grafana addition — TraceQL feature toggle:**
```yaml
environment:
  - GF_FEATURE_TOGGLES_ENABLE=traceqlEditor
```

Enables the TraceQL query editor in Grafana Explore.

### Port Mapping

| Service | Internal port | External port | Protocol |
|---|---|---|---|
| Tempo HTTP | 3200 | 3200 | HTTP |
| Tempo OTLP gRPC | 4317 | 4317 | gRPC |
| Tempo OTLP HTTP | 4318 | 4318 | HTTP |
| OTel Collector OTLP HTTP | 4318 | 4319 | HTTP |
| OTel Collector OTLP gRPC | 4317 | 4320 | gRPC |

> **Note on port mapping:** Tempo and the OTel Collector both use ports 4317 and 4318 internally. Tempo exposes them directly on the host. The OTel Collector is remapped to 4319/4320 on the host to avoid conflicts. Applications sending traces should target the OTel Collector ports (4319/4320) rather than Tempo directly.

### Startup Sequence

```bash
# Bring down Week 2 stack
cd ~/grafana-lab/week2
docker compose down

# Start Week 3 stack
cd ~/grafana-lab/week3
docker compose up -d
```

### Verification Endpoints

| Endpoint | What it confirms |
|---|---|
| `http://localhost:3200/ready` | Tempo healthy — wait 15 seconds after start |
| `http://localhost:3000` | Grafana — add Tempo data source |

### Grafana Data Sources — Week 3

All three must be configured:

| Data source | URL |
|---|---|
| Prometheus | `http://prometheus:9090` |
| Loki | `http://loki:3100` |
| Tempo | `http://tempo:3200` |

---

## 6. Operational Lessons — Version Compatibility

### Tempo v2.10 Breaking Change

Tempo v2.10 (the current `latest` tag as of April 2026) changed the default ingest architecture to require Kafka as a message queue between the distributor and ingester. This is a significant architectural change that adds operational complexity unsuitable for a simple lab setup.

**Error when using latest with simple config:**
```
error running Tempo: failed to init module services:
error initialising module: distributor: failed to create distributor:
the Kafka topic has not been configured
```

**Resolution:** Pin to Tempo v2.6.1 — the last stable release using the classic ingest path without requiring Kafka.

```yaml
image: grafana/tempo:2.6.1  # not latest
```

**Enterprise relevance:** The Kafka ingest path in v2.10+ provides better scalability and durability for high-volume trace ingest at enterprise scale. It is the correct architectural choice for production deployments handling millions of spans per second. For small to medium deployments and labs, the classic path remains appropriate. Knowing which architecture fits which scale is a Senior Observability Architect competency.

### Configuration Schema Changes Across Versions

Three separate configuration field errors were encountered during setup — `compactor`, `ingester`, and Kafka dependency — all caused by schema changes between versions.

**Operational lesson:** When a Tempo container fails to start with a config parsing error, always verify the exact version before applying configuration examples. Community posts, documentation, and AI-generated configs may reference different schema versions. The version string is the authoritative anchor.

```bash
# Get exact version before applying configuration
docker run --rm grafana/tempo:latest --version
```

### Tempo Ingester Warm-Up Period

The `/ready` endpoint returns "not ready" for approximately 15 seconds after Tempo starts — this is documented expected behavior, not an error. The ingester requires time to join the ring and initialize before accepting traces.

```
Ingester not ready: ingester check ready failed: waiting for 15s after being ready
```

Wait 20 seconds after `docker compose up -d` before checking the ready endpoint.

---

## 7. Questions and Answers

### Q1: What problem does distributed tracing solve that metrics and logs cannot?

**Summary:** Metrics and logs describe individual components in isolation. When a request traverses multiple services, neither can show the end-to-end request path or identify which specific service caused a latency problem. Distributed tracing tracks a single request across all services it touches, producing a waterfall view that shows exactly where time was spent and which service is the bottleneck.

---

### Q2: What is the difference between a span and a trace?

**Summary:** A span is a single unit of work — one operation in one service with a name, start time, duration, and attributes. A trace is a collection of spans that share the same trace ID, representing the complete journey of one request across all services it touched. All spans in a trace are linked by the trace ID propagated through request headers.

---

### Q3: Why does OpenTelemetry matter for enterprise customers?

**Summary:** Before OpenTelemetry, each observability vendor had proprietary instrumentation libraries. Switching backends required re-instrumenting the application. OpenTelemetry is a vendor-neutral CNCF standard — instrument once using the OTel SDK, route telemetry to any compatible backend by changing collector configuration. This eliminates vendor lock-in at the instrumentation layer and is the primary reason Grafana Labs recommends it.

---

### Q4: Why was Tempo pinned to v2.6.1 instead of using latest?

**Summary:** Tempo v2.10 changed the default distributor ingest path to require Kafka — a message queue that adds significant operational complexity. The classic ingest path (distributor → ingester directly) is still appropriate for small to medium deployments and labs. v2.6.1 is the last stable release using the classic path. The Kafka path is the correct enterprise choice for very high-volume trace ingest but is not needed here.

---

## 8. Advanced Topics

Topics identified during Weeks 1, 2, and 3 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — native histograms | Significant cardinality source. Native histograms change storage model. | Week 1 Day 2 |
| **Recording rules** — advanced design at scale | Rule evaluation performance, dependencies, federation. | Week 1 Day 2 |
| **SNMP exporter** — Counter32 vs Counter64 | Migration gap from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing | Full deployment, routing trees, inhibition. Week 4 topic. | Week 1 Day 3 |
| **Prometheus CI/CD integration** — promtool | Instrumentation validation before deployment. | Week 1 Day 3 |
| **Grafana Enterprise features** | Large organization deployment relevance. | Week 1 Day 4 |
| **Loki distributed mode** | Single-node has ingest and query limits. | Week 2 Day 1 |
| **LogQL parsing stages** — full parser reference | Additional parsers beyond logfmt and json. | Week 2 Day 2 |
| **Promtail to Alloy migration** | Customers on Promtail need migration path. | Week 2 Day 1 |
| **Loki recording rules** | Pre-computing log-derived metrics. | Week 2 Day 2 |
| **Alloy pipeline processing stages** | Edge filtering and label extraction. | Week 2 Day 2 |
| **Self-triggering alert patterns** | Monitoring systems matching own query strings. | Week 2 Day 3 |
| **Loki stream label vs structured metadata** | What is indexed vs metadata. | Week 2 Day 3 |
| **Tempo v2.10 Kafka ingest architecture** | New default ingest path for high-volume production deployments. Enterprise architectural choice. | Week 3 Day 1 — version compatibility |
| **TraceQL depth** — advanced query patterns | Tempo's query language for trace search and analysis. Covered in Week 3 Day 3. | Week 3 Day 1 — Tempo introduction |
| **Exemplars** — metrics to traces correlation | The link between a Prometheus metric spike and a specific trace. Week 3 Day 3 topic. | Week 3 Day 1 — three pillars discussion |
| **Tempo metrics generator** | Derives service graph and span metrics from traces, pushes to Prometheus. Adds automatic RED metrics for any instrumented service. | Week 3 Day 1 — tempo config discussion |

---

## 9. Reference Material

### Tempo

| Resource | URL | Notes |
|---|---|---|
| Tempo documentation | https://grafana.com/docs/tempo/latest/ | Authoritative — covers TraceQL, storage, configuration |
| Tempo configuration reference | https://grafana.com/docs/tempo/latest/configuration/ | Full configuration schema |
| Tempo Docker Compose examples | https://github.com/grafana/tempo/tree/main/example/docker-compose | Official examples — always check version compatibility |
| Tempo local storage example | https://github.com/grafana/tempo/blob/main/example/docker-compose/local/readme.md | Closest to lab setup |
| TraceQL documentation | https://grafana.com/docs/tempo/latest/traceql/ | Tempo's query language |

### OpenTelemetry

| Resource | URL | Notes |
|---|---|---|
| OpenTelemetry documentation | https://opentelemetry.io/docs/ | Authoritative — vendor-neutral standard |
| OpenTelemetry Python SDK | https://opentelemetry.io/docs/languages/python/ | Python instrumentation — auto and manual |
| OTel Collector documentation | https://opentelemetry.io/docs/collector/ | Receiver, processor, exporter pipeline |
| OTel Collector contrib receivers | https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver | All available receivers including OTLP |

### Distributed Tracing Concepts

| Resource | URL | Notes |
|---|---|---|
| OpenTelemetry trace data model | https://opentelemetry.io/docs/concepts/signals/traces/ | Spans, traces, context propagation |
| W3C Trace Context specification | https://www.w3.org/TR/trace-context/ | The standard for trace ID propagation in HTTP headers |
| Grafana blog — three pillars | https://grafana.com/blog/2019/10/21/whats-the-difference-between-metrics-logs-and-traces/ | Metrics, logs, and traces compared |

### Version Compatibility

| Resource | URL | Notes |
|---|---|---|
| Tempo releases | https://github.com/grafana/tempo/releases | All release versions and changelogs |
| Tempo v2.10 changelog | https://github.com/grafana/tempo/releases/tag/v2.10.0 | Kafka ingest architecture changes |
| OTel Collector changelog | https://github.com/open-telemetry/opentelemetry-collector/releases | logging → debug exporter deprecation |

---

*Week 3 Day 1 complete. Day 2: Instrumenting a Python application with OpenTelemetry — auto-instrumentation, manual span creation, and sending traces to Tempo via the OTel Collector.*

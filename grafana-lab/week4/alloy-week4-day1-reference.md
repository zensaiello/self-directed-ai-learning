# Alloy-Only Tracing + Meta-Observability — Week 4 Day 1 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand why Alloy replaces the OTel Collector as the production Grafana pattern
- Understand Alloy's otelcol component family for trace collection
- Build the Alloy-only trace pipeline — removing the OTel Collector entirely
- Verify traces flowing end to end through Alloy to Tempo
- Document the architectural difference from Week 3

### Working Parameters
- Direct, no filler, factually accurate
- This week IS the production best practice — no deviation notes required for the trace pipeline
- Enterprise vs. general use distinctions called out explicitly
- Real-world examples over theory

---

## Table of Contents

1. [Architectural Change — Week 3 vs Week 4](#1-architectural-change--week-3-vs-week-4)
2. [Alloy otelcol Component Family](#2-alloy-otelcol-component-family)
3. [Stack Setup](#3-stack-setup)
4. [Verification](#4-verification)
5. [Questions and Answers](#5-questions-and-answers)
6. [Advanced Topics](#6-advanced-topics)
7. [Reference Material](#7-reference-material)

---

## 1. Architectural Change — Week 3 vs Week 4

### Week 3 Pipeline (OTel Collector)

```
order-api (Flask + OTel SDK)
    ↓ OTLP/HTTP to otel-collector:4318 (host port 4319)
OTel Collector
    ↓ OTLP/gRPC to tempo:4317
Tempo
```

### Week 4 Pipeline (Alloy only)

```
order-api (Flask + OTel SDK)
    ↓ OTLP/HTTP to alloy:4318 (host port 4318)
Alloy
    ↓ OTLP/gRPC to tempo:4317
Tempo
```

### What Changed

| | Week 3 | Week 4 |
|---|---|---|
| Trace collector | OTel Collector | Alloy |
| Log collector | Alloy | Alloy |
| Total containers | 8 | 7 |
| Collector config format | YAML (OTel) + HCL (Alloy) | HCL only |
| Production best practice | No | Yes |
| Application code change | — | Endpoint URL only |
| Ports 4317/4318 owner | OTel Collector | Alloy |

### Why This Matters

**Operational simplification:** One fewer container, one fewer configuration format, one fewer component to monitor and upgrade. The OTel Collector and Alloy were both needed in Week 3 only because the lab was teaching both tools simultaneously. In production you choose one.

**Unified pipeline:** Alloy now handles all telemetry collection — logs to Loki and traces to Tempo — in a single component with a single configuration file. Day 2 adds metrics scraping to complete the unified three-signal pipeline.

**Configuration consistency:** A single HCL configuration describes the complete collection pipeline. No context switching between YAML and HCL. No reconciling two separate component health UIs.

---

### The Only Application Change Required

The application does not need re-instrumentation. The OTel SDK is vendor-neutral — changing backends requires only updating the exporter endpoint:

**Week 3:**
```python
exporter = OTLPSpanExporter(
    endpoint="http://otel-collector:4318/v1/traces"
)
```

**Week 4:**
```python
exporter = OTLPSpanExporter(
    endpoint="http://alloy:4318/v1/traces"
)
```

One line change. This is the vendor-neutrality value proposition of OpenTelemetry made concrete — the instrumentation is identical, only the routing changes.

---

## 2. Alloy otelcol Component Family

Alloy supports OpenTelemetry signals natively through its `otelcol` component family. These are Alloy-native wrappers around the same OTel Collector components — same functionality, unified in Alloy's HCL configuration model.

### Three Components for a Trace Pipeline

**`otelcol.receiver.otlp`** — receives traces from applications via OTLP protocol:
- Listens on gRPC (default port 4317) and HTTP (default port 4318)
- Accepts traces from any OTel SDK regardless of language
- Output connects to the next pipeline stage

**`otelcol.processor.batch`** — batches spans before export:
- Aggregates spans and sends in bulk rather than one at a time
- Reduces network overhead significantly on high-volume applications
- Configurable timeout and batch size

**`otelcol.exporter.otlp`** — exports traces to a backend via OTLP:
- Points to Tempo in this configuration
- Supports TLS — `insecure = true` for lab use
- Can be pointed at any OTLP-compatible backend

### Pipeline Flow

```
otelcol.receiver.otlp.default
    ↓ output.traces
otelcol.processor.batch.default
    ↓ output.traces
otelcol.exporter.otlp.tempo
    ↓ OTLP/gRPC
Tempo
```

Each component's `output` block explicitly declares where data flows next. This is the same component-graph model used for log collection — composable and auditable.

### Alloy HCL vs OTel Collector YAML

The Week 3 OTel Collector configuration:

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

exporters:
  otlp:
    endpoint: tempo:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp]
```

The equivalent Week 4 Alloy configuration:

```hcl
otelcol.receiver.otlp "default" {
  grpc { endpoint = "0.0.0.0:4317" }
  http { endpoint = "0.0.0.0:4318" }
  output {
    traces = [otelcol.processor.batch.default.input]
  }
}

otelcol.processor.batch "default" {
  output {
    traces = [otelcol.exporter.otlp.tempo.input]
  }
}

otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
    tls { insecure = true }
  }
}
```

Same three stages. Same functionality. Different syntax. The Alloy version makes the data flow explicit through the `output` blocks — you can trace exactly where data goes at each step by reading the configuration.

---

## 3. Stack Setup

### Week 4 Directory Structure

```
~/grafana-lab/week4/
├── docker-compose.yml
├── alloy-config.alloy      ← Extended from Week 2 — adds otelcol components
└── app/                    ← Week 4 version of order-api
    ├── app.py              ← Endpoint updated to http://alloy:4318/v1/traces
    ├── requirements.txt
    └── Dockerfile
```

> **Note on app directory:** The Week 4 app directory is a copy of Week 3's app with only the exporter endpoint changed. Week 3 is preserved with its original OTel Collector endpoint. Each week is self-contained.

### alloy-config.alloy — Full Configuration

```hcl
// ============================================================
// LOG COLLECTION — carried forward from Week 2
// ============================================================

discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

loki.source.docker "container_logs" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.containers.targets
  forward_to = [loki.write.local.receiver]
  relabel_rules = loki.relabel.container_labels.rules
}

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

loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}

// ============================================================
// TRACE COLLECTION — new in Week 4
// ============================================================

otelcol.receiver.otlp "default" {
  grpc {
    endpoint = "0.0.0.0:4317"
  }
  http {
    endpoint = "0.0.0.0:4318"
  }
  output {
    traces = [otelcol.processor.batch.default.input]
  }
}

otelcol.processor.batch "default" {
  output {
    traces = [otelcol.exporter.otlp.tempo.input]
  }
}

otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
    tls {
      insecure = true
    }
  }
}
```

### docker-compose.yml — Key Differences From Week 3

**OTel Collector removed:**
```yaml
# This service no longer exists in Week 4
# otel-collector:
#   image: otel/opentelemetry-collector-contrib:latest
```

**Alloy now exposes OTLP ports:**
```yaml
alloy:
  ports:
    - "12345:12345"
    - "4317:4317"    ← new — Alloy owns these ports now
    - "4318:4318"    ← new
```

**Tempo no longer needs to expose OTLP ports to host:**
```yaml
tempo:
  ports:
    - "3200:3200"    ← only HTTP port exposed — OTLP handled internally
```

**order-api depends on alloy instead of otel-collector:**
```yaml
order-api:
  depends_on:
    - alloy           ← was otel-collector
```

### Startup Sequence

```bash
# Bring down Week 3
cd ~/grafana-lab/week3
docker compose down

# Start Week 4
cd ~/grafana-lab/week4
docker compose up -d --build
```

### Verification

**Alloy UI — seven components all healthy:**

```
http://localhost:12345
```

Expected components:
- `discovery.docker.containers`
- `loki.relabel.container_labels`
- `loki.source.docker.container_logs`
- `loki.write.local`
- `otelcol.receiver.otlp.default`
- `otelcol.processor.batch.default`
- `otelcol.exporter.otlp.tempo`

**Alloy startup logs:**

```bash
docker logs alloy 2>&1 | grep -i "otelcol" | tail -10
```

Expected:
```
msg="Starting GRPC server" component_id=otelcol.receiver.otlp.default endpoint=[::]:4317
msg="Starting HTTP server" component_id=otelcol.receiver.otlp.default endpoint=[::]:4318
```

**Traces in Grafana:**

Grafana Explore → Tempo → Search → Service Name: `order-api`

---

## 4. Verification

### Lab Results

**Stack:** Seven containers — prometheus, grafana, node-exporter, loki, alloy, tempo, order-api. No otel-collector.

**Alloy UI:** Seven components all showing healthy including three new otelcol components.

**Traces:** Consistent with Week 3 results — same span structure, same latency characteristics, same 10% slow tax service path visible.

**Confirmed:** The OTel SDK's vendor-neutrality in practice. Changing from OTel Collector to Alloy required only one line change in the application — the exporter endpoint URL. All instrumentation, span attributes, and trace structure remained identical.

---

## 5. Questions and Answers

### Q1: Why does switching from OTel Collector to Alloy only require one application change?

**Summary:** OpenTelemetry's vendor neutrality means the instrumentation layer is completely decoupled from the backend. The application sends OTLP — a standard protocol. Any OTLP-compatible receiver can accept it. Changing receivers requires only updating the endpoint URL. The OTel SDK, span creation, attribute setting, and BatchSpanProcessor are unchanged because they are backend-agnostic by design.

---

### Q2: What is the otelcol component family in Alloy?

**Summary:** Alloy-native wrappers around the same components used in the OTel Collector. Three components form a trace pipeline: `otelcol.receiver.otlp` receives OTLP traces from applications, `otelcol.processor.batch` aggregates spans before export, `otelcol.exporter.otlp` forwards to Tempo. Same functionality as the OTel Collector pipeline, expressed in Alloy's HCL component model with explicit data flow via `output` blocks.

---

### Q3: What are the operational benefits of Alloy over running both Alloy and OTel Collector?

**Summary:** One fewer container to deploy, monitor, and upgrade. One configuration format (HCL) instead of two (HCL + YAML). One component health UI instead of two. One pipeline to reason about. The operational surface area is smaller — fewer things that can fail independently, fewer configuration files to keep in sync, fewer images to keep updated.

---

## 6. Advanced Topics

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — native histograms | Significant cardinality source. Native histograms change storage model. | Week 1 Day 2 |
| **Recording rules** — advanced design at scale | Rule evaluation performance and dependencies. | Week 1 Day 2 |
| **SNMP exporter** — Counter32 vs Counter64 | Migration gap from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing | Full deployment, routing trees, inhibition. Week 5 topic. | Week 1 Day 3 |
| **Loki distributed mode** | Single-node has ingest and query limits. | Week 2 Day 1 |
| **Loki recording rules** | Pre-computing log-derived metrics. | Week 2 Day 2 |
| **Self-triggering alert patterns** | Monitoring systems matching own query strings. | Week 2 Day 3 |
| **Tempo v2.10 Kafka ingest architecture** | New default ingest for high-volume production. | Week 3 Day 1 |
| **Tail sampling** | Keep errors and slow traces, drop normal traffic. | Week 3 Day 2 |
| **Tempo metrics generator** | Derives RED metrics from traces. Full Prometheus cardinality constraints apply. | Week 3 Day 1 |
| **Exemplars** — metrics to traces link | Direct link from Prometheus metric to specific trace ID. | Week 3 Day 3 |
| **Meta-observability** — stack self-monitoring | Platform monitoring itself. Week 4 Day 2 topic. | Week 3 Day 3 |
| **TraceQL advanced patterns** | Service graph queries, span set operations. | Week 3 Day 3 |
| **prometheus-flask-exporter cardinality** | path vs endpoint grouping anti-pattern. | Week 3 Day 3 |
| **OpenTelemetry deep dive** | OTel as its own topic. Week 6. | Week 3 Day 2 |
| **Kubernetes + LGTM on K8s** | CKA track + deploying full stack. Week 7. | Lab planning |

---

## 7. Reference Material

### Alloy otelcol Components

| Resource | URL | Notes |
|---|---|---|
| otelcol.receiver.otlp | https://grafana.com/docs/alloy/latest/reference/components/otelcol.receiver.otlp/ | Full receiver configuration options |
| otelcol.processor.batch | https://grafana.com/docs/alloy/latest/reference/components/otelcol.processor.batch/ | Batch processor configuration |
| otelcol.exporter.otlp | https://grafana.com/docs/alloy/latest/reference/components/otelcol.exporter.otlp/ | OTLP exporter configuration |
| Alloy traces overview | https://grafana.com/docs/alloy/latest/collect/opentelemetry-data/ | Collecting OTel data with Alloy |

### Architecture Reference

| Resource | URL | Notes |
|---|---|---|
| Alloy component reference | https://grafana.com/docs/alloy/latest/reference/components/ | All available pipeline components |
| Grafana LGTM stack overview | https://grafana.com/about/press/2022/06/09/announcing-the-lgtm-stack-grafana-loki-tempo-and-mimir/ | How the four components fit together |
| Promtail to Alloy migration | https://grafana.com/docs/alloy/latest/tasks/migrate/from-promtail/ | Relevant for customers on deprecated collectors |

---

*Week 4 Day 1 complete. Day 2: Meta-observability — Alloy scraping LGTM component metrics and building the stack health dashboard.*

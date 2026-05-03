# Alloy-Only Tracing + Meta-Observability — Week 4 Day 3 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Configure Alloy to emit OpenTelemetry traces about its own internal pipeline operations
- Understand the `tracing` block syntax and correct `write_to` configuration
- Verify Alloy traces appear in Tempo alongside application traces
- Interpret Alloy's self-traces to understand what they represent operationally
- Complete the meta-observability picture — metrics, logs, and traces from Alloy itself

### Working Parameters
- Direct, no filler, factually accurate
- This week IS the production best practice — no deviation notes required
- Enterprise vs. general use distinctions called out explicitly

---

## Table of Contents

1. [How Alloy Self-Tracing Works](#1-how-alloy-self-tracing-works)
2. [Configuration — The tracing Block](#2-configuration--the-tracing-block)
3. [Verification and Results](#3-verification-and-results)
4. [Reading Alloy Traces](#4-reading-alloy-traces)
5. [The Complete Meta-Observability Picture](#5-the-complete-meta-observability-picture)
6. [Questions and Answers](#6-questions-and-answers)
7. [Advanced Topics](#7-advanced-topics)
8. [Reference Material](#8-reference-material)

---

## 1. How Alloy Self-Tracing Works

Alloy has built-in support for emitting OpenTelemetry traces about its own component evaluations and pipeline operations. The `tracing` configuration block activates this and points the traces at any otelcol component that accepts trace input.

Since Alloy already runs an OTLP batch processor and exporter for the order-api traces, Alloy's own traces can reuse the same pipeline — sent directly to the batch processor rather than through the receiver:

```
Alloy internal operations
    ↓ write_to = [otelcol.processor.batch.default.input]
otelcol.processor.batch.default
    ↓
otelcol.exporter.otlp.tempo
    ↓ OTLP/gRPC
Tempo
```

Alloy traces appear in Tempo alongside order-api traces, queryable by `resource.service.name="alloy"`.

---

### Why write_to Points to the Processor, Not the Receiver

The `tracing` block's `write_to` argument accepts any otelcol component that accepts trace input — processors and exporters. It does **not** accept a receiver's `.input`.

**Incorrect:**
```hcl
tracing {
  write_to = [otelcol.receiver.otlp.default.input]  # ERROR — receivers don't accept write_to
}
```

**Correct:**
```hcl
tracing {
  write_to = [otelcol.processor.batch.default.input]  # Correct — bypasses receiver, goes to processor
}
```

The traces bypass the receiver entirely and enter the pipeline at the processor stage. This avoids a feedback loop where Alloy's self-traces would trigger additional receiver traces.

---

## 2. Configuration — The tracing Block

### Final alloy-config.alloy

```hcl
// ============================================================
// TRACING — Alloy self-instrumentation
// ============================================================

tracing {
  sampling_fraction = 0.1
  write_to = [otelcol.processor.batch.default.input]
}

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
// TRACE COLLECTION — receives from order-api and forwards to Tempo
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

### tracing Block Parameters

| Parameter | Value | Meaning |
|---|---|---|
| `sampling_fraction` | 0.1 | Sample 10% of Alloy's internal traces — Alloy generates high internal activity |
| `write_to` | `[otelcol.processor.batch.default.input]` | Send traces directly to batch processor |

**sampling_fraction values:**
- `1.0` — 100% of traces captured — useful for debugging, high volume
- `0.1` — 10% sampled — good production default for Alloy self-traces
- `0.0` — no traces — effectively disables self-tracing

### Hot Reload

The tracing block change was applied via hot reload — no container restart required:

```bash
curl -X POST http://localhost:12345/-/reload
```

Confirmation in Alloy logs:
```
msg="finished node evaluation" node_id=tracing
msg="config reloaded"
```

---

## 3. Verification and Results

### Alloy Service in Tempo

After reload, `alloy` appeared in the Tempo Search Service Name dropdown alongside `order-api`. Two services now generating traces:

| Service | Source | Trace types |
|---|---|---|
| `order-api` | Flask application OTel SDK | HTTP requests, DB queries, external service calls |
| `alloy` | Alloy `tracing` block | Docker discovery queries, OTLP export operations |

---

## 4. Reading Alloy Traces

### Two Types of Alloy Traces

**`POST /v1/traces` — OTLP Export Operations**

Alloy records a trace every time the batch processor flushes and sends spans to Tempo.

Span attributes observed:
```
accepted_spans:    16
failed_spans:       0
refused_spans:      0
transport:         http
format:            protobuf
alloy.component_id: otelcol.receiver.otlp.default
```

This trace represents one batch export — 16 spans sent to Tempo, all accepted, zero failures. Duration under 1ms — consistent with the 5ms p99 push duration seen in the metrics dashboard.

**`GET /v1.51/containers/<id>/json` — Docker Discovery Operations**

Alloy records a trace every time the `discovery.docker` component queries the Docker API for container metadata.

The container ID in the URL is a specific running container. Cross-referencing with `docker ps --no-trunc` identifies which container was inspected.

**Lab finding:** One of the Docker discovery traces had container ID `37c9295b...` which resolved to the Alloy container itself — Alloy discovering and inspecting itself via the Docker API. A self-referential trace that is a concrete illustration of meta-observability.

---

### What the Trace Types Tell You Operationally

| Trace | Pipeline it monitors | What elevated duration would indicate |
|---|---|---|
| `GET /v1.51/containers/...` | Log collection — Docker discovery | Docker socket under pressure, log collection degrading |
| `POST /v1/traces` | Trace export — Alloy → Tempo | Tempo accepting traces slowly, export backpressure building |

These traces provide early warning of pipeline degradation before metrics thresholds are breached and before log output shows errors.

---

### The alloy.component_id Attribute

Alloy adds `alloy.component_id` to every self-generated span. This identifies which pipeline component generated the trace — making it possible to filter in TraceQL:

```
{resource.service.name="alloy" && span.alloy.component_id="otelcol.receiver.otlp.default"}
```

At enterprise scale with complex Alloy pipelines containing dozens of components, this attribute allows you to isolate traces from a specific component that is behaving unexpectedly.

---

## 5. The Complete Meta-Observability Picture

All three observability signals now available from Alloy itself:

| Signal | How collected | Where stored | What it shows |
|---|---|---|---|
| Metrics | Alloy `/metrics` scraped by Prometheus | Prometheus TSDB | Component health count, pipeline throughput, memory, export success rate |
| Logs | Alloy stdout collected by itself | Loki | Configuration errors, reload events, pipeline warnings |
| Traces | Alloy `tracing` block → batch processor → Tempo | Tempo | Internal pipeline operations — Docker discovery, OTLP exports |

### The Self-Referential Loop

Alloy collects its own logs (via `loki.source.docker` discovering the alloy container), scrapes its own metrics (Prometheus scraping `alloy:12345/metrics`), and now generates its own traces (via the `tracing` block). The platform monitors itself using the same mechanisms it uses to monitor everything else.

This is the meta-observability pattern stated as a principle: **the observability platform should be observable using the same tools and patterns used to observe applications.**

### Enterprise Value of This Pattern

**Operational:** Pipeline failures are visible before they cause data loss. A degrading Docker socket connection shows in trace duration before log gaps appear in Loki.

**Customer demonstration:** Showing a customer that the platform monitors itself answers "how do we know the monitoring is working?" — a question every enterprise customer asks. The answer is concrete and demonstrable rather than theoretical.

**Template:** The same three-signal approach used for Alloy applies directly to any modular application. Resource attributes, pipeline component tracing, and metrics endpoints are patterns any engineering team can adopt.

---

## 6. Questions and Answers

### Q1: Why does write_to point to the batch processor instead of the receiver?

**Summary:** The `tracing` block's `write_to` argument accepts otelcol components that accept trace input — processors and exporters. Receivers do not expose an `.input` that accepts externally written traces. Pointing `write_to` at the receiver would create a feedback loop. The correct path bypasses the receiver and enters the pipeline at the processor stage directly.

---

### Q2: What does sampling_fraction = 0.1 mean and when would you change it?

**Summary:** 10% of Alloy's internal traces are captured and sent to Tempo. Alloy generates high internal activity — every component evaluation, every Docker discovery query, every batch flush creates potential trace data. At 100% sampling this would generate significant trace volume. 0.1 keeps it manageable for production. Increase to 1.0 temporarily when debugging a specific pipeline problem. Decrease further in very high-activity environments.

---

### Q3: What do the two types of Alloy traces represent?

**Summary:** `POST /v1/traces` traces represent OTLP export operations — the trace pipeline sending batches to Tempo. Attributes show accepted/failed/refused span counts per batch. `GET /v1.51/containers/...` traces represent Docker API queries from the `discovery.docker` component — the log collection pipeline inspecting container metadata. Container IDs in the URL identify which specific container was queried. Duration of both should be under 5ms on a healthy stack.

---

## 7. Advanced Topics

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — native histograms | Significant cardinality source. Native histograms change storage model. | Week 1 Day 2 |
| **Recording rules** — advanced design at scale | Rule evaluation performance and dependencies. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing | Full deployment, routing trees, inhibition. Week 5 topic. | Week 1 Day 3 |
| **Loki distributed mode** | Single-node has ingest and query limits. | Week 2 Day 1 |
| **Tempo v2.10 Kafka ingest architecture** | New default ingest for high-volume production. | Week 3 Day 1 |
| **Tail sampling** | Keep errors and slow traces, drop normal traffic. | Week 3 Day 2 |
| **Tempo metrics generator** | Derives RED metrics from traces. | Week 3 Day 1 |
| **Exemplars** — metrics to traces link | Direct link from Prometheus metric to specific trace ID. | Week 3 Day 3 |
| **TraceQL advanced patterns** | Service graph queries, span set operations. | Week 3 Day 3 |
| **OpenTelemetry deep dive** | OTel as its own topic. Week 6. | Week 3 Day 2 |
| **Kubernetes + LGTM on K8s** | CKA track + deploying full stack. Week 7. | Lab planning |
| **Grafana dashboard variables for stack health** | Making the LGTM Stack Health dashboard dynamic. | Week 4 Day 2 |
| **Alert rules for pipeline health** | Alerting when export failures > 0, queue fill > 80%. Week 5. | Week 4 Day 2 |
| **Status history visualization** | Up/down state over time — more informative than current-value Stat. | Week 4 Day 2 |
| **Alloy tracing depth** — component-level filtering | Using `alloy.component_id` in TraceQL to isolate specific pipeline components. | Week 4 Day 3 |
| **Alloy metrics scraping via otelcol** | Alloy can scrape Prometheus metrics and forward via OTLP — bridging Prometheus and OTel ecosystems. | Week 4 Day 3 |

---

## 8. Reference Material

### Alloy Tracing Block

| Resource | URL | Notes |
|---|---|---|
| Alloy tracing block documentation | https://grafana.com/docs/alloy/latest/reference/config-blocks/tracing/ | Full tracing block configuration including sampling_fraction and write_to |
| Alloy self-monitoring | https://grafana.com/docs/alloy/latest/monitor/ | Metrics, logs, and traces from Alloy itself |

### Meta-Observability

| Resource | URL | Notes |
|---|---|---|
| Grafana observability for Alloy | https://grafana.com/docs/alloy/latest/monitor/monitoring_alloy/ | Official guidance on monitoring Alloy deployments |
| Grafana community dashboards | https://grafana.com/grafana/dashboards/ | Import official LGTM component dashboards by ID |
| Tempo operational dashboard | https://grafana.com/grafana/dashboards/16310 | Official Tempo monitoring dashboard |
| Loki operational dashboard | https://grafana.com/grafana/dashboards/14055 | Official Loki monitoring dashboard |

### TraceQL for Pipeline Investigation

| Resource | URL | Notes |
|---|---|---|
| TraceQL documentation | https://grafana.com/docs/tempo/latest/traceql/ | Full query language including span attribute filtering |
| Tempo search | https://grafana.com/docs/tempo/latest/getting-started/tempo-in-grafana/ | Service name filtering and trace exploration |

---

*Week 4 Day 3 complete. Day 4: Week 4 consolidation — GitHub repository update, Week 4 review, screening questions, and Week 5 scope.*

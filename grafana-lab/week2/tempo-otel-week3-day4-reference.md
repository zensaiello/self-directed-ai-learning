# Tempo + OpenTelemetry — Week 3 Day 4 Consolidation Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Finalize the Week 3 GitHub repository as a portfolio artifact
- Review Week 3 content at a level sufficient for a screening conversation
- Identify honest gaps and areas needing reinforcement
- Scope Week 4 — Alloy-only tracing with meta-observability

### Working Parameters
- Direct, no filler, factually accurate
- Honest gap assessment — no overclaiming
- Quantification tied to observable indicators where possible
- Screening questions scoped to covered material only

---

## Table of Contents

1. [GitHub Repository Finalization](#1-github-repository-finalization)
2. [Week 3 Stack Summary](#2-week-3-stack-summary)
3. [Screening Questions and Honest Assessment](#3-screening-questions-and-honest-assessment)
4. [Gap Analysis](#4-gap-analysis)
5. [Revised Lab Track](#5-revised-lab-track)
6. [Week 4 Scope](#6-week-4-scope)
7. [Advanced Topics Carried Forward](#7-advanced-topics-carried-forward)
8. [Reference Material](#8-reference-material)

---

## 1. GitHub Repository Finalization

### Final Repository Structure

```
grafana-observability-lab/
├── README.md                                    ← Updated — Week 3 complete, Week 4 in progress
├── week1/                                       ← Unchanged
├── week2/
│   ├── README.md                                ← Renamed from week2-README.md
│   └── ...
└── week3/
    ├── README.md                                ← New — full Week 3 lab guide
    ├── docker-compose.yml
    ├── tempo-config.yml
    ├── otel-collector-config.yml
    ├── app/
    │   ├── app.py
    │   ├── requirements.txt
    │   └── Dockerfile
    ├── tempo-otel-week3-day1-reference.md
    ├── tempo-otel-week3-day2-reference.md
    └── tempo-otel-week3-day3-reference.md
```

> **Fix required:** `week2/week2-README.md` should be renamed to `week2/README.md` for GitHub to render it as the directory README:
> ```bash
> cd ~/grafana-lab/week2
> git mv week2-README.md README.md
> git commit -m "fix: rename week2 README to render correctly on GitHub"
> ```

### What the Week 3 Repository Demonstrates to a Reviewer

- A working distributed trace pipeline reproducible from configuration files
- Python Flask application with both OTel auto-instrumentation and manual spans
- Prometheus metrics on the same application with cardinality anti-pattern identified and fixed
- TraceQL queries documented with real lab results
- Three-pillar correlation workflow — metrics, logs, and traces from one application
- Documented architectural decisions including version pinning rationale and production best practice deviations

---

## 2. Week 3 Stack Summary

### What Is Running

| Component | Role | Port |
|---|---|---|
| Prometheus | Metrics collection and rule evaluation | 9090 |
| Grafana | Visualization — three data sources | 3000 |
| Node Exporter | Host metrics | 9100 |
| Loki | Log storage | 3100 |
| Alloy | Container log collection | 12345 |
| Tempo | Trace storage | 3200 |
| OTel Collector | Trace collection from order-api | 4319/4320 |
| order-api | Flask app — metrics, logs, traces | 5000 |

### The order-api Application

**Three signals from one application:**

| Signal | How collected | Where stored | Query tool |
|---|---|---|---|
| Metrics | `/metrics` endpoint scraped by Prometheus | Prometheus TSDB | PromQL |
| Logs | stdout collected by Alloy | Loki | LogQL |
| Traces | OTLP exported to OTel Collector → Tempo | Tempo | TraceQL |

**Endpoints and span structure:**

| Endpoint | Spans | Notes |
|---|---|---|
| GET /health | 1 | Health check only |
| GET /orders | 2 | Root + 1 DB query |
| GET /orders/\<id\> | 4 | Root + 2 DB queries + pricing call |
| POST /orders/checkout | 8 | Root + 2 DB + 3 external + 1 DB write |

**10% slow path:** `external.tax-service` has a 10% probability of triggering a 500ms artificial delay. Set via `span.set_attribute("slow_call", True)` — queryable in TraceQL as `{span.slow_call=true}`.

### Key Lab Results

| Finding | Value | Notes |
|---|---|---|
| Checkout duration range | 287ms — 951ms | Tax service slow calls drive the high end |
| slow_call traces per 20 requests | ~4 (20%) | Higher than 10% probability — small sample variance |
| tax-service >200ms traces | 12 across two bursts | Confirmed slow path detection working |
| Histogram p99 checkout | ~2.05s | Flat due to burst traffic pattern — moves with continuous traffic |
| Cardinality fix | path → endpoint label | Prevents one series per unique URL path |

### Operational Lessons

| Lesson | Context |
|---|---|
| Tempo v2.10 requires Kafka | Pin to v2.6.1 for simple deployments |
| Tempo ingester 15s warm-up | `/ready` returns not ready during warm-up — expected |
| OTel Collector `logging` exporter removed | Use `debug` exporter in current versions |
| block_retention must match investigation window | Initially 1h — traces expired before Day 3 queries. Extended to 24h |
| prometheus-flask-exporter path label | Causes cardinality explosion for URL parameter endpoints. Fix: `group_by='endpoint'` |
| BatchSpanProcessor required | SimpleSpanProcessor blocks request handling — never use in production |

---

## 3. Screening Questions and Honest Assessment

---

### Q1: Application feels slow, error rate and CPU metrics look normal — how do you investigate?

**Answer summary:** Customer conversation first — understand the application, external dependencies, demo the slowness. Walk through current monitoring to identify gaps. Determine if traces are missing and involve dev team for instrumentation if needed.

**Assessment — Strong customer framing, corrected feedback:**

Initial feedback incorrectly penalized for not covering existing signal investigation and quantifying "slow" — both were in the answer. Corrected assessment:

**Genuinely missing:**
- Naming the specific value traces add — why traces solve this problem, not just that they are missing. The answer is: traces show individual span durations across all service calls, identifying exactly which external dependency is adding latency
- The external dependency connection — the question about dependencies should have been explicitly connected to the likely root cause: normal metrics, no errors, but a slow external call (the lab scenario exactly)

---

### Q2: Difference between span attribute and resource attribute in OpenTelemetry?

**Answer summary:** Resource attributes describe the trace level/resource. Span attributes describe the specific span.

**Assessment — Correct direction, needed more precision:**

**Missing precision:**
- Resource attributes describe the **service or process** that produced the telemetry — not the trace. The resource is constant across all spans from a given service instance
- The one-sentence definition: resource attributes answer "who produced this?" — service name, version, environment. Span attributes answer "what happened in this specific operation?" — varying values per execution
- TraceQL prefix behavior — `resource.service.name` vs `span.peer.service` vs intrinsic `duration`. Using the wrong prefix returns no results

```python
# Resource — same for every span from this service
resource = Resource(attributes={
    "service.name": "order-api",
    "service.version": "1.0.0"
})

# Span — different for every execution
span.set_attribute("order.id", order_id)
span.set_attribute("db.rows_returned", count)
```

---

### Q3: Should customer use Grafana Alloy or OTel Collector for trace collection?

**Answer summary:** Requirements-dependent. Check existing instrumentation. Alloy preferred for pure Grafana LGTM. OTel Collector for multi-vendor or vendor-neutral requirements.

**Assessment — Strongest answer of the week. Complete and senior-level:**

**Minor gaps:**
- Coexistence pattern — many production environments run both. OTel Collector near applications, Alloy for infrastructure collection, handing off to each other. Not always either/or
- Configuration model difference — Alloy uses HCL, OTel Collector uses YAML. Teams with existing OTel expertise face a learning curve migrating to Alloy
- Promtail/Grafana Agent migration — if customer is on deprecated components that is a separate related conversation

---

### Q4: What is TraceQL and when would you use it over the Tempo search UI?

**Answer summary:** Query syntax for searching Tempo span data. Filters by resource, span, and intrinsic attributes. Used to filter and narrow investigation.

**Assessment — Definition solid, concrete scenario missing:**

**Missing:**
- The specific boundary — the UI covers basic filtering (service name, duration, time). TraceQL is needed for custom application span attributes. The UI cannot express `{span.slow_call=true}` or `{span.peer.service="tax-service" && duration>200ms}`
- Pipeline operator as a UI-impossible capability — `| count() > 5`, `| avg(duration) > 100ms` — no UI equivalent

**The key example:** `{span.peer.service="tax-service" && duration>200ms}` immediately isolates traces where that specific dependency was slow without manually clicking through every trace. The UI cannot express this.

---

### Q5: Instrumenting a Python web application with OTel for the first time — what decisions before writing code?

**Answer summary:** Audit existing instrumentation. Understand framework and dependencies. Develop monitoring schema for reuse. Determine destination platform. Scope signals.

**Assessment — Strongest answer across all three weeks:**

**Minor gaps:**
- Sampling strategy — head vs tail, percentage, always-sample-errors policy. Must be decided before TracerProvider initialization
- Resource attribute schema — `service.name` naming convention must be consistent across all services before any instrumentation ships
- Cardinality governance for span attributes — policy for what goes in attributes, especially if metrics are also being generated from the same instrumentation
- Auto vs manual instrumentation boundary — which operations get manual spans

---

## 4. Gap Analysis

### Consistent Gaps

**Quantification — still the primary gap across all three weeks**

Present but not as severe in Week 3 — the tracing and instrumentation questions are less amenable to hard numbers than the Prometheus cardinality questions. The places where quantification would strengthen answers: sampling percentages, trace volume at scale, retention requirements.

**Concrete scenario specificity**

Several answers were directionally correct but stopped short of the specific example that demonstrates hands-on experience. The TraceQL question is the clearest case — knowing what the UI cannot do (custom span attribute filtering) is the detail that separates someone who used it in a lab from someone who read about it.

**Pre-implementation decisions**

Q5 showed the right instinct but sampling strategy, resource attribute schema, and cardinality governance are the three technical pre-code decisions consistently missing. These are the decisions that prevent problems in production that are painful to fix after instrumentation is deployed at scale.

### What Is Solid

- Customer conversation framing — consistently strong across all three weeks
- Architectural judgment — Alloy vs OTel Collector answer was the clearest response of all three weeks
- Knowing when to escalate and when to involve other teams
- Understanding the three-pillar relationship — metrics detect, logs rule out, traces identify
- Pre-work thinking — instinct to audit existing state before recommending anything

### Improvement Trajectory

Weeks 1 → 2 → 3 shows consistent improvement in:
- Answer structure and completeness
- Customer framing confidence
- Knowing when to push back on feedback (Q1 correction was appropriate)

Quantification remains the consistent gap but is less critical for tracing topics than for infrastructure topics.

---

## 5. Revised Lab Track

The five-week deadline is removed. Each week completes when the content is solid.

| Week | Focus | Status |
|---|---|---|
| 1 | Prometheus + Grafana + Node Exporter | ✅ Complete |
| 2 | Loki + Grafana Alloy | ✅ Complete |
| 3 | Tempo + OTel Collector + Flask app | ✅ Complete |
| 4 | Alloy-only tracing + meta-observability | 🔄 Next |
| 5 | Alertmanager + Mimir | Planned |
| 6 | OpenTelemetry deep dive | Planned |
| 7 | Kubernetes + LGTM on K8s | Planned |
| 8 | Consolidation + interview prep | Planned |

**Rationale for Week 4 change:**

Week 3 ran both Grafana Alloy and the OTel Collector simultaneously — not the standard production Grafana Labs pattern. Week 4 corrects this by rebuilding the trace pipeline using only Alloy. Adding meta-observability (the platform monitoring itself) alongside this makes it a stronger portfolio artifact and a better customer demonstration scenario than simply repeating the tracing work with a different collector.

---

## 6. Week 4 Scope

### Goal

Build a clean production-representative stack where Alloy is the single collector for all telemetry signals — logs, metrics, and traces. Add meta-observability so the Grafana stack monitors its own health using the same tools used to monitor applications.

### What Gets Built

**Single Alloy pipeline handling:**
- Container log collection → Loki (carried forward from Week 2)
- Component metrics scraping → Prometheus (Alloy scraping Loki, Tempo, itself)
- Trace collection from order-api → Tempo (replacing OTel Collector)

**Meta-observability:**
- Alloy self-metrics scraped by Prometheus
- Alloy pipeline traces — Alloy emitting OTel traces for its own internal operations
- Full stack health dashboard — every LGTM component monitored via its `/metrics` endpoint

### Week 4 Day Plan

| Day | Topics | Primary Deliverable |
|---|---|---|
| 1 | Alloy trace pipeline concepts, Alloy OTLP receiver configuration, replace OTel Collector | Alloy receiving and forwarding traces to Tempo |
| 2 | Meta-observability — stack self-monitoring, Alloy self-metrics, component health dashboard | Dashboard showing health of every LGTM component |
| 3 | Alloy pipeline traces, full three-pillar correlation with Alloy-only stack | Alloy pipeline traces visible in Tempo alongside Flask app traces |
| 4 | Consolidation — repo update, review, screening questions, Week 5 scope | Clean repo, Week 4 reference documents |

### What Carries Forward

- The order-api Flask application — unchanged, same instrumentation
- Loki, Tempo, Prometheus, Grafana — same backends
- Week 2 Alloy config — extended with OTLP receiver and metrics scraping components
- All existing dashboards and alert rules

### Week 4 Directory Target

```
grafana-observability-lab/
└── week4/
    ├── README.md
    ├── docker-compose.yml       ← OTel Collector removed, Alloy config extended
    ├── alloy-config.alloy       ← Extended: logs + metrics scraping + trace collection
    ├── tempo-config.yml         ← Carried from week3
    └── dashboards/
        └── stack-health.json    ← Grafana dashboard for LGTM component health
```

---

## 7. Advanced Topics Carried Forward

Full cumulative list.

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
| **Tail sampling in OTel Collector** | Keep errors and slow traces, drop normal traffic. | Week 3 Day 2 |
| **Loki stream label vs structured metadata** | What is indexed vs metadata. | Week 2 Day 3 |
| **Tempo metrics generator** | Derives RED metrics from traces. Full Prometheus cardinality constraints apply. | Week 3 Day 1 |
| **Exemplars** — metrics to traces link | Direct link from Prometheus metric to specific trace ID. | Week 3 Day 3 |
| **Meta-observability** — stack self-monitoring | Platform monitoring itself. Week 4 primary topic. | Week 3 Day 3 |
| **TraceQL advanced patterns** | Service graph queries, span set operations, metrics from traces. | Week 3 Day 3 |
| **prometheus-flask-exporter cardinality** | path vs endpoint grouping anti-pattern found and fixed in lab. | Week 3 Day 3 |
| **OpenTelemetry deep dive** — sampling, multi-language, Collector in depth | OTel as its own topic. Week 6. | Week 3 Day 2 |
| **Kubernetes + LGTM on K8s** | CKA track + deploying full stack in Kubernetes. Week 7. | Lab planning |

---

## 8. Reference Material

### Week 4 Preparation

| Resource | URL | Notes |
|---|---|---|
| Alloy OTLP receiver | https://grafana.com/docs/alloy/latest/reference/components/otelcol.receiver.otlp/ | Receiving traces in Alloy |
| Alloy trace pipeline | https://grafana.com/docs/alloy/latest/reference/components/otelcol.exporter.otlp/ | Forwarding traces to Tempo |
| Alloy self-monitoring | https://grafana.com/docs/alloy/latest/monitor/ | Alloy metrics and pipeline traces |
| Grafana dashboards for LGTM | https://grafana.com/grafana/dashboards/ | Community dashboards for stack health |
| Loki operational dashboard | https://grafana.com/grafana/dashboards/14055 | Official Loki monitoring dashboard |

### Week 3 Reference

| Resource | URL | Notes |
|---|---|---|
| TraceQL documentation | https://grafana.com/docs/tempo/latest/traceql/ | Full query language reference |
| OpenTelemetry Python SDK | https://opentelemetry.io/docs/languages/python/ | Auto and manual instrumentation |
| OTel Python contrib libraries | https://opentelemetry-python-contrib.readthedocs.io/en/latest/ | Full auto-instrumentation library list |
| Tempo configuration reference | https://grafana.com/docs/tempo/latest/configuration/ | Full schema including compactor retention |
| prometheus-flask-exporter | https://github.com/rycus86/prometheus_flask_exporter | group_by configuration |
| Exemplars in Prometheus | https://prometheus.io/docs/prometheus/latest/exemplars/ | Metrics to traces link |

### Screening Preparation

| Resource | URL | Notes |
|---|---|---|
| Grafana Alloy vs OTel Collector | https://grafana.com/docs/alloy/latest/concepts/component-controller/ | Alloy architecture and design decisions |
| OpenTelemetry sampling | https://opentelemetry.io/docs/concepts/sampling/ | Head vs tail sampling — pre-code decision |
| Tempo getting started | https://grafana.com/docs/tempo/latest/getting-started/ | Quick reference for Tempo concepts |

---

*Week 3 complete. Week 4: Alloy-only tracing + meta-observability — the production Grafana pattern with the platform monitoring itself.*

# Loki + Grafana Alloy — Week 2 Day 4 Consolidation Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Finalize the Week 2 GitHub repository as a portfolio artifact
- Review Week 2 content at a level sufficient for a screening conversation
- Identify honest gaps and areas needing reinforcement
- Scope Week 3 — Tempo + OpenTelemetry

### Working Parameters
- Direct, no filler, factually accurate
- Honest gap assessment — no overclaiming
- Quantification tied to observable indicators where possible
- Screening questions scoped to covered material only

---

## Table of Contents

1. [GitHub Repository Finalization](#1-github-repository-finalization)
2. [Week 2 Stack Summary](#2-week-2-stack-summary)
3. [Screening Questions and Honest Assessment](#3-screening-questions-and-honest-assessment)
4. [Gap Analysis](#4-gap-analysis)
5. [Advanced Topics Carried Forward](#5-advanced-topics-carried-forward)
6. [Week 3 Scope](#6-week-3-scope)
7. [Reference Material](#7-reference-material)

---

## 1. GitHub Repository Finalization

### Final Repository Structure

```
grafana-observability-lab/
├── README.md                              ← Updated — Week 2 complete
├── week1/                                 ← Unchanged
│   ├── README.md
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   ├── recording_rules.yml
│   ├── alerting_rules.yml
│   ├── prometheus-day2-reference.md
│   ├── prometheus-day3-reference.md
│   ├── prometheus-day4-reference.md
│   ├── prometheus-day5-reference.md
│   └── week1-grafana-prometheus-lab.md
└── week2/
    ├── README.md                          ← New — full Week 2 lab guide
    ├── docker-compose.yml
    ├── loki-config.yml
    ├── alloy-config.alloy
    ├── loki-rules/
    │   └── log_alerts.yml
    ├── loki-alloy-week2-day1-reference.md
    ├── loki-alloy-week2-day2-reference.md
    └── loki-alloy-week2-day3-reference.md
```

### What the Week 2 Repository Demonstrates to a Reviewer

- A working Loki + Alloy log pipeline reproducible from configuration files alone
- Grafana Alloy component-based pipeline — discovery, relabeling, and push to Loki
- Two Loki alerting rules with documented design decisions including a real false positive diagnosis and fix
- A unified Grafana dashboard combining Prometheus metrics and Loki log panels
- Day reference documents showing depth of understanding beyond running the stack
- Documented operational lessons — self-triggering alerts, localhost Docker gotcha, stream labels vs structured metadata

---

## 2. Week 2 Stack Summary

### What Is Running

| Component | Role | Port |
|---|---|---|
| Prometheus | Metrics collection, TSDB storage, rule evaluation | 9090 |
| Grafana | Visualization, dashboarding, Explore mode | 3000 |
| Node Exporter | Host system metrics | 9100 |
| Loki | Log aggregation, storage, rule evaluation | 3100 |
| Alloy | Telemetry collector — discovers containers, collects logs, ships to Loki | 12345 |

### What Was Built

**Alloy pipeline — four components:**

| Component | Function |
|---|---|
| `discovery.docker` | Discovers running Docker containers via Docker socket |
| `loki.relabel` | Extracts `container` and `service` labels from Docker metadata |
| `loki.source.docker` | Reads log output from discovered containers |
| `loki.write` | Pushes labeled log streams to Loki at `http://loki:3100` |

**Loki stream schema — three indexed labels:**

```
{"status":"success","data":["container","service","service_name"]}
```

**Loki alerting rules:**

| Alert | Expression | For | Severity | Note |
|---|---|---|---|---|
| HighLogErrorRate | `rate({container=~".+"} \|= "error" [5m]) > 0.5` | 5m | warning | |
| FatalLogEvent | `count_over_time({...} \|~ "fatal\|panic..." !~ "caller=metrics.go\|caller=evaluator" [5m]) > 0` | 1m | critical | Exclusion pattern required to prevent self-triggering false positive |

**Stack Observability dashboard — five panels:**

| Panel | Data source | Visualization |
|---|---|---|
| Log Ingestion Rate | Loki | Time series |
| Log Error Rate | Loki | Time series |
| Warnings and Errors | Loki | Logs |
| CPU Utilization | Prometheus | Time series |
| Total Errors (1h) | Loki | Stat |

Dashboard variable: `container` — query type, `label_values(container)`, Include All with custom value `.+`

### Key Lab Observations

| Observation | Explanation |
|---|---|
| Loki highest log volume at ~1.5 lines/sec | Loki self-logs ingest, compaction, and query operations |
| Loki ~50 minute error count cycle | Compaction cycle — scheduled internal process, not a fault |
| `detected_level` not in `/api/v1/labels` | Structured metadata, not an indexed stream label in this configuration |
| FatalLogEvent false positive | Ruler logs its own query string containing "panic" — self-triggering |
| Alertmanager connection refused | Expected — Alertmanager not deployed until Week 4 |

---

## 3. Screening Questions and Honest Assessment

---

### Q1: ELK customer evaluating Loki — what tradeoffs would you walk them through?

**Answer summary:** ELK indexes full log lines — higher compute and storage. Loki indexes only labels — lower cost but requires format awareness. Ask about specific use cases before recommending.

**Assessment — Solid foundation, missing quantification and explicit limitations:**
- Core architectural difference correctly identified
- Right instinct to ask about use cases before recommending
- **Missing:** Quantification — Loki typically achieves 3-10x better storage efficiency. At 1TB/day ingest that difference is $50,000-$200,000/year in storage costs
- **Missing:** Query performance specificity — Elasticsearch full-text search is faster because everything is pre-indexed. LogQL line filters scan raw data — slower for ad-hoc queries across unknown fields
- **Missing:** Operational complexity difference — ELK requires significant cluster management engineering. Loki is simpler to operate
- **Missing:** Where Loki is the wrong choice — SIEM, heavy ad-hoc forensic search, unstructured log sources with no label design possible

---

### Q2: What is a Loki stream and why does cardinality matter?

**Answer summary:** Correctly identified push model and pipeline model but did not land on the precise definition of a stream.

**Assessment — Understanding present, precise definition missing:**
- Cardinality principles correctly applied — bounded labels, performance and memory impact
- Pipeline model description accurate
- **Missing:** A stream is a unique label set plus its associated log lines — analogous to a Prometheus time series
- **Missing:** Multiplicative cardinality — 5 containers × 5 levels × 3 environments = 75 streams
- **Missing:** Labels are the only thing indexed — stream selection is cheap, line filtering is expensive because it scans compressed content within selected streams

**The one-sentence definition to know:** A Loki stream is a unique combination of label key-value pairs and the log lines associated with that label set — every unique label combination is a separate stream stored and indexed independently.

---

### Q3: Loki query running slowly — diagnostic process?

**Answer summary:** Establish baseline, check label cardinality, narrow scope, evaluate line filter efficiency, mention query inspector.

**Assessment — Strong structured answer, missing specific tools:**
- Establishing baseline and asking about recent changes — correct first move
- Scope narrowing approach — correct
- Line filter efficiency and edge filtering suggestion — operationally mature
- Honest acknowledgment of query inspector without overclaiming — appropriate
- **Missing:** Check time range first — broad time windows are the most common cause of slow queries and the quickest to check
- **Missing:** Check stream count before investigating query structure — `count(count_over_time({job=~".+"}[5m]))` shows how many streams the selector matches
- **Missing:** Loki query logs — every query execution logs `total_bytes`, `duration`, `lines_per_second`. These fields are the primary performance diagnostic. Seen in ruler evaluation logs during Day 3.
- **Missing:** Specific diagnostic endpoints — `/api/v1/labels`, `/api/v1/label/<n>/values`

---

### Q4: What is Grafana Alloy and why does it matter that it replaced Promtail?

**Answer summary:** Multi-signal collector replacing log-only Promtail. Deprecation means customers need a migration plan.

**Assessment — Accurate, missing architectural significance and completeness:**
- Multi-signal capability correctly identified
- Deprecation and migration need correctly emphasized
- **Missing:** Alloy also replaced the Grafana Agent — two deprecated components, not one
- **Missing:** The pipeline model significance — composable, auditable, each component does one thing
- **Missing:** Single agent for the full LGTM stack — one deployment replaces multiple previous agents
- **Missing:** Migration is a configuration translation — concepts map directly, Grafana provides documented migration paths

---

### Q5: Customer wants to alert on a specific error message in logs, no Prometheus metrics exist — how would you implement this?

**Answer summary:** Loki alerting rule. Review existing configuration, LogQL performance, alerting requirements, complementary Prometheus metrics, and template reusability.

**Assessment — Strongest answer across both weeks. Complete and senior-level:**
- Correct mechanism identified immediately
- Customer conversation framing before implementation — right instinct
- LogQL performance review before committing — correct
- `for` clause considerations framed as business requirements — correct
- Acknowledging Alertmanager without overclaiming — appropriate
- Prometheus metrics for context — thinking beyond the immediate ask
- Template question — thinking at scale, not just solving one problem
- **Minor gap:** Explicit false positive risk — log-based alerts need careful expression design. Self-triggering patterns are a real risk (demonstrated in lab)
- **Minor gap:** Log pipeline health dependency — if Alloy or Loki goes down this alert goes silent. Recommend complementary pipeline health alert

---

## 4. Gap Analysis

### Consistent Gaps

**Quantification — still the primary gap**

Consistent across both weeks. The ELK vs Loki answer needed storage efficiency numbers. The stream cardinality answer needed the multiplication math.

Key numbers worth retaining for Loki conversations:

| Metric | Value |
|---|---|
| Loki storage efficiency vs Elasticsearch | ~3-10x better for equivalent log volume |
| Stream memory overhead | Scales with number of active streams in ingester |
| Loki single-node ingest limit | ~1-2 MB/s sustained — beyond this requires distributed mode |
| Default Loki retention | Configured per deployment — no universal default like Prometheus 15 days |

**Precise terminology**

"Stream" definition was the specific gap this week. In an interview with a Grafana Labs engineer using imprecise terminology for core concepts is noticeable. The fix is the one-sentence definition: a stream is a unique label set and its associated log lines.

**Naming specific diagnostic tools**

Instincts are correct but naming the specific endpoint or command strengthens answers. `/api/v1/labels`, `/api/v1/label/<n>/values`, Loki query logs with `total_bytes` and `duration` fields.

### What Is Solid

- Customer conversation framing — consistently asking about context before recommending
- Understanding when Loki is and is not the right tool
- Alert design principles — `for` clause, false positive risk, pipeline health dependency
- LogQL query structure and performance principles
- Alloy pipeline model and deprecation context
- Knowing when to escalate or bring in additional resources

### Improvement From Week 1

Noticeable improvement in structured diagnostic answers and customer conversation framing. The implementation question (Q5) was the strongest answer across both weeks. Quantification remains the consistent gap.

---

## 5. Advanced Topics Carried Forward

Full cumulative list from Weeks 1 and 2.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, native histograms | Significant cardinality source. Native histograms change storage model. | Week 1 Day 2 |
| **Recording rules** — advanced design and performance at scale | Rule evaluation performance, dependencies, federation. | Week 1 Day 2 |
| **SNMP exporter** — Counter32 vs Counter64 OID selection | Migration gap from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing and inhibition | Full deployment, routing trees, inhibition rules. Week 4 topic. | Week 1 Day 3 |
| **Prometheus CI/CD integration** — promtool in pipelines | Instrumentation validation before deployment. | Week 1 Day 3 |
| **Grafana Enterprise features** — caching, RBAC, reporting | Large organization deployment relevance. | Week 1 Day 4 |
| **Loki distributed mode** — scaling beyond single node | Single-node has ingest and query limits. | Week 2 Day 1 |
| **LogQL parsing stages** — full parser reference | Additional parsers — pattern, regexp, unpack. | Week 2 Day 2 |
| **Promtail to Alloy migration** — customer migration path | Customers on Promtail need documented migration path. | Week 2 Day 1 |
| **Loki recording rules** — configuration and use cases | Pre-computing log-derived metrics. | Week 2 Day 2 |
| **Alloy pipeline processing stages** — drop, label extraction | Edge filtering and label extraction at ingest. | Week 2 Day 2 |
| **Self-triggering alert patterns** — detection and prevention | Monitoring systems can match their own query strings. | Week 2 Day 3 |
| **Loki stream label vs structured metadata** — promotion strategies | What is indexed vs what is metadata. Affects query design. | Week 2 Day 3 |

---

## 6. Week 3 Scope

### Goal

Add distributed tracing to the stack. Understand the third pillar of observability. Instrument a Python application with OpenTelemetry and correlate traces with the existing metrics and logs.

### Components Being Added

| Component | Role |
|---|---|
| Tempo | Distributed trace storage and querying — the T in LGTM |
| OpenTelemetry Collector | Vendor-neutral telemetry collection — receives traces from instrumented applications |
| Instrumented Python app | Simple Flask application emitting traces via OpenTelemetry SDK |

### Why This Matters for the Grafana Role

Distributed tracing is the third pillar of observability alongside metrics and logs. OpenTelemetry is increasingly the industry standard for instrumentation — vendor-neutral, widely adopted, and explicitly listed in the Senior Observability Architect job requirements. Week 3 closes that gap directly.

### Week 3 Day Plan

| Day | Topics | Primary Deliverable |
|---|---|---|
| 1 | Tempo concepts, trace data model, stack setup | Running Tempo + OTel Collector, traces visible in Grafana |
| 2 | Python app instrumentation with OpenTelemetry | Instrumented Flask app emitting traces |
| 3 | Correlating traces, metrics, and logs — exemplars, TraceQL, full three-pillar workflow | Grafana Explore showing all three signals for one request |
| 4 | Consolidation — repo update, review, screening questions, Week 4 scope | Clean repo, Week 3 reference documents |

### What Carries Forward From Week 2

- The existing Docker Compose stack — Tempo and OTel Collector are additions
- The Grafana Explore split view pattern — extended to three-way correlation
- The label consistency principle — traces use service name labels consistent with Prometheus and Loki
- The Alloy pipeline — Alloy can receive and forward traces as well as logs

### Week 3 Directory Target

```
grafana-observability-lab/
└── week3/
    ├── README.md
    ├── docker-compose.yml
    ├── tempo-config.yml
    ├── otel-collector-config.yml
    └── app/
        ├── app.py
        └── requirements.txt
```

---

## 7. Reference Material

### Week 3 Preparation

| Resource | URL | Notes |
|---|---|---|
| Tempo documentation | https://grafana.com/docs/tempo/latest/ | Authoritative — covers TraceQL, storage, configuration |
| OpenTelemetry documentation | https://opentelemetry.io/docs/ | Vendor-neutral instrumentation standard |
| OpenTelemetry Python SDK | https://opentelemetry.io/docs/languages/python/ | Python instrumentation — auto and manual |
| TraceQL documentation | https://grafana.com/docs/tempo/latest/traceql/ | Tempo's query language |
| Exemplars in Prometheus | https://prometheus.io/docs/prometheus/latest/exemplars/ | Metrics-to-traces link — covered in Week 3 |

### Loki and Alloy — Week 2 Reference

| Resource | URL | Notes |
|---|---|---|
| Loki documentation | https://grafana.com/docs/loki/latest/ | Authoritative |
| LogQL best practices | https://grafana.com/docs/loki/latest/query/bp-query/ | Performance guidance |
| Loki alerting rules | https://grafana.com/docs/loki/latest/rules/ | Rule syntax and ruler configuration |
| Loki labels best practices | https://grafana.com/docs/loki/latest/get-started/labels/best-practices/ | Stream cardinality guidance |
| Alloy documentation | https://grafana.com/docs/alloy/latest/ | Component reference and pipeline configuration |
| Promtail to Alloy migration | https://grafana.com/docs/alloy/latest/tasks/migrate/from-promtail/ | Customer migration path |
| Loki structured metadata | https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/ | Stream labels vs metadata distinction |

### Screening Preparation

| Resource | URL | Notes |
|---|---|---|
| Grafana Labs blog — Loki | https://grafana.com/blog/category/loki/ | Current Loki developments and customer use cases |
| Loki vs Elasticsearch | https://grafana.com/docs/loki/latest/get-started/overview/ | Authoritative comparison |
| LGTM stack overview | https://grafana.com/about/press/2022/06/09/announcing-the-lgtm-stack-grafana-loki-tempo-and-mimir/ | Full stack context |

---

*Week 2 complete. Week 3: Tempo + OpenTelemetry — distributed tracing, Python instrumentation, and three-pillar correlation.*

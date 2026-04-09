# Week 1 Consolidation — Day 5 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Finalize the GitHub repository as a portfolio artifact
- Review Week 1 content at a level sufficient for a screening conversation
- Identify honest gaps and areas needing reinforcement
- Scope Week 2 — Loki + Grafana Alloy

### Working Parameters
- Direct, no filler, factually accurate
- Honest gap assessment — no overclaiming
- Quantification tied to observable indicators where possible
- Screening questions scoped to covered material only

---

## Table of Contents

1. [GitHub Repository Finalization](#1-github-repository-finalization)
2. [Week 1 Stack Summary](#2-week-1-stack-summary)
3. [Screening Questions and Honest Assessment](#3-screening-questions-and-honest-assessment)
4. [Gap Analysis](#4-gap-analysis)
5. [Advanced Topics Carried Forward](#5-advanced-topics-carried-forward)
6. [Week 2 Scope](#6-week-2-scope)
7. [Reference Material](#7-reference-material)

---

## 1. GitHub Repository Finalization

### Final Repository Structure

```
grafana-observability-lab/
├── README.md                        ← Project overview, stack status, key decisions
└── week1/
    ├── README.md                    ← Full Week 1 lab guide — setup through alerting rules
    ├── docker-compose.yml           ← Stack definition
    ├── prometheus.yml               ← Scrape and evaluation config
    ├── recording_rules.yml          ← Pre-computed PromQL expressions
    ├── alerting_rules.yml           ← Infrastructure alerting rules
    ├── prometheus-day2-reference.md ← Prometheus internals deep dive
    ├── prometheus-day3-reference.md ← PromQL and recording rules deep dive
    ├── prometheus-day4-reference.md ← Grafana and alerting deep dive
    └── week1-grafana-prometheus-lab.md ← Original Day 1 setup document
```

### What the Repository Demonstrates to a Reviewer

- A working Prometheus + Grafana + Node Exporter stack reproducible from configuration files alone
- Recording rules pre-computing CPU, memory, and filesystem utilization
- Alerting rules covering five infrastructure conditions with appropriate `for` durations and severity labels
- A dynamic Grafana dashboard using variables — scales to any fleet size without modification
- Day reference documents showing depth of understanding beyond just running the stack
- Documented decisions — why each technical choice was made, not just what was done

---

## 2. Week 1 Stack Summary

### What Is Running

| Component | Role | Port |
|---|---|---|
| Prometheus | Metrics collection, TSDB storage, rule evaluation | 9090 |
| Grafana | Visualization, dashboarding, Explore mode | 3000 |
| Node Exporter | Host system metrics — CPU, memory, disk, network | 9100 |

### What Was Built

**Recording rules — three pre-computed metrics:**

| Metric | Expression summary | Evaluation interval |
|---|---|---|
| `instance:node_cpu_utilization:avg_rate5m` | CPU usage % per instance | 1 minute |
| `instance:node_memory_utilization:ratio` | Memory utilization ratio | 1 minute |
| `instance:node_filesystem_utilization:ratio` | Filesystem utilization ratio | 1 minute |

**Alerting rules — five infrastructure alerts:**

| Alert | Condition | For | Severity |
|---|---|---|---|
| HighCPUUsage | CPU > 80% | 5m | warning |
| HighMemoryUsage | Memory > 85% | 5m | warning |
| DiskFilling | Disk > 80% | 15m | warning |
| InstanceDown | `up == 0` | 1m | critical |
| InstanceMissing | `absent(up{job="node-exporter"})` | 2m | critical |

**Grafana dashboard — Host Infrastructure:**
- Four panels: CPU, memory, disk, network
- Two variables: `instance` (query), `job` (query, chained to instance)
- All panel queries use `$instance` variable — dynamic, fleet-scalable

### Lab Metrics at Week 1 Close

| Metric | Value |
|---|---|
| Active series | ~2,654 |
| Persistent blocks | 5 |
| WAL segments | 3 active |
| Total on-disk storage | ~23MB |
| Compactions run | 7 |
| CPU utilization | ~8% |
| Memory utilization | ~60.6% |
| Disk utilization | ~21.96% |

---

## 3. Screening Questions and Honest Assessment

Questions were scoped to Week 1 covered material. Format: question asked, summary of answer given, honest assessment.

---

### Q1: Large Kubernetes cluster with thousands of short-lived pods — what concerns would you raise about using Prometheus?

**Answer summary:** High churn from ephemeral pods impacts storage. Prometheus may work as a proof-of-concept but Mimir or similar platforms are needed for production scale and data reliability.

**Assessment — Solid foundation, missing depth:**
- Core concern correctly identified — churn from pod restarts
- Storage impact correctly noted
- Mimir as forward path correctly named
- **Missing:** Memory pressure is the more immediate concern than storage — stale series remain in the head block before aging out. At 100-500 new series per second on a large cluster, head block memory exhaustion precedes storage exhaustion
- **Missing:** Kubernetes label anti-patterns — pod ID, container ID as labels compound the memory problem beyond churn alone
- **Missing:** Single-node HA gap — no replication means losing monitoring during an incident
- **Missing:** Quantification — 1,000 pods with frequent restarts generates ~100-500 series/second, ~8-43 million new series per day

---

### Q2: Dashboard working for months suddenly shows no data on three of four panels — diagnostic process?

**Answer summary:** Check data sources, check for performance issues, check query timeout, check cardinality.

**Assessment — Right territory, missing specific steps:**
- Data source availability check is correct first move
- Query performance and cardinality correctly identified
- **Missing:** The working panel is the most important clue — what is structurally different about the one that works narrows the cause immediately
- **Missing:** Run the broken panel PromQL directly in the Prometheus UI — separates Grafana problem from Prometheus problem in one step
- **Missing:** Check `/rules` endpoint — if broken panels use recorded metrics, confirm rules are evaluating with `health: ok`
- **Missing:** Ask what changed recently — months of working then sudden failure is almost always caused by a change

**Correct diagnostic sequence:**
1. Compare working panel to broken panels — what is different
2. Run broken panel PromQL directly in Prometheus UI
3. Check `http://localhost:9090/targets` — scrape target health
4. Check `http://localhost:9090/rules` — recording rule health
5. Ask what changed recently
6. Check browser console for query errors not visible in panel UI

---

### Q3: What is cardinality in Prometheus and why does it matter?

**Answer summary:** Number of unique combinations of label values. Affects query performance, memory, and storage.

**Assessment — Correct definition, missing mechanics and quantification:**
- Definition accurate
- Impact on performance, memory, storage correctly noted
- **Missing:** Multiplicative nature — 10 hosts × 8 modes × 22 CPUs = 1,760 series from one metric. Not additive
- **Missing:** Memory is the primary concern — ~3-4KB per active series in head block. 1 million series = 3-4GB RAM
- **Missing:** The specific anti-pattern — labels with unbounded unique values (user IDs, UUIDs, full URLs) create a new series per unique value
- **Missing:** Quantified threshold — Prometheus recommends staying under 10 million active series per instance for reliable performance

---

### Q4: What is the difference between a recording rule and an alerting rule?

**Answer summary:** Recording rule stores PromQL result as a new metric. Alerting rule has three states (inactive, primed, fired), `for` clause controls transition, Prometheus only changes state not sends notifications.

**Assessment — Strong on alerting rules, good on recording rules, one terminology error:**
- Recording rule definition correct
- Alerting rule mechanics correct
- `for` clause explanation accurate and well reasoned
- Correctly noted Prometheus does not send notifications — only state change
- **Terminology error:** States are **inactive**, **pending**, **firing** — not primed. Pending is the correct term used in the Prometheus UI and API
- **Missing on recording rules:** Labels on the result are determined by the aggregation — `by` clause controls what is preserved
- **Missing:** The performance argument for recording rules — pre-computing expensive aggregations so dashboards hit one series instead of millions
- **Missing:** Alertmanager as the component that acts on firing alerts — Prometheus detects, Alertmanager routes and notifies

---

### Q5: Customer needs 2 years of metrics retention for compliance. Currently running single Prometheus instance. What do you tell them?

**Answer summary:** Needs to move to Mimir. Thanos is an alternative but Mimir is Grafana's current direction. Would bring in additional technical resources for detailed discussion.

**Assessment — Correct direction, missing the why and the quantification:**
- Mimir as correct forward path — correct
- Thanos acknowledged — correct
- Knowing when to bring in additional resources — professionally appropriate
- **Missing:** Explain why Prometheus cannot do it — local TSDB, no replication, data loss on hardware failure, not compliance-grade
- **Missing:** Quantification — at 1 million series, 2 years retention ≈ 2.8TB on a single node with no redundancy
- **Missing:** What Mimir provides — object storage backend (S3, GCS, Azure Blob), horizontally scalable, redundant by design
- **Missing:** This is additive, not a forklift migration — Prometheus continues operating and writes to Mimir via remote_write
- **Missing:** Compliance may have requirements beyond retention duration — immutability, audit trails, data integrity depending on the specific regulation

---

### Q6: Grafana dashboard shows p99 latency climbing over 6 hours while p50 is flat. What does this tell you and what would you investigate?

**Answer summary:** Averages hide tail latency problems. Small percentage of users affected. Dashboard implies historical awareness of the issue — find out who built it and why.

**Assessment — Good conceptual foundation, organizational context valid, missing technical interpretation:**
- Correctly identified that p99 climbing while p50 flat means a small percentage of users affected — correct
- Organizational context observation is mature and valid
- **Missing:** Read the technical signal directly — p99 climbing while p50 flat means tail latency degradation, not a widespread problem
- **Missing:** 6-hour gradual increase vs sudden spike — gradual suggests resource exhaustion, leak, or growing pressure, not a deployment change
- **Missing:** Investigate by breaking down histogram by dimensions — endpoint, user tier, region — to identify which request subset is in the p99
- **Missing:** Exemplars link slow requests to specific traces — note: this is Week 3 material, flagged as forward-looking

**What the pattern means technically:**
- Majority of requests still fast — flat p50
- Slowest 1% getting progressively slower — widening tail
- Likely cause: specific code path, resource exhaustion affecting edge cases, downstream dependency degrading, connection pool or cache threshold being hit

---

## 4. Gap Analysis

### Consistent Gaps Identified

**Quantification**

The most consistent gap across all six questions. Correct concepts stated without the numbers that make a senior answer convincing. This is acknowledged as a known weakness — quantification without lived experience is hard to retain.

Mitigation strategy: in future lab sessions, deliberately push toward observable limits and tie numbers to what was actually seen rather than memorized thresholds.

| Threshold worth knowing | Value |
|---|---|
| Prometheus recommended max active series | 10 million |
| Memory per active series (head block) | ~3-4KB |
| RAM for 1 million series | ~3-4GB |
| RAM for 10 million series | ~30-40GB |
| Default retention | 15 days |
| Storage at 1M series, 15s interval, 15 days | ~57GB |
| Storage at 1M series, 15s interval, 2 years | ~2.8TB |
| WAL size at 1M series | ~5-10GB |

**Reading specific metric patterns**

The p99/p50 question revealed a gap in interpreting specific observability signals and connecting them to diagnostic actions. Correct at the conceptual level but stopped short of the technical interpretation a senior role requires.

**Incomplete use of available diagnostic tools**

Dashboard diagnostic question showed the right general approach but missed the specific first steps — Prometheus UI as immediate separator of Grafana vs Prometheus problems, `/rules` endpoint for recording rule health.

### What Is Solid

- Prometheus data model and cardinality conceptual understanding
- Metric types and correct function selection
- PromQL function mechanics — rate(), delta(), increase(), histogram_quantile()
- Alert rule design — for clause, states, severity labels
- Grafana architecture — visualization layer only, data source dependency
- Enterprise fit assessment — where Prometheus works and where it doesn't
- Knowing when to escalate or bring in additional resources

---

## 5. Advanced Topics Carried Forward

Full cumulative list from Days 2-5 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, and native histograms | Histograms are a significant cardinality source. Native histograms change the storage model and reduce series count overhead substantially. | Day 2 — TSDB cardinality analysis |
| **Recording rules** — advanced design, naming conventions, and performance impact at scale | Day 3 covered foundational implementation. Enterprise scale introduces rule evaluation performance, rule dependencies, and federation of recorded metrics. | Day 2 — metric types; Day 3 — hands-on |
| **SNMP exporter configuration** — Counter32 vs Counter64 OID selection | Operational gap when customers migrate from traditional NMS to Prometheus-based observability. Counter32 wrapping at high throughput produces unreliable rate calculations. | Day 2 — counter ceiling discussion |
| **Alerting rules** — full design, Alertmanager routing, and inhibition | Day 4 covered alert rule implementation. Full Alertmanager deployment, routing trees, and inhibition rules are a dedicated Week 4 topic. | Day 3 — comparison operators; Day 4 — alerting rules |
| **Prometheus CI/CD integration** — promtool in pipelines | Metric instrumentation validation before deployment. Prevents naming conflicts, type mismatches, and cardinality anti-patterns from reaching production. | Day 3 — metric type conflicts |
| **Grafana Enterprise features** — advanced caching, RBAC, reporting | Cache level differences, role-based access control for dashboards, and scheduled PDF reporting are Enterprise features relevant to large organization deployments. | Day 4 — data source performance section |

---

## 6. Week 2 Scope

### Goal

Add log ingestion to the existing stack. Understand push-based log collection. Write LogQL queries. Correlate logs and metrics in Grafana Explore split view.

### Components Being Added

| Component | Role |
|---|---|
| Loki | Log aggregation and storage |
| Grafana Alloy | Telemetry collector — collects logs, ships to Loki |

### Why This Matters for the Grafana Role

Loki uses a push-based ingest model — logs are shipped to Loki by an agent rather than Loki polling for them. This is the architectural shift from Prometheus's pull model. Understanding both collection patterns and when each applies is a core Senior Observability Architect competency.

Grafana Alloy is the modern replacement for Promtail and the Grafana Agent. It is the central collector for the full LGTM stack — handling metrics, logs, and traces. Understanding Alloy's pipeline configuration model is increasingly important as customers adopt it.

### What Carries Forward From Week 1

- The existing Docker Compose stack — Loki and Alloy are additions, not replacements
- The Prometheus data source in Grafana — the split view in Explore uses both Prometheus and Loki simultaneously
- The understanding of label design — Loki uses labels similarly to Prometheus and the same cardinality concerns apply
- The Grafana Explore mode — Week 2 makes split view the primary investigation interface

### Key Concepts to Cover in Week 2

- LogQL — Loki's query language, structure compared to PromQL
- Label strategy in Loki — why labels matter for query performance
- Log to metric correlation in Grafana — linking a log entry to a metric spike
- Grafana Alloy pipeline configuration — collection, transformation, export
- Push vs pull model architectural comparison — concrete now that both have been implemented

### Week 2 Directory Target

```
grafana-observability-lab/
└── week2/
    ├── README.md
    ├── docker-compose.yml      ← Extended from week1
    ├── alloy-config.alloy      ← Grafana Alloy pipeline configuration
    └── loki-config.yml         ← Loki configuration
```

---

## 7. Reference Material

### Week 2 Preparation

| Resource | URL | Notes |
|---|---|---|
| Loki documentation | https://grafana.com/docs/loki/latest/ | Authoritative — covers LogQL, label design, storage |
| Grafana Alloy documentation | https://grafana.com/docs/alloy/latest/ | Pipeline configuration, component model |
| LogQL documentation | https://grafana.com/docs/loki/latest/query/ | Query language reference — structure compared to PromQL |
| Grafana Alloy workshop | https://grafana.com/workshops/ | Free hands-on workshop — building telemetry pipelines |

### Prometheus and Grafana — Week 1 Reference

| Resource | URL | Notes |
|---|---|---|
| Prometheus data model | https://prometheus.io/docs/concepts/data_model/ | Authoritative |
| PromQL function reference | https://prometheus.io/docs/prometheus/latest/querying/functions/ | All functions |
| Prometheus storage documentation | https://prometheus.io/docs/prometheus/latest/storage/ | Retention, WAL, block structure |
| Prometheus alerting best practices | https://prometheus.io/docs/practices/alerting/ | Alert design guidance |
| Grafana variable documentation | https://grafana.com/docs/grafana/latest/dashboards/variables/ | All variable types and chaining |
| Alertmanager documentation | https://prometheus.io/docs/alerting/latest/alertmanager/ | Routing, inhibition, silencing — Week 4 |
| Grafana Mimir documentation | https://grafana.com/docs/mimir/latest/ | Long-term storage — Week 4 |
| Fabian Reinartz — TSDB deep dive | https://fabxc.org/tsdb/ | Best explanation of Prometheus storage design |

### Screening Preparation

| Resource | URL | Notes |
|---|---|---|
| Prometheus FAQ | https://prometheus.io/docs/introduction/faq/ | Common questions with authoritative answers |
| Grafana Labs blog | https://grafana.com/blog/ | Current product direction, customer use cases |
| Prometheus comparison page | https://prometheus.io/docs/introduction/comparison/ | Competitive landscape — authoritative |

---

*Week 1 complete. Week 2: Loki + Grafana Alloy — log ingestion, LogQL, and metrics-to-logs correlation.*

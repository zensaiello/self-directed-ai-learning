# Loki + Grafana Alloy — Week 2 Day 3 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand Loki label design in depth — what is indexed vs structured metadata
- Implement Loki alerting rules and understand how they differ from Prometheus rules
- Diagnose and fix a real alert false positive
- Build a unified Grafana dashboard combining Prometheus metrics and Loki log panels
- Understand the container variable pattern for scoping log panels

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- All scaling claims quantified where possible
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Table of Contents

1. [Loki Label Design in Depth](#1-loki-label-design-in-depth)
2. [Loki Alerting Rules](#2-loki-alerting-rules)
3. [Alert False Positive — Diagnosis and Fix](#3-alert-false-positive--diagnosis-and-fix)
4. [Building a Unified Grafana Dashboard](#4-building-a-unified-grafana-dashboard)
5. [Stream Labels vs Structured Metadata](#5-stream-labels-vs-structured-metadata)
6. [Questions and Answers](#6-questions-and-answers)
7. [Advanced Topics](#7-advanced-topics)
8. [Reference Material](#8-reference-material)

---

## 1. Loki Label Design in Depth

### Current Lab Stream Schema

Three indexed stream labels in the lab instance:

```
{"status":"success","data":["container","service","service_name"]}
```

Verify indexed labels at any time:
```
http://localhost:3100/loki/api/v1/labels
```

Verify unique values for a specific label:
```
http://localhost:3100/loki/api/v1/label/container/values
```

**Why this schema is correct:**

| Label | Unique values | Cardinality |
|---|---|---|
| `container` | 5 | Bounded — number of containers |
| `service` | 5 | Bounded — number of services |
| `service_name` | 5 | Bounded — same as service |

Total maximum stream count: 5 containers × label combinations = low cardinality by design.

---

### Stream Inventory Query

```logql
sum by (container, service) (count_over_time({container=~".+"}[5m]))
```

Shows every unique stream in the Loki instance as a labeled combination. Use this to audit stream cardinality on any Loki instance.

---

### What detected_level Is and Is Not

Alloy's `detect_level` feature scans log lines for level indicators and attaches the result. However the behavior depends on Alloy version and configuration:

- **As a stream label** — indexed, queryable in stream selectors, cheap index lookup
- **As structured metadata** — visible when expanding a log line in Grafana, not indexed, not usable in stream selectors

**In the lab:** `detected_level` is structured metadata, not an indexed stream label. It appears when expanding log lines but is absent from `http://localhost:3100/loki/api/v1/labels`.

**Consequence:** `{detected_level="error"}` returns no results — it is not an indexed label. Use a line filter instead:

```logql
# Does not work — detected_level not indexed
{container="prometheus", detected_level="error"}

# Works — line filter scans content
{container="prometheus"} |~ "error|ERROR"
```

---

### Promoting detected_level to a Stream Label

To make `detected_level` a proper indexed stream label, add an explicit processing stage in Alloy:

```hcl
loki.process "promote_labels" {
  forward_to = [loki.write.local.receiver]

  stage.logfmt {
    mapping = {
      "detected_level" = "level",
    }
  }

  stage.labels {
    values = {
      "detected_level" = "detected_level",
    }
  }
}
```

**Cardinality impact:** Adding `detected_level` as a stream label multiplies stream count by the number of unique level values. With 5 containers × 5 possible levels = 25 streams maximum — low cardinality, worth doing for the query performance benefit.

---

### High Cardinality Anti-Patterns in Loki

| Anti-pattern | Problem | Correct approach |
|---|---|---|
| `{request_id="abc-123"}` | One stream per request — unbounded | Keep request IDs in log line content |
| `{client_ip="192.168.1.x"}` | One stream per client IP — unbounded | Keep IPs in log content |
| `{filename="/var/log/app/2026-04-09.log"}` | Log rotation creates new streams daily | Use `{app="myapp"}` static label |
| Kubernetes `pod_template_hash` as label | Random suffix changes on every restart — high churn | Use namespace, container, node only |

---

### Stream Selector Design — Fast by Design

Design label schemas so the most common queries can be answered entirely by label selectors — the cheap index lookup layer:

```logql
# Poorly designed — broad stream selection, relies on line filter
{container=~".+"} |= "error" |= "api-gateway"

# Well designed — index lookup for both filters
{container="api-gateway", detected_level="error"}
```

Excluding noisy containers at the stream selector level is cheaper than filtering them out with line operators:

```logql
# More expensive — includes loki then filters lines
{container=~".+"} |= "error"

# Less expensive — excludes loki entirely before any scan
{container=~".+", container!="loki"} |= "error"
```

---

## 2. Loki Alerting Rules

### How Loki Alerting Rules Work

Loki alerting rules use LogQL metric expressions. When the expression exceeds a threshold the Loki ruler generates a firing alert and attempts to send it to Alertmanager.

**Key differences from Prometheus alerting rules:**

| | Prometheus alert | Loki alert |
|---|---|---|
| Expression | PromQL | LogQL metric query |
| Data source | Prometheus TSDB | Loki log streams |
| Evaluation | Prometheus ruler | Loki ruler |
| Sends to | Alertmanager | Alertmanager |
| Rule file format | YAML | YAML — identical syntax |

Both ultimately send firing alerts to Alertmanager — the routing and notification layer is shared.

---

### When to Alert on Logs vs Metrics

**Alert on metrics when:**
- The application exposes a counter or gauge for the condition
- You need precise numeric thresholds
- The condition is about system state — CPU, memory, disk

**Alert on logs when:**
- The application does not expose a metric for the condition but does log it
- The condition is a specific event — fatal exception, database connection refused
- The application is a third-party component you cannot instrument

**The honest tradeoff:** Log-based alerts depend on the log pipeline being healthy. If Alloy stops collecting or Loki goes down, log-based alerts go silent at the same time you lose the logs. For critical alerts prefer metrics where possible.

---

### Lab Implementation

**Directory structure:**
```
~/grafana-lab/week2/
└── loki-rules/
    └── log_alerts.yml
```

**log_alerts.yml — corrected version after false positive fix:**

```yaml
groups:
  - name: log_alerts
    rules:
      - alert: HighLogErrorRate
        expr: |
          sum by (container) (
            rate({container=~".+"} |= "error" [5m])
          ) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate in logs for {{ $labels.container }}"
          description: "Log error rate is {{ $value | humanize }} errors/sec in {{ $labels.container }}"

      - alert: FatalLogEvent
        expr: |
          sum by (container) (
            count_over_time(
              {container=~".+"} |~ "fatal|panic|FATAL|PANIC" !~ "caller=metrics.go|caller=evaluator"
              [5m]
            )
          ) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Fatal event detected in {{ $labels.container }}"
          description: "A fatal or panic log event was detected in {{ $labels.container }}"
```

**loki-config.yml ruler section:**

```yaml
ruler:
  alertmanager_url: http://localhost:9093
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /loki/rules-temp
  enable_api: true
```

**docker-compose.yml Loki volume mount:**

```yaml
loki:
  volumes:
    - ./loki-config.yml:/etc/loki/local-config.yaml
    - ./loki-rules:/loki/rules/fake
    - loki_data:/loki
```

> **Note on `/loki/rules/fake`:** The `fake` subdirectory is required by Loki's single-tenant mode. In single-tenant mode Loki uses `fake` as the default org_id. Rules must be placed in a directory matching the org_id.

**Verify rules loaded:**
```
http://localhost:3100/loki/api/v1/rules
```

**Check ruler evaluation logs:**
```bash
docker logs loki 2>&1 | grep -i "FatalLogEvent\|HighLogErrorRate" | tail -5
```

Key fields to verify in ruler log output:

| Field | Meaning |
|---|---|
| `msg="evaluating rule"` | Rule is being evaluated on schedule |
| `total_entries=0` | Expression returned no results — inactive |
| `total_entries=1` | Expression returned results — firing |
| `query_hash` | Changes when rule expression is updated — confirms hot reload |

---

### The Alertmanager Connection Error — Expected

```
level=error msg="Error sending alerts" alertmanager=http://localhost:9093/api/v2/alerts
err="dial tcp [::1]:9093: connect: connection refused"
```

Loki is trying to reach Alertmanager at `localhost:9093`. Inside a Docker container `localhost` resolves to the container itself — not the host or other containers. Alertmanager is not deployed yet — this error is expected.

**When Alertmanager is deployed in Week 4** the correct URL in loki-config.yml will be:
```
alertmanager_url: http://alertmanager:9093
```

Using the Docker service name — same pattern as `http://prometheus:9090` and `http://loki:3100`.

---

## 3. Alert False Positive — Diagnosis and Fix

### What Happened

The `FatalLogEvent` rule fired immediately after deployment. Investigation revealed:

**Root cause:** Loki's ruler logs its own query expressions when evaluating rules. The query string contains the literal word `panic` as part of `"fatal|panic|FATAL|PANIC"`. That log line was being ingested into Loki and matched by the same rule on the next evaluation cycle.

**Evidence in ruler logs:**
```
query="(sum by (container)(count_over_time({container=~\".+\"} |~ \"fatal|panic|FATAL|PANIC\"[5m])) > 0)"
total_entries=1
```

The `total_entries=1` confirmed the expression was returning a result. The query field confirmed the match was against the ruler's own log output containing the query string.

---

### Two Fix Approaches

**Fix 1 — Exclude Loki container entirely:**
```logql
{container=~".+", container!="loki"} |~ "fatal|panic|FATAL|PANIC"
```
Simple but too broad — would miss genuine Loki panics.

**Fix 2 — Exclude ruler evaluation log lines specifically (preferred):**
```logql
{container=~".+"} |~ "fatal|panic|FATAL|PANIC" !~ "caller=metrics.go|caller=evaluator"
```
Surgical — keeps Loki in scope for genuine panics while excluding ruler noise.

---

### Verifying the Fix

Loki picked up the updated rule file automatically via the volume mount — no container restart required. Query hash change in the logs confirmed the new expression was loaded:

```
Old: query_hash=1034317321
New: query_hash=4083641128
```

Subsequent evaluations showed no `total_entries=1` — false positive eliminated.

---

### The Enterprise Lesson

**Self-triggering alerts** occur when the monitoring system's own log output matches the alert expression. Common in production when:
- Alerting on generic terms (`panic`, `error`, `fatal`) without scoping
- The monitoring pipeline logs its own query activity
- Log collection is recursive — the collector logs about collecting logs

**Design principles to prevent this:**
1. Always run the raw LogQL expression in Explore before putting it in an alert rule — examine what it actually matches
2. Scope stream selectors as narrowly as possible before adding line filters
3. Test alert expressions against real log samples, not just expected patterns
4. Exclusion patterns (`!~`) are maintenance overhead — document why each one exists

---

## 4. Building a Unified Grafana Dashboard

### Dashboard — Stack Observability

Five panels combining Prometheus metrics and Loki log data.

---

### Panel Configuration

**Panel 1 — Log Ingestion Rate**
- Data source: Loki
- Query: `sum by (container) (rate({container=~"$container"}[5m]))`
- Visualization: Time series
- Title: `Log Ingestion Rate (lines/sec)`

**Panel 2 — Log Error Rate**
- Data source: Loki
- Query: `sum by (container) (rate({container=~"$container"} |= "error" [5m]))`
- Visualization: Time series
- Title: `Log Error Rate (errors/sec)`

**Panel 3 — Warnings and Errors Log Tail**
- Data source: Loki
- Query: `{container=~"$container"} |~ "warn|error|WARN|ERROR"`
- Visualization: **Logs** — not Time series
- Title: `Warnings and Errors`

> **Critical:** The Logs visualization type must be selected for log stream queries. Setting this panel to Time series produces "Data is missing a number field" because log lines are not numeric. The Logs visualization type expects raw log line data.

**Panel 4 — CPU Utilization**
- Data source: Prometheus
- Query: `instance:node_cpu_utilization:avg_rate5m`
- Visualization: Time series
- Title: `CPU Utilization %`

> Note: This panel does not use the `$container` variable — it shows infrastructure metrics regardless of container selection.

**Panel 5 — Total Errors Stat**
- Data source: Loki
- Query: `sum(count_over_time({container=~"$container"} |= "error" [1h]))`
- Visualization: Stat
- Title: `Total Errors (last 1h)`

---

### Dashboard Variable — Container

| Field | Value |
|---|---|
| Name | `container` |
| Type | Query |
| Data source | Loki |
| Query | `label_values(container)` |
| Label | Container |
| Include All option | On |
| Custom all value | `.+` |

When **All** is selected the variable resolves to `.+` — matching all containers. When a specific container is selected all Loki panels scope to that container simultaneously. The Prometheus panel is unaffected.

**Verified behavior:**
- Selecting a specific container scopes all Loki panels correctly
- Selecting All returns data from all containers
- Prometheus CPU panel shows data regardless of container selection

---

### The Unified Observability View

One dashboard, one dropdown, all signals for one service:

```
Container dropdown = "loki"
    ↓
Log Ingestion Rate  → Loki's log volume
Log Error Rate      → Loki's error frequency
Warnings and Errors → Loki's actual warn/error lines
Total Errors (1h)   → Single number error count
CPU Utilization     → Host-level context (unscoped)
```

This is the unified observability view Grafana is designed to provide. Selecting a container from the dropdown immediately shows all available signals for that service in one place.

---

## 5. Stream Labels vs Structured Metadata

### The Distinction

| | Stream labels | Structured metadata |
|---|---|---|
| Indexed | Yes | No |
| Queryable in stream selector | Yes | No |
| Visible in log line detail | Yes | Yes |
| Query cost | Index lookup — cheap | Not filterable at stream level |
| Cardinality impact | Yes — creates new streams | No |
| Example | `container`, `service` | `detected_level` in lab |

### Practical Impact

```logql
# Stream label — works, cheap index lookup
{container="prometheus"}

# Structured metadata — does NOT work as stream selector
{detected_level="error"}

# Workaround — line filter for unindexed fields
{container="prometheus"} |~ "error|ERROR"
```

### Verifying What Is Indexed

```
http://localhost:3100/loki/api/v1/labels
```

If a label name does not appear here it is not indexed — it cannot be used in a stream selector regardless of whether it appears in the log line detail view in Grafana.

---

## 6. Questions and Answers

### Q1: Why did the Logs panel show "Data is missing a number field"?

**Summary:** The wrong visualization type was selected. The **Time series** visualization expects numeric data. Log stream queries return raw log lines, not numbers. The **Logs** visualization type must be selected for any panel displaying raw log line data from Loki. The Logs type is specific to log data sources and displays lines with timestamps, level indicators, and expandable detail.

---

### Q2: Why is detected_level not usable in stream selectors?

**Summary:** `detected_level` is attached as structured metadata by Alloy in the lab configuration — not promoted to an indexed stream label. Structured metadata is visible when expanding a log line in Grafana but is absent from the Loki labels index. Only indexed stream labels can be used in stream selectors. Verified via `http://localhost:3100/loki/api/v1/labels` which returned only `container`, `service`, and `service_name`.

To make `detected_level` queryable as a stream selector, add an explicit `stage.labels` block in the Alloy pipeline to promote it to an indexed label.

---

### Q3: Why does localhost:9093 fail for Alertmanager inside Docker?

**Summary:** Inside a Docker container `localhost` resolves to the container itself — not the host machine or other containers. `http://localhost:9093` attempts to connect to port 9093 on the Loki container, which has no Alertmanager running. The correct URL for container-to-container communication is the Docker service name: `http://alertmanager:9093`. Same pattern as `http://prometheus:9090` and `http://loki:3100`.

---

## 7. Advanced Topics

Topics identified during Week 2 Days 1, 2, and 3 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, and native histograms | Histograms are a significant cardinality source. Native histograms change the storage model. | Week 1 Day 2 |
| **Recording rules** — advanced design and performance impact at scale | Enterprise scale introduces rule evaluation performance and rule dependencies. | Week 1 Day 2 |
| **SNMP exporter configuration** — Counter32 vs Counter64 OID selection | Operational gap when customers migrate from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing and inhibition | Full Alertmanager deployment, routing trees, and inhibition rules. Week 4 topic. | Week 1 Day 3 |
| **Prometheus CI/CD integration** — promtool in pipelines | Metric instrumentation validation before deployment. | Week 1 Day 3 |
| **Grafana Enterprise features** — advanced caching, RBAC, reporting | Relevant to large organization deployments. | Week 1 Day 4 |
| **Loki distributed mode** — scaling beyond single node | Single-node Loki has ingest and query limits. | Week 2 Day 1 |
| **LogQL parsing stages** — full parser reference | Additional parsers beyond logfmt and json — pattern, regexp, unpack. | Week 2 Day 2 |
| **Promtail to Alloy migration** — customer migration path | Customers running Promtail need a migration path. | Week 2 Day 1 |
| **Loki recording rules** — configuration and use cases | Pre-computing log-derived metrics for repeated parsed queries. | Week 2 Day 2 |
| **Alloy pipeline processing stages** — drop, label extraction, format transformation | Edge filtering and label extraction at ingest time. | Week 2 Day 2 |
| **Self-triggering alert patterns** — detection and prevention | Monitoring systems logging their own query strings can match alert expressions. Real operational discipline. | Week 2 Day 3 — FatalLogEvent false positive |
| **Loki stream label vs structured metadata** — promotion strategies | Understanding what is indexed vs what is metadata. Affects query design and performance. | Week 2 Day 3 — detected_level investigation |

---

## 8. Reference Material

### Loki Label Design and Configuration

| Resource | URL | Notes |
|---|---|---|
| Loki labels best practices | https://grafana.com/docs/loki/latest/get-started/labels/best-practices/ | Production label design guidance |
| Loki structured metadata | https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/ | Difference between stream labels and metadata |
| Loki ruler configuration | https://grafana.com/docs/loki/latest/configure/#ruler | Full ruler config options |
| Loki alerting rules | https://grafana.com/docs/loki/latest/rules/ | Rule syntax and examples |

### Grafana Alloy Pipeline

| Resource | URL | Notes |
|---|---|---|
| loki.process component | https://grafana.com/docs/alloy/latest/reference/components/loki.process/ | Processing stages including label promotion |
| Alloy component reference | https://grafana.com/docs/alloy/latest/reference/components/ | All available pipeline components |
| detect_level documentation | https://grafana.com/docs/alloy/latest/reference/components/loki.source.docker/ | Alloy automatic level detection behavior |

### Grafana Dashboard

| Resource | URL | Notes |
|---|---|---|
| Grafana Logs panel | https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/logs/ | Logs visualization configuration |
| Grafana Stat panel | https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/stat/ | Single value display configuration |
| Grafana variable documentation | https://grafana.com/docs/grafana/latest/dashboards/variables/ | Variable types and chaining |

### LogQL

| Resource | URL | Notes |
|---|---|---|
| LogQL log queries | https://grafana.com/docs/loki/latest/query/log_queries/ | Full pipeline stage reference |
| LogQL metric queries | https://grafana.com/docs/loki/latest/query/metric_queries/ | rate(), count_over_time(), bytes_over_time() |
| LogQL query best practices | https://grafana.com/docs/loki/latest/query/bp-query/ | Performance guidance |

---

*Week 2 Day 3 complete. Day 4: Week 2 consolidation — GitHub repository update, Week 2 review, screening questions scoped to Loki and Alloy topics, and Week 3 scope.*

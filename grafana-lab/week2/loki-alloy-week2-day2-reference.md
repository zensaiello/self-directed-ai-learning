# Loki + Grafana Alloy — Week 2 Day 2 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand LogQL filtering in depth — building on Day 1 line filter operators
- Understand parsing stages — extracting structured fields from log content
- Understand LogQL metric queries — converting log data into numeric time series
- Use Grafana Explore split view for log to metric correlation
- Understand the performance implications of parsing and how to mitigate them
- Build hands-on familiarity with practical LogQL query patterns

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- All scaling claims quantified where possible
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Table of Contents

1. [LogQL Filtering in Depth](#1-logql-filtering-in-depth)
2. [Parsing Stages](#2-parsing-stages)
3. [LogQL Metric Queries](#3-logql-metric-queries)
4. [Log to Metric Correlation — Explore Split View](#4-log-to-metric-correlation--explore-split-view)
5. [Practical Query Patterns](#5-practical-query-patterns)
6. [Performance — Parsing at Query Time vs Ingest Time](#6-performance--parsing-at-query-time-vs-ingest-time)
7. [Questions and Answers](#7-questions-and-answers)
8. [Advanced Topics](#8-advanced-topics)
9. [Reference Material](#9-reference-material)

---

## 1. LogQL Filtering in Depth

### Building a Filter Chain

Filters chain left to right — each stage narrows the result set from the previous stage:

```logql
{container="loki"} |= "error" != "context canceled"
```

Reads as: from the Loki container stream, show lines containing "error" but exclude lines containing "context canceled". The "context canceled" exclusion is a real-world pattern — in Go-based applications like Loki this message appears frequently when a client disconnects cleanly and is not a real error.

---

### Regex Filters for Multiple Conditions

When you need to match any of several patterns in a single filter:

```logql
# Lines containing either "error" or "warn"
{container=~".+"} |~ "error|warn"

# Lines containing either "timeout" or "refused" or "reset"
{container=~".+"} |~ "timeout|refused|reset"
```

More efficient than chaining two separate `|=` filters — performs one scan pass instead of two.

---

### Negative Regex for Exclusion Patterns

```logql
{container="loki"} |= "error" !~ "context canceled|health check|routine"
```

A common production pattern — exclude all known noise in one stage rather than chaining multiple `!=` filters.

---

### Excluding Streams at the Label Selector Level

Excluding noisy containers at the label selector level is cheaper than including them and filtering out their lines with a `!=` operator:

```logql
# More expensive — includes loki stream then filters
{container=~".+"} |= "error" != "loki_noise"

# Less expensive — excludes loki stream entirely before any scan
{container=~".+", container!="loki"} |~ "warn|error"
```

The exclusion happens at the index lookup layer rather than during log line scanning — no decompression cost for the excluded streams.

---

### Important Behavioral Notes from Lab

**LogQL field value comparisons are case sensitive.**

Prometheus logs uppercase level values (`INFO`, `WARN`, `ERROR`). A query for `level="info"` returns no results against Prometheus logs. Use case-insensitive regex to handle inconsistency:

```logql
# Case-insensitive level filter
{container="prometheus"} | logfmt | level=~"(?i)error"
```

The `(?i)` prefix makes the regex case-insensitive — works regardless of whether the application logs `ERROR`, `error`, or `Error`.

**Range `[5m]` is only valid inside metric functions.**

This is a syntax error:
```logql
{container=~".+"} |~ "error|ERROR" [5m]
```

The range parameter only belongs inside metric query functions:
```logql
# Correct — range inside the function
sum by (container) (count_over_time({container=~".+"} |~ "error|ERROR" [5m]))
```

---

## 2. Parsing Stages

### Why Parsing Matters

Without parsing, log lines are opaque strings — you can only filter them as a whole. Parsing extracts structured fields from log content and makes those fields available for precise filtering and numeric aggregation.

**Before parsing:**
```
level=INFO ts=2026-04-09T10:15:32Z caller=scrape.go msg="completed scrape" duration=0.023
```

**After `| logfmt` parsing:**
- `level` = INFO
- `ts` = 2026-04-09T10:15:32Z
- `caller` = scrape.go
- `msg` = completed scrape
- `duration` = 0.023

Each extracted field is separately filterable. Numeric comparisons become possible — `duration > 0.1`.

---

### The logfmt Parser

Used for Go-based applications — Prometheus, Loki, Alloy all use logfmt format:

```logql
{container="prometheus"} | logfmt
```

After parsing, filter on extracted fields:

```logql
# Correct level filter — case matters
{container="prometheus"} | logfmt | level="INFO"

# Case-insensitive approach
{container="prometheus"} | logfmt | level=~"(?i)warn"

# Numeric comparison — only possible after parsing
{container="prometheus"} | logfmt | duration > 0.1
```

> **Lab observation:** The sidebar expands significantly after adding `| logfmt` — all extracted key=value pairs from the log lines become available as filterable fields. This is Grafana exposing the structured fields that parsing unlocked.

---

### The json Parser

For applications that log in JSON format — Grafana uses JSON logging:

```logql
{container="grafana"} | json
```

**Handling parse errors:**

Grafana logs some non-JSON lines during startup. The `__error__` special field captures parsing failures:

```logql
# Show only lines that failed to parse
{container="grafana"} | json | __error__ != ""
```

This is the correct approach for investigating "Error when parsing some of the logs" warnings — it surfaces exactly which lines are not valid JSON without discarding the rest.

---

### Field Availability Varies by Application

Before filtering on a specific extracted field, confirm it exists by running the base parse query first and inspecting the sidebar:

```logql
{container="grafana"} | json
```

Check which fields appear in the Fields sidebar before writing filters against specific field names. Field names vary by application — do not assume a field exists without verifying.

---

### Filtering on Extracted Fields

After parsing, extracted fields support the same operators as label selectors:

```logql
# Exact match on extracted field
{container="prometheus"} | logfmt | level="INFO"

# Regex match on extracted field
{container="grafana"} | json | logger=~".*http.*"

# Numeric comparison — only works on fields with numeric values
{container="prometheus"} | logfmt | duration > 0.1

# Exclude lines with empty component field
{container="prometheus"} | logfmt | component != ""
```

---

## 3. LogQL Metric Queries

### count_over_time() — Log Volume as a Metric

```logql
# Log lines per container per minute
sum by (container) (count_over_time({container=~".+"}[1m]))

# Error count per container over 5 minutes
sum by (container) (count_over_time({container=~".+"} |= "error" [5m]))
```

Log-derived error metrics capture signals from any application that logs errors — even applications that do not expose a Prometheus error counter.

---

### rate() — Lines Per Second

```logql
# Log ingestion rate per container — lines per second
sum by (container) (rate({container=~".+"}[5m]))

# Error rate per second across all containers
sum by (container) (rate({container=~".+"} |= "error" [5m]))
```

**Lab result:** Loki has the highest log ingestion rate at approximately 1.5 lines per second. Node-exporter generates so few log lines it does not appear in the rate results at a 5-minute window.

---

### bytes_over_time() — Log Volume in Bytes

```logql
# Bytes of logs per container over 5 minutes
sum by (container) (bytes_over_time({container=~".+"}[5m]))
```

Useful for capacity planning — identifying which log sources are driving Loki storage consumption.

---

### The Metrics vs Logs Data Shape Distinction

A critical behavioral difference confirmed in the lab:

**Prometheus metrics — continuous line:**
`rate(prometheus_http_requests_total[5m])` produces a continuous line because Prometheus writes a sample on every scrape interval regardless of whether anything changed. There is always a value.

**LogQL rate — disconnected lines:**
`sum by (container) (rate({container=~".+"}[5m]))` produces disconnected lines because log lines only exist when something happened. When no log lines arrive for a period the rate drops to zero and the line disappears.

**The operational implication:**
- A flat line on a Prometheus graph means "nothing changed"
- A gap on a LogQL graph means "no log events occurred in that window" — which could mean the system was idle or could mean the log pipeline broke

These two interpretations require different responses — knowing which you are looking at matters.

---

## 4. Log to Metric Correlation — Explore Split View

### Setting Up the Split View

In Grafana Explore at `http://localhost:3000/explore`:

1. Click the **Split** button at the top right
2. Set the left panel to **Prometheus** data source
3. Set the right panel to **Loki** data source

Both panels share the same time range — zooming into a spike on the left automatically scopes the right panel to the same window.

---

### The Correlation Workflow

The operational workflow a Senior Observability Architect should be able to describe:

1. **Alert fires** — Prometheus detects a condition, Alertmanager notifies
2. **Open Explore** — navigate to the time window of the alert
3. **Left panel — metrics** — confirm the triggering metric, understand the shape (gradual vs sudden, one instance vs many)
4. **Right panel — logs** — filter to the relevant service during the same time window, look for error patterns or state changes that correlate with the metric behavior
5. **Narrow the time range** — zoom into the exact moment the metric changed, confirm whether log errors preceded or followed
6. **Find the specific event** — the log line that explains the metric behavior

**Enterprise relevance:** This workflow is a core Grafana selling point. The ability to correlate metrics and logs in a single interface without switching tools is one of the primary enterprise value propositions of the LGTM stack.

---

### Important Caveat — Metrics and Logs Are Not Always 1-to-1

Not every metric has a corresponding log entry. Not every log entry has a corresponding metric. The correlation workflow is most useful when you have a metric spike that you suspect has a logged explanation — which requires the application to actually log the relevant events.

**Lab example:** Prometheus scrape activity is visible in `scrape_duration_seconds` metrics but produces no log output at the default `info` log level. A split view pairing scrape metrics with Prometheus logs will show activity on the left and silence on the right — not because the correlation is broken but because scrape operations are not logged at default verbosity.

**Better split view for the lab:**

Left panel — Prometheus:
```promql
rate(prometheus_http_requests_total[5m])
```

Right panel — Loki:
```logql
{container="prometheus"} | logfmt | level="INFO"
```

---

## 5. Practical Query Patterns

### Stack Health From Logs

```logql
# Error count per container over last 15 minutes
sum by (container) (count_over_time({container=~".+"} |= "error" [15m]))

# Any fatal or panic level messages — should return nothing on a healthy stack
{container=~".+"} |~ "fatal|panic|FATAL|PANIC"

# Configuration reload events
{container="prometheus"} |= "reload"

# Log volume rate per container
sum by (container) (rate({container=~".+"}[5m]))
```

**Lab health picture from these four queries:**

| Query | Result | Interpretation |
|---|---|---|
| Error count | Grafana and Loki only | Prometheus and Alloy clean |
| Fatal/panic | No results | No critical failures |
| Reload events | No results | No reload issued since startup |
| Log volume rate | Loki highest at ~1.5/sec | Normal — Loki self-logging dominates |

---

### Loki's 50-Minute Error Pattern

Loki shows a periodic growing and shrinking error count on a ~50 minute cycle. This is Loki's compaction cycle — Loki periodically compacts its index and chunk data, generating elevated log output including some error-level messages from internal operations. The pattern is regular and self-resolving — a scheduled internal process, not a genuine fault.

**Operational lesson:** Knowing your baseline error patterns is essential before writing alerts. An alert on any error in Loki would fire continuously due to compaction noise. The correct alert would filter out known compaction noise before thresholding.

---

### Finding Specific Events

```logql
# When did any container report a fatal error?
{container=~".+"} |~ "fatal|panic|FATAL|PANIC"

# Loki ingestion errors excluding known noise
{container="loki"} |= "error" != "context canceled"

# All warn or error lines excluding the noisiest container
{container=~".+", container!="loki"} |~ "warn|error"
```

---

### Log Volume Anomaly Detection

```logql
# Sudden spike in log volume — often an early indicator of a problem
sum by (container) (rate({container=~".+"}[5m]))
```

A sudden increase in log volume from a specific container frequently precedes a metric threshold breach. This is a signal that pure metrics-based monitoring cannot detect — it requires log volume visibility.

---

## 6. Performance — Parsing at Query Time vs Ingest Time

### The Performance Priority Order

| Priority | Approach | Cost at query time | Cardinality risk |
|---|---|---|---|
| 1st | Extract as label in Alloy at ingest | Zero — index lookup | High if not bounded |
| 2nd | Loki recording rules | Low — pre-computed | None |
| 3rd | Parse at query time `\| logfmt` | Medium — scan + parse | None |
| 4th | Line filter only `\|= "text"` | Low — scan only, no parse | None |

---

### Option 1 — Extract Labels in Alloy at Ingest Time

The most performant solution. Fields extracted as labels at collection time become part of the Loki stream index — queryable without any parse cost at query time.

```hcl
loki.process "parse_prometheus_logs" {
  forward_to = [loki.write.local.receiver]

  stage.logfmt {
    mapping = {
      "level" = "level",
      "component" = "component",
    }
  }

  stage.labels {
    values = {
      "level" = "level",
      "component" = "component",
    }
  }
}
```

**The cardinality warning applies here too.** Only extract fields with bounded cardinality as labels — `level` (5 values) and `component` (bounded set) are appropriate. `caller` (hundreds of unique values) is not.

Alloy's built-in `detect_level` already does this for log level automatically — which is why `{detected_level="error"}` is cheaper than `| logfmt | level="ERROR"`.

---

### Option 2 — Loki Recording Rules

Loki has recording rules (added in Loki 2.8) that pre-compute LogQL metric expressions and store results — analogous to Prometheus recording rules:

```yaml
groups:
  - name: log_metrics
    rules:
      - record: job:loki_error_rate:rate5m
        expr: |
          sum by (container) (
            rate({container=~".+"} |= "error" [5m])
          )
```

**Key distinction from Prometheus recording rules:** Loki recording rules produce metrics stored in Loki — not in Prometheus. They are accessed via the Loki data source in Grafana, not the Prometheus data source.

**Enterprise use case:** Log-derived SLO metrics — "what percentage of requests logged an error" or "p99 of a duration value extracted from log lines." These are metrics that do not exist in Prometheus because the application did not instrument them but can be derived from logs and pre-computed for consistent low-cost querying.

---

### Option 3 — Edge Filtering in Alloy

Known noise can be dropped in the Alloy pipeline before it reaches Loki — reducing ingest volume and storage cost:

```hcl
loki.process "filter_noise" {
  forward_to = [loki.write.local.receiver]

  stage.drop {
    expression = "context canceled"
    drop_counter_reason = "noise_filter"
  }

  stage.drop {
    expression = "health check"
    drop_counter_reason = "noise_filter"
  }
}
```

**Enterprise relevance:** Filtering at the edge has two benefits — reduced Loki storage cost and reduced query noise. Operators do not have to remember to exclude known noise patterns in every query.

**Design principle:** Filter at the edge for known, consistent noise. Filter at query time for ad-hoc investigation where you do not know in advance what to exclude.

---

### Loki Structured Metadata

A newer Loki feature that sits between labels and parsed fields. Structured metadata is attached to log lines at ingest time but is not part of the stream label set — it does not affect cardinality. Queryable at query time without a parse stage. Worth knowing exists as an intermediate option between labels and full parsing.

Reference: https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/

---

## 7. Questions and Answers

### Q1: Is there a way to limit the time range in a LogQL query?

**Summary:** Two mechanisms. The Grafana time picker applies to all queries in the Explore panel and is the standard approach for incident investigation — set the time range to the incident window. The range parameter inside metric functions controls the aggregation window:

```logql
# [5m] is the aggregation window, not the overall query range
count_over_time({container=~".+"} |= "error" [5m])
```

LogQL does not support inline absolute timestamp filters in the query string itself. Time bounding is always done via the Grafana time picker or the Loki API's `start` and `end` parameters when querying programmatically.

**Enterprise implication:** Dashboard default time ranges are critical for Loki-based dashboards. A dashboard without a meaningful default time range will either show too much data (slow queries) or too little context.

---

### Q2: Is there a Loki equivalent of Prometheus recording rules for pre-computing parsed queries?

**Summary:** Yes — three options depending on the use case. Extract bounded fields as labels in Alloy at ingest time (zero query-time cost, cardinality risk). Use Loki recording rules (Loki 2.8+) to pre-compute metric expressions from log data. Filter known noise at the edge in Alloy before it reaches Loki.

The correct choice depends on cardinality of the field and query frequency. High-frequency, low-cardinality fields belong in labels. High-frequency derived metrics belong in recording rules. Everything else is parsed at query time.

---

### Q3: Can log noise be filtered before reaching Loki?

**Summary:** Yes — using a `loki.process` component in the Alloy pipeline with `stage.drop` rules. Lines matching the drop expression are discarded before being sent to Loki. This reduces ingest volume, storage cost, and query noise. The correct approach for known, consistent noise patterns that would never be queried.

---

### Q4: Is there a way to customize which columns are shown in Grafana Explore log view?

**Summary:** Yes — in the Fields sidebar in Explore, click the eye icon or select button next to any field to add it as a visible column. Enabling `container` adds the container name before each log line — useful when querying across multiple containers simultaneously. The Table view toggle switches to a fully structured table where each parsed field appears as its own column.

---

## 8. Advanced Topics

Topics identified during Week 2 Days 1 and 2 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, and native histograms | Histograms are a significant cardinality source. Native histograms change the storage model and reduce series count overhead substantially. | Week 1 Day 2 |
| **Recording rules** — advanced design and performance impact at scale | Enterprise scale introduces rule evaluation performance, rule dependencies, and federation of recorded metrics. | Week 1 Day 2 |
| **SNMP exporter configuration** — Counter32 vs Counter64 OID selection | Operational gap when customers migrate from traditional NMS to Prometheus. | Week 1 Day 2 |
| **Alerting rules** — full Alertmanager routing and inhibition | Full Alertmanager deployment, routing trees, and inhibition rules. Week 4 topic. | Week 1 Day 3 |
| **Prometheus CI/CD integration** — promtool in pipelines | Metric instrumentation validation before deployment. | Week 1 Day 3 |
| **Grafana Enterprise features** — advanced caching, RBAC, reporting | Relevant to large organization deployments. | Week 1 Day 4 |
| **Loki distributed mode** — scaling beyond single node | Single-node Loki has ingest and query limits. Distributed mode splits components for horizontal scaling. | Week 2 Day 1 |
| **LogQL parsing stages** — full parser reference and structured field extraction | Day 2 covered logfmt and json parsers. Additional parsers exist — pattern, regexp, unpack. | Week 2 Day 2 — parsing discussion |
| **Promtail to Alloy migration** — customer migration path | Customers running Promtail need a migration path. | Week 2 Day 1 |
| **Loki recording rules** — configuration and use cases | Pre-computing log-derived metrics. Direct answer to performance concerns with repeated parsed queries. | Week 2 Day 2 — parsing performance discussion |
| **Alloy pipeline processing stages** — drop, label extraction, format transformation | Edge filtering and label extraction at ingest time. Foundation for production-grade log pipelines. | Week 2 Day 2 — noise filtering discussion |

---

## 9. Reference Material

### LogQL

| Resource | URL | Notes |
|---|---|---|
| LogQL log queries | https://grafana.com/docs/loki/latest/query/log_queries/ | Full pipeline stage reference including all parsers |
| LogQL metric queries | https://grafana.com/docs/loki/latest/query/metric_queries/ | rate(), count_over_time(), bytes_over_time() |
| LogQL query best practices | https://grafana.com/docs/loki/latest/query/bp-query/ | Performance guidance — label vs line filter tradeoffs |
| LogQL template functions | https://grafana.com/docs/loki/latest/query/template_functions/ | Functions available in format and label_format stages |

### Loki Configuration and Performance

| Resource | URL | Notes |
|---|---|---|
| Loki recording rules | https://grafana.com/docs/loki/latest/rules/ | Configuration and syntax — Loki 2.8+ |
| Loki structured metadata | https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/ | Between labels and parsed fields — newer feature |
| Loki labels best practices | https://grafana.com/docs/loki/latest/get-started/labels/best-practices/ | Cardinality guidance |
| Loki storage configuration | https://grafana.com/docs/loki/latest/configure/storage/ | Filesystem vs object storage backends |

### Grafana Alloy Pipeline Stages

| Resource | URL | Notes |
|---|---|---|
| loki.process component | https://grafana.com/docs/alloy/latest/reference/components/loki.process/ | Full list of processing stages including drop and label extraction |
| Alloy component reference | https://grafana.com/docs/alloy/latest/reference/components/ | All available pipeline components |

### Grafana Explore

| Resource | URL | Notes |
|---|---|---|
| Grafana Explore documentation | https://grafana.com/docs/grafana/latest/explore/ | Full Explore mode documentation including split view |
| Correlating metrics and logs | https://grafana.com/docs/grafana/latest/explore/logs-integration/ | Split view pattern for metrics and Loki logs |

### Log Formats

| Resource | URL | Notes |
|---|---|---|
| logfmt format | https://brandur.org/logfmt | The log format used by Prometheus, Loki, and Alloy |
| OpenTelemetry log data model | https://opentelemetry.io/docs/specs/otel/logs/data-model/ | Relevant for Week 3 Tempo integration |

---

*Week 2 Day 2 complete. Day 3: Loki label design in depth, log-derived alerting rules, and Grafana dashboard panels built from LogQL queries.*

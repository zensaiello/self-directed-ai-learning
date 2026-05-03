# Prometheus Deep Dive — Day 3 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand PromQL query structure at a level sufficient for enterprise architecture conversations
- Ground all concepts in the running lab instance with real data
- Quantify enterprise implications — no vague descriptors like "long-term" or "highly available"
- Distinguish general use from enterprise use throughout
- Build hands-on familiarity with PromQL functions, operators, and recording rules
- Understand the Prometheus query UI modes and their operational use

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- All scaling claims quantified where possible
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Table of Contents

1. [PromQL Query Structure](#1-promql-query-structure)
2. [Functions](#2-functions)
3. [Binary Operators and Vector Matching](#3-binary-operators-and-vector-matching)
4. [Recording Rules](#4-recording-rules)
5. [Real-World Query Patterns](#5-real-world-query-patterns)
6. [Query UI — Table, Graph, Explain](#6-query-ui--table-graph-explain)
7. [Questions and Answers](#7-questions-and-answers)
8. [Advanced Topics](#8-advanced-topics)
9. [Reference Material](#9-reference-material)

---

## 1. PromQL Query Structure

### Instant Vectors vs Range Vectors

**Instant vector** — a single value per time series at a specific point in time:

```promql
node_memory_MemAvailable_bytes
```

Returns one current value per matching time series. Used for current state — gauges, dashboard panels showing a single value.

**Range vector** — a set of values over a time window for each time series:

```promql
node_memory_MemAvailable_bytes[5m]
```

Returns the last 5 minutes of samples per series. Range vectors cannot be graphed directly — they are inputs to functions like `rate()` and `increase()` that reduce them back to instant vectors.

**Practical rule:**
- Gauges — query as instant vectors directly
- Counters — always wrap in `rate()` or `increase()` with a range vector

---

### Selectors and Matchers

Label matchers filter which time series are returned:

```promql
# Exact match
node_cpu_seconds_total{mode="idle"}

# Negative match
node_cpu_seconds_total{mode!="idle"}

# Regex match
node_cpu_seconds_total{mode=~"user|system"}

# Negative regex
node_cpu_seconds_total{mode!~"idle|iowait"}

# Multiple matchers — all conditions must match
node_cpu_seconds_total{mode="idle", cpu="0"}
```

**Enterprise pattern:** Scope queries to specific jobs or environments to prevent mixing production and staging data:

```promql
rate(http_requests_total{job="api-server", environment="production"}[5m])
```

---

### The Offset Modifier

Queries data from a point in the past relative to current time:

```promql
node_memory_MemAvailable_bytes offset 1h        # value from 1 hour ago
rate(node_cpu_seconds_total[5m] offset 24h)     # CPU rate from 24 hours ago
```

**Real-world use:** Day-over-day or week-over-week comparisons. Subtract the offset result from the current result to answer "is today's CPU usage higher than yesterday's at this time?"

---

## 2. Functions

### rate() — In Depth

`rate()` calculates the per-second rate of increase of a counter over a range window. Always returns a **per-second value** regardless of window size. Handles counter resets automatically.

**The minimum window rule:** `rate()` requires at least two samples in the range window. Rule of thumb — range window should be at least **4× the scrape interval**:

| Scrape interval | Minimum range | Standard range |
|---|---|---|
| 15s | 1m | 5m |
| 30s | 2m | 10m |
| 60s | 4m | 20m |

```promql
rate(node_cpu_seconds_total[5m])     # per-second rate, 5min smoothing
rate(node_cpu_seconds_total[1m])     # minimum viable at 15s scrape interval
rate(node_cpu_seconds_total[30s])    # too narrow — will produce gaps
```

**Converting to other time units:**

```promql
rate(metric[5m])      # per-second (default)
rate(metric[5m]) * 10 # per-10-seconds
rate(metric[5m]) * 60 # per-minute
rate(metric[5m]) * 3600 # per-hour
```

Per-second output is fixed by design — standardizes results across targets with different scrape intervals.

---

### increase() vs rate()

```promql
rate(http_requests_total[5m])       # per-second rate — how fast right now
increase(http_requests_total[5m])   # total increase over 5 minutes — how many
```

- Use `rate()` for dashboards showing current throughput
- Use `increase()` when you want a total count over a window

---

### delta() and idelta() — For Gauges

> **Never use `rate()` or `increase()` on gauges.** Those functions assume counter semantics and produce incorrect results on metrics that can decrease.

**`delta()`** — difference between first and last value across the full range window:

```promql
delta(node_memory_MemAvailable_bytes[1h])   # memory change over last hour
delta(node_filesystem_avail_bytes[24h])     # disk consumption over last day
```

Returns positive if gauge increased, negative if decreased. Used for trend analysis and capacity planning.

**`idelta()`** — difference between the last two samples only:

```promql
idelta(node_hwmon_temp_celsius[2m])   # change between last two scrapes
```

More responsive than `delta()` — reacts immediately to sudden changes. Used for alerting on sharp state changes.

**Choosing between them:**

| Need | Function | Reason |
|---|---|---|
| Trend over time | `delta()` | Uses full window — smooths noise |
| Sudden change detection | `idelta()` | Uses last two samples — maximum responsiveness |
| Capacity planning | `delta()` | Long window gives meaningful trend |
| Alerting on spikes | `idelta()` | Fires immediately on sharp changes |

---

### The Quick Rule — Which Function to Use

| Question | Metric type | Function |
|---|---|---|
| How many X happened? | Counter | `increase()` |
| How fast is X happening? | Counter | `rate()` |
| How much did X change? | Gauge | `delta()` |
| Did X change suddenly? | Gauge | `idelta()` |

If the metric name ends in `_total` — it is a counter. Use `rate()` or `increase()`. Everything else is likely a gauge — use `delta()` or query directly.

---

### Aggregation Operators

Reduce multiple time series into fewer series by applying a mathematical operation across label dimensions:

```promql
# Sum across all series — single value
sum(rate(node_cpu_seconds_total[5m]))

# Sum grouped by mode — one value per mode
sum by (mode) (rate(node_cpu_seconds_total[5m]))

# Sum dropping specific labels
sum without (cpu, mode) (rate(node_cpu_seconds_total[5m]))

# Average memory across all instances
avg(node_memory_MemAvailable_bytes)

# Maximum CPU usage — find the busiest host
max by (instance) (rate(node_cpu_seconds_total{mode!="idle"}[5m]))

# Count scrape targets currently up
count(up{job="node-exporter"})
```

**`by` vs `without`:**
- `by (label1, label2)` — keep only these labels, aggregate everything else
- `without (label1, label2)` — drop these labels, keep everything else

`by` is more common — explicitly declare what dimensions you want in the output.

**Enterprise pattern — fleet-wide CPU visibility:**

```promql
avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100
```

One number per host regardless of CPU count — the fleet view needed for capacity planning.

---

### histogram_quantile()

Calculates estimated quantile values from histogram bucket data:

```promql
# 99th percentile HTTP request duration
histogram_quantile(0.99, rate(prometheus_http_request_duration_seconds_bucket[5m]))

# 95th percentile
histogram_quantile(0.95, rate(prometheus_http_request_duration_seconds_bucket[5m]))

# 50th percentile (median)
histogram_quantile(0.50, rate(prometheus_http_request_duration_seconds_bucket[5m]))
```

The `rate()` wrapper is necessary — histogram buckets are counters and must be converted to rates before quantile calculation.

**What is a quantile:** The value below which X percent of observations fall. Equivalent to percentiles expressed as a decimal (0.99 = 99th percentile).

**Why quantiles matter over averages:** Averages hide tail latency. A p99 of 10,000ms on an API handling 1,000 requests/min means 10 users per minute are waiting 10 seconds — invisible in the average if the other 990 complete in 50ms.

**Enterprise SLO connection:** SLAs are almost always expressed in quantile terms — "99% of requests must complete within 200ms" is a p99 SLO. `histogram_quantile()` is the direct query answer to SLO measurement.

**NaN results:** Returned when insufficient samples exist in the window to calculate a meaningful quantile. Expected for low-traffic handlers. Persistent NaN on an expected-active handler indicates a data collection problem.

**Lab results (Prometheus self-scrape):**

| Handler | p99 | p95 | p50 |
|---|---|---|---|
| `/metrics` | 99ms | 95ms | 50ms |
| `/api/v1/query` | 99ms | — | 50ms |

Small gap between p50 and p99 indicates consistent response times with no severe tail latency — expected on a lightly loaded lab instance.

---

### absent() — Alerting on Missing Data

Returns a value when a time series does **not** exist:

```promql
# Returns result only if node-exporter is NOT being scraped
absent(up{job="node-exporter"})

# Returns result only if no data received in 5 minutes
absent(rate(node_cpu_seconds_total[5m]))
```

**Why it matters:** Standard threshold alerts require data to exist. When a target goes down entirely metrics disappear — there is nothing to threshold against. `absent()` detects the disappearance itself.

**Enterprise pattern:** Every critical monitoring target should have an `absent()` alert alongside its threshold alerts. "Alert if we stop receiving data" is complementary to "alert if this value exceeds a threshold" — both are required for complete coverage.

---

### avg_over_time() — Availability Reporting

Aggregates a single series over time — distinct from `avg()` which aggregates across multiple series:

```promql
# Percentage of time each target was up over last 24 hours
avg_over_time(up[24h]) * 100

# Fleet-wide availability over last 24 hours
avg(avg_over_time(up[24h])) * 100

# Monthly SLA reporting
avg(avg_over_time(up[30d])) * 100
```

**`avg()` vs `avg_over_time()`:**

| Function | Aggregates | Use case |
|---|---|---|
| `avg()` | Across multiple series at one point in time | "What is the average value across all instances right now?" |
| `avg_over_time()` | One series over a time range | "What was the average value of this series over the last 24 hours?" |

**Lab result:** Both targets (node-exporter and Prometheus) showed 100% availability over 24 hours — expected on a cleanly running lab.

---

## 3. Binary Operators and Vector Matching

### Arithmetic Between Metrics

```promql
# Memory usage percentage
100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))

# Disk usage percentage
100 - ((node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100)

# CPU usage percentage
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

---

### Comparison Operators

Return only series where the condition is true — the foundation of alerting rules:

```promql
# Memory below 1GB
node_memory_MemAvailable_bytes < 1073741824

# CPU idle below 20%
avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100 < 20

# Disk usage above 80%
100 - ((node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100) > 80
```

When no series match the condition the expression returns nothing — alert is not firing. When series match — alert fires.

---

### Vector Matching — on() and ignoring()

Required when arithmetic is performed between metrics with different label sets:

```promql
# Match only on specific labels
metric_a / on(instance, job) metric_b

# Match on everything except specified labels
metric_a / ignoring(le) metric_b
```

**Common pattern — aggregate to common label set before arithmetic:**

```promql
# HTTP error rate — aggregate away code label before dividing
sum by (instance) (rate(http_requests_total{status=~"5.."}[5m]))
/
sum by (instance) (rate(http_requests_total[5m]))
```

---

## 4. Recording Rules

### What They Are

Pre-computed PromQL expressions stored as new metrics. Prometheus evaluates them on a defined interval and writes results to the TSDB as regular time series.

**Use recording rules when:**
- A query is expensive — high cardinality aggregation across many series
- The same query is used in multiple dashboards or alerts
- You want to downsample high-frequency data for long-range queries

**Do not use recording rules for:**
- Simple queries that are already fast
- One-off investigative queries

---

### Naming Convention

```
level:metric:operations
```

- `level` — aggregation level (e.g., `job`, `instance`, `cluster`)
- `metric` — base metric name without suffixes
- `operations` — PromQL operations applied (e.g., `rate5m`, `avg`)

Examples:
```
job:http_requests_total:rate5m
instance:node_cpu:avg_rate5m
cluster:node_memory_available:avg
```

---

### Lab Implementation

**recording_rules.yml:**

```yaml
groups:
  - name: node_cpu_rules
    interval: 1m
    rules:
      - record: instance:node_cpu_utilization:avg_rate5m
        expr: |
          100 - (
            avg by (instance) (
              rate(node_cpu_seconds_total{mode="idle"}[5m])
            ) * 100
          )

      - record: instance:node_memory_utilization:ratio
        expr: |
          1 - (
            node_memory_MemAvailable_bytes
            /
            node_memory_MemTotal_bytes
          )

      - record: instance:node_filesystem_utilization:ratio
        expr: |
          1 - (
            node_filesystem_avail_bytes{fstype="ext4"}
            /
            node_filesystem_size_bytes{fstype="ext4"}
          )
```

**prometheus.yml addition:**

```yaml
rule_files:
  - "recording_rules.yml"
```

**docker-compose.yml volume mount addition:**

```yaml
volumes:
  - ./prometheus.yml:/etc/prometheus/prometheus.yml
  - ./recording_rules.yml:/etc/prometheus/recording_rules.yml
  - prometheus_data:/prometheus
```

**Hot reload without restart:**

```bash
curl -X POST http://localhost:9090/-/reload
```

> **Note:** A full `docker compose up -d` was required in the lab to mount the new volume. Hot reload handles configuration changes to already-mounted files — it does not mount new volumes.

---

### Verifying Recording Rules

**Rules page:** `http://localhost:9090/rules`

What to verify:
- **State** — must be `ok`. `err` indicates PromQL error. `unknown` means not yet evaluated.
- **Last evaluation time** — should update on your configured interval
- **Last evaluation duration** — sub-millisecond for simple rules. Seconds-range duration at enterprise scale indicates a rule that needs optimization

**Lab results:**

| Rule | State | Evaluation duration |
|---|---|---|
| `instance:node_cpu_utilization:avg_rate5m` | ok | 1ms |
| `instance:node_memory_utilization:ratio` | ok | 0ms |
| `instance:node_filesystem_utilization:ratio` | ok | 0ms |

**Query recorded metrics:**

```promql
instance:node_cpu_utilization:avg_rate5m      # lab result: 8.01%
instance:node_memory_utilization:ratio        # lab result: 0.606 (60.6%)
instance:node_filesystem_utilization:ratio    # lab result: 0.2196 (21.96%)
```

---

### Enterprise Value of Recording Rules

The Explain tab demonstrates why recording rules matter at scale:

```
sum by (mode) (rate(node_cpu_seconds_total[5m]))

Step 1 — series selection:   176 series, 10ms
Step 2 — rate():             176 series, 11ms
Step 3 — sum by (mode):      8 series,   5ms
```

At enterprise scale the same query might load 2,000,000 series taking 8+ seconds before aggregation. A recording rule pre-computes the aggregation — the dashboard query hits 8 series instead of 2,000,000. The Explain tab is the diagnostic tool that identifies which queries need this treatment.

---

## 5. Real-World Query Patterns

### System Health

```promql
# All targets and current up/down status
up

# Targets currently down
up == 0

# Percentage of targets currently up
avg(up) * 100
```

### CPU Saturation

```promql
# Using recording rule
instance:node_cpu_utilization:avg_rate5m

# Inline
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# CPU time breakdown by mode
sum by (mode) (rate(node_cpu_seconds_total[5m])) * 100
```

### Memory Pressure

```promql
# Available memory
node_memory_MemAvailable_bytes

# Utilization percentage
100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))

# Trend — growing or shrinking?
delta(node_memory_MemAvailable_bytes[1h])
```

### Disk — Usage and Prediction

```promql
# Current utilization
100 - ((node_filesystem_avail_bytes{fstype="ext4"} / node_filesystem_size_bytes{fstype="ext4"}) * 100)

# Consumption rate
delta(node_filesystem_avail_bytes{fstype="ext4"}[1h]) * -1

# Predict time until full (seconds) — only meaningful with consistent consumption
(node_filesystem_avail_bytes{fstype="ext4"})
/
(delta(node_filesystem_avail_bytes{fstype="ext4"}[6h]) * -1)
> 0
```

> The `> 0` filter excludes negative results (disk growing or flat) — the prediction is only meaningful when consumption is real and positive. On lab or low-write systems the result will be noisy or negative.

**Enterprise relevance:** Reactive disk alerts ("disk is 90% full") are too late for production systems. A predictive alert ("disk will be full in 4 hours") gives operators time to act. This calculation is not possible in a system that only supports threshold comparisons — a direct answer to why a robust query language matters.

### Error Rate and Availability

```promql
# HTTP error rate as percentage of total
100 * (
  sum by (instance) (rate(prometheus_http_requests_total{code=~"5.."}[5m]))
  /
  sum by (instance) (rate(prometheus_http_requests_total[5m]))
)

# Per-target availability over last 24 hours
avg_over_time(up[24h]) * 100

# Fleet-wide monthly availability — SLA reporting
avg(avg_over_time(up[30d])) * 100
```

### Capacity Planning

```promql
# Least available memory across fleet
min by (instance) (node_memory_MemAvailable_bytes)

# Instance with least available disk
min by (instance) (node_filesystem_avail_bytes{fstype="ext4"})

# CPU headroom on most loaded instance
min by (instance) (
  avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
) * 100
```

---

## 6. Query UI — Table, Graph, Explain

Located at `http://localhost:9090/graph`.

### Table

Returns current value of each matching series at query execution time. One row per series showing full label set and value.

Best used for:
- Inspecting current state
- Verifying a query returns expected series
- Cardinality investigation — how many series does this match

---

### Graph

Plots query result over a configurable time range. Requires an instant vector — range vectors must be wrapped in a function before graphing.

Best used for:
- Visualizing trends
- Confirming recording rules or derived metrics behave as expected
- Validating alert expressions before implementing — if the line crosses your threshold at expected times, the logic is correct

---

### Explain

Shows the query execution plan — how Prometheus evaluated the query internally, how many series were loaded at each step, and where the computational cost is.

**Lab example — `sum by (mode) (rate(node_cpu_seconds_total[5m]))`:**

| Step | Series in | Series out | Time |
|---|---|---|---|
| `node_cpu_seconds_total[5m]` | — | 176 | 10ms |
| `rate(...)` | 176 | 176 | 11ms |
| `sum by (mode)` | 176 | 8 | 5ms |

Reading bottom to top follows actual execution order. The label cardinality breakdown at each step (cpu: 22, mode: 8, instance: 1, job: 1) confirms the series selection matches expectations.

**Enterprise use:** When a dashboard query is slow, Explain identifies whether the cost is in series selection (cardinality problem) or aggregation (vector matching problem). That distinction determines the fix — reduce cardinality via better label design, or add a recording rule to pre-compute the aggregation.

---

## 7. Questions and Answers

### Q1: What is a quantile?

**Summary:** The value below which X percent of observations fall. Equivalent to a percentile expressed as a decimal. p99 = 99th percentile = 99% of observations fall below this value.

Averages hide tail latency — a p99 of 10,000ms is invisible in an average if 99% of requests complete in 50ms. Enterprise SLOs are almost always expressed as quantiles: "99% of requests must complete within 200ms."

---

### Q2: What is the difference between delta() and increase()?

**Summary:** `increase()` is for counters and handles resets. `delta()` is for gauges and treats all value changes as real. Using the wrong function on the wrong metric type produces silently incorrect results.

| Function | Metric type | Reset handling | Use case |
|---|---|---|---|
| `increase()` | Counter | Yes — adjusts for resets | Total events over a window |
| `delta()` | Gauge | No — drop = real decrease | Change in state over a window |

---

### Q3: Can a metric type be changed once established?

**Summary:** Prometheus does not persist type information in the TSDB — types are scrape-time metadata only. A type change on a metric without renaming it will silently produce incorrect query results for any dashboard or alert using type-specific functions.

**Correct approach:** Rename the metric. Introduce a new name with the correct type, deprecate the old one. This is a breaking change management problem — at enterprise scale, changing a metric type without renaming it breaks dashboards and alerts across every consumer.

---

### Q4: When would you use idelta() over delta()?

**Summary:** Use `delta()` for trend analysis over a meaningful time window. Use `idelta()` when you need maximum responsiveness to sudden changes — it uses only the last two samples regardless of window size.

```promql
delta(node_memory_MemAvailable_bytes[6h])       # 6-hour memory trend
idelta(node_hwmon_temp_celsius[2m])             # sudden temperature spike detection
```

---

### Q5: How do you see a metric's type and description?

**Summary:** Three places — the raw `/metrics` endpoint, the Prometheus API metadata endpoint, and the Prometheus UI autocomplete.

```
# Raw exposition — search for metric name
http://localhost:9100/metrics

# API metadata — scoped to one metric
http://localhost:9090/api/v1/metadata?metric=node_memory_MemAvailable_bytes

# UI autocomplete — shows HELP text inline as you type
http://localhost:9090/graph
```

At enterprise scale with hundreds of metrics, a dedicated metric catalog built on the `/api/v1/metadata` endpoint is more practical than the UI.

---

### Q6: How do you get avg(up) over the last 24 hours?

**Summary:** `avg()` aggregates across series at one point in time and does not accept a range vector. Use `avg_over_time()` to aggregate one series over time, then wrap in `avg()` to aggregate across series.

```promql
# Wrong — parse error
avg(up[24h])

# Correct — per target availability
avg_over_time(up[24h]) * 100

# Correct — fleet-wide availability
avg(avg_over_time(up[24h])) * 100
```

---

### Q7: What happens when two sources expose the same metric with conflicting #HELP, #TYPE, or #UNIT?

**Summary:** Each conflict is handled differently. #HELP and #UNIT conflicts are silent — last scrape wins, no warning. #TYPE conflicts generate a logged warning but data is still ingested. Type conflicts produce silently incorrect query results at runtime.

| Field | On conflict | Impact |
|---|---|---|
| `# HELP` | Last scrape wins, no warning | Documentation unreliable |
| `# TYPE` | Warning logged, data ingested | Silent incorrect query results |
| `# UNIT` | Last scrape wins, no warning | Documentation unreliable |

**Mitigation:** Prefix metric names with application or service name to prevent collisions. Validate instrumentation in CI/CD pipelines using promtool before deployment.

---

### Q8: How do you identify OpenMetrics format vs traditional Prometheus format?

**Summary:** Three signals — the Content-Type header (most reliable), the presence of `# EOF` at the end of the response, and the optional `# UNIT` field.

| Signal | Traditional format | OpenMetrics format |
|---|---|---|
| Content-Type | `text/plain; version=0.0.4` | `application/openmetrics-text; version=1.0.0` |
| EOF marker | None | `# EOF` as last line |
| UNIT field | Not present | Optional `# UNIT` field |

**Lab results:**

| Target | Format | Content-Type |
|---|---|---|
| node-exporter | Traditional | `text/plain; version=0.0.4; charset=utf-8; escaping=underscores` |
| Prometheus self | Traditional | `text/plain; charset=utf-8` |

The `escaping=underscores` field on node-exporter is a Prometheus 3.x addition indicating how special characters in metric names are handled — not a format difference.

---

### Q9: Where are Prometheus log messages seen?

**Summary:** Prometheus logs to stdout by default. In Docker environments logs are accessed via `docker logs`. Prometheus does not write to a file unless output is explicitly redirected.

```bash
# All logs
docker logs prometheus

# Follow live
docker logs prometheus -f

# Recent logs only
docker logs prometheus --tail 100

# Filter for warnings and errors
docker logs prometheus 2>&1 | grep -i "warn\|error"

# Confirm clean startup
docker logs prometheus 2>&1 | grep "Server is ready"
```

> `2>&1` is required because Prometheus writes to stderr, not stdout. Without it grep will not see log lines.

**Log levels** — controlled via `--log.level` flag: `debug`, `info` (default), `warn`, `error`. Never run `debug` in production long-term — at high scrape volumes it generates significant output and can itself become a performance bottleneck.

**Enterprise pattern:** Grafana Alloy can collect Prometheus container logs and ship them to Loki — enabling LogQL queries against Prometheus warnings and errors alongside the metrics they relate to. This is the logs and metrics correlation pattern introduced in Week 2.

---

### Q10: What is CI/CD and how does it relate to Prometheus?

**Summary:** CI (Continuous Integration) automatically builds and tests code on every commit. CD (Continuous Delivery) automatically deploys code that passes all checks. Together they form a pipeline from code commit to production.

In a mature observability organization, metric instrumentation code goes through the same CI pipeline as application code. **promtool** runs as a CI step to validate metric naming conventions, type declarations, and cardinality anti-patterns before code reaches production. This prevents naming conflicts, type mismatches, and label cardinality problems from reaching a production Prometheus instance.

"Do you validate your metric instrumentation in CI" is a meaningful observability maturity diagnostic question. Teams at early maturity do not. Teams at advanced maturity treat metrics as a contract requiring the same rigor as an API.

---

## 8. Advanced Topics

Topics identified during Days 2 and 3 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, and native histograms | Histograms are a significant cardinality source. Native histograms (Prometheus 2.40+) change the storage model and reduce series count overhead substantially. | Day 2 — TSDB cardinality analysis |
| **Recording rules** — advanced design, naming conventions, and performance impact at scale | Day 3 covered foundational implementation. Enterprise scale introduces rule evaluation performance, rule dependencies, and federation of recorded metrics. | Day 2 — metric types; Day 3 — hands-on implementation |
| **SNMP exporter configuration** — Counter32 vs Counter64 OID selection | Operational gap when customers migrate from traditional NMS to Prometheus-based observability. Counter32 wrapping at high throughput produces unreliable rate calculations. | Day 2 — counter ceiling discussion |
| **Alerting rules** — design, routing, and inhibition | Day 3 covered comparison operators as the foundation. Full alerting rule design, Alertmanager routing, and inhibition rules are a dedicated topic. | Day 3 — comparison operators, absent() |
| **Prometheus CI/CD integration** — promtool in pipelines | Metric instrumentation validation before deployment. Prevents naming conflicts, type mismatches, and cardinality anti-patterns from reaching production. | Day 3 — metric type conflicts discussion |

---

## 9. Reference Material

### PromQL Functions and Operators

| Resource | URL | Notes |
|---|---|---|
| PromQL function reference | https://prometheus.io/docs/prometheus/latest/querying/functions/ | Authoritative — covers all functions including rate(), delta(), histogram_quantile() |
| PromQL operators | https://prometheus.io/docs/prometheus/latest/querying/operators/ | Binary operators, vector matching, aggregation operators |
| PromQL basics | https://prometheus.io/docs/prometheus/latest/querying/basics/ | Selectors, matchers, offset modifier, staleness |
| Querying examples | https://prometheus.io/docs/prometheus/latest/querying/examples/ | Real-world query patterns from the Prometheus maintainers |

### Recording Rules

| Resource | URL | Notes |
|---|---|---|
| Recording rules documentation | https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/ | Syntax, naming conventions, configuration |
| Recording rules best practices | https://prometheus.io/docs/practices/rules/ | When to use, naming conventions, anti-patterns |

### Histograms and Quantiles

| Resource | URL | Notes |
|---|---|---|
| Histograms vs summaries | https://prometheus.io/docs/practices/histograms/ | Maintainers' guidance — bucket design, quantile accuracy |
| histogram_quantile() reference | https://prometheus.io/docs/prometheus/latest/querying/functions/#histogram_quantile | Official function docs including native histogram support |
| Native histograms feature flag | https://prometheus.io/docs/prometheus/latest/feature_flags/#native-histograms | Reduces histogram cardinality overhead significantly |

### Data Model and Labels

| Resource | URL | Notes |
|---|---|---|
| Prometheus data model | https://prometheus.io/docs/concepts/data_model/ | Authoritative, short, read in full |
| Prometheus naming best practices | https://prometheus.io/docs/practices/naming/ | Naming conventions including suffix standards |
| Prometheus instrumentation best practices | https://prometheus.io/docs/practices/instrumentation/ | Label design, anti-patterns |
| Cardinality is key (Robust Perception) | https://www.robustperception.io/cardinality-is-key | Brian Brazil — best plain-language cardinality explanation |

### Scrape Mechanics and Metric Types

| Resource | URL | Notes |
|---|---|---|
| Exposition format specification | https://prometheus.io/docs/instrumenting/exposition_formats/ | Traditional and OpenMetrics format spec |
| Metric types | https://prometheus.io/docs/concepts/metric_types/ | Authoritative definitions with examples |
| Staleness handling | https://prometheus.io/docs/prometheus/latest/querying/basics/#staleness | How missing scrapes and stale markers work |
| rate() function reference | https://prometheus.io/docs/prometheus/latest/querying/functions/#rate | Counter reset handling, minimum window requirements |

### TSDB and Storage

| Resource | URL | Notes |
|---|---|---|
| Prometheus storage documentation | https://prometheus.io/docs/prometheus/latest/storage/ | Retention flags, WAL config, block structure |
| Fabian Reinartz — TSDB deep dive | https://fabxc.org/tsdb/ | Original TSDB author — design rationale and compaction strategy |
| Prometheus Admin API | https://prometheus.io/docs/prometheus/latest/querying/api/#tsdb-admin-apis | Deletion, tombstones, and admin operations |

### Competitive Landscape and Architecture

| Resource | URL | Notes |
|---|---|---|
| Prometheus comparison page | https://prometheus.io/docs/introduction/comparison/ | Official comparison to other monitoring systems |
| Grafana Mimir — what's new | https://grafana.com/blog/2023/01/25/whats-new-in-grafana-mimir/ | Grafana's framing of why Mimir exists vs Thanos |
| VictoriaMetrics vs Prometheus | https://victoriametrics.com/blog/prometheus-vs-victoriametrics/ | Biased source but technically accurate on comparison points |
| Prometheus SNMP exporter | https://github.com/prometheus/snmp_exporter | SNMP OID mapping including counter type handling |

### Enterprise Tooling

| Resource | URL | Notes |
|---|---|---|
| Grafana Mimirtool | https://grafana.com/docs/mimir/latest/manage/tools/mimirtool/ | Cardinality and active series analysis beyond stock Prometheus |
| promtool | https://prometheus.io/docs/prometheus/latest/command-line/promtool/ | Metric naming validation, rule checking, CI/CD integration |

---

*Day 3 complete. Day 4: Grafana depth — dashboard variables, dynamic queries, Explore mode, and alerting rules implementation.*

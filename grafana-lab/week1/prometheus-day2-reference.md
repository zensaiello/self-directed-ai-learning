# Prometheus Deep Dive — Day 2 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand the Prometheus data model at a level sufficient for enterprise architecture conversations
- Ground all concepts in the running lab instance with real data
- Quantify enterprise implications — no vague descriptors like "long-term" or "highly available"
- Distinguish general use from enterprise use throughout
- Identify where Prometheus fits well and where it does not
- Understand the competitive landscape
- Build hands-on familiarity with Prometheus internals via the running lab

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- All scaling claims quantified where possible
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Table of Contents

1. [The Prometheus Data Model](#1-the-prometheus-data-model)
2. [Labels, Cardinality, and Anti-Patterns](#2-labels-cardinality-and-anti-patterns)
3. [Scrape Mechanics](#3-scrape-mechanics)
4. [Metric Types](#4-metric-types)
5. [The Prometheus TSDB](#5-the-prometheus-tsdb)
6. [Storage Internals — WAL, Blocks, Compaction, Retention](#6-storage-internals--wal-blocks-compaction-retention)
7. [Competitive Landscape](#7-competitive-landscape)
8. [Questions and Answers](#8-questions-and-answers)
9. [Advanced Topics](#9-advanced-topics)
10. [Reference Material](#10-reference-material)

---

## 1. The Prometheus Data Model

A time series in Prometheus is uniquely identified by:
1. A **metric name** — e.g., `node_cpu_seconds_total`
2. A set of **labels** — key/value pairs describing dimensions of that metric

Each unique combination of metric name + label set is a **separate time series**. Prometheus stores a sequence of `(timestamp, value)` pairs for each one.

```
node_cpu_seconds_total{cpu="0", mode="idle", instance="node-exporter:9100", job="node-exporter"}
node_cpu_seconds_total{cpu="0", mode="user", instance="node-exporter:9100", job="node-exporter"}
node_cpu_seconds_total{cpu="1", mode="idle", instance="node-exporter:9100", job="node-exporter"}
```

> **Key distinction from Zenoss:** In Prometheus there are no objects. There are only labeled time series. The labels ARE the identity.

### Terminology
- **Time series** — a unique metric name + label set combination with its sequence of samples
- **Label set** — the collection of key/value label pairs that identify a series
- **Cardinality** — the total count of unique time series in a Prometheus instance, or the count of unique values for a specific label

### Lab Verification
Your instance label list: `http://localhost:9090/api/v1/labels`  
Unique values for a specific label: `http://localhost:9090/api/v1/label/<label_name>/values`  
Total series count: `http://localhost:9090/tsdb-status` → TSDB Head Status

**Lab result:** 2,584 active series from a single node-exporter + Prometheus self-scrape.

---

## 2. Labels, Cardinality, and Anti-Patterns

### Cardinality Math

Cardinality is multiplicative across label dimensions:

| Scenario | Series Count |
|---|---|
| 10 hosts, 4 CPU modes, 8 CPUs each | 10 × 4 × 8 = **320 series** |
| 1,000 hosts, same config | **32,000 series** |
| Add high-churn label (e.g., container_id) | Cardinality explodes |

### Memory Cost of Cardinality

In-memory overhead per active time series is approximately **3–4KB per series** in the head block:

| Active Series | Approximate RAM for Head Block |
|---|---|
| 100,000 | ~300–400MB |
| 1,000,000 | ~3–4GB |
| 5,000,000 | ~15–20GB |
| 10,000,000 | ~30–40GB |

> **Enterprise threshold:** Prometheus recommends staying under **10 million active series** per instance for reliable performance. A production Prometheus node for serious workloads should be sized at **32GB+ RAM**.

### The Label Anti-Pattern

**Never use a label that has unbounded unique values** — user IDs, email addresses, request UUIDs, full URLs. Each unique value creates a new time series.

**Rule:** Labels are for dimensions you aggregate or filter by. Ask before adding any label: *"Will I ever query 'show me all series where this label = X' or group by this label?"* If no — it does not belong as a label.

### Best Practices — What To Do Instead

| Anti-pattern | Best practice |
|---|---|
| `user_id="u-48291"` | `user_tier="enterprise"` |
| `url="/api/users/48291/orders/9921"` | `endpoint="/api/users/{id}/orders/{id}"` (templatized) |
| `error_message="full stack trace"` | `error_type="not_found"` |
| `instance_id="i-0a1b2c3d4e5f"` | `availability_zone="us-east-1a"` |

**High-cardinality identifiers belong in log data, not metrics.** This is one of the architectural arguments for running Loki alongside Prometheus — metrics answer *how many* and *how fast*, logs answer *which specific one* and *what happened*.

**Exemplars** — the bridge between metrics and traces. A trace ID can be attached to a metric data point as an exemplar without inflating cardinality. When a latency spike appears in Grafana you can click through to the specific trace in Tempo. Implemented in Week 3.

### Cardinality Diagnostic Queries

```promql
# All unique values for a specific label across all metrics
# http://localhost:9090/api/v1/label/mode/values

# Count series per metric — identify cardinality contributors
sort_desc(count by (__name__) ({__name__=~".+"}))

# Which metrics use a specific label
count by (__name__) ({mode!=""})

# Break down series per metric per label value
count by (__name__, mode) ({mode!=""})

# Series creation and removal rate — churn indicator
rate(prometheus_tsdb_head_series_created_total[5m])
rate(prometheus_tsdb_head_series_removed_total[5m])
```

> **Note:** `http://localhost:9090/api/v1/label/<name>/values` returns values across ALL metrics using that label — it is not scoped to a single metric. Use the PromQL approach above to scope to a specific metric.

### Lab Results — Top Series Contributors

| Metric | Series Count | Reason |
|---|---|---|
| `prometheus_http_request_duration_seconds_bucket` | 200 | Histogram — Prometheus self-scrape |
| `prometheus_http_response_size_bytes_bucket` | 180 | Histogram — Prometheus self-scrape |
| `node_cpu_seconds_total` | 176 | CPU modes × CPU count |
| `prometheus_http_requests_total` | 62 | Counter — Prometheus self-scrape |
| `node_scrape_collector_duration_seconds` | 48 | One series per collector |

> The two histogram metrics alone account for **~15% of total TSDB series** from Prometheus monitoring itself. This illustrates why histogram design matters at enterprise scale.

### Top Label Memory Usage (Lab)

| Label | Bytes | Reason |
|---|---|---|
| `__name__` | 115,578 | Every series has a metric name — always highest |
| `instance` | 70,302 | Every scraped metric carries instance label |
| `job` | 43,992 | Every scraped metric carries job label |
| `handler` | 12,674 | Prometheus self-scrape HTTP handler paths |
| `le` | 5,880 | Histogram bucket boundaries |

> `instance` and `job` are added automatically by Prometheus at scrape time to every series. At enterprise scale with thousands of targets these become significant index memory consumers.

---

## 3. Scrape Mechanics

### The Scrape Cycle

1. Prometheus opens an HTTP connection to the target's `/metrics` endpoint
2. Target responds with all current metric values in Prometheus exposition format (plain text)
3. Prometheus parses the response and writes new samples to the WAL
4. Prometheus records the scrape itself as a metric — duration, success/failure, sample count

### The Exposition Format

Raw output from node-exporter: `http://localhost:9100/metrics`

```
# HELP node_cpu_seconds_total Seconds the CPUs spent in each mode.
# TYPE node_cpu_seconds_total counter
node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67
node_cpu_seconds_total{cpu="0",mode="user"} 234.56
```

Three components:
- `# HELP` — human readable description
- `# TYPE` — declares the metric type
- Data lines — metric name, label set, current value

### Pull Model — Fit and Limitations

| Scenario | Fit | Notes |
|---|---|---|
| Stable infrastructure, direct network access | Good | Standard use case |
| Kubernetes with service discovery | Excellent | Native SD support |
| Firewall-segmented enterprise networks | Poor | Needs network path to every target |
| Short-lived batch jobs | Poor | May finish before scrape; Pushgateway workaround has limitations |
| Multi-datacenter / multi-region | Poor alone | Needs federation or remote_write |
| Push-only network environments | Poor | Pull model is incompatible |

> **From your Zenoss background:** Prometheus pull = same tension that led you to build PS.DataIngest as a push-based framework. The same architectural tradeoff exists here.

### Scrape Intervals and Storage Impact

Default scrape interval: **15 seconds** (configured in `prometheus.yml`)  
Default scrape timeout: **10 seconds**  
Staleness period: **5 minutes** before a series with no new samples is marked stale

| Interval | Samples/series/day | Storage (1M series, compressed) |
|---|---|---|
| 15s (default) | 5,760 | ~11GB/day |
| 30s | 2,880 | ~5.5GB/day |
| 60s | 1,440 | ~2.75GB/day |

> Halving scrape interval doubles storage and ingest load. Not every metric needs 15-second resolution.

### Useful Diagnostic Endpoints

| Endpoint | What it shows |
|---|---|
| `http://localhost:9090/api/v1/labels` | All label names in TSDB |
| `http://localhost:9090/api/v1/label/job/values` | All values for a specific label |
| `http://localhost:9090/tsdb-status` | Cardinality stats, top series by label |
| `http://localhost:9090/targets` | Scrape target health — UP/DOWN, duration |
| `http://localhost:9100/metrics` | Raw node-exporter exposition output |

---

## 4. Metric Types

### Counter
- Always increases, never decreases (resets to 0 on process restart)
- Never query the raw value — use `rate()` or `increase()`
- Examples: `node_cpu_seconds_total`, `http_requests_total`

```promql
rate(node_cpu_seconds_total[5m])     # per-second rate over 5 min window
increase(node_cpu_seconds_total[5m]) # total increase over 5 min window
```

### Gauge
- Can go up or down — represents current state
- Query the raw value directly
- Examples: `node_memory_MemAvailable_bytes`, `node_filesystem_avail_bytes`

### Histogram
- Samples observations into configurable buckets
- Generates three metric families automatically:
  - `_bucket` — one series per bucket boundary (`le` label)
  - `_sum` — running total of all observed values
  - `_count` — total number of observations
- Used for latency, request sizes, anything where distribution matters
- **Expensive in series count** — see cardinality impact below

### Summary
- Similar to histogram but calculates quantiles **client-side at the application**
- Generates `_sum`, `_count`, and quantile series
- **Cannot be aggregated across multiple instances** — hard limitation
- Generally histogram is preferred at enterprise scale for this reason

### Series Count by Metric Type

| Metric Type | Series (single instance) |
|---|---|
| Counter | 1 per label combination |
| Gauge | 1 per label combination |
| Histogram (10 buckets) | ~12 per label combination |
| Histogram (30 buckets) | ~32 per label combination |
| Summary (4 quantiles) | ~6 per label combination |

**Enterprise example:**
```
10 histograms × 32 series × 100 instances = 32,000 series from one service
```

### Metric Units — Convention Not Enforcement

Units are embedded in metric names by convention:

| Unit | Suffix | Example |
|---|---|---|
| Seconds | `_seconds` | `http_request_duration_seconds` |
| Bytes | `_bytes` | `node_memory_MemAvailable_bytes` |
| Ratio (0–1) | `_ratio` | `disk_usage_ratio` |
| Counter total | `_total` | `http_requests_total` |
| Celsius | `_celsius` | `node_hwmon_temp_celsius` |

Prometheus has no formal unit enforcement — naming conventions are enforced via community standards and linting tools like **promtool**.

### rate() — Understanding the Output Unit

`rate()` **always returns a per-second value** regardless of window size. The `[5m]` parameter is the lookback window, not the output unit.

```promql
rate(metric[5m])      # per-second rate, 5min smoothing window
rate(metric[5m]) * 10 # per-10-second rate, 5min smoothing window
rate(metric[5m]) * 60 # per-minute rate, 5min smoothing window
```

This is by design — standardizing on per-second makes results comparable regardless of scrape interval, which matters when writing alerts or recording rules that span targets with different scrape intervals.

### Derive Metric Type — Does Prometheus Have One?

No. Prometheus stores raw counter values always. Derivation happens at **query time** via PromQL (`rate()`, `increase()`, `delta()`), not at ingest time.

**Advantage over derive-at-ingest:** You can change the derivation window after the fact. You can query `rate()[1m]` or `rate()[1h]` against the same stored data without data loss.

**Recording rules** are the explicit equivalent — pre-computing expensive derivations and storing results as new metrics. Covered in Day 3.

---

## 5. The Prometheus TSDB

Prometheus built a **custom TSDB from scratch**, written in Go. It is not built on RocksDB, LevelDB, or any general-purpose storage backend. Extracted to `github.com/prometheus/prometheus/tsdb` — used by Mimir and other projects.

### Why Custom

General-purpose databases are not optimized for time series workload characteristics:
- Append-heavy writes
- Range queries by time
- High compression of numeric sequences

### Gorilla Compression

Prometheus uses compression based on **Gorilla** (Facebook, 2015):
- **Delta-of-delta encoding** for timestamps — consecutive timestamps are predictable
- **XOR encoding** for float64 values — consecutive values change minimally
- Achieves approximately **1–2 bytes per sample** on disk vs. 16 bytes raw (timestamp + float64)

### Enterprise Limitations

| Limitation | Impact |
|---|---|
| No built-in replication | Single node — data loss on failure |
| No horizontal scaling | Cannot distribute load across nodes |
| Compaction is single-threaded | At high series counts, compaction causes query latency spikes |
| Local storage only | Cannot meet compliance retention requirements alone |

---

## 6. Storage Internals — WAL, Blocks, Compaction, Retention

### The Write Path

```
Scrape → WAL → Head Block (memory) → Persistent Block (disk) → Compaction → Retention
```

### WAL (Write-Ahead Log)

Location: `/prometheus/wal/`

- Sequential append-only log — crash recovery mechanism
- Written in **128MB segments** by default (00000000, 00000001, ...)
- On restart, Prometheus replays WAL to reconstruct head block state
- Segments are deleted after being checkpointed into persistent blocks
- Checkpoint happens every **2 hours** when head block flushes

**WAL size at scale:**

| Active Series | Approximate WAL Size |
|---|---|
| 10,000 | ~50–100MB |
| 100,000 | ~500MB–1GB |
| 1,000,000 | ~5–10GB |
| 10,000,000 | ~50–100GB |

> **Operational note:** WAL and data should be on the same filesystem. Separating them risks filling a small WAL volume and crashing Prometheus — a common enterprise deployment mistake.

### Head Block

- The **current active write target** — covers the most recent 2 hours
- Partially in memory, partially in memory-mapped files
- The only **mutable** block — all persistent blocks are immutable
- Primary source of memory pressure (~3–4KB per active series)

| Component | Location |
|---|---|
| Series index (label sets) | Memory |
| Recent chunks (~last 1hr) | Memory |
| Older chunks within head window | Memory-mapped files |
| WAL | Disk |

### Persistent Blocks

Written every 2 hours from the head block flush. Each block:
- Covers a fixed time range
- Has a unique **ULID** directory name
- Contains `chunks/`, `index`, `meta.json`, `tombstones`

**meta.json key fields:**

```json
{
  "ulid": "01KNMF055T0805WZNGFDYB24CR",
  "minTime": 1775571257647,
  "maxTime": 1775577600000,
  "stats": {
    "numSamples": 447620,
    "numSeries": 2447,
    "numChunks": 2648
  },
  "compaction": {
    "level": 1,
    "sources": ["01KNMF055T0805WZNGFDYB24CR"]
  }
}
```

- `minTime`/`maxTime` — Unix timestamps in **milliseconds**
- `compaction.level` — 1 = written directly from head flush, 2+ = merged from multiple blocks
- `compaction.sources` — ULIDs of all blocks that contributed to this block
- `compaction.parents` — present on level 2+ blocks, shows original block time ranges

### Compaction

Merges smaller blocks into larger ones to reduce file handle overhead and improve range query performance.

**Compaction schedule:**

| Stage | Block size |
|---|---|
| Initial (head flush) | 2 hours |
| After first compaction | Up to 6 hours |
| After second compaction | Up to 18 hours |
| After third compaction | Up to 54 hours |
| Maximum | 10% of retention period |

With default 15-day retention, maximum block size = **36 hours**.

> **Enterprise note:** Compaction is CPU and I/O intensive. At high series counts it causes query latency spikes and elevated disk I/O. Mitigate with dedicated fast NVMe storage and CPU headroom.

**Monitor compaction:**
```promql
rate(prometheus_tsdb_compactions_total[1h])
prometheus_tsdb_compaction_duration_seconds
```

### Retention

**Time-based (default 15 days):**
```
--storage.tsdb.retention.time=15d
```

**Size-based:**
```
--storage.tsdb.retention.size=100GB
```

Both can be used together — whichever limit is hit first triggers deletion. Deletion is at the **block level** — Prometheus cannot delete individual series or samples within a block.

**Tombstones — soft deletes:** Admin API deletions write a tombstone file. Data is immediately invisible to queries but disk space is not recovered until the next compaction rewrites the block.

**Enterprise retention requirements:**

| Retention | 1M series, 15s interval | Notes |
|---|---|---|
| 15 days (default) | ~57GB | Single node, no replication |
| 90 days | ~342GB | Single node, approaching practical limits |
| 1 year | ~1.4TB | Single node — unsustainable without object storage |
| 1 year (60s interval) | ~350GB | Reduced resolution trades fidelity for cost |

> Compliance workloads (finance, healthcare) commonly require **1–3 years** retention. A single Prometheus TSDB cannot meet these requirements alone. This is the architectural gap that **Mimir** addresses with object storage backends (S3, GCS, Azure Blob).

### Storage Diagnostic Queries

```promql
prometheus_tsdb_storage_blocks_bytes      # current persistent block storage
prometheus_tsdb_wal_storage_size_bytes    # current WAL size
prometheus_tsdb_compactions_total         # total compaction runs
prometheus_tsdb_blocks_loaded             # number of blocks currently loaded
prometheus_tsdb_head_series               # total series in head block
```

**Lab storage profile:**

| Metric | Value |
|---|---|
| Persistent blocks | 9.5MB (5 blocks, ~24hrs data) |
| WAL | 14.3MB (3 active segments) |
| Total on-disk | ~23MB |
| Compactions run | 7 |
| Head series | 2,654 |

### Stale Series

When Prometheus stops receiving samples for a series, after **5 minutes** it writes a stale marker — a sentinel NaN float64 value signaling the series is no longer being scraped.

**Causes:**
- Target goes down
- Label set changes (old series goes stale, new series created)
- Metric disappears from a target's `/metrics` output

**Impact:**
- PromQL correctly excludes stale series from calculations
- Stale series remain on disk until they age out of retention
- High-churn environments (Kubernetes with frequent pod restarts) generate continuous stale series — a primary driver of memory and CPU pressure

**Stale series diagnostic:**
```promql
# No direct stale count metric in Prometheus 3.x
# Approximate: head series minus active series
prometheus_tsdb_head_series

# Churn rate — series creation and removal
rate(prometheus_tsdb_head_series_created_total[5m])
rate(prometheus_tsdb_head_series_removed_total[5m])
```

**Churn at scale:**

| Environment | Typical created rate | Daily new series |
|---|---|---|
| Stable single host (lab) | ~0/sec | ~0 |
| Small K8s (50 pods) | ~5–10/sec | ~430K–860K |
| Large K8s (1000 pods) | ~100–500/sec | ~8.6M–43M |

---

## 7. Competitive Landscape

| Tool | Type | Model | Key Differentiator |
|---|---|---|---|
| **Prometheus** | Open source | Pull | PromQL, native K8s integration, no long-term storage built-in |
| **Grafana Mimir** | Open source | Pull (via remote_write) | Horizontally scalable, long-term storage, PromQL compatible, Grafana's forward path |
| **Thanos** | Open source | Pull (sidecar) | HA + object storage for Prometheus, older than Mimir, more operationally complex |
| **VictoriaMetrics** | Open source | Pull/Push | High resource efficiency, MetricsQL (PromQL superset), lower memory than Prometheus at scale |
| **Datadog** | SaaS | Push (agent) | Full-stack in one platform, lower ops burden, highest cost, proprietary query language, vendor lock-in |
| **InfluxDB** | Open source / commercial | Push | Own data model and query language (Flux), common in IoT/industrial use cases |
| **OpenTelemetry Collector** | Open source | Both | Vendor-neutral collection pipeline, not a storage backend — feeds into Prometheus, Mimir, Datadog, etc. |

> **Thanos vs Mimir:** Grafana Labs' position is that Mimir is the forward path. Thanos is widely deployed and worth knowing — customers will have it — but Mimir is the active development focus for Grafana.

> **VictoriaMetrics:** Commonly cited as using significantly less memory than Prometheus at equivalent scale. Customers will ask about it. Know that it exists and what the tradeoff is (PromQL-compatible but not identical, different operational model).

---

## 8. Questions and Answers

### Q1: How do I scope a label value query to a specific metric?

**Summary:** `http://localhost:9090/api/v1/label/<name>/values` returns values across ALL metrics using that label. Use PromQL to scope to a specific metric.

```promql
count by (mode) (node_cpu_seconds_total)   # distinct mode values within one metric
group by (mode) (node_cpu_seconds_total)   # same, without counts
```

[See label and cardinality section for full context.](#2-labels-cardinality-and-anti-patterns)

---

### Q2: How do I find all metrics that use a specific label?

**Summary:** No single PromQL expression retrieves metric names by label natively. Use the count by `__name__` pattern or the series API.

```promql
# PromQL — count series per metric name for all metrics carrying the label
count by (__name__) ({mode!=""})

# HTTP API — returns all series carrying the label with full label sets
http://localhost:9090/api/v1/series?match[]={mode!=""}
```

**Lab result:** `mode` is used by both `node_cpu_guest_seconds_total` and `node_cpu_seconds_total`.

---

### Q3: Can I define a unit on a metric?

**Summary:** By naming convention only — not enforced by Prometheus. OpenMetrics format adds a `# UNIT` field but it is metadata only and does not affect storage or queries.

Units are embedded in metric name suffixes: `_seconds`, `_bytes`, `_total`, `_ratio`, `_celsius`. Enforced via promtool linting in enterprise CI/CD pipelines.

---

### Q4: Does the Counter type have a ceiling?

**Summary:** No practical ceiling. Stored as float64 (max ~1.8 × 10³⁰⁸). Integer precision is exact up to 2⁵³ (~9 quadrillion). Counter resets on process restart are handled automatically by `rate()` and `increase()`.

**SNMP-specific consideration:** Counter32 wraps at **4,294,967,295**. On a saturated 1Gbps interface this wraps every ~34 seconds. With a 15-second scrape interval, multiple wraps per scrape window can make `rate()` unreliable. Mitigation: prefer Counter64 OIDs where available. See [Advanced Topics — SNMP exporter](#9-advanced-topics).

---

### Q5: Does Prometheus have a derive metric type?

**Summary:** No. Prometheus stores raw counter values always. Derivation happens at query time via PromQL functions (`rate()`, `increase()`, `delta()`). Recording rules are the explicit equivalent for pre-computing expensive derivations.

**Advantage:** You can change the derivation window after the fact — query `rate()[1m]` or `rate()[1h]` against the same stored raw data.

---

### Q6: What does stale mean and what is the impact?

**Summary:** After 5 minutes without new samples, Prometheus writes a special stale marker (sentinel NaN) for that series. PromQL uses stale markers to stop including dead series in calculations — preventing ghost values and incorrect rates. Stale series remain on disk until they age out of retention.

**Enterprise impact:** High-churn Kubernetes environments generate continuous stale series from pod restarts. At large K8s scale (1000+ pods) this creates constant head block pressure — a primary scaling challenge for single-node Prometheus.

---

### Q7: What is the TSDB built on?

**Summary:** Prometheus built a custom TSDB from scratch in Go — not built on any existing database engine. Uses Gorilla compression (delta-of-delta for timestamps, XOR for values) achieving ~1–2 bytes per sample on disk. The TSDB is extracted as a standalone library used by Mimir and other projects.

See [Section 5 — The Prometheus TSDB](#5-the-prometheus-tsdb) for full internals detail.

---

### Q8: Can I get a per-10-second rate from rate()?

**Summary:** `rate()` always returns per-second values. Multiply to convert:

```promql
rate(metric[5m]) * 10  # per-10-second rate, 5min window
rate(metric[5m]) * 60  # per-minute rate, 5min window
```

The `[5m]` parameter is the lookback window for smoothing, not the output unit. Per-second output is fixed by design so results are comparable regardless of scrape interval.

---

### Q9: How do I query current stale series count?

**Summary:** No direct metric in Prometheus 3.x. Approximate via:

```promql
# Gap between head series and active series (requires Prometheus 2.39+)
prometheus_tsdb_head_series - prometheus_tsdb_head_active_series

# Churn rates as proxy
rate(prometheus_tsdb_head_series_created_total[5m])
rate(prometheus_tsdb_head_series_removed_total[5m])
```

`prometheus_tsdb_head_active_series` is not present in Prometheus 3.11.0 despite being documented for 2.39+. For serious cardinality investigation at enterprise scale use **Grafana Mimirtool** which provides active series analysis beyond stock Prometheus.

---

## 9. Advanced Topics

Topics identified during Day 2 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, and native histograms | Histograms are a significant cardinality source. Native histograms (Prometheus 2.40+) change the storage model and reduce series count overhead substantially. | Day 2 — TSDB cardinality analysis |
| **Recording rules** — design, naming conventions, and performance impact | Pre-computed derivations for expensive queries. Explicit equivalent of derive metric types. Bridges directly to alerting rule design. | Day 2 — metric types, derive discussion |
| **SNMP exporter configuration** — Counter32 vs Counter64 OID selection | Operational gap when customers migrate from traditional NMS to Prometheus-based observability. Counter32 wrapping at high throughput produces unreliable rate calculations. | Day 2 — counter ceiling discussion |

---

## 10. Reference Material

### Data Model and Labels

| Resource | URL | Notes |
|---|---|---|
| Prometheus data model | https://prometheus.io/docs/concepts/data_model/ | Authoritative, short, read in full |
| Prometheus naming best practices | https://prometheus.io/docs/practices/naming/ | Naming conventions that enforce bounded cardinality |
| Prometheus instrumentation best practices | https://prometheus.io/docs/practices/instrumentation/ | Label design with specific guidance on anti-patterns |
| Cardinality is key (Robust Perception) | https://www.robustperception.io/cardinality-is-key | Brian Brazil (Prometheus maintainer) — best plain-language cardinality explanation |
| Grafana blog — cardinality spikes | https://grafana.com/blog/2022/02/15/what-are-cardinality-spikes-and-why-do-they-matter/ | Practical explanation with production numbers |
| Prometheus exemplars | https://prometheus.io/docs/prometheus/latest/exemplars/ | Metrics-to-traces bridge without cardinality cost |

### Scrape Mechanics and Metric Types

| Resource | URL | Notes |
|---|---|---|
| Exposition format specification | https://prometheus.io/docs/instrumenting/exposition_formats/ | Full text format spec — useful for debugging metrics endpoints |
| Metric types | https://prometheus.io/docs/concepts/metric_types/ | Authoritative definitions with examples |
| Histograms vs summaries | https://prometheus.io/docs/practices/histograms/ | Maintainers' guidance — explains why summaries can't be aggregated |
| Pushgateway — when not to use it | https://prometheus.io/docs/practices/pushing/ | Prometheus maintainers' own guidance on Pushgateway limitations |
| Staleness handling | https://prometheus.io/docs/prometheus/latest/querying/basics/#staleness | How missing scrapes and stale markers work — relevant for alerting |
| rate() function reference | https://prometheus.io/docs/prometheus/latest/querying/functions/#rate | Official docs — covers counter reset handling |

### TSDB and Storage

| Resource | URL | Notes |
|---|---|---|
| Prometheus storage documentation | https://prometheus.io/docs/prometheus/latest/storage/ | Retention flags, WAL config, block structure |
| TSDB on-disk format specification | https://github.com/prometheus/prometheus/blob/main/tsdb/docs/format/README.md | Actual format spec |
| Fabian Reinartz — TSDB deep dive | https://fabxc.org/tsdb/ | Original TSDB author — best single explanation of design rationale and compaction strategy |
| Gorilla compression paper (Facebook, 2015) | https://www.vldb.org/pvldb/vol8/p1816-teller.pdf | Original research Prometheus compression is based on |
| Prometheus Admin API (tombstones/deletion) | https://prometheus.io/docs/prometheus/latest/querying/api/#tsdb-admin-apis | Deletion and tombstone API |
| Native histograms feature flag | https://prometheus.io/docs/prometheus/latest/feature_flags/#native-histograms | New storage model that reduces histogram cardinality overhead |

### Competitive Landscape and Architecture

| Resource | URL | Notes |
|---|---|---|
| Prometheus comparison page | https://prometheus.io/docs/introduction/comparison/ | Official comparison to other monitoring systems |
| Grafana Mimir — what's new | https://grafana.com/blog/2023/01/25/whats-new-in-grafana-mimir/ | Grafana's framing of why Mimir exists vs Thanos |
| VictoriaMetrics vs Prometheus | https://victoriametrics.com/blog/prometheus-vs-victoriametrics/ | Biased source but technically accurate on comparison points |
| Prometheus SNMP exporter | https://github.com/prometheus/snmp_exporter | Configuration model for SNMP OID mapping including counter type handling |

### Enterprise Tooling

| Resource | URL | Notes |
|---|---|---|
| Grafana Mimirtool | https://grafana.com/docs/mimir/latest/manage/tools/mimirtool/ | Cardinality and active series analysis beyond stock Prometheus |
| promtool | https://prometheus.io/docs/prometheus/latest/command-line/promtool/ | Built-in Prometheus utility — metric naming validation, rule checking |

---

*Day 2 complete. Day 3: PromQL with intent — functions, operators, recording rules, real-world query patterns.*

# Prometheus & Grafana Deep Dive — Day 4 Reference
## Observability Upskilling — Steven Aiello

---

## Learning Criteria

### Session Goals
- Understand Grafana's role in the stack at a level sufficient for enterprise architecture conversations
- Build hands-on familiarity with dashboard variables, dynamic queries, and Explore mode
- Implement alerting rules in the running lab instance
- Understand Alertmanager's role and enterprise relevance
- Ground all concepts in the running lab instance with real data
- Quantify enterprise implications — no vague descriptors

### Working Parameters
- Direct, no filler, factually accurate
- Enterprise vs. general use distinctions called out explicitly
- All scaling claims quantified where possible
- Real-world examples over theory
- Related topics flagged as Advanced Topics for later exploration

---

## Table of Contents

1. [Grafana Architecture and Data Flow](#1-grafana-architecture-and-data-flow)
2. [Dashboard Variables](#2-dashboard-variables)
3. [Explore Mode](#3-explore-mode)
4. [Alerting Rules](#4-alerting-rules)
5. [Alertmanager Overview](#5-alertmanager-overview)
6. [Questions and Answers](#6-questions-and-answers)
7. [Advanced Topics](#7-advanced-topics)
8. [Reference Material](#8-reference-material)

---

## 1. Grafana Architecture and Data Flow

### Grafana's Role — Visualization Layer Only

Grafana does not store any data. It has no time series database of its own. Every number displayed in a Grafana dashboard is retrieved in real time from a connected data source at the moment the dashboard loaded or refreshed.

**Data flow for every panel:**

```
Browser loads dashboard
        ↓
Grafana reads panel configuration — data source + query
        ↓
Grafana sends PromQL query to Prometheus HTTP API
        ↓
Prometheus evaluates query against TSDB
        ↓
Prometheus returns JSON result
        ↓
Grafana renders result as visualization
```

**Enterprise implication:** If Prometheus is down, Grafana shows no data regardless of its own health. Grafana's availability SLA is bounded by the availability SLA of every data source it connects to. A Senior Observability Architect needs to be able to articulate this dependency clearly when designing production architectures.

---

### Data Source Configuration

Lab configuration values:

| Field | Value | Notes |
|---|---|---|
| URL | `http://prometheus:9090` | Docker internal network — container name resolves to container IP |
| Scrape interval | 15s | Must match prometheus.yml scrape_interval — mismatch causes gaps or wasted queries |
| Query timeout | 60s | Maximum wait before Grafana gives up — increase for expensive queries, prefer recording rules |
| HTTP method | POST | Preferred over GET — no URL length limit constraint on complex queries |

**Scrape interval alignment:** Grafana uses the configured scrape interval to calculate appropriate step intervals for graph queries. A mismatch with the actual Prometheus scrape interval produces either gaps (Grafana requests finer resolution than exists) or wasted queries (Grafana requests coarser resolution than needed).

**Query timeout:** At enterprise scale with expensive queries this sometimes needs increasing. However increasing the timeout is the wrong first response — if queries are timing out the correct fix is adding recording rules to pre-compute expensive aggregations.

**HTTP method POST:** PromQL queries can be arbitrarily long. Complex queries with many label matchers can exceed URL length limits if sent as GET. POST sends the query in the request body with no length constraint.

---

### Data Source URL in Production

The appropriate data source URL depends on the architecture:

| Architecture | Data source URL points to |
|---|---|
| Single Prometheus node | Direct host/port of that node |
| Active-passive HA | VIP or load balancer with failover to standby |
| Thanos | Thanos Query frontend |
| Mimir | Mimir query frontend load balancer |

> **Important distinction:** A traditional round-robin load balancer in front of multiple stock Prometheus instances does not work — each instance has independent local TSDB storage. Sending a query to a random instance returns incomplete or inconsistent results. Load balancing only applies when multiple query frontends share the same backend storage — which is the Mimir and Thanos architecture, not stock Prometheus.

---

### Performance Section — Prometheus Type and Cache Level

Located in Grafana data source configuration under the Performance section.

**Prometheus type:** Tells Grafana which Prometheus-compatible backend it is talking to — Prometheus, Mimir, Thanos, Cortex, or VictoriaMetrics. Grafana adjusts query behavior based on this selection. Setting it correctly allows Grafana to use backend-specific optimizations. When a customer migrates from Prometheus to Mimir, updating this field enables Grafana to take full advantage of the new backend.

**Cache level:** Controls query result caching. Present in open source Grafana — not Enterprise only. Options: None, Low, Medium, High.

**Lab setting:** Low — query results are cached for a short TTL. Practical impact on a single-user lab is negligible but the mechanism is confirmed active.

**Enterprise distinction:** Open source Grafana caching is in-process and limited. Grafana Enterprise adds more granular cache control, cache sharing across users, and external cache backends like Redis. The open source version is sufficient for basic query deduplication — not for large multi-user deployments.

---

### label_values() — Grafana-Specific vs PromQL

`label_values()` is **not a PromQL function**. It is a Grafana-specific function that only exists inside Grafana's variable query editor. It calls the Prometheus HTTP API directly — specifically `/api/v1/label/<name>/values` — and returns results as a list for populating dropdowns.

Running `label_values()` in the Prometheus UI returns:
```
parse error: unknown function with name "label_values"
```

This is correct behavior — Prometheus has no knowledge of Grafana-specific functions.

**Where each query type works:**

| Function | Grafana variable editor | Grafana panel editor | Prometheus UI |
|---|---|---|---|
| `label_values()` | ✓ | ✗ | ✗ |
| `rate()`, `sum()`, etc. | ✓ | ✓ | ✓ |
| `$__interval` | ✓ | ✓ | ✗ |
| LogQL functions | Loki only | Loki only | ✗ |

The variable editor uses the same code box styling as the PromQL editor and in some Grafana versions is labeled "PromQL" — creating genuine confusion. The Grafana-specific functions are only valid in the variable editor context.

**Prometheus UI equivalent of `label_values(up, instance)`:**

```
http://localhost:9090/api/v1/label/instance/values
```

Or via PromQL scoped to a specific metric:

```promql
group by (instance) (up)
```

**Enterprise debugging pattern:** When a Grafana dashboard query returns unexpected results, run the underlying PromQL — without Grafana-specific functions — directly in the Prometheus UI. If it works there and not in Grafana, the problem is in Grafana's variable substitution or Grafana-specific function wrapping. If it fails in both places, the problem is the PromQL itself.

---

## 2. Dashboard Variables

### The Problem With Static Dashboards

A dashboard with hardcoded queries works for one host. At enterprise scale with 1,000 hosts the alternatives without variables are:
- One dashboard per host — 1,000 dashboards to maintain, each needing updates when queries change
- One dashboard with 1,000 panels — unusable

Dashboard variables make label dimensions runtime parameters. The user selects a value from a dropdown and every panel updates simultaneously.

---

### Variable Types

**Query variable** — runs a PromQL or Grafana-specific query against the data source and populates the dropdown dynamically. List updates automatically as infrastructure changes.

```promql
# Populates dropdown with all unique instance values
label_values(up, instance)
```

**Custom variable** — static list of values defined manually. Used for dimensions that don't exist as metric labels.

```
production,staging,development
```

**Interval variable** — list of time intervals for controlling rate() window parameters. Lets users switch between 1m, 5m, 15m smoothing windows without editing queries.

```
1m,5m,15m,30m,1h
```

**Constant variable** — fixed value used across multiple panels. Useful for a default scrape interval that appears in many queries but should be changed in one place.

---

### Implementing Variables — Lab Configuration

**Variable configuration (Dashboard settings → Variables → Add variable):**

| Field | Instance variable | Job variable |
|---|---|---|
| Name | `instance` | `job` |
| Type | Query | Query |
| Data source | Prometheus | Prometheus |
| Query | `label_values(up, instance)` | `label_values(up{instance="$instance"}, job)` |
| Label | Instance | Job |

The job variable query uses `$instance` — this is **variable chaining**. The job dropdown only shows jobs associated with the selected instance. Output of one variable filters input of another.

---

### Updated Panel Queries Using Variables

Variables are referenced in PromQL using `$variable_name` syntax.

**CPU panel:**
```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{instance="$instance", mode="idle"}[5m])) * 100)
```

**Memory panel:**
```promql
100 * (1 - (node_memory_MemAvailable_bytes{instance="$instance"} / node_memory_MemTotal_bytes{instance="$instance"}))
```

**Disk panel:**
```promql
100 - ((node_filesystem_avail_bytes{instance="$instance", mountpoint="/", fstype="ext4"} / node_filesystem_size_bytes{instance="$instance", mountpoint="/", fstype="ext4"}) * 100)
```

**Network panel:**
```promql
rate(node_network_receive_bytes_total{instance="$instance", device!="lo"}[5m])
```

---

### The $__interval Built-in Variable

Grafana provides `$__interval` — automatically calculates an appropriate scrape interval based on the dashboard's current time range:

```promql
rate(node_cpu_seconds_total{instance="$instance", mode="idle"}[$__interval])
```

On a 1-hour view `$__interval` resolves to `1m`. On a 7-day view it resolves to something larger — preventing Prometheus from returning millions of data points that Grafana cannot render. Use this in place of hardcoded range windows on production dashboards.

---

### Enterprise Relevance of Variables

Variables are not a convenience feature. At scale they are the difference between a maintainable observability platform and one that collapses under its own weight. A single parameterized dashboard serves an entire fleet — select the affected instance from the dropdown during an incident and immediately see all relevant metrics scoped to that host.

---

## 3. Explore Mode

Located at `http://localhost:3000` → Explore (compass icon in left sidebar).

### How Explore Differs From Dashboards

| | Dashboard | Explore |
|---|---|---|
| Purpose | Persistent monitoring | Ad-hoc investigation |
| Queries | Saved, versioned | Temporary |
| Layout | Fixed panels | Freeform |
| Time range | Dashboard-wide | Per-query |
| Use case | "Show me normal" | "What is happening right now" |

### When to Use Explore

- Investigating an alert — ad-hoc queries without modifying a dashboard
- Testing a PromQL query before adding it to a dashboard panel
- Correlating metrics with logs during an incident (split view — covered in Week 2)
- Looking at a metric that does not have a dashboard panel

### Split View

The split view button opens two query panels side by side. In Week 2 this becomes the primary incident investigation interface — Prometheus metrics on the left, Loki logs on the right. This metrics-to-logs correlation view is one of Grafana's strongest enterprise selling points and a direct answer to "why use the full LGTM stack."

### Builder vs Code View

Explore provides two query input modes:
- **Code view** — raw PromQL, same as Prometheus UI
- **Builder view** — visual query builder that generates PromQL. Useful for users less familiar with PromQL syntax but produces the same queries under the hood

---

## 4. Alerting Rules

### Alert Rule Structure

```yaml
groups:
  - name: infrastructure_alerts
    rules:
      - alert: HighCPUUsage
        expr: instance:node_cpu_utilization:avg_rate5m > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU utilization is {{ $value | humanize }}% on {{ $labels.instance }}"
```

**Five components:**

- **`alert`** — alert name. Used in Alertmanager routing and notification templates.
- **`expr`** — PromQL expression. When this returns results the alert is active. When it returns nothing the alert is inactive.
- **`for`** — how long the expression must continuously return results before transitioning from pending to firing.
- **`labels`** — key/value pairs attached to the alert. Used by Alertmanager for routing. `severity` is the most common.
- **`annotations`** — human-readable context. `summary` is short description. `description` provides detail. Both support Go template syntax — `{{ $labels.instance }}` inserts label values, `{{ $value }}` inserts the triggering metric value.

---

### The `for` Clause — Why It Exists

Without `for`, an alert fires the instant the expression returns a result — including momentary spikes that resolve within one scrape interval. This produces false positives and alert fatigue.

**The three alert states:**

| State | Meaning | ALERTS metric written |
|---|---|---|
| Inactive | Expression returns no results | No |
| Pending | Expression returns results but `for` duration not yet met | Yes |
| Firing | Expression has returned results continuously for full `for` duration | Yes |

> **Critical design note:** Prometheus does not write the `ALERTS` metric for inactive alerts. Inactive is the normal expected state — writing a metric entry for every inactive alert across hundreds of rules would generate significant cardinality for no operational value.

**Enterprise implication:** Alert fatigue is one of the most common operational problems in large environments. Engineers who receive too many low-quality alerts start ignoring all alerts — including critical ones. The `for` clause is a primary tool for reducing false positives. Most production alerting rules should have a `for` duration of at least 2-5 minutes.

---

### Lab Implementation

**alerting_rules.yml:**

```yaml
groups:
  - name: infrastructure_alerts
    rules:

      - alert: HighCPUUsage
        expr: instance:node_cpu_utilization:avg_rate5m > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU utilization is {{ $value | humanize }}% on {{ $labels.instance }}"

      - alert: HighMemoryUsage
        expr: instance:node_memory_utilization:ratio > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory utilization is {{ $value | humanizePercentage }} on {{ $labels.instance }}"

      - alert: DiskFilling
        expr: instance:node_filesystem_utilization:ratio > 0.80
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Disk usage above 80% on {{ $labels.instance }}"
          description: "Filesystem utilization is {{ $value | humanizePercentage }} on {{ $labels.instance }}"

      - alert: InstanceDown
        expr: up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Instance {{ $labels.instance }} is down"
          description: "{{ $labels.instance }} of job {{ $labels.job }} has been down for more than 1 minute"

      - alert: InstanceMissing
        expr: absent(up{job="node-exporter"})
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "node-exporter target missing"
          description: "No data is being received from the node-exporter job"
```

**prometheus.yml rule_files section:**

```yaml
rule_files:
  - "recording_rules.yml"
  - "alerting_rules.yml"
```

**docker-compose.yml volume mounts:**

```yaml
volumes:
  - ./prometheus.yml:/etc/prometheus/prometheus.yml
  - ./recording_rules.yml:/etc/prometheus/recording_rules.yml
  - ./alerting_rules.yml:/etc/prometheus/alerting_rules.yml
  - prometheus_data:/prometheus
```

> **Note:** Adding a new volume mount requires `docker compose up -d` — hot reload via `curl -X POST http://localhost:9090/-/reload` only handles changes to already-mounted files.

---

### Verifying Alert Rules

**UI:** `http://localhost:9090/alerts` — shows all rules including inactive. The authoritative view for current alert state.

**PromQL — currently firing alerts only:**
```promql
ALERTS{alertstate="firing"}
```

Returns results only when alerts are in pending or firing state. Returns no data on a healthy system — this is correct and expected, not an error.

**API — full rule state including inactive:**
```
http://localhost:9090/api/v1/rules
```

Returns all rule groups with state, health, last evaluation time, and evaluation duration. Key fields:

| Field | Meaning |
|---|---|
| `state` | `inactive`, `pending`, or `firing` |
| `health` | `ok` = evaluating correctly, `err` = PromQL error — rule is silently not evaluating |
| `duration` | `for` clause in seconds |
| `keepFiringFor` | Minimum firing duration after condition resolves (0 = standard behavior) |
| `alerts` | Array of active alert instances — empty when inactive |
| `evaluationTime` | How long the rule took to evaluate |
| `lastEvaluation` | Timestamp of most recent evaluation |

**Lab results — all five alerting rules:**

| Rule | State | Health | Duration |
|---|---|---|---|
| HighCPUUsage | inactive | ok | 300s (5m) |
| HighMemoryUsage | inactive | ok | 300s (5m) |
| DiskFilling | inactive | ok | 900s (15m) |
| InstanceDown | inactive | ok | 60s (1m) |
| InstanceMissing | inactive | ok | 120s (2m) |

> **Operational note:** A rule showing `"health": "err"` is silently not evaluating — it will never fire even if the condition is met. Monitoring rule health via the `/api/v1/rules` endpoint is itself an enterprise operational concern. In large rule sets, automated tooling that alerts when any rule transitions to `err` state is standard practice.

---

### Rule Evaluation Staggering

Multiple rule groups evaluate at slightly different times — Prometheus staggers evaluations to avoid all groups hitting the TSDB simultaneously. At enterprise scale with hundreds of rule groups this staggering is important for avoiding evaluation spikes that cause query latency.

Lab observation: alerting rules group evaluated ~4 seconds after recording rules group — confirmed in API `lastEvaluation` timestamps.

---

## 5. Alertmanager Overview

### What Alertmanager Is

A separate component that handles alert notifications. Prometheus evaluates alert rules and sends firing alerts to Alertmanager. Alertmanager decides what to do with them — who to notify, how, and when.

The separation is deliberate:
- Prometheus's job is to **detect**
- Alertmanager's job is to **route and notify**
- Multiple Prometheus instances can send alerts to a single Alertmanager
- Notification routing can be changed without touching Prometheus configuration

> **Lab note:** Alertmanager is not deployed in the current lab. Alert rules evaluate in Prometheus and states are visible at `/alerts` and `/api/v1/rules` — but no notifications are sent. Alertmanager is the Week 4 topic when the full alerting pipeline is covered.

---

### What Alertmanager Does That Prometheus Cannot

**Routing** — sends different alerts to different receivers based on labels:
- `severity: critical` → PagerDuty → wakes someone up
- `severity: warning` → Slack channel → reviewed during business hours

**Grouping** — when 50 hosts go down simultaneously, sends one notification saying "50 instances are down" rather than 50 individual notifications. Critical at enterprise scale — a network partition taking down an entire datacenter should generate one page, not thousands.

**Inhibition** — suppresses lower-priority alerts when a higher-priority alert is already firing. If a datacenter is completely unreachable, all individual service alerts from that datacenter are inhibited — they are caused by the same root issue and notifying on each adds noise without value.

**Silencing** — temporary suppression of specific alerts. During a planned maintenance window, alerts for systems being worked on are silenced. The alerts continue evaluating in Prometheus — they just don't generate notifications during the silence window.

---

### Enterprise Quantification

| Feature | Without it at scale | With it |
|---|---|---|
| Routing | Every alert goes to everyone — noise overwhelms signal | Right person gets right alert |
| Grouping | 1,000 hosts down = 1,000 pages | 1,000 hosts down = 1 page |
| Inhibition | Root cause + 500 symptoms = 501 pages | Root cause + 500 symptoms = 1 page |
| Silencing | Maintenance generates noise | Maintenance window is quiet |

**Alert fatigue** is the failure mode all four features address. An on-call engineer receiving 500 pages during a single incident starts ignoring pages. An engineer receiving 1 page with clear context acts on it. The difference is not the alerting rules — it is Alertmanager configuration.

---

## 6. Questions and Answers

### Q1: Does or can Grafana cache data obtained from a data source?

**Summary:** Yes, with important distinctions by Grafana edition. Open source Grafana includes basic in-process query caching controlled by the Cache level field in data source configuration. Grafana Enterprise adds more granular control, cross-user cache sharing, and external cache backends like Redis.

Lab cache level is set to Low — active but with short TTL. Every panel refresh still queries Prometheus directly unless a cached result exists within the TTL window.

Caching is complementary to recording rules — pre-aggregated metrics are cheaper for Prometheus to serve regardless of whether Grafana caches results.

---

### Q2: Why would a load balancer be placed in front of Prometheus?

**Summary:** A traditional round-robin load balancer in front of multiple stock Prometheus instances does not work — each instance has independent local TSDB storage and would return incomplete results. Load balancing only applies when query frontends share the same backend storage.

Valid use cases:
- **Active-passive HA** — VIP or load balancer provides a stable endpoint that fails over to a standby Prometheus instance
- **Mimir or Thanos** — multiple query frontend instances share the same object storage backend and can be round-robin load balanced

Point Grafana at a stable endpoint appropriate to your architecture — not necessarily a load balancer.

---

### Q3: Can label_values() be run from the Prometheus UI?

**Summary:** No. `label_values()` is a Grafana-specific function, not PromQL. The Prometheus UI correctly rejects it with a parse error. Despite appearing in the same code box styling as PromQL queries in Grafana's variable editor, it is only valid in that specific context.

Prometheus UI equivalent:
```
http://localhost:9090/api/v1/label/instance/values
```

Or via PromQL:
```promql
group by (instance) (up)
```

---

### Q4: Why doesn't ALERTS{alertstate="inactive"} return results?

**Summary:** Prometheus does not write the ALERTS metric for inactive alerts at all. Only pending and firing states generate ALERTS metric entries. Inactive is the normal expected condition — writing entries for every inactive alert across potentially hundreds of rules would generate significant cardinality for no operational value.

To see all rules including inactive ones use the UI or API:
```
http://localhost:9090/alerts
http://localhost:9090/api/v1/rules
```

---

## 7. Advanced Topics

Topics identified during Days 2, 3, and 4 for exploration after foundational coverage is complete.

| Topic | Why It Matters | Identified During |
|---|---|---|
| **Prometheus histograms** — usage, setup, bucket design, and native histograms | Histograms are a significant cardinality source. Native histograms change the storage model and reduce series count overhead substantially. | Day 2 — TSDB cardinality analysis |
| **Recording rules** — advanced design, naming conventions, and performance impact at scale | Day 3 covered foundational implementation. Enterprise scale introduces rule evaluation performance, rule dependencies, and federation of recorded metrics. | Day 2 — metric types; Day 3 — hands-on |
| **SNMP exporter configuration** — Counter32 vs Counter64 OID selection | Operational gap when customers migrate from traditional NMS to Prometheus-based observability. Counter32 wrapping at high throughput produces unreliable rate calculations. | Day 2 — counter ceiling discussion |
| **Alerting rules** — full design, Alertmanager routing, and inhibition | Day 4 covered alert rule implementation. Full Alertmanager deployment, routing trees, and inhibition rules are a dedicated Week 4 topic. | Day 3 — comparison operators; Day 4 — alerting rules |
| **Prometheus CI/CD integration** — promtool in pipelines | Metric instrumentation validation before deployment. Prevents naming conflicts, type mismatches, and cardinality anti-patterns from reaching production. | Day 3 — metric type conflicts |
| **Grafana Enterprise features** — advanced caching, RBAC, reporting | Cache level differences, role-based access control for dashboards, and scheduled PDF reporting are Enterprise features relevant to large organization deployments. | Day 4 — data source performance section |

---

## 8. Reference Material

### Grafana Configuration and Data Sources

| Resource | URL | Notes |
|---|---|---|
| Grafana data source configuration | https://grafana.com/docs/grafana/latest/datasources/prometheus/ | Full Prometheus data source options including performance settings |
| Grafana query caching | https://grafana.com/docs/grafana/latest/administration/data-source-management/#query-caching | Cache level configuration and behavior |
| Grafana $__interval variable | https://grafana.com/docs/grafana/latest/dashboards/variables/add-template-variables/#__interval | Built-in interval variable documentation |

### Dashboard Variables

| Resource | URL | Notes |
|---|---|---|
| Grafana variable documentation | https://grafana.com/docs/grafana/latest/dashboards/variables/ | All variable types, chaining, and syntax |
| label_values() function | https://grafana.com/docs/grafana/latest/datasources/prometheus/template-variables/ | Grafana-specific template functions for Prometheus |

### Alerting Rules

| Resource | URL | Notes |
|---|---|---|
| Prometheus alerting rules | https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/ | Rule syntax, for clause, template variables |
| Alerting best practices | https://prometheus.io/docs/practices/alerting/ | Prometheus maintainers' guidance on alert design |
| ALERTS metric | https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/#inspecting-alerts-during-runtime | How the ALERTS metric works and its states |
| Go template syntax in annotations | https://prometheus.io/docs/prometheus/latest/configuration/template_reference/ | humanize, humanizePercentage, and other template functions |

### Alertmanager

| Resource | URL | Notes |
|---|---|---|
| Alertmanager documentation | https://prometheus.io/docs/alerting/latest/alertmanager/ | Configuration, routing, inhibition, silencing |
| Alertmanager routing | https://prometheus.io/docs/alerting/latest/configuration/#route | Route tree configuration — how alerts are matched to receivers |
| Alertmanager inhibition rules | https://prometheus.io/docs/alerting/latest/configuration/#inhibit_rule | Suppressing symptoms when root cause is already firing |

### Explore Mode

| Resource | URL | Notes |
|---|---|---|
| Grafana Explore documentation | https://grafana.com/docs/grafana/latest/explore/ | Full Explore mode documentation including split view |
| Correlating metrics and logs | https://grafana.com/docs/grafana/latest/explore/logs-integration/ | Split view pattern for metrics and Loki logs — preview of Week 2 |

### PromQL Functions and Operators

| Resource | URL | Notes |
|---|---|---|
| PromQL function reference | https://prometheus.io/docs/prometheus/latest/querying/functions/ | Authoritative — all functions |
| PromQL operators | https://prometheus.io/docs/prometheus/latest/querying/operators/ | Binary operators, vector matching, aggregation |
| Prometheus Admin API | https://prometheus.io/docs/prometheus/latest/querying/api/#rules | Rules API including health and evaluation time fields |

### Enterprise Tooling

| Resource | URL | Notes |
|---|---|---|
| Grafana Mimirtool | https://grafana.com/docs/mimir/latest/manage/tools/mimirtool/ | Cardinality and active series analysis |
| promtool | https://prometheus.io/docs/prometheus/latest/command-line/promtool/ | Metric naming validation, rule checking, CI/CD integration |
| Grafana Enterprise | https://grafana.com/products/enterprise/ | Advanced caching, RBAC, reporting features |

---

*Day 4 complete. Day 5: Consolidation — GitHub portfolio finalization, Week 1 review, screening question preparation, and Week 2 scope.*

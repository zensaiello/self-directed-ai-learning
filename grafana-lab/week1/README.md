# Week 1 Lab — Grafana + Prometheus Stack
## Grafana Observability Lab — Setup & Configuration Guide

---

## Overview

This lab sets up a local observability stack using Docker Compose, consisting of:

- **Prometheus** — metrics collection, storage, and alerting rule evaluation
- **Grafana** — visualization, dashboarding, and Explore mode
- **Node Exporter** — host system metrics (CPU, memory, disk, network, hardware sensors)

By the end of this lab you will have a working infrastructure dashboard pulling live metrics from your own machine, with recording rules pre-computing key utilization metrics and alerting rules monitoring for infrastructure problems.

---

## Prerequisites

### Docker Installation (Pop!_OS / Ubuntu-based)

**Step 1 — Remove any old Docker packages**
```bash
sudo apt-get remove docker docker-engine docker.io containerd runc
```

**Step 2 — Install prerequisites**
```bash
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

**Step 3 — Add Docker repository**

First check your Ubuntu base codename:
```bash
cat /etc/upstream-release/UPSTREAM_RELEASE_CODENAME
```

Then add the repository (replace `jammy` with your codename if different):
```bash
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

**Step 4 — Install Docker Engine and Compose**
```bash
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**Step 5 — Add your user to the docker group**
```bash
sudo usermod -aG docker $USER
newgrp docker
```

**Step 6 — Verify installation**
```bash
docker --version
docker compose version
docker run hello-world
```

Expected output confirms Docker Engine and Compose are working correctly.

**Step 7 — Prevent laptop suspend while plugged in**

This ensures your lab keeps running while on AC power:
```bash
sudo sed -i 's/#HandleLidSwitch=suspend/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
sudo sed -i 's/#HandleLidSwitchExternalPower=suspend/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
```

---

## Lab Setup

### Create working directory
```bash
mkdir -p ~/grafana-lab/week1
cd ~/grafana-lab/week1
```

---

### Docker Compose file

Create `docker-compose.yml`:

```yaml
networks:
  monitoring:
    driver: bridge

volumes:
  prometheus_data:
  grafana_data:

services:

  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - ./recording_rules.yml:/etc/prometheus/recording_rules.yml
      - ./alerting_rules.yml:/etc/prometheus/alerting_rules.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.enable-lifecycle'
    ports:
      - "9090:9090"
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=grafana
    ports:
      - "3000:3000"
    networks:
      - monitoring
    depends_on:
      - prometheus

  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    restart: unless-stopped
    ports:
      - "9100:9100"
    networks:
      - monitoring
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/host/root:ro,rslave
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/host/root'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
```

> **Note on node-exporter volume mounts:** Docker containers are isolated from the host filesystem by default. Without explicitly mounting `/proc`, `/sys`, and `/` into the container, node-exporter cannot see your actual disk partitions or host-level metrics. The `ro` flag mounts these read-only for safety. The `rslave` flag on the root mount ensures bind-mount propagation works correctly. This is a real-world operational issue — a common mistake when deploying node-exporter in containerized environments.

> **Note on `--web.enable-lifecycle`:** This flag enables the Prometheus hot reload API endpoint at `POST /-/reload`. It allows configuration and rule file changes to be applied without restarting the container. Adding a new volume mount still requires `docker compose up -d` — hot reload only handles changes to already-mounted files.

---

### Prometheus configuration file

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "recording_rules.yml"
  - "alerting_rules.yml"

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['prometheus:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

> **Note on service names:** Use `prometheus:9090` not `localhost:9090` in configuration files. Docker Compose creates an internal network where containers communicate using their service names as hostnames, not localhost.

> **Note on `evaluation_interval`:** This controls how often Prometheus evaluates recording rules and alerting rules. Keep it aligned with `scrape_interval` — mismatches can cause rules to evaluate against data that is older than expected.

---

### Recording rules file

Create `recording_rules.yml`:

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

**Why recording rules:** These three expressions are used in both dashboard panels and alerting rules. Pre-computing them as named metrics means the dashboard queries hit a single pre-aggregated series rather than recomputing the full expression on every panel load. At enterprise scale with millions of series this distinction is significant — a dashboard query hitting 3 recorded series vs recomputing across 176+ raw series on every refresh.

**Naming convention:** `level:metric:operations` — the community standard for recorded metric names. `instance` is the aggregation level, the middle segment is the base metric, and the suffix describes the operations applied. This makes recorded metrics immediately identifiable as derived rather than raw.

**Verify recording rules loaded:**
```
http://localhost:9090/rules
```

All three rules should show state `ok` and update their last evaluation timestamp every minute.

**Query recorded metrics directly:**
```promql
instance:node_cpu_utilization:avg_rate5m
instance:node_memory_utilization:ratio
instance:node_filesystem_utilization:ratio
```

---

### Alerting rules file

Create `alerting_rules.yml`:

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

**Alert rule design notes:**

- `HighCPUUsage`, `HighMemoryUsage`, `DiskFilling` — reference recorded metrics rather than raw expressions. Keeps alert definitions clean and consistent with dashboard queries.
- `InstanceDown` — thresholds on `up == 0`. The `up` metric is written by Prometheus itself on every scrape — 1 if the scrape succeeded, 0 if it failed. A `for: 1m` duration prevents a single failed scrape from firing.
- `InstanceMissing` — uses `absent()` to detect when the node-exporter job stops appearing in scrape results entirely. This is complementary to `InstanceDown` — `InstanceDown` fires when a target is reachable but returning errors, `InstanceMissing` fires when the target has disappeared completely.
- `severity` labels — used by Alertmanager for routing. `critical` alerts go to immediate notification channels, `warning` alerts go to lower-priority channels. Alertmanager is not deployed in Week 1 — routing is covered in Week 4.

**Verify alerting rules loaded:**
```
http://localhost:9090/alerts
```

All five rules should show as Inactive on a healthy system. Inactive is the correct expected state — it means the alert conditions are not currently met.

**Check rule health via API:**
```
http://localhost:9090/api/v1/rules
```

Key fields to verify per rule:
- `"health": "ok"` — rule is evaluating correctly
- `"state": "inactive"` — condition not currently met
- `"duration"` — confirms `for` clause parsed correctly (in seconds)

A rule showing `"health": "err"` is silently not evaluating and will never fire — check the PromQL expression for errors.

---

### Start the stack
```bash
docker compose up -d
```

### Verify all containers are running
```bash
docker compose ps
```

All three services (prometheus, grafana, node-exporter) should show as **Up** or **running**.

---

## Accessing the Stack

| Service | URL | Credentials |
|---|---|---|
| Grafana | http://localhost:3000 | admin / grafana |
| Prometheus | http://localhost:9090 | none required |
| Node Exporter | http://localhost:9100/metrics | none required |

---

## Verify Prometheus Targets

1. Open http://localhost:9090
2. Click **Status** → **Targets**
3. Both targets should show **State: UP** in green:
   - `prometheus` — scraping itself at port 9090
   - `node-exporter` — scraping host metrics at port 9100

---

## Connect Prometheus to Grafana

1. In Grafana, click the **hamburger menu** (top left) → **Connections** → **Data sources**
2. Click **Add data source**
3. Select **Prometheus**
4. Set URL to: `http://prometheus:9090`
5. Click **Save & test** — should return a green checkmark

**Data source configuration notes:**

| Field | Value | Notes |
|---|---|---|
| URL | `http://prometheus:9090` | Docker internal network — container name resolves correctly |
| Scrape interval | 15s | Must match prometheus.yml — mismatch causes gaps or wasted queries |
| Query timeout | 60s | Default — increase only if queries are timing out, prefer recording rules instead |
| HTTP method | POST | Preferred — no URL length constraint on complex PromQL queries |

---

## Build the Dashboard

### Create the dashboard

1. Hamburger menu → **Dashboards** → **New** → **New dashboard**
2. Click **Add visualization**
3. Confirm **Prometheus** is selected as the data source

---

### Add Dashboard Variables

Variables make the dashboard dynamic — a dropdown lets you select which instance to view and all panels update simultaneously. This scales to a fleet of any size without creating additional dashboards.

**Add Instance variable (Dashboard settings → Variables → Add variable):**

| Field | Value |
|---|---|
| Name | `instance` |
| Type | Query |
| Data source | Prometheus |
| Query | `label_values(up, instance)` |
| Label | Instance |

**Add Job variable (chain to Instance):**

| Field | Value |
|---|---|
| Name | `job` |
| Type | Query |
| Data source | Prometheus |
| Query | `label_values(up{instance="$instance"}, job)` |
| Label | Job |

The job variable query uses `$instance` — variable chaining. The job dropdown only shows jobs associated with the currently selected instance.

> **Note on `label_values()`:** This is a Grafana-specific function, not PromQL. It is only valid in the Grafana variable editor — running it in the Prometheus UI will return a parse error. The Prometheus UI equivalent is `http://localhost:9090/api/v1/label/instance/values`.

---

### Panel 1 — CPU Usage

**Query:**
```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{instance="$instance", mode="idle"}[5m])) * 100)
```

**How it works:** Calculates CPU usage percentage by measuring how much time CPUs spend outside idle mode over a 5-minute rate window. `avg by (instance)` collapses multiple CPU cores into a single per-host value. The `$instance` variable scopes the query to the selected host.

- Visualization: **Time series**
- Title: `CPU Usage %`

---

### Panel 2 — Memory Usage

**Query:**
```promql
100 * (1 - (node_memory_MemAvailable_bytes{instance="$instance"} / node_memory_MemTotal_bytes{instance="$instance"}))
```

**How it works:** Calculates memory usage as a percentage of total RAM. Uses available vs total memory bytes reported by the kernel — `MemAvailable` is more accurate than `MemFree` as it accounts for reclaimable cache.

- Visualization: **Time series**
- Title: `Memory Usage %`

---

### Panel 3 — Disk Usage

**Query:**
```promql
100 - ((node_filesystem_avail_bytes{instance="$instance", mountpoint="/", fstype="ext4"} / node_filesystem_size_bytes{instance="$instance", mountpoint="/", fstype="ext4"}) * 100)
```

**How it works:** Calculates disk usage percentage on the root filesystem. The `mountpoint="/"` and `fstype="ext4"` label filters target your actual root partition specifically.

> **Troubleshooting:** If this panel shows "No data", run `node_filesystem_size_bytes` in the Prometheus UI to see which mountpoints and fstypes are being reported. Adjust the label filters to match. If your host filesystem is not visible at all, the node-exporter volume mounts in docker-compose.yml may need to be verified — see the note in the Docker Compose section above.

- Visualization: **Gauge**
- Title: `Disk Usage %`

---

### Panel 4 — Network Inbound Traffic

**Query:**
```promql
rate(node_network_receive_bytes_total{instance="$instance", device!="lo"}[5m])
```

**How it works:** Shows incoming network bytes per second averaged over 5 minutes. The `device!="lo"` filter excludes the loopback interface — only real network interfaces are shown.

- Visualization: **Time series**
- Title: `Network Inbound (bytes/sec)`

---

### Save the dashboard

Click the **Save dashboard** icon (top right), name it `Host Infrastructure`, and save.

---

## Useful Diagnostic Endpoints and Queries

### Prometheus UI endpoints

| Endpoint | What it shows |
|---|---|
| `http://localhost:9090/targets` | Scrape target health — UP/DOWN, last scrape duration |
| `http://localhost:9090/tsdb-status` | TSDB head status — active series count, top label memory usage |
| `http://localhost:9090/rules` | Recording and alerting rule state, last evaluation time |
| `http://localhost:9090/alerts` | Current alert states — inactive, pending, firing |
| `http://localhost:9090/api/v1/labels` | All label names present in the TSDB |
| `http://localhost:9090/api/v1/label/job/values` | All values for a specific label |
| `http://localhost:9090/api/v1/rules` | Full rule state including health and evaluation timing |
| `http://localhost:9100/metrics` | Raw node-exporter exposition output |

### Cardinality diagnostic queries

```promql
# Top series contributors — sorted by count
sort_desc(count by (__name__) ({__name__=~".+"}))

# Which metrics use a specific label
count by (__name__) ({mode!=""})

# Series creation rate — churn indicator
rate(prometheus_tsdb_head_series_created_total[5m])
rate(prometheus_tsdb_head_series_removed_total[5m])
```

### Storage diagnostic queries

```promql
prometheus_tsdb_storage_blocks_bytes      # persistent block storage
prometheus_tsdb_wal_storage_size_bytes    # WAL size
prometheus_tsdb_compactions_total         # total compaction runs
prometheus_tsdb_blocks_loaded             # blocks currently loaded
prometheus_tsdb_head_series               # total series in head block
```

### Log access

```bash
# All Prometheus logs
docker logs prometheus

# Follow live
docker logs prometheus -f

# Filter for warnings and errors only
docker logs prometheus 2>&1 | grep -i "warn\|error"

# Confirm clean startup
docker logs prometheus 2>&1 | grep "Server is ready"
```

> `2>&1` is required because Prometheus writes to stderr, not stdout.

---

## Configuration Changes and Hot Reload

Changes to already-mounted configuration files can be applied without restarting:

```bash
curl -X POST http://localhost:9090/-/reload
```

Adding a new file that requires a new volume mount requires a full restart:

```bash
docker compose up -d
```

---

## Stopping and Starting the Stack

**Stop:**
```bash
docker compose down
```

**Start:**
```bash
docker compose up -d
```

Data persists between restarts via the named Docker volumes (`prometheus_data`, `grafana_data`).

---

## Key Concepts Covered

### Prometheus data model
- Every metric is a set of labeled time series — each unique combination of metric name and label values is a separate series
- Cardinality is the total count of unique series — multiplicative across label dimensions
- High-cardinality labels (user IDs, UUIDs, full URLs) create series explosions — use bounded categorical labels instead
- In-memory overhead is approximately 3–4KB per active series in the head block

### PromQL fundamentals
- `rate()` — per-second rate of change for counters over a time window. Always returns per-second regardless of window size
- `increase()` — total counter increase over a window. Use when you want a count, not a rate
- `delta()` — change in a gauge value over a window. Use for trend analysis on metrics that can go up or down
- `histogram_quantile()` — calculates p50/p95/p99 latency from histogram bucket data
- `absent()` — returns a result when a series does not exist. Foundation of "alert on missing data" patterns
- `avg_over_time()` — averages a single series over a time range. Used for availability reporting

### Metric types
- **Counter** — only increases, resets on restart. Always use `rate()` or `increase()`, never query raw value
- **Gauge** — current state, can go up or down. Query directly or use `delta()`
- **Histogram** — distribution of observations in buckets. Expensive in series count — each bucket boundary is a separate series
- **Summary** — client-side quantile calculation. Cannot be aggregated across instances — prefer histograms at scale

### Recording rules
- Pre-computed PromQL expressions stored as new metrics
- Evaluated on a defined interval, results written to TSDB as regular time series
- Use when a query is expensive, used in multiple places, or needs consistent naming
- Naming convention: `level:metric:operations`

### Alerting rules
- `expr` — PromQL expression. Alert is active when this returns results
- `for` — minimum duration the condition must hold before firing. Prevents false positives from momentary spikes
- Three states: inactive (normal), pending (condition met but `for` not elapsed), firing (condition met for full duration)
- `severity` label drives Alertmanager routing — covered in Week 4

### Grafana
- Visualization layer only — no data storage. Every panel queries Prometheus in real time
- Dashboard variables — runtime parameters that make dashboards dynamic. A single dashboard serves an entire fleet
- `label_values()` is Grafana-specific, not PromQL — only valid in the variable editor
- Explore mode — ad-hoc investigation interface. Split view correlates metrics and logs side by side (Week 2)

### Operational lessons
- Node Exporter requires explicit host filesystem mounts to see actual disk partitions in Docker
- WAL and Prometheus data should be on the same filesystem — separating them risks filling a small volume and crashing Prometheus
- Hot reload handles config changes to mounted files — new volume mounts require `docker compose up -d`
- Prometheus logs to stderr — `2>&1` is required when piping to grep

---

## Next Steps (Week 2)

- Add Loki for log aggregation
- Configure Grafana Alloy as the telemetry collector
- Write LogQL queries
- Correlate logs and metrics in Grafana Explore split view

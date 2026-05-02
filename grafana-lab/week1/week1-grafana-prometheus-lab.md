# Week 1 Lab — Grafana + Prometheus Stack
## Grafana Observability Lab — Setup & Configuration Guide

---

## Overview

This lab sets up a local observability stack using Docker Compose, consisting of:

- **Prometheus** — metrics collection and storage
- **Grafana** — visualization and dashboarding
- **Node Exporter** — host system metrics (CPU, memory, disk, network)

By the end of this lab you will have a working infrastructure dashboard pulling live metrics from your own machine.

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

> **Note on node-exporter volume mounts:** Docker containers are isolated from the host filesystem by default. Without explicitly mounting `/proc`, `/sys`, and `/` into the container, node-exporter cannot see your actual disk partitions or host-level metrics. The `ro` flag mounts these read-only for safety. The `rslave` flag on the root mount ensures bind-mount propagation works correctly.

---

### Prometheus configuration file

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['prometheus:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

> **Note on service names:** Use `prometheus:9090` not `localhost:9090` in configuration files. Docker Compose creates an internal network where containers communicate using their service names, not localhost.

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

---

## Build Your First Dashboard

### Create the dashboard

1. Hamburger menu → **Dashboards** → **New** → **New dashboard**
2. Click **Add visualization**
3. Confirm **Prometheus** is selected as the data source

---

### Panel 1 — CPU Usage

**Query:**
```
100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

**How it works:** Calculates CPU usage percentage by measuring how much time the CPU spends NOT in idle mode over a 5-minute rate window. The `rate()` function handles the counter reset logic automatically.

- Visualization: **Time series**
- Title: `CPU Usage %`

---

### Panel 2 — Memory Usage

**Query:**
```
100 * (1 - ((node_memory_MemAvailable_bytes) / (node_memory_MemTotal_bytes)))
```

**How it works:** Calculates memory usage as a percentage of total RAM using available vs total memory bytes reported by the kernel.

- Visualization: **Time series**
- Title: `Memory Usage %`

---

### Panel 3 — Disk Usage

**Query:**
```
100 - ((node_filesystem_avail_bytes{mountpoint="/",fstype="ext4"} / node_filesystem_size_bytes{mountpoint="/",fstype="ext4"}) * 100)
```

**How it works:** Calculates disk usage percentage on the root filesystem. The `mountpoint="/"` and `fstype="ext4"` label filters target your actual root partition specifically.

> **Troubleshooting:** If this panel shows "No data", run `node_filesystem_size_bytes` in the Prometheus UI to see which mountpoints and fstypes are being reported. Adjust the label filters to match. If your host filesystem isn't visible at all, the node-exporter volume mounts in docker-compose.yml may need to be added — see the note in the Docker Compose section above.

- Visualization: **Gauge**
- Title: `Disk Usage %`

---

### Panel 4 — Network Inbound Traffic

**Query:**
```
rate(node_network_receive_bytes_total{device!="lo"}[5m])
```

**How it works:** Shows incoming network bytes per second averaged over 5 minutes. The `device!="lo"` filter excludes the loopback interface so you're only seeing real network traffic.

- Visualization: **Time series**
- Title: `Network Inbound (bytes/sec)`

---

### Save the dashboard

Click the **Save dashboard** icon (top right), name it `Host Infrastructure`, and save.

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

**PromQL fundamentals:**
- `rate()` — calculates per-second rate of change for counter metrics over a time window
- Label filtering with `{}` — selects specific time series by label values
- Arithmetic operations — combining metrics to derive meaningful values like percentages

**Grafana fundamentals:**
- Data source configuration
- Panel editor and visualization types
- Time series vs Gauge — when to use each

**Docker Compose fundamentals:**
- Multi-container service orchestration
- Named networks for inter-container communication
- Volume mounts for data persistence and host filesystem access
- Service dependencies with `depends_on`

**Operational problem solving:**
- Diagnosing container isolation issues
- Using Prometheus UI to inspect raw metric labels before writing dashboard queries
- Matching label filters to actual reported values

---

## Next Steps (Week 2)

- Add Loki for log aggregation
- Configure Grafana Alloy as the telemetry collector
- Write LogQL queries
- Correlate logs and metrics in a unified Grafana dashboard

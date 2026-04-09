# Grafana Observability Lab

A hands-on observability upskilling project building and operating the Grafana LGTM stack (Loki, Grafana, Tempo, Mimir) from scratch on local infrastructure.

## Purpose

This repository documents a structured five-week lab program covering the full Grafana observability stack. Each week adds a new layer to the stack, building toward a production-representative local environment with metrics, logs, traces, and long-term storage.

The goal is hands-on portfolio work — working configurations, documented decisions, and real lab results — not theory or tutorials.

## Stack Being Built

| Week | Components | Status |
|---|---|---|
| 1 | Prometheus + Grafana + Node Exporter | ✅ Complete |
| 2 | Loki + Grafana Alloy | 🔄 In progress |
| 3 | Tempo + OpenTelemetry | Planned |
| 4 | Mimir + full alerting pipeline | Planned |
| 5 | Consolidation + interview prep | Planned |

## Lab Environment

- **OS:** Pop!_OS (Ubuntu jammy base)
- **Docker:** v27.3.1
- **Docker Compose:** v2.1.1
- **Lab directory:** `~/grafana-lab/`

All lab work runs directly on the host OS via Docker Compose — no VM, no Kubernetes (yet). Kubernetes is a longer-term track running in parallel.

## Repository Structure

```
grafana-observability-lab/
├── README.md                        ← This file
├── week1/                           ← Prometheus + Grafana + Node Exporter
│   ├── README.md                    ← Week 1 lab guide and configuration reference
│   ├── docker-compose.yml           ← Stack definition
│   ├── prometheus.yml               ← Prometheus scrape and evaluation config
│   ├── recording_rules.yml          ← Pre-computed PromQL expressions
│   ├── alerting_rules.yml           ← Infrastructure alerting rules
│   ├── prometheus-day2-reference.md ← Prometheus internals deep dive
│   ├── prometheus-day3-reference.md ← PromQL and recording rules deep dive
│   └── prometheus-day4-reference.md ← Grafana and alerting deep dive
├── week2/                           ← Loki + Grafana Alloy (in progress)
├── week3/                           ← Tempo + OpenTelemetry (planned)
├── week4/                           ← Mimir + alerting pipeline (planned)
└── week5/                           ← Consolidation (planned)
```

## Week 1 — What Was Built

A complete local metrics observability stack:

- **Prometheus** scraping itself and Node Exporter every 15 seconds
- **Node Exporter** exposing host system metrics — CPU, memory, disk, network, hardware sensors
- **Grafana** connected to Prometheus with a dynamic infrastructure dashboard
- **Recording rules** pre-computing CPU, memory, and filesystem utilization metrics
- **Alerting rules** covering CPU saturation, memory pressure, disk fill, instance down, and missing targets

The Grafana dashboard uses variables to make it dynamic — selecting a host from a dropdown updates all panels simultaneously. At one host in the lab this is invisible, but the same dashboard scales to a fleet of any size without modification.

See [week1/README.md](week1/README.md) for full setup, configuration, and reproduction instructions.

## Key Technical Decisions

**Docker Compose over a VM** — simplicity. The lab is on a laptop. No hypervisor overhead, direct host metric access for Node Exporter, easy to start and stop.

**Node Exporter host filesystem mounts** — Docker containers are isolated from the host by default. Explicit mounts of `/proc`, `/sys`, and `/` with appropriate flags are required for Node Exporter to see real disk partitions. Documented in the Week 1 lab guide — a common operational issue worth knowing for customer conversations.

**Recording rules from Day 3** — CPU, memory, and disk utilization are pre-computed as named metrics. Alerting rules reference these recorded metrics rather than repeating the raw expressions. This keeps alert definitions clean and reduces query-time computation.

**`--web.enable-lifecycle` flag** — enables the Prometheus hot reload endpoint (`POST /-/reload`). Required for reloading configuration and rule files without restarting the container. Note: adding a new volume mount still requires `docker compose up -d`.

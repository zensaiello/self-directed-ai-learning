# Grafana Observability Lab

A hands-on observability upskilling project building and operating the Grafana LGTM stack (Loki, Grafana, Tempo, Mimir) from scratch on local infrastructure.

## Purpose

This repository documents a structured five-week lab program covering the full Grafana observability stack. Each week adds a new layer to the stack, building toward a production-representative local environment with metrics, logs, traces, and long-term storage.

The goal is hands-on portfolio work — working configurations, documented decisions, and real lab results — not theory or tutorials.

## Stack Being Built

| Week | Components | Status |
|---|---|---|
| 1 | Prometheus + Grafana + Node Exporter | ✅ Complete |
| 2 | Loki + Grafana Alloy | ✅ Complete |
| 3 | Tempo + OpenTelemetry | 🔄 In progress |
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
├── README.md                              ← This file
├── week1/                                 ← Prometheus + Grafana + Node Exporter
│   ├── README.md                          ← Week 1 lab guide and configuration reference
│   ├── docker-compose.yml                 ← Stack definition
│   ├── prometheus.yml                     ← Prometheus scrape and evaluation config
│   ├── recording_rules.yml                ← Pre-computed PromQL expressions
│   ├── alerting_rules.yml                 ← Infrastructure alerting rules
│   ├── prometheus-day2-reference.md       ← Prometheus internals deep dive
│   ├── prometheus-day3-reference.md       ← PromQL and recording rules deep dive
│   ├── prometheus-day4-reference.md       ← Grafana and alerting deep dive
│   ├── prometheus-day5-reference.md       ← Week 1 consolidation and screening prep
│   └── week1-grafana-prometheus-lab.md    ← Original Day 1 setup document
├── week2/                                 ← Loki + Grafana Alloy
│   ├── README.md                          ← Week 2 lab guide and configuration reference
│   ├── docker-compose.yml                 ← Full stack — references week1 config files
│   ├── loki-config.yml                    ← Loki server configuration
│   ├── alloy-config.alloy                 ← Grafana Alloy pipeline configuration
│   ├── loki-rules/
│   │   └── log_alerts.yml                 ← Loki alerting rules
│   ├── loki-alloy-week2-day1-reference.md ← Loki and Alloy introduction deep dive
│   ├── loki-alloy-week2-day2-reference.md ← LogQL depth deep dive
│   └── loki-alloy-week2-day3-reference.md ← Label design, alerting, and dashboards
├── week3/                                 ← Tempo + OpenTelemetry (in progress)
├── week4/                                 ← Mimir + alerting pipeline (planned)
└── week5/                                 ← Consolidation (planned)
```

## Week 1 — What Was Built

A complete local metrics observability stack:

- **Prometheus** scraping itself and Node Exporter every 15 seconds
- **Node Exporter** exposing host system metrics — CPU, memory, disk, network, hardware sensors
- **Grafana** connected to Prometheus with a dynamic infrastructure dashboard
- **Recording rules** pre-computing CPU, memory, and filesystem utilization metrics
- **Alerting rules** covering CPU saturation, memory pressure, disk fill, instance down, and missing targets

The Grafana dashboard uses variables to make it dynamic — selecting a host from a dropdown updates all panels simultaneously.

See [week1/README.md](week1/README.md) for full setup, configuration, and reproduction instructions.

## Week 2 — What Was Built

A complete local log ingestion and correlation stack added to the Week 1 foundation:

- **Loki** receiving and storing log streams from all five running containers
- **Grafana Alloy** discovering Docker containers, reading their log output, extracting labels, and pushing labeled streams to Loki
- **Loki alerting rules** — two rules monitoring for high error rates and fatal events in log content
- **Grafana Loki data source** added alongside the existing Prometheus data source
- **Stack Observability dashboard** — unified dashboard with Prometheus metric panels and Loki log panels side by side, driven by a container variable

A self-triggering false positive was discovered and resolved during the alerting rules work — the `FatalLogEvent` rule was matching Loki's own ruler evaluation logs which contained the word "panic" as part of the query string. Fixed with a surgical exclusion pattern.

See [week2/README.md](week2/README.md) for full setup, configuration, and reproduction instructions.

## Key Technical Decisions

**Docker Compose over a VM** — simplicity. The lab is on a laptop. No hypervisor overhead, direct host metric access for Node Exporter, easy to start and stop.

**Node Exporter host filesystem mounts** — Docker containers are isolated from the host by default. Explicit mounts of `/proc`, `/sys`, and `/` with appropriate flags are required for Node Exporter to see real disk partitions. A common operational issue worth knowing for customer conversations.

**Recording rules from Week 1 Day 3** — CPU, memory, and disk utilization are pre-computed as named metrics. Alerting rules reference these recorded metrics rather than repeating raw expressions. Keeps alert definitions clean and reduces query-time computation.

**Alloy over Promtail** — Promtail is deprecated. Alloy is the current Grafana Labs collector supporting logs, metrics, and traces in a single component with a consistent pipeline model.

**Push model for logs** — Prometheus pulls metrics on a schedule. Alloy pushes logs to Loki as they are generated. Logs are event-driven — polling would risk missing lines between intervals.

**Surgical alert exclusions over broad container exclusions** — the `FatalLogEvent` rule uses `!~ "caller=metrics.go|caller=evaluator"` to exclude ruler noise rather than excluding the entire Loki container. More precise — genuine Loki panics are still caught.

**`--web.enable-lifecycle` on Prometheus** — enables hot reload via `POST /-/reload`. Required for reloading configuration and rule files without restarting the container.

**Service names for inter-container communication** — `http://prometheus:9090`, `http://loki:3100`. Never `localhost` inside Docker containers — `localhost` resolves to the container itself.

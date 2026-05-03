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
| 3 | Tempo + OpenTelemetry | ✅ Complete |
| 4 | Mimir + Alertmanager + full alerting pipeline | 🔄 In progress |
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
├── README.md                                    ← This file
├── week1/                                       ← Prometheus + Grafana + Node Exporter
│   ├── README.md
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   ├── recording_rules.yml
│   ├── alerting_rules.yml
│   ├── prometheus-day2-reference.md
│   ├── prometheus-day3-reference.md
│   ├── prometheus-day4-reference.md
│   ├── prometheus-day5-reference.md
│   └── week1-grafana-prometheus-lab.md
├── week2/                                       ← Loki + Grafana Alloy
│   ├── README.md
│   ├── docker-compose.yml
│   ├── loki-config.yml
│   ├── alloy-config.alloy
│   ├── loki-rules/
│   │   └── log_alerts.yml
│   ├── loki-alloy-week2-day1-reference.md
│   ├── loki-alloy-week2-day2-reference.md
│   ├── loki-alloy-week2-day3-reference.md
│   └── loki-alloy-week2-day4-reference.md
├── week3/                                       ← Tempo + OpenTelemetry
│   ├── README.md
│   ├── docker-compose.yml
│   ├── tempo-config.yml
│   ├── otel-collector-config.yml
│   ├── app/
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── tempo-otel-week3-day1-reference.md
│   ├── tempo-otel-week3-day2-reference.md
│   └── tempo-otel-week3-day3-reference.md
├── week4/                                       ← Mimir + Alertmanager (in progress)
└── week5/                                       ← Consolidation (planned)
```

## Week 1 — What Was Built

A complete local metrics observability stack:

- **Prometheus** scraping itself and Node Exporter every 15 seconds
- **Node Exporter** exposing host system metrics — CPU, memory, disk, network, hardware sensors
- **Grafana** connected to Prometheus with a dynamic infrastructure dashboard
- **Recording rules** pre-computing CPU, memory, and filesystem utilization metrics
- **Alerting rules** covering CPU saturation, memory pressure, disk fill, instance down, and missing targets

See [week1/README.md](week1/README.md) for full setup and reproduction instructions.

## Week 2 — What Was Built

A complete local log ingestion and correlation stack:

- **Loki** receiving and storing log streams from all running containers
- **Grafana Alloy** discovering Docker containers, collecting logs, extracting labels, pushing to Loki
- **Loki alerting rules** — two rules with a real self-triggering false positive diagnosed and fixed
- **Stack Observability dashboard** — unified dashboard with Prometheus metric panels and Loki log panels

See [week2/README.md](week2/README.md) for full setup and reproduction instructions.

## Week 3 — What Was Built

A complete local distributed tracing stack:

- **Tempo** receiving and storing traces from the order-api application
- **OpenTelemetry Collector** receiving OTLP traces from the application and forwarding to Tempo
- **order-api** — a Python Flask application with OTel auto-instrumentation and manual spans, plus Prometheus metrics via prometheus-flask-exporter
- **Three-pillar correlation** — Prometheus metrics, Loki logs, and Tempo traces from the same application queryable in Grafana Explore

A real cardinality anti-pattern was identified and fixed — the default `path` label in prometheus-flask-exporter creates unbounded cardinality for endpoints with URL parameters. Fixed with `group_by='endpoint'`.

Tempo v2.10 was found to require Kafka as a dependency — pinned to v2.6.1 which uses the classic ingest path without Kafka.

> **Architecture note:** This lab runs both Grafana Alloy and the OTel Collector simultaneously, which is not the standard production Grafana Labs pattern. Production deployments use Alloy as the single collector for all telemetry signals. An Alloy-only tracing lab with meta-observability is planned as a follow-on.

See [week3/README.md](week3/README.md) for full setup and reproduction instructions.

## Planned Follow-On Labs

In addition to Weeks 4 and 5, two additional lab tracks are planned:

**Alloy-only tracing lab** — rebuilds the Week 3 trace pipeline using only Grafana Alloy as the collector. Includes meta-observability — Alloy self-metrics, Alloy pipeline traces, and Flask app traces all in one environment. This is the production Grafana best practice pattern.

**OpenTelemetry deep dive track** — OTel treated as its own topic alongside the Kubernetes track. Covers instrumentation across languages, sampling strategies, the OTel Collector in depth, and auto-instrumentation library coverage.

**Kubernetes track** — CKA preparation alongside deploying the LGTM stack into Kubernetes once operational.

## Key Technical Decisions

**Docker Compose over a VM** — simplicity. No hypervisor overhead, direct host metric access for Node Exporter.

**Node Exporter host filesystem mounts** — Docker containers are isolated from the host by default. Explicit mounts required for Node Exporter to see real disk partitions.

**Recording rules from Week 1 Day 3** — CPU, memory, and disk utilization pre-computed as named metrics. Alerting rules reference recorded metrics rather than raw expressions.

**Alloy over Promtail** — Promtail is deprecated. Alloy is the current Grafana Labs collector.

**Surgical alert exclusions** — the `FatalLogEvent` Loki rule uses `!~ "caller=metrics.go|caller=evaluator"` to exclude ruler noise rather than excluding the Loki container entirely.

**OTel Collector alongside Alloy** — deliberate for learning breadth, not production recommendation. The OTel Collector pipeline model is widely deployed in enterprise environments.

**Tempo pinned to v2.6.1** — v2.10 introduced a Kafka dependency unsuitable for a simple lab. v2.6.1 uses the classic ingest path.

**prometheus-flask-exporter with group_by='endpoint'** — the default `path` label causes cardinality explosion for endpoints with URL parameters. `group_by='endpoint'` fixes this by using the Flask route function name.

**BatchSpanProcessor over SimpleSpanProcessor** — SimpleSpanProcessor blocks request handling on every span export. BatchSpanProcessor sends spans in bulk on a background thread.

**`--web.enable-lifecycle` on Prometheus** — enables hot reload. Required for configuration changes without container restart.

**Service names for inter-container communication** — `http://prometheus:9090`, `http://loki:3100`, `http://tempo:3200`. Never `localhost` inside Docker containers.

# Observability

The ticketing system uses the **PLTG stack** (Prometheus, Loki, Tempo, Grafana) deployed exclusively in Kubernetes. All configuration lives under `infra/k8s/observability/`.

---

## Architecture

```
Services ──► Prometheus  (metrics, port 9090)
         ──► Loki        (logs via stdout JSON, port 3100)
         ──► Tempo       (traces via OTLP gRPC, port 4317)
                              │         │         │
                              └────────►Grafana◄──┘  (port 3000 / NodePort 30030)
```

All six application services are instrumented with:
- **Structured JSON logging** → collected by Loki from container stdout
- **Prometheus metrics** → scraped from each service's `/metrics` endpoint
- **OpenTelemetry traces** → exported via OTLP gRPC to Tempo

---

## K8s Components

| Component  | Image                     | Internal port(s)       | NodePort        |
|------------|---------------------------|------------------------|-----------------|
| Prometheus | `prom/prometheus:latest`  | 9090                   | **30090**       |
| Loki       | `grafana/loki:latest`     | 3100 (HTTP), 9096 (gRPC) | 30100, 30096  |
| Tempo      | `grafana/tempo:latest`    | 3200 (API), 4317 (OTLP gRPC), 4318 (OTLP HTTP), 14250 (Jaeger) | 30020, 30431, 31425 |
| Grafana    | `grafana/grafana:latest`  | 3000                   | **30030**       |

**Access in Minikube:**
```
http://$(minikube ip):30030   # Grafana  (admin / admin)
http://$(minikube ip):30090   # Prometheus
http://$(minikube ip):30100   # Loki
http://$(minikube ip):30020   # Tempo
```

---

## Logging

### Format

All services write JSON logs to stdout. The `JSONFormatter` in `services/common/logging_config.py` produces one JSON object per line:

```json
{
  "timestamp": "2026-04-11T12:00:00.123456Z",
  "level": "INFO",
  "service": "booking",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "logger": "services.booking.main",
  "message": "Seat reserved",
  "venue": "arena-a",
  "seat_count": 2
}
```

Fields:

| Field       | Description                                          |
|-------------|------------------------------------------------------|
| `timestamp` | UTC ISO 8601 with millisecond precision              |
| `level`     | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`      |
| `service`   | Service name set at startup (`auth`, `booking`, etc.)|
| `trace_id`  | UUID propagated via `X-Trace-ID` header              |
| `logger`    | Python logger name (module path)                     |
| `message`   | Human-readable log message                           |
| extra fields| Any `extra={}` kwargs passed to the logger           |

### Usage in service code

```python
from logging_config import setup_logging, get_logger

setup_logging(service_name="booking", log_level="INFO")  # once at startup
logger = get_logger(__name__)

logger.info("Seat reserved", extra={"venue": venue, "seat_count": n})
logger.error("Reservation failed", extra={"reason": str(e), "venue": venue})
```

### Loki configuration

- **Retention**: 7 days
- **Storage**: `boltdb-shipper` index + filesystem chunks at `/loki/chunks`
- **Ingestion limits**: 256 MB/s burst, 512 MB burst size, 10,000 streams per user
- **Compression**: gzip chunks

**LogQL examples:**

```logql
# All logs from booking service
{service="booking"}

# Error logs across all services
{service=~".+"} | json | level = "ERROR"

# Logs for a specific trace
{service=~".+"} | json | trace_id = "550e8400-e29b-41d4-a716-446655440000"

# Failed reservation events
{service="booking"} | json | message =~ ".*failed.*"
```

---

## Metrics

### Collection

Prometheus scrapes the `/metrics` endpoint of each service every **15 seconds**. Metrics are retained for **7 days**.

**Scrape targets:**

| Job             | Target                              |
|-----------------|-------------------------------------|
| `auth`          | `ticketing-system-auth:8000`        |
| `booking`       | `ticketing-system-booking:8000`     |
| `booking-status`| `ticketing-system-booking-status:8000` |
| `gateway`       | `ticketing-system-gateway:8000`     |
| `payment`       | `ticketing-system-payment-mock:9000`|
| `mysql`         | `mysql-exporter:9104`               |
| `redis`         | `redis-exporter:9121`               |
| `prometheus`    | `localhost:9090` (self)             |

### Custom metrics by service

**Gateway**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `gateway_requests_routed_total` | Counter | `service`, `endpoint`, `status` | Total requests routed to downstream services |
| `gateway_routing_latency_seconds` | Histogram | `service` | Routing latency (buckets: 10ms–5s) |

**Auth**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `auth_login_success_total` | Counter | `login_method` | Successful logins |
| `auth_login_failed_total` | Counter | `failure_reason` | Failed login attempts |
| `auth_registration_total` | Counter | — | Total user registrations |
| `auth_token_generation_seconds` | Histogram | — | JWT generation latency (buckets: 1ms–100ms) |

**Booking**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `booking_reserved_total` | Counter | `venue` | Successful seat reservations |
| `booking_reservation_failed_total` | Counter | `failure_reason` | Failed reservation attempts |
| `booking_available_seats` | Gauge | `venue` | Current available seats per venue |
| `booking_reservation_latency_seconds` | Histogram | `operation` | Reservation latency incl. Redis+MySQL (buckets: 10ms–5s) |

**Payment**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `payment_intents_created_total` | Counter | — | Payment intents created |
| `payment_capture_total` | Counter | — | Capture attempts |
| `payment_capture_succeeded_total` | Counter | — | Successful captures |
| `payment_capture_failed_total` | Counter | `reason` | Failed captures |
| `payment_capture_latency_seconds` | Histogram | — | Capture latency incl. webhook delivery (buckets: 100ms–10s) |

**Notification**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `queue_messages_processed_total` | Counter | `status` | Messages processed from the Redis notification queue |
| `notification_send_latency_seconds` | Histogram | `notification_type` | End-to-end notification send time (buckets: 100ms–30s) |
| `email_send_total` | Counter | `status` | Emails sent (success / failed) |

### PromQL examples

```promql
# Request rate (5-minute window)
rate(http_requests_total[5m])

# 5xx error rate by service
sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
/ sum by (job) (rate(http_requests_total[5m])) * 100

# P95 latency by service
histogram_quantile(0.95,
  sum by (le, job) (rate(http_request_latency_seconds_bucket[5m])))

# Booking rate per minute
rate(booking_reserved_total[5m]) * 60

# Payment success rate
sum(rate(payment_capture_succeeded_total[5m]))
/ sum(rate(payment_capture_total[5m])) * 100

# Available seats by venue
booking_available_seats
```

---

## Distributed Tracing

### Setup

All services export OpenTelemetry traces to Tempo via **OTLP gRPC** on port 4317. The shared module is `services/common/tracing_config.py`.

**Environment variables (set via K8s ConfigMap):**

| Variable | Value |
|----------|-------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://tempo:4317` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` |
| `OTEL_TRACES_EXPORTER` | `otlp` |
| `OTEL_METRICS_EXPORTER` | `prometheus` |
| `OTEL_PROPAGATORS` | `tracecontext` |
| `SERVICE_NAME` | service name (e.g. `auth`, `booking`) |

### Trace propagation

The API Gateway generates a **UUID trace ID** (`X-Trace-ID` header) for every incoming request and propagates it to all downstream services. Each service:
1. Extracts `X-Trace-ID` from the incoming request headers
2. Sets it in thread-local context via `set_trace_id()`
3. Includes it in all log entries for log–trace correlation
4. Creates child spans via the OTEL tracer

### Manual spans

```python
from tracing_config import setup_tracing, get_tracer

setup_tracing(service_name="booking", tempo_host="tempo")
tracer = get_tracer(__name__)

# Create a manual span for a DB operation
with tracer.start_as_current_span("redis-reserve") as span:
    span.set_attribute("venue", venue_id)
    result = redis_client.eval(lua_script, ...)
```

### Tempo configuration

- **Retention**: 7 days (`block_retention: 168h`)
- **Receivers**: OTLP gRPC (4317), OTLP HTTP (4318), Jaeger gRPC (14250)
- **Storage**: local filesystem at `/var/tempo/traces` + WAL at `/var/tempo/wal`
- **Rate limiting**: 10,000 traces/user, 1 MB max per trace, 100,000 spans per trace
- **Metrics generator**: exports span-derived metrics labelled `cluster=minikube`

### TraceQL examples

```traceql
# Find all traces for the booking service
{ .service.name = "booking" }

# Slow requests (> 1 second)
{ duration > 1s }

# Failed spans in the payment service
{ .service.name = "payment" && status = error }

# Traces that touched both auth and booking
{ .service.name = "auth" } && { .service.name = "booking" }
```

---

## Alerts

Eleven alert rules are defined in `infra/k8s/observability/prometheus/configmap.yaml` (evaluation interval: 15s):

| Alert | Severity | Condition | For |
|-------|----------|-----------|-----|
| `ServiceDown` | critical | `up == 0` | 2m |
| `HighErrorRate` | warning | 5xx rate > 5% | 5m |
| `HighLatency` | warning | P95 latency > 1s | 5m |
| `CriticalLatency` | critical | P95 latency > 5s | 2m |
| `RedisQueueBacklog` | warning | `queue:notifications` > 1000 messages | 5m |
| `MySQLDown` | critical | MySQL exporter `up == 0` | 2m |
| `LowBookingRate` | warning | < 10 bookings/min | 10m |
| `HighPaymentFailureRate` | warning | payment failure rate > 10% | 5m |
| `PrometheusStorageNearFull` | warning | TSDB > 80% full | 5m |
| `LokiDroppedLogs` | warning | Loki dropping any logs | 5m |

Alertmanager is configured but targets are empty by default — wire up a receiver (Slack, PagerDuty, etc.) in the Prometheus ConfigMap to enable notifications.

---

## Grafana Dashboards

Four dashboards are auto-provisioned in the **Ticketing System** folder (credentials: `admin` / `admin`):

### API Performance
Panels: HTTP Request Rate, Error Rate (5xx/total), P95/P99 API Latency, Service Health (up/down)

### Service Health
Panels: Auth login success/failure, Token generation latency, Booking reservations/min, Available seats, Payment capture success/failure, Error logs by severity

### Business Metrics
Panels: Booking rate, Revenue rate, User registration rate, Active users (24h), Recent error logs

### System Overview
Panels: Gateway service status, Auth service status, all service-level health indicators, Redis connected clients

### Datasource cross-linking

| From | To | How |
|------|----|-----|
| Loki (log entry) | Tempo (trace) | `trace_id` derived field → click jumps to trace view |
| Tempo (trace) | Loki (logs) | `tracesToLogs` → shows logs for the trace's time window |
| Tempo (service map) | Prometheus | `serviceMap` → links service graph nodes to metrics |

---

## Configuration Files

| Path | Description |
|------|-------------|
| `infra/k8s/observability/prometheus/configmap.yaml` | Scrape jobs + 10 alert rules |
| `infra/k8s/observability/prometheus/deployment.yaml` | Prometheus Deployment + Service (NodePort 30090) |
| `infra/k8s/observability/loki/configmap.yaml` | Loki storage, ingestion limits, retention |
| `infra/k8s/observability/loki/deployment.yaml` | Loki Deployment + Service |
| `infra/k8s/observability/tempo/configmap.yaml` | OTLP receivers, storage, rate limits |
| `infra/k8s/observability/tempo/deployment.yaml` | Tempo Deployment + Service |
| `infra/k8s/observability/grafana/configmap.yaml` | Datasource definitions + dashboard provisioning + 4 dashboard JSONs |
| `infra/k8s/observability/grafana/deployment.yaml` | Grafana Deployment + PVC (5Gi) + Service (NodePort 30030) |
| `services/common/logging_config.py` | JSON log formatter + `setup_logging()` / `get_logger()` |
| `services/common/tracing_config.py` | OTEL tracer setup + `setup_tracing()` / `get_tracer()` |

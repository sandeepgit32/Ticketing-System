# System Architecture

## Component Diagram

```
┌─────────┐
│  User   │
└────┬────┘
     │
     ▼
┌─────────────────┐
│  Frontend       │ (Vue.js - Port 5174)
│  Server         │
└────┬────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│                     API Gateway                              │
│              (FastAPI - Port 8000)                          │
│  • JWT Token Verification                                   │
│  • Request Routing                                          │
│  • Authentication Middleware                                │
└──┬──────────────────┬────────────────┬──────────────────┬──┘
   │                  │                │                  │
   ▼                  ▼                ▼                  ▼
┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐
│  Auth    │   │ Booking  │   │   Booking    │   │ Payment  │
│ Service  │   │ Service  │   │   Status     │   │ Service  │
│          │   │          │   │   Service    │   │  (Mock)  │
│ Port     │   │ Port     │   │              │   │          │
│ 8002     │   │ 8001     │   │   Port 8003  │   │ Port 9001│
└────┬─────┘   └────┬─────┘   └──────┬───────┘   └─────┬────┘
     │              │                 │                  │
     │              │                 │                  │
     ▼              ▼                 ▼                  │
┌─────────────────────────────────────────────┐         │
│             MySQL Database                   │         │
│              (Port 3306)                    │         │
│                                             │         │
│  Tables:                                    │         │
│  • users                                    │         │
│  • reservations                             │         │
│  • bookings                                 │         │
│  • events                                   │         │
└─────────────────────────────────────────────┘         │
                     ▲                                   │
                     │                                   │
     ┌───────────────┴───────────────┐                  │
     │                               │                  │
┌────┴─────┐                   ┌────┴─────────┐        │
│  Redis   │◄──────────────────│   Booking    │        │
│          │  Seat Bitmaps     │   Service    │────────┘
│ Port     │                   │              │  Webhook
│ 6379     │                   └──────┬───────┘
│          │                          │
└────┬─────┘                          │ Publish
     │                                │
     │         ┌──────────────────────┘
     │         │
     │         │ Queues:
     │         │ • queue:notifications
     │         │ • queue:jobs
     │         │
     ▼         ▼
┌──────────────────┐        ┌─────────────────────┐
│  Notification    │        │      Worker         │
│    Service       │        │     Service         │
│                  │        │                     │
│  • Email via     │        │  • Job Processing   │
│    Mailtrap      │        │  • Webhook Handler  │
│  • Console Log   │        │                     │
└──────────────────┘        └─────────────────────┘
```

## Data Flow

### User Registration & Login

```
User → Frontend → API Gateway → Auth Service → MySQL
                                               ↓
                               ← JWT Token ←───┘
```

### Seat Reservation

```
User → Frontend → API Gateway → Booking Service
      (with JWT)                      ↓
                               ┌──────┴──────┐
                               ▼             ▼
                            Redis         MySQL
                         (Bitmap)    (Reservations)
                               ↓
                         Notification Queue
                               ↓
                       Notification Service
                               ↓
                         Email (Mailtrap)
```

### Payment Processing

```
Booking Service → Payment Service (Mock)
                        ↓
                  Webhook Callback
                        ↓
                 Booking Service
                    ↓       ↓
                  MySQL   Redis Queue
                    ↓          ↓
             (Create      Notification
              Booking)        ↓
                        Notification
                          Service
                            ↓
                       Email Sent
```

### Checking Booking Status

```
User → Frontend → API Gateway → Booking Status Service
      (with JWT)       ↓                    ↓
                 Verify Token          Query MySQL
                  (Auth Service)            ↓
                                      Return Status
```

## Message Queue Architecture

### Redis Queues

1. **Notification Queue** (`queue:notifications`)
   - Producer: Booking Service
   - Consumer: Notification Service
   - Purpose: Asynchronous email notifications
   - Format:
   ```json
   {
     "type": "reservation_confirmed | payment_confirmed | payment_failed",
     "data": {
       "user_email": "...",
       "event_name": "...",
       "seats": [...],
       ...
     }
   }
   ```

2. **Job Queue** (`queue:jobs`)
   - Producer: Booking Service (webhooks)
   - Consumer: Worker Service
   - Purpose: Background job processing
   - Format:
   ```json
   {
     "job_id": "uuid",
     "type": "payment_webhook",
     "payload": {...},
     "created_at": "timestamp"
   }
   ```

## Security Architecture

### Authentication Flow

```
1. User Login
   └─→ Auth Service generates JWT
       └─→ JWT contains: user_id, email, full_name, expiry

2. Protected Request
   └─→ Client sends: Authorization: Bearer <JWT>
       └─→ API Gateway verifies JWT
           ├─→ Valid: Forward to service with X-User-Id header
           └─→ Invalid: Return 401 Unauthorized

3. Service-to-Service
   └─→ Internal network communication
       └─→ No external exposure
```

### Database Security

- Passwords hashed with bcrypt
- MySQL user has limited permissions
- Connection pooling for efficiency
- Prepared statements prevent SQL injection

## Scalability Considerations

### Current Architecture
- Single instance of each service
- Redis for fast seat allocation
- MySQL for persistent storage
- Queue-based async processing

### Horizontal Scaling Ready
- Stateless services (except databases)
- API Gateway can be replicated
- Workers can be scaled independently
- MySQL can be replicated (read replicas)
- Redis can use Redis Cluster

### KEDA Integration (Kubernetes)
- Auto-scale based on queue length
- Scale booking service based on load
- Scale workers based on job queue depth
- Configuration in `infra/helm/booking/templates/keda-scaledobject.yaml`

## Deployment Architecture

### Docker Compose (Development)
```
All services in single docker network
- Easy local development
- Quick startup
- Shared volumes for data persistence
```

### Kubernetes (Production)
```
Services as Deployments
- Auto-scaling with KEDA
- Service mesh ready
- Health checks and readiness probes
- Resource limits and requests
- ConfigMaps for configuration
- Secrets for sensitive data
```

## Monitoring & Observability (PLTG Stack)

### Overview
The system uses the PLTG stack (Prometheus, Loki, Tempo, Grafana) for comprehensive observability:

- **Prometheus** (Port 9090): Metrics collection from all services
  - Scrapes metrics every 15 seconds
  - 7-day retention for development
  - PromQL query language for metric analysis
  
- **Loki** (Port 3100): Log aggregation and search
  - JSON-formatted logs with trace IDs
  - LogQL query language for log search
  - Correlation with traces and metrics
  
- **Tempo** (Port 3200): Distributed tracing backend
  - Traces request flows across all services
  - OTLP (OpenTelemetry Protocol) gRPC receiver (port 4317)
  - Trace search and visualization
  
- **Grafana** (Port 3000): Unified dashboarding and alerting
  - Real-time dashboards (metrics, logs, traces)
  - Alert rules with multi-channel notification
  - Default credentials: admin/admin

### Observability Data Flow

```
API Request Flow:
┌──────────┐ (X-Trace-ID: abc123)
│ Frontend │
└─────┬────┘
      │
      ▼
┌─────────────────────────────────────────────┐
│  API Gateway                                │
│  • Generates Trace ID if missing            │
│  • Logs request with trace ID               │
│  • Creates span in Tempo                    │
│  • Metrics: request_count, request_latency  │
└────┬─────────────┬──────────┬───────────────┘
     │             │          │
     ▼             ▼          ▼
  Auth       Booking      Payment
  (span)      (span)       (span)
  ├─logs    ├─logs         ├─logs
  ├─metrics ├─metrics      ├─metrics
  └─trace   └─trace        └─trace
     │        │              │
     └────────┴──────────────┘
            │
      ┌─────┴─────┐
      ▼           ▼
    Prometheus  Loki  Tempo
    (metrics) (logs) (traces)
      │         │      │
      └─────────┴──────┘
              │
              ▼
          Grafana
     (unified dashboard)
```

### Key Metrics

**HTTP Metrics:**
- `http_requests_total`: Total requests by method, endpoint, status
- `http_request_duration_seconds`: Latency histogram (P50, P95, P99)
- `http_request_errors_total`: Error count by type

**Business Metrics:**
- `booking_reserved_total`: Booking count per venue
- `payment_capture_total`: Payment volume
- `queue_depth`: Messages waiting in notification queue

**Resource Metrics:**
- CPU, memory, disk usage from Prometheus Node Exporter
- Database connection pool usage
- Redis memory and clients

### Log Search Examples

Access Grafana at http://localhost:3000 and use LogQL:

```logql
# Find all errors
{level="ERROR"}

# Find errors for specific service
{service="booking", level="ERROR"}

# Find a specific user's activity (if logged)
{trace_id="550e8400-e29b-41d4-a716-446655440000"}

# Find slow requests
{service="gateway"} | json | request_latency_ms > 1000
```

### Alert Rules

Configured in `infra/observability/docker-compose/alert.rules.yml`:

- **ServiceDown**: Service unreachable for 5+ minutes
- **HighErrorRate**: >5% requests returning errors
- **HighLatency**: P95 response time > 1 second
- **RedisQueueBacklog**: Queue depth > 1000 for 10 minutes
- **PaymentFailures**: >10% of payment captures failing

### Documentation

- **OBSERVABILITY.md** - PLTG stack overview and quick start
- **INSTRUMENTATION.md** - Code instrumentation guide per service
- **MONITORING.md** - How to monitor the system in production
- **DASHBOARDS.md** - Dashboard guide and metric interpretation
- **TROUBLESHOOTING.md** - Common issues and debug procedures
- **ALERTS.md** - Alert meanings and response procedures

### Implementation Details

**Structured Logging:**
- All logs output as JSON to make filtering/parsing easier
- Trace ID injected in every log for correlation
- Service name and level included for filtering

**Distributed Tracing:**
- Trace ID generated in API Gateway
- Propagated via X-Trace-ID header to all services
- Each service creates spans for operations
- Spans include context (service, method, duration, status)

**Metrics Collection:**
- Prometheus middleware in each FastAPI service
- Custom metrics for business logic (bookings, payments)
- Queue metrics from Redis
- 7-day retention (configurable)

## Technology Stack

### Backend
- **FastAPI** - Modern async Python web framework
- **Redis** - In-memory data store for queues and caching
- **MySQL** - Relational database for persistent data
- **JWT** - Stateless authentication
- **bcrypt** - Password hashing

### Frontend
- **Vue.js 3** - Progressive JavaScript framework
- **Vite** - Build tool and dev server

### Infrastructure
- **Docker** - Containerization
- **Docker Compose** - Multi-container orchestration
- **Helm** - Kubernetes package manager
- **KEDA** - Kubernetes event-driven autoscaling

### External Services
- **Mailtrap** - Email testing service

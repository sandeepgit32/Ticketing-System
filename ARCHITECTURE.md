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

## Monitoring & Observability

### Current Logging
- Console logs for all services
- Docker logs aggregation
- View with: `docker compose logs -f`

### Future Enhancements
- [ ] Prometheus metrics
- [ ] Grafana dashboards
- [ ] Distributed tracing (Jaeger)
- [ ] ELK stack for log aggregation
- [ ] Application Performance Monitoring (APM)

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

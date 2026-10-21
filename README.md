# Real-Time Appointment / Booking System

Production-style **FastAPI** backend for a clinic booking product. Built as a portfolio project you can walk through in SDE interviews — especially the **Redis distributed lock** that prevents double-booking under concurrency.

## Why this project stands out in interviews

| Topic | What you can explain |
| --- | --- |
| Concurrency | Redis `SET key NX EX` lock around booking; why DB unique constraints alone are not enough for clean UX |
| Horizontal scale | Same Redis (ElastiCache) shared by all EC2 workers; Redis Pub/Sub fans WebSocket events across instances |
| Auth / RBAC | JWT + roles (`patient` / `doctor` / `admin`) with route-level guards |
| Real-time | WebSockets push `slot_booked` / `slot_freed` instead of polling |
| Background jobs | APScheduler reminders (and when you'd graduate to Celery/SQS) |
| Abuse control | Redis fixed-window rate limit on `POST /appointments/book` |

---

## Architecture (high level)

```
Client ──HTTP──► FastAPI (EC2 / local)
                   │
                   ├── PostgreSQL (RDS)     users, doctors, time_slots, appointments
                   ├── Redis (ElastiCache)  locks · slot cache · rate limits · pub/sub
                   └── APScheduler          reminder scan every N minutes

Client ──WS────► /ws/doctors/{id}/slots   live slot updates
```

### Booking conflict prevention (core design)

```
Request A & B hit POST /appointments/book for the same slot_id

  A: SET lock:slot:42 <token> NX EX 10   → OK
  B: SET lock:slot:42 ... NX             → FAIL → 409 Conflict

  A: BEGIN; SELECT … FOR UPDATE; INSERT appointment; is_booked=true; COMMIT
  A: DEL lock (Lua, token-safe) + invalidate cache + publish WS event
```

**Why Redis lock instead of only a DB unique constraint?**

1. Check-then-act races: two transactions can both read `is_booked=false` before either commits.
2. Unique constraints turn the loser into an `IntegrityError` / 500 unless you carefully map errors — Redis lets you return a clear **409 Slot already booked**.
3. The critical section often spans more than one row write (appointment + slot flag + cache + notify). A distributed lock coordinates that across **multiple app servers**.

**Why not only `SELECT FOR UPDATE`?** Row locks work inside one Postgres primary, but they don't help if you later add side effects outside the DB, and interviewers specifically look for multi-instance awareness. This project uses **both**: Redis lock (cluster-wide) + `with_for_update()` (same-DB belt-and-suspenders).

**Why APScheduler over Celery here?** One process, no broker/worker fleet, enough for periodic reminders. Move to Celery/SQS when job volume, retries, or isolation demand it.

**Why WebSockets over polling?** Push on change → lower latency and load. Multi-EC2: Redis Pub/Sub bridges instances so a booking on worker A updates sockets on worker B.

---

## Project structure

```
appointment-booking-system/
├── app/
│   ├── main.py                 # FastAPI app + lifespan (scheduler, WS subscriber)
│   ├── config.py               # pydantic-settings from .env
│   ├── database.py             # SQLAlchemy engine / sessions
│   ├── models/                 # ORM: User, Doctor, TimeSlot, Appointment
│   ├── schemas/                # Pydantic request/response models
│   ├── auth/                   # JWT, password hashing, RBAC dependencies
│   ├── redis_client/           # client, SETNX lock, rate limit, slot cache
│   ├── services/               # booking (lock!), doctors, reminders
│   ├── routes/                 # auth, doctors, appointments, websocket
│   └── websocket/              # ConnectionManager + Redis pub/sub fan-out
├── scripts/
│   ├── seed_data.py            # Demo users + slots
│   └── concurrency_test.py     # Prove only one of N parallel books wins
├── docker-compose.yml          # PostgreSQL 16 + Redis 7
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quick start (local)

### 1. Prerequisites

- Python 3.11+
- Docker Desktop (for Postgres + Redis)

### 2. Start infrastructure

```bash
cd appointment-booking-system
docker compose up -d
```

### 3. Python env

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env    # Windows
# cp .env.example .env    # macOS / Linux
```

### 4. Seed demo data

```bash
python -m scripts.seed_data
```

Demo accounts:

| Email | Password | Role |
| --- | --- | --- |
| `admin@clinic.example.com` | `AdminPass123!` | admin |
| `alice@clinic.example.com` | `PatientPass123!` | patient |
| `bob@clinic.example.com` | `PatientPass123!` | patient |
| `sarah@clinic.example.com` | `DoctorPass123!` | doctor (Cardiology) |
| `james@clinic.example.com` | `DoctorPass123!` | doctor (Dermatology) |

> Note: use `.example.com` (not `.test`) — Pydantic's email validator rejects reserved TLDs like `.test`.

### 5. Run the API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: http://127.0.0.1:8000/docs  
- Health: http://127.0.0.1:8000/health  

---

## API overview

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | — | Role selection; doctors need `specialization` |
| `POST` | `/auth/login` | — | Returns JWT |
| `GET` | `/doctors` | — | Doctors + available slots (Redis-cached) |
| `GET` | `/doctors/{id}/slots` | — | Unbooked slots only |
| `POST` | `/appointments/book` | patient/admin | **Redis lock + rate limit (5/min)** |
| `PATCH` | `/appointments/{id}/cancel` | owner / doctor / admin | Frees slot, WS `slot_freed` |
| `GET` | `/appointments/my` | any | Role-aware list |
| `PATCH` | `/appointments/{id}/status` | doctor/admin | `confirmed` / `completed` / `cancelled` |
| `WS` | `/ws/doctors/{id}/slots` | — | Live `slot_booked` / `slot_freed` |

### Example: book a slot

```bash
# Login
curl -s -X POST http://127.0.0.1:8000/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"email\":\"alice@clinic.example.com\",\"password\":\"PatientPass123!\"}"

# List free slots
curl -s http://127.0.0.1:8000/doctors/1/slots

# Book (replace TOKEN and SLOT_ID)
curl -s -X POST http://127.0.0.1:8000/appointments/book ^
  -H "Authorization: Bearer TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{\"slot_id\": SLOT_ID}"
```

### Concurrency demo (interview gold)

```bash
python -m scripts.concurrency_test --token YOUR_JWT --slot-id 1 --workers 10
```

Expected: **exactly one `201`**, nine `409` — no double-booking.

### WebSocket (browser console)

```javascript
const ws = new WebSocket("ws://127.0.0.1:8000/ws/doctors/1/slots");
ws.onmessage = (e) => console.log("live update", JSON.parse(e.data));
```

Then book/cancel a slot for doctor `1` from another tab — the socket receives an event immediately.

---

## Error handling (what clients see)

| Situation | Status |
| --- | --- |
| Missing / expired JWT | `401` |
| Wrong role (e.g. doctor booking as patient) | `403` |
| Cancelling someone else's appointment | `403` |
| Unknown slot / appointment | `404` |
| Slot already booked / lock contended | `409` |
| >5 booking attempts / minute / user | `429` |

---

## Deploy on AWS (EC2 + RDS + ElastiCache)

1. **RDS PostgreSQL** — create instance, security group allows 5432 from EC2 SG. Set `DATABASE_URL`.
2. **ElastiCache Redis** — same VPC; allow 6379 from EC2 SG. Set `REDIS_URL=redis://<primary-endpoint>:6379/0`.
3. **EC2** — Amazon Linux / Ubuntu: install Docker or Python, clone repo, set `.env` (or SSM Parameter Store), run:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
   ```

4. **ALB** — forward HTTP to EC2:8000; health check `/health`. For WebSockets, enable idle timeout ≥ 60s and (optionally) stickiness if you ever drop Redis Pub/Sub.
5. **Secrets** — put `JWT_SECRET_KEY` in Secrets Manager / SSM; never commit `.env`.

Optional: wrap the app in the included `Dockerfile` and run on ECS/Fargate with the same RDS + ElastiCache backends.

---

## Interview cheat-sheet (design decisions)

1. **Redis SETNX lock** — cluster-wide mutual exclusion with TTL crash recovery; Lua release compares token so we never delete another worker's lock after expiry.
2. **DB `SELECT FOR UPDATE`** — second line of defense inside the transaction on one primary.
3. **`is_booked` flag** — fast available-slot queries without joining appointment status history.
4. **Cancel keeps history** — status → `cancelled`, `is_booked=false`; slot can be rebooked.
5. **APScheduler** — simple in-process reminders; Celery when you need a worker fleet.
6. **WebSockets + Redis Pub/Sub** — real-time UX that still works with multiple EC2 instances.
7. **Rate limit in Redis** — abuse protection that is global across the ASG, not per process.

---

## License

MIT — feel free to use in your portfolio and adapt for take-home assignments.

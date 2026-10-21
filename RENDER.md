# Deploy on Render (Web Service + Postgres + Redis)
#
# Exact values for the "New Web Service" form:
# ------------------------------------------------
# Source:        sriakshaya10/real-time-appointment-booking-system
# Language:      Docker
# Branch:        main
# Root Directory:  (LEAVE EMPTY)  ← repo root already has Dockerfile
# Region:        Oregon (or same as your other services)
# Instance:      Free (hobby) or Starter
#
# You ALSO need a database + Redis (this app cannot run on the web service alone).

## 1) Create PostgreSQL on Render

Dashboard → New → PostgreSQL
- Name: appointment-db
- Plan: Free (or Starter)
- Region: same as web service (Oregon)
- Create

After it is ready, open it → **Connections** → copy **Internal Database URL**
(Looks like `postgres://user:pass@dpg-xxxx/dbname`)

## 2) Create Redis (Key Value) on Render

Dashboard → New → Key Value (Redis)
- Name: appointment-redis
- Plan: Free if available, otherwise Starter / or use Upstash free Redis
- Region: same as web service
- Create

Copy the **Internal Redis URL**
(Looks like `redis://red-xxxx:6379`)

> Alternative free Redis: https://upstash.com → create Redis → copy REDIS_URL

## 3) Create Web Service (the form you are on)

| Field | What to enter |
| --- | --- |
| Source Code | `sriakshaya10/real-time-appointment-booking-system` |
| Name | `real-time-appointment-booking-system` (or keep default) |
| Project | optional |
| Language | **Docker** |
| Branch | **main** |
| Region | **Oregon** (match DB/Redis) |
| Root Directory | **leave blank / empty** |
| Instance Type | **Free** for demo |

Do **not** put `src` or `app` in Root Directory — Dockerfile is at the repo root.

## 4) Environment Variables (Add these before Deploy)

Click **Add Environment Variable** for each:

| NAME | VALUE |
| --- | --- |
| `DATABASE_URL` | paste Internal Database URL from step 1 |
| `REDIS_URL` | paste Redis URL from step 2 |
| `JWT_SECRET_KEY` | any long random string (click Generate, or make one up) |
| `APP_ENV` | `production` |
| `DEBUG` | `false` |
| `CORS_ORIGINS` | `*` (or your frontend URL later) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` |
| `REDIS_LOCK_TTL_SECONDS` | `10` |
| `BOOKING_RATE_LIMIT_PER_MINUTE` | `5` |
| `REMINDER_JOB_INTERVAL_MINUTES` | `15` |
| `REMINDER_LOOKAHEAD_HOURS` | `24` |

Optional: use **Add from .env** and paste a block like:

```env
DATABASE_URL=postgres://...from render...
REDIS_URL=redis://...from render...
JWT_SECRET_KEY=replace-with-long-random-secret
APP_ENV=production
DEBUG=false
CORS_ORIGINS=*
```

## 5) Deploy

Click **Deploy web service**.

Wait for build logs → should end with live URL like:
`https://real-time-appointment-booking-system-xxxx.onrender.com`

Open:
- `https://YOUR-SERVICE.onrender.com/docs`
- `https://YOUR-SERVICE.onrender.com/health`

## 6) Seed demo data (one time)

After first successful deploy, from your laptop (with DATABASE_URL pointing at Render **External** DB URL):

```bash
# set DATABASE_URL to Render External Database URL temporarily
python -m scripts.seed_data
```

Or open a Render shell (paid) and run the same.

Demo logins after seeding:
- `alice@clinic.example.com` / `PatientPass123!`
- `sarah@clinic.example.com` / `DoctorPass123!`

## Common errors

| Error | Fix |
| --- | --- |
| connection refused localhost:5432 | You forgot `DATABASE_URL` env var, or used localhost instead of Render URL |
| Redis errors on book | Set `REDIS_URL` to Render/Upstash Redis |
| Build OK but site sleeps | Free web services sleep after idle — first request is slow |
| Root Directory wrong | Leave it empty |

## Root Directory reminder

```
real-time-appointment-booking-system/   ← this IS the root (leave form blank)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
└── scripts/
```

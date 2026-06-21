# Multi-Node Distributed Architecture Strategy
## (Reusable for any project — extracted from Sarathi Bot)

---

## What This Strategy Does

Turns a single-container monolith into a horizontally scalable, highly available
multi-node system that runs across multiple cheap servers (Oracle free VPS + home
mini PC + any future cloud node), with automated payments, zero-downtime deploys,
and no single point of failure.

---

## Core Principles

1. **Stateless services** — no service stores state locally. All state lives in
   shared Redis and PostgreSQL accessible by every node.
2. **Redis as the nervous system** — pub/sub for real-time events, BullMQ for
   job queues, SET NX for distributed dedup/locks.
3. **WireGuard VPN** — private encrypted tunnel between all nodes. Database ports
   (Postgres, Redis) are NEVER exposed to the public internet.
4. **Docker + GHCR + Portainer** — every service is a Docker image, built via
   GitHub Actions, stored in GitHub Container Registry, deployed via Portainer UI.
5. **Automated payments** — Razorpay QR + webhook. No manual admin approval.

---

## Node Layout

```
Node A — Oracle VPS (ARM64, always-on, free)
├── postgres          ← shared DB (only here)
├── redis             ← shared queue/pub-sub (only here)
├── [your-gateway-1]  ← primary request intake (e.g. API server, WA bot, extension server)
├── [your-gateway-2]  ← hot standby (same image, same Redis dedup)
├── worker-fast       ← handles light/quick jobs from BullMQ queue
├── worker-heavy      ← handles slow/browser/CPU-intensive jobs
├── scheduler         ← cron jobs (billing, cleanup, reports)
└── api               ← admin dashboard + REST API + Razorpay webhook

Node B — Home Mini PC / Extra VPS (Intel/AMD, optional)
├── [your-gateway-3]  ← 3rd hot standby (connects to Node A Redis/Postgres via VPN)
└── worker-heavy      ← extra capacity for heavy jobs

Node C, D... (future)
└── worker-heavy      ← add as many as needed for horizontal scale
```

---

## Service Roles

| Service | Role | Scales horizontally? |
|---------|------|---------------------|
| `[gateway]` | Accepts incoming requests (HTTP, WebSocket, bot, extension, etc.) | ✅ Yes — Redis dedup prevents double processing |
| `worker-fast` | Processes quick jobs from BullMQ queue (API calls, DB reads) | ✅ Yes — BullMQ handles distribution |
| `worker-heavy` | Processes slow jobs (browser automation, PDF, OCR, etc.) | ✅ Yes — add more nodes |
| `scheduler` | Cron jobs — billing reset, expiry check, cleanup | ❌ Only 1 — use Redis distributed lock to prevent duplicate runs |
| `api` | Admin dashboard + REST API + payment webhook | ❌ Only 1 (or behind load balancer) |
| `postgres` | Relational database | ❌ Only 1 (or use managed DB like Supabase/RDS) |
| `redis` | Queue + pub/sub + cache | ❌ Only 1 (or Redis Cluster for extreme scale) |

---

## Key Patterns

### 1. Redis SET NX Dedup (prevents double processing across nodes)
```js
// First node to claim this key processes the request. Others skip.
const claimed = await redis.set(`dedup:req:${requestId}`, nodeId, 'EX', 300, 'NX');
if (!claimed) return; // another node already handling this
```

### 2. BullMQ Job Queue (distributes work across workers)
```js
// Gateway pushes job
await queue.add('job_type', { userId, data }, { attempts: 3, backoff: 5000 });

// Worker (on any node) picks it up
worker.process('job_type', async (job) => { /* do work */ });
```

### 3. Redis Pub/Sub for real-time response delivery
```js
// Worker publishes result after completing job
await redis.publish(`response:${transport}:${sessionId}`, JSON.stringify(result));

// Gateway listens and delivers to user
subscriber.on('pmessage', async (pattern, channel, data) => {
  // Dedup: only first gateway to claim delivery key sends it
  const claimed = await redis.set(`dedup:resp:${channel}:${hash}`, nodeId, 'EX', 60, 'NX');
  if (!claimed) return;
  await deliverToUser(sessionId, JSON.parse(data));
});
```

### 4. Cron with Redis distributed lock (prevents duplicate scheduler runs)
```js
const lock = await redis.set('lock:billing-reset', '1', 'EX', 3600, 'NX');
if (!lock) return; // another scheduler instance already ran this
// ... do the cron work
```

### 5. Razorpay Auto-Payment (no admin needed)
```
User requests topup
  → Create Razorpay QR (single_use, fixed_amount)
  → Store userId + sessionId in QR notes
  → Send QR image to user
  → User scans + pays
  → Razorpay webhook fires → POST /api/payments/razorpay/webhook
  → Verify HMAC signature
  → Read userId from notes → addCredits() → notify user via Redis pub/sub
```

---

## WireGuard VPN Setup (inter-node secure networking)

```
Node A (VPS) — WireGuard server
  Interface: 10.99.0.1/24
  ListenPort: 51820

Node B (Home/Cloud) — WireGuard client
  Interface: 10.99.0.2/24
  Connects to: NodeA_PublicIP:51820
  AllowedIPs: 10.99.0.0/24
  PersistentKeepalive: 25  ← important when behind NAT

Node C (future)
  Interface: 10.99.0.3/24
  ...
```

Node B connects to Postgres and Redis using VPN IPs:
```
DATABASE_URL=postgres://user:pass@10.99.0.1:5432/mydb
REDIS_URL=redis://:pass@10.99.0.1:6379
```

Only port `51820/UDP` needs to be open on Node A firewall.
Postgres (5432) and Redis (6379) stay completely private.

---

## CI/CD Pipeline

```
git push → scaling-production branch
  → GitHub Actions triggers
  → Builds 6 Docker images in parallel
  → Multi-platform: linux/amd64 + linux/arm64
    (amd64 = home PC/Intel cloud, arm64 = Oracle ARM free tier)
  → Pushes to GHCR:
      ghcr.io/your-org/your-project:service-name-latest
      ghcr.io/your-org/your-project:service-name-{git-sha}
  → Portainer on each node pulls latest image + redeploys
```

GitHub Actions workflow needs:
- `permissions: packages: write`
- `docker/setup-qemu-action@v3` (for ARM64 cross-compile)
- `docker/setup-buildx-action@v3`
- `docker/build-push-action@v5` with `platforms: linux/amd64,linux/arm64`

---

## PostgreSQL Schema Essentials

```sql
-- Users / auth
CREATE TABLE auth_users (
  id SERIAL PRIMARY KEY,
  canonical_phone TEXT UNIQUE,  -- or email/username depending on your app
  name TEXT,
  credits INTEGER DEFAULT 0,
  plan_id INTEGER,
  plan_expiry TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Credit audit log
CREATE TABLE credit_transactions (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES auth_users(id),
  amount INTEGER,  -- positive = credit, negative = debit
  note TEXT,
  triggered_by TEXT,  -- 'razorpay', 'admin', 'system'
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Payment requests (manual UTR fallback)
CREATE TABLE payment_requests (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES auth_users(id),
  utr TEXT UNIQUE,
  amount INTEGER,
  status TEXT DEFAULT 'pending',  -- pending, approved, rejected
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Plans/subscriptions
CREATE TABLE plans (
  id SERIAL PRIMARY KEY,
  name TEXT,
  credits_per_month INTEGER,
  price INTEGER,
  is_active BOOLEAN DEFAULT true
);
```

---

## Docker Compose Structure (per node)

**Node A (docker-compose.portainer.yml):**
```yaml
services:
  postgres:    # infrastructure
  redis:       # infrastructure
  gateway-1:   # your app gateway (instance 1)
  gateway-2:   # your app gateway (instance 2) — hot standby
  worker-fast: # handles light jobs
  worker-heavy:# handles heavy jobs
  scheduler:   # cron jobs
  api:         # admin + REST API + payment webhook
    ports:
      - "3000:3000"
```

**Node B (docker-compose.server-b.yml):**
```yaml
services:
  gateway-3:   # 3rd hot standby — connects to Node A via VPN
  worker-heavy:# extra compute — connects to Node A Redis/Postgres via VPN
```

---

## Environment Variables (minimum required)

```bash
# Node A
PG_PASSWORD=strong_password
REDIS_PASSWORD=strong_password
CONFIG_PATH=/opt/yourapp           # host path for persistent data

# Node B (additional)
SERVER_A_IP=10.99.0.1             # VPN tunnel IP of Node A

# Shared across all nodes
DATABASE_URL=postgres://...
REDIS_URL=redis://:pass@...
INSTANCE_ID=node-a-1              # unique per container for dedup logging
DISCORD_WEBHOOK_URL=              # for admin alerts

# Admin dashboard
ADMIN_USERNAME=admin
ADMIN_TOKEN=strong_secret

# Razorpay (optional — falls back to manual flow if not set)
RAZORPAY_KEY_ID=rzp_live_xxx
RAZORPAY_KEY_SECRET=xxx
RAZORPAY_WEBHOOK_SECRET=xxx
```

---

## Files to Create in Every New Project

```
.github/workflows/docker-publish.yml   ← CI/CD, multi-platform build + push to GHCR
docker-compose.portainer.yml           ← Node A (paste into Portainer)
docker-compose.server-b.yml            ← Node B (home server / extra cloud node)
.env.portainer.example                 ← all env vars with descriptions
.env.server-b.example                  ← Node B env vars
wireguard/setup-server-a.sh            ← automated WireGuard setup for Node A
wireguard/setup-server-b.sh            ← automated WireGuard setup for Node B
packages/
  common/                              ← shared: db, redis, queue, razorpayService
  gateway/                             ← request intake (your app's entry point)
  worker-fast/                         ← light job processor
  worker-heavy/                        ← heavy job processor
  scheduler/                           ← cron jobs
  api/                                 ← admin dashboard + REST API
```

---

## What Makes This Different From a Simple Single-Container App

| Feature | Single Container | This Strategy |
|---------|-----------------|---------------|
| Downtime if container crashes | ❌ Full outage | ✅ Other gateways keep running |
| Scale heavy jobs | ❌ Must restart whole app | ✅ Add more worker nodes |
| Deploy update | ❌ Downtime during restart | ✅ Rolling: workers drain, gateway restarts fast |
| Payment processing | ❌ Manual admin approval | ✅ Razorpay auto-credits instantly |
| Multi-server | ❌ One machine | ✅ Oracle + Home + any cloud |
| DB exposure | ❌ Often port-forwarded | ✅ VPN only, never public |

# Node B CAPTCHA Workers

This setup lets a mini PC run EazyFill CAPTCHA solver workers while Node A
remains the source of truth for API, Postgres, Redis, billing, users, scheduler,
and backups.

## Topology

```text
Extension -> Node A API -> Node A Redis queue -> Node B worker
                         <- Node A Redis result <-
```

Node B also connects to Node A Postgres during startup and for model-routing
schema validation. Node B must have the same ONNX model files locally.

## Node A: Worker-Access Sidecar

The current live Portainer stack discovered on Node A is:

- stack: `test-stack-eazyfill`
- Docker network: `test-stack-eazyfill-network`
- Postgres alias: `test-stack-eazyfill-postgres`
- Redis alias: `test-stack-eazyfill-redis`

Create a new small Portainer stack on Node A, for example
`eazyfill-node-a-worker-access`, using:

- compose file: `docker-compose.node-a-worker-access.yml`
- env file template: `.env.node-a-worker-access.example`

Bind these ports only to a private/VPN IP:

```env
POSTGRES_WORKER_BIND=10.99.0.1
POSTGRES_WORKER_PORT=15432
REDIS_WORKER_BIND=10.99.0.1
REDIS_WORKER_PORT=16379
```

Do not use `0.0.0.0` unless the host firewall only permits Node B.

## Node B: Worker Stack

Create a Portainer stack on Node B, for example `eazyfill-node-b-workers`, using:

- compose file: `docker-compose.node-b-workers.yml`
- env file template: `.env.node-b-workers.example`

Set these to Node A's private/VPN IP:

```env
NODE_A_POSTGRES_HOST=10.99.0.1
NODE_A_POSTGRES_PORT=15432
NODE_A_REDIS_HOST=10.99.0.1
NODE_A_REDIS_PORT=16379
```

Copy these secret values from Node A:

```env
POSTGRES_DB=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...
REDIS_PASSWORD=...
REDIS_PREFIX=...
AUTH_HASH_SALT=...
ADMIN_TOKEN=...
ADMIN_USERNAME=...
ADMIN_PASSWORD=...
```

## Model Files

Node B workers run ONNX inference locally. Before starting Node B workers, copy
Node A model files into:

```text
${NODE_B_CONFIG_PATH}/data/models/
```

At minimum, this file should exist:

```text
${NODE_B_CONFIG_PATH}/data/models/model.onnx
```

If admin model mappings point to other model filenames, copy those files too.

## Preflight From Node B

Check Redis:

```bash
docker run --rm redis:7-alpine \
  redis-cli -h 10.99.0.1 -p 16379 -a "$REDIS_PASSWORD" ping
```

Expected:

```text
PONG
```

Check Postgres:

```bash
docker run --rm postgres:16-alpine \
  pg_isready -h 10.99.0.1 -p 15432 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

Expected:

```text
accepting connections
```

## Tuning

Start with:

```env
SOLVER_WORKER_CONCURRENCY=2
```

Increase only if Node B has CPU and memory headroom. If CAPTCHA requests time
out, check Node B worker logs first, then verify Redis/Postgres connectivity and
that the ONNX model file exists.

# Load balancing and scaling LenDen Saathi

This folder runs **HAProxy** (free, open source) in front of any number of identical copies of the app, with **Redis** holding
the things that must be shared between copies (rate limits, OTP cool-downs, sessions). It is the "scale sideways" part of
the plan. Read the honest limits at the end before promising anything to anyone.

```
visitors ──HTTPS──> Cloudflare (free, optional) ──HTTP──> HAProxy ──> app copy 1 ┐
                                                              │       app copy 2 ├──> Redis (shared limits, sessions)
                                                              │       app copy N ┘──> PostgreSQL (pooled endpoint)
                                                              └── status page 127.0.0.1:8404/stats
```

## What was changed in the application (all optional, nothing changes until you set the variables)

| Setting | Default | What it does |
|---|---|---|
| `REDIS_URL` | empty | Rate limits, OTP cool-downs and cached lookups go to ONE shared Redis instead of living inside each process. Without it, 4 copies would give every visitor 4x the allowed attempts, and a blocked address would only be blocked on one copy. Sessions are also served from Redis (they stay stored in the database). |
| `TRUSTED_PROXY_COUNT` | `0` | How many proxies you control in front of the app. At `1` or more the visitor's address is taken from the trusted end of `X-Forwarded-For`, so a visitor can no longer forge the header to reset their rate limit. `0` keeps the old behaviour (the live Render site is unchanged). |
| `DB_POOLED` | empty | Set to `1` when a transaction pooler such as PgBouncer sits in front of the database: connections are then not reused. (Neon's `-pooler` host is detected automatically.) |

The rate limiter now **lets a request through (and logs a warning) if Redis is briefly unreachable**, so a cache hiccup cannot lock everybody out.
The image (`backend/Dockerfile`) was also rebuilt: static files are collected at build time, it runs as a non-root user, has a
health check, takes its size from `WEB_CONCURRENCY` / `GUNICORN_THREADS`, and `.dockerignore` keeps every `.env` file out of it.

## Run it

```bash
cd deploy/loadbalancer
cp .env.example .env                 # set DJANGO_SECRET_KEY and DATABASE_URL (use the database's POOLED endpoint)
docker compose up -d --build --scale app=4
# site:   http://localhost:8080        balancer status: http://127.0.0.1:8404/stats
docker compose up -d --no-recreate --scale app=8      # more capacity, no downtime
docker compose logs -f haproxy                         # see which copy answered which request
```

A self-contained trial with its own throw-away PostgreSQL (nothing touches Neon), good for load tests:

```bash
docker compose -f docker-compose.yml -f docker-compose.localdb.yml up -d --build --scale app=4
RATE_PER_10S=1000000 docker compose -f docker-compose.yml -f docker-compose.localdb.yml up -d --no-recreate    # lift the per-address limit for the test machine
docker run --rm -i --network lenden-saathi-lb_default -e BASE_URL=http://haproxy -e VUS=50 -v "%cd%/loadtest.js:/script.js" grafana/k6 run /script.js
```

Run the k6 test once with `--scale app=1` and once with `--scale app=4` and compare requests per second and the 95th percentile.

## What was verified (6 November 2026, Docker 26 on a Windows laptop with 8 logical CPUs)

The whole stack was built and run with `docker-compose.localdb.yml`: HAProxy 2.9, Redis 7, PostgreSQL 16, and the app image.

| Check | Result |
|---|---|
| HAProxy accepts `haproxy.cfg` | **Yes**, no warnings (see the note below on how to run this check) |
| Image builds, database setup job runs, site answers through HAProxy | **Yes**: home page 200 in 0.19 s, HAProxy shows the copy `UP` |
| `--scale app=4` is discovered with no config change | **Yes**: all 4 copies `UP` within about 15 s |
| Shared Redis is used by the copies | **Yes**: the shared plan and site-setting cache keys appear in Redis |
| Sign-in rate limit at the balancer, with a forged `X-Forwarded-For` on every request | **Yes**: the 21st POST in a minute got `429` whatever address the request claimed |
| A copy is killed while requests are flowing | **Yes**: 151 of 151 requests succeeded; HAProxy dropped the dead copy and kept serving |
| Load: 50 simulated visitors, 70 s, public pages (`loadtest.js`) | **1 copy: 148 requests/s, 95 % answered within 0.38 s, 0 failures out of 10,366.  4 copies: 277 requests/s, 95 % within 0.23 s, 0 failures out of 19,412.** |

Four copies gave **1.9 times** the throughput, not 4 times. That is this laptop, not the design: k6 (the load generator),
HAProxy, Redis, PostgreSQL and eight worker processes were all sharing the same 8 CPUs, and the database was local. On separate
machines the gain is close to linear until the database becomes the limit. What the test does show is that the design works:
no errors, lower latency with more copies, automatic discovery, and survival of a failed copy.

Not tested: HTTPS/Cloudflare in front, a real hosted database, sign-in and ledger pages under load (only public pages), and
more than 4 copies.

**Checking the HAProxy file yourself.** The official image's startup script turns `-c` into "start the server", so the plain
check never ends, and HAProxy also tries to look up the name `app` 20 times, which is slow outside Docker's network. This works:

```bash
sed 's/init-addr libc,none/init-addr none/' haproxy.cfg > /tmp/haproxy-check.cfg      # skip the name lookups, for the check only
docker run --rm --network none --entrypoint haproxy -v /tmp/haproxy-check.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro     -e RATE_PER_10S=300 -e AUTH_POSTS_PER_MIN=20 -e BEHIND_CLOUDFLARE=0 haproxy:2.9-alpine -c -f /usr/local/etc/haproxy/haproxy.cfg
echo $?      # 0 means valid
```

## Real numbers: what one app process can do

Measured on a developer PC (8 logical CPUs), 1,500 requests to the public pages in a realistic mix, one process, **in-process
with no network or TLS**, local PostgreSQL:

| | |
|---|---|
| Throughput | **about 217 requests per second per process (one CPU core)** |
| Latency | mean 4.6 ms, 95th percentile 6.6 ms, 99th 7.6 ms |

A real server will do less (network, TLS, a database over the internet, heavier pages such as the ledger, password hashing on
sign-in). Inside Docker with everything sharing one laptop, one app copy (2 workers) served **148 requests per second**, about 75 per core.
For planning use **75 to 150 requests per second per CPU core** for ordinary pages, and much less for sign-ins.

## What "10 million users" actually needs

"10 million users" is registered accounts. What matters is how many act at the same moment. Assumptions (change them):

| Assumption | Value |
|---|---|
| Registered users | 10,000,000 |
| Active on a day | 10 % = 1,000,000 |
| Share of a day's traffic in the busiest hour | 15 % = 150,000 visits |
| Requests per visit | 25 |
| Busiest hour | 3.75 million requests = about 1,040 per second on average, **about 3,000 per second at the peak** |

At 75 to 150 requests per second per core that is **20 to 40 CPU cores of app servers**, about 10 to 20 copies with 2 cores each,
behind the load balancer. The balancer itself is not the problem: one HAProxy instance handles tens of thousands of requests per second.

The parts that this folder does **not** solve, and where the real cost is:

1. **The database.** 3,000 requests a second means roughly 10,000 queries a second, which needs a properly sized managed PostgreSQL
   (and a read replica for reports), plus a pooler. The free Neon plan has a 0.5 GB storage limit and small compute; ten million
   users' ledgers run to hundreds of gigabytes and hundreds of millions of rows (plan partitioning or archiving of old entries).
2. **Email and SMS inside a request.** Sending an OTP email can take seconds; at scale this must move to a background queue
   (Celery or similar) so web threads are never blocked.
3. **Uploads and downloads of documents** go through the app to Google Drive and are limited by Google's API quotas. At scale store
   files in object storage (S3 compatible) and give users signed links.
4. **Static files and public pages** should sit behind a CDN (Cloudflare's free plan is enough to start): most visitors then never reach the app.
5. **Sign-in cost.** Argon2 password hashing is deliberately slow (CPU). Keep sign-ins on their own capacity planning.
6. **The two ledgers** (website and app) should be unified first (see `docs/UNIFY_LEDGER_PLAN.md`) so there is one set of data to scale.

## What is free and what is not

| Part | Free? |
|---|---|
| HAProxy, Redis, PgBouncer, k6, Docker | Yes, open source |
| Cloudflare CDN and TLS in front | Yes (free plan) |
| A machine to run them | **Oracle Cloud "Always Free" ARM virtual machines** (up to 4 cores and 24 GB in total) can run the balancer, Redis and 2 to 3 app copies. You must create that account yourself. |
| Render free web services | They cannot be scaled sideways at all: one instance, it sleeps when idle, and Render already provides its own balancer. A second instance needs a paid plan (`numInstances` 2 or more). |
| The database for a large user base | **No.** Budget for a managed PostgreSQL. |
| Serving 10 million users end to end | **No.** Not on free infrastructure. This work makes the application *able* to run as many copies; the machines and database for that scale are paid. |

## A sensible path

| Stage | Users | What to run |
|---|---|---|
| Now | up to tens of thousands | Render free or Starter, one instance, as today. Optionally the keep-alive ping. |
| 1 | up to ~100,000 | Render Starter or Standard, 2 instances, a free Redis (Render Key Value or Upstash) in `REDIS_URL`, Neon paid plan, Cloudflare in front. |
| 2 | up to ~1 million | This Compose stack on 1 to 2 VMs (or Render with 3 to 5 instances), pooled database endpoint, background queue for email, object storage for documents. |
| 3 | 10 million registered | 10 to 20 app copies across several VMs or a Kubernetes cluster (the same image runs there; HAProxy or the cloud's balancer in front), managed PostgreSQL with a replica, Redis cluster, CDN, background workers, monitoring and alerting. |

## Using this on Render instead

Render already puts its own load balancer in front of every web service, so you do not need HAProxy there. To run more than one
instance you must pay for a plan above free and set the service's instance count. Then also set `REDIS_URL` so the instances
share rate limits. Leave `TRUSTED_PROXY_COUNT` at `0` until the number of proxies in front of the service has been measured
(Render sits behind its own proxies), otherwise client addresses would be read wrongly.

## Cloudflare in front of HAProxy

Point the domain at Cloudflare, set `BEHIND_CLOUDFLARE=1` in `.env`, and let **only Cloudflare's published address ranges** reach
the machine's port 80/443 (a firewall rule). HAProxy then uses Cloudflare's `CF-Connecting-IP` for the visitor's address. Never set
`BEHIND_CLOUDFLARE=1` while the machine is reachable from anywhere else: anyone could then send that header themselves.

# Garena Service

Thin FastAPI microservice that executes Garena Shell direct top-ups on `termgame.com` for [erosterz](https://github.com/thomasblack168/erosterz).

erosterz submits orders outbound (Dynasty pattern); this service owns the termgame HTTP calls, OTP, quantity loops, and optional status callbacks.

**Integration reference (erosterz):** [docs/garena-direct-integration.md](https://github.com/thomasblack168/erosterz/blob/main/docs/garena-direct-integration.md) (in the erosterz repo)

**Legacy workers (archived):** [Garena-erosterz](https://github.com/thomasblack168/Garena-erosterz) — `_archive/` only; do not run.

---

## Requirements

- Python 3.11+
- Outbound HTTPS to `termgame.com`
- Valid Garena Shell merchant session (cookies + headers + TOTP secret) — sent **per order** by erosterz, not stored on the Droplet in v1

---

## Setup

```bash
git clone <this-repo-url>
cd garena-service
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `GARENA_SERVICE_API_KEY` | yes | Bearer token; must match erosterz admin **Garena API Key** |
| `EROSTERZ_WEBHOOK_BASE` | no | e.g. `https://erosterz.com` — base URL for optional terminal-state callbacks |

---

## Run locally

```bash
export GARENA_SERVICE_API_KEY=dev-key
uvicorn src.main:app --host 0.0.0.0 --port 8099 --reload
```

Health check:

```bash
curl -s -H "Authorization: Bearer dev-key" http://localhost:8099/v1/health | jq
```

Create order (example — use real session from admin):

```bash
curl -s -X POST http://localhost:8099/v1/orders \
  -H "Authorization: Bearer dev-key" \
  -H "Content-Type: application/json" \
  -d '{
    "partnerReferenceId": "ORD-TEST-cm123",
    "gameKey": "rov",
    "playerId": "1234567890",
    "itemId": "4587",
    "quantity": 1,
    "session": {
      "cookies": { "mspid2": "…" },
      "headers": { "User-Agent": "…", "Referer": "https://termgame.com/" },
      "otpSecret": "BASE32SECRET"
    }
  }'
```

Poll job status:

```bash
curl -s -H "Authorization: Bearer dev-key" http://localhost:8099/v1/orders/{ref} | jq
```

---

## API (v1)

Base path: `/v1`  
Auth: `Authorization: Bearer {GARENA_SERVICE_API_KEY}`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/health` | Liveness (no session probe) |
| `POST` | `/v1/health` | Optional session probe (`session` in body) |
| `POST` | `/v1/orders` | Enqueue top-up job → `202` |
| `GET` | `/v1/orders/{ref}` | Job snapshot + progress |

See erosterz [garena-direct-integration.md §6](https://github.com/thomasblack168/erosterz/blob/main/docs/garena-direct-integration.md) for request/response schemas and status values.

**Idempotency:** duplicate `partnerReferenceId` → `409` with existing `ref`.

---

## Games (`games.yaml`)

| `gameKey` | Legacy `game_id` | `app_id` | Notes |
|-----------|------------------|----------|-------|
| `rov` | 180 | 100055 | Arena of Valor TH |
| `freefire` | 179 | 100067 | |
| `deltaforce` | 1713 | 100151 | |
| `hai` | 1712 | 100153 | |
| `undraw` | 1714 | 100105 | pay/init uses 100105 |

Add new games here; erosterz `Product.garenaGameKey` must match.

---

## Data

Jobs persist in SQLite at `data/jobs.db` (created on first order). v1 is single-process; use a shared store before horizontal scaling.

---

## Tests

```bash
pytest tests/ -v
```

Maps termgame error strings → service status (`session_expired`, `invalid_player`, `pack_limit`, etc.).

---

## Deploy (DigitalOcean Droplet)

1. Install Python 3.11+, clone this repo, `pip install -e .`
2. Set `GARENA_SERVICE_API_KEY` and optional `EROSTERZ_WEBHOOK_BASE` in systemd env or `.env`.
3. Run behind nginx with TLS; **restrict ingress** to erosterz egress IP only.
4. Point erosterz admin **Garena Direct → Service URL** at `https://your-droplet` (no trailing `/v1` — erosterz client appends it).

**Security:** Rotate every secret that ever appeared in legacy `_archive/` scripts before production. Never log cookies, OTP secret, or full termgame responses.

---

## Layout

```
games.yaml           # Game registry (app_id, channel_id, …)
src/
  main.py            # FastAPI routes
  worker.py          # Background job loop + optional webhook
  store.py           # SQLite job store
  termgame/
    topup.py         # pay/init + error mapping
    otp.py           # TOTP helper
tests/
  test_topup_errors.py
```

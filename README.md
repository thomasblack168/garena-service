# Garena Service

Thin FastAPI microservice that executes Garena Shell direct top-ups on `termgame.com` for [erosterz](https://github.com/thomasblack168/erosterz).

erosterz submits orders outbound (Dynasty pattern); this service owns the termgame HTTP calls, OTP, quantity loops, and optional status callbacks.

## Documentation

| Doc | Description |
|-----|-------------|
| **[docs/README.md](./docs/README.md)** | Documentation index |
| [Integration](./docs/integration.md) | erosterz ↔ service API, env matrix, webhook, status mapping |
| [Deploy](./docs/deploy.md) | DigitalOcean Droplet, systemd, nginx, TLS, go-live |
| [Operations guide (คู่มือ)](./docs/guide.md) | Session export, products, troubleshooting, เพิ่มเกม |

**erosterz reference:** [garena-direct-integration.md](https://github.com/thomasblack168/erosterz/blob/main/docs/garena-direct-integration.md)

**Legacy archive:** [Garena-erosterz](https://github.com/thomasblack168/Garena-erosterz) — `_archive/` only

---

## Quick start (local)

```bash
git clone https://github.com/thomasblack168/garena-service.git
cd garena-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # edit keys
export $(grep -v '^#' .env | xargs)
uvicorn src.main:app --host 0.0.0.0 --port 8099 --reload
```

```bash
curl -s -H "Authorization: Bearer $GARENA_SERVICE_API_KEY" http://localhost:8099/v1/health | jq
```

---

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `GARENA_SERVICE_API_KEY` | yes | Bearer token — must match erosterz admin **Garena API Key** |
| `EROSTERZ_WEBHOOK_BASE` | for callbacks | erosterz public origin, e.g. `https://erosterz.com` |
| `GARENA_WEBHOOK_SECRET` | for callbacks | Must match erosterz admin **Webhook secret** |

See [docs/deploy.md](./docs/deploy.md) for production setup.

---

## API summary

Base: `/v1` · Auth: `Authorization: Bearer {key}`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/health` | Liveness |
| `POST` | `/v1/health` | Optional session probe |
| `POST` | `/v1/orders` | Enqueue top-up → `202` |
| `GET` | `/v1/orders/{ref}` | Job status + progress |

Full contract: [docs/integration.md](./docs/integration.md)

---

## Games

Registry in [`games.yaml`](./games.yaml) — `rov`, `freefire`, `deltaforce`, `hai`, `undraw`.  
erosterz `Product.garenaGameKey` must match `gameKey`.

---

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Layout

```
games.yaml
src/
  main.py            # FastAPI routes
  worker.py          # Background loop + webhook
  store.py           # SQLite job store
  termgame/          # pay/init + OTP
tests/
docs/                # Deploy, integration, คู่มือ
```

Jobs persist in `data/jobs.db` (gitignored). v1 = single instance only.

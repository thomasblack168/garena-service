# Integration — erosterz ↔ Garena Service

## Architecture

```
┌─────────────┐     POST /v1/orders      ┌──────────────────┐     pay/init     ┌─────────────┐
│   erosterz  │ ───────────────────────► │  garena-service  │ ─────────────► │ termgame.com│
│  (Next.js)  │     session in body      │    (FastAPI)     │   + TOTP       │  (Garena)   │
└─────────────┘                          └──────────────────┘                └─────────────┘
       ▲                                          │
       │  GET /v1/orders/{ref}  (cron poll)      │
       │  POST /api/webhooks/garena (optional)    │
       └──────────────────────────────────────────┘
```

- **Push model:** erosterz ส่งออเดอร์หลังชำระเงิน (เหมือน Dynasty) — ไม่มี poll จาก service ไปหา erosterz แบบ legacy Laravel
- **Session v1:** cookies, headers, OTP เก็บใน erosterz `IntegrationConfig` (เข้ารหัส) ส่งมากับทุก `POST /v1/orders` — **ไม่เก็บบน Droplet**
- **Reseller Garena Shells** (WePay/MooGold/Lapak card) ไม่ผ่าน service นี้ — เฉพาะ `FulfillmentSupplier.GARENA`

---

## Repositories

| Repo | Role |
|------|------|
| [erosterz](https://github.com/thomasblack168/erosterz) | Storefront, admin, `submit-garena`, poll cron, webhook receiver |
| **garena-service** (this repo) | termgame HTTP, job queue, optional callback |
| [Garena-erosterz](https://github.com/thomasblack168/Garena-erosterz) | Legacy `_archive/` only — do not run |

---

## Environment matrix

### garena-service (Droplet)

| Variable | Required | Must match |
|----------|----------|------------|
| `GARENA_SERVICE_API_KEY` | yes | erosterz admin → **Garena API Key** |
| `EROSTERZ_WEBHOOK_BASE` | for push status | Public origin, e.g. `https://erosterz.com` (no trailing slash) |
| `GARENA_WEBHOOK_SECRET` | for push status | erosterz admin → **Garena Webhook secret** |

If `EROSTERZ_WEBHOOK_BASE` or `GARENA_WEBHOOK_SECRET` is unset, the service still works — erosterz relies on cron poll only.

### erosterz (IntegrationConfig + bootstrap env)

Configure at **Admin → Settings → Integrations → Garena Direct**:

| Admin field | Prisma | Purpose |
|-------------|--------|---------|
| Service URL | `garenaBaseUrl` | e.g. `https://garena.example.com` — **ไม่ใส่** `/v1` ท้าย URL |
| API Key | `garenaApiKeyEnc` | Bearer token → `GARENA_SERVICE_API_KEY` |
| Webhook secret | `garenaWebhookSecretEnc` | Verify `POST /api/webhooks/garena` |
| Session cookies | `garenaSessionCookiesEnc` | JSON object → `session.cookies` |
| Session headers | `garenaSessionHeadersEnc` | JSON object → `session.headers` |
| OTP secret | `garenaOtpSecretEnc` | Base32 TOTP → `session.otpSecret` |

Bootstrap env on erosterz (not rotatable via admin): `DATABASE_URL`, `AUTH_SECRET`, `CONFIG_ENCRYPTION_KEY`, `CRON_SECRET`.

Optional env fallback on erosterz: `GARENA_BASE_URL`, `GARENA_API_KEY`.

---

## HTTP API (v1)

Base: `{garenaBaseUrl}/v1`  
Auth: `Authorization: Bearer {apiKey}`

### `POST /v1/orders` → `202`

```json
{
  "partnerReferenceId": "ORD-20260801-ABC-cm123xyz",
  "gameKey": "rov",
  "playerId": "1234567890",
  "itemId": "4587",
  "quantity": 1,
  "session": {
    "cookies": { "mspid2": "…" },
    "headers": { "User-Agent": "…" },
    "otpSecret": "BASE32SECRET"
  }
}
```

| Field | Source on erosterz |
|-------|-------------------|
| `partnerReferenceId` | `supplierPartnerReferenceId(orderNumber, orderItemId)` |
| `gameKey` | `Product.garenaGameKey` |
| `playerId` | `OrderItem.playerUserId` |
| `itemId` | `ProductPackage.packCode` (termgame `item_id`) |
| `quantity` | `OrderItem.quantity` (max 20) |
| `session` | Parsed from IntegrationConfig on submit |

**Response `202`:**

```json
{
  "ok": true,
  "ref": "garena-a1b2c3d4e5f6",
  "status": "accepted",
  "partnerReferenceId": "ORD-20260801-ABC-cm123xyz"
}
```

**`409`:** duplicate `partnerReferenceId` — erosterz treats as already submitted (idempotent).

**`400`:** unknown `gameKey` — add game to `games.yaml` and redeploy service.

### `GET /v1/orders/{ref}`

```json
{
  "ok": true,
  "ref": "garena-a1b2c3d4e5f6",
  "partnerReferenceId": "ORD-20260801-ABC-cm123xyz",
  "status": "delivered",
  "progress": { "completedUnits": 1, "totalUnits": 1 },
  "displayId": "termgame-display-id",
  "failureReason": null
}
```

### Job statuses (service)

| Status | Meaning |
|--------|---------|
| `accepted` | Queued, worker not started |
| `processing` | termgame call in progress |
| `delivered` | All units succeeded |
| `failed` | Stopped with `failureReason` |

### `failureReason` values (termgame mapping)

| Reason | termgame signal | erosterz line status |
|--------|-----------------|----------------------|
| `session_expired` | `error_require_login` | `processing` (hold — fix session) |
| `invalid_player` | `invalid_id` / `error_params` | `supplier_failed` |
| `pack_limit` | `error_limited_package_exceed_limit` | `supplier_failed` |
| other | upstream error | `submit_failed` or `supplier_failed` |

### Health

| Method | Path | Use |
|--------|------|-----|
| `GET` | `/v1/health` | Liveness — `{ ok, sessionProvided: false, shellBalance: null }` |
| `POST` | `/v1/health` | Optional body `{ "session": { … } }` — admin test connection |

---

## Webhook (service → erosterz)

When job reaches terminal state (`delivered` or `failed`), worker may POST:

```
POST {EROSTERZ_WEBHOOK_BASE}/api/webhooks/garena
Header: x-garena-webhook-secret: {GARENA_WEBHOOK_SECRET}
Content-Type: application/json
```

Body (same shape as `GET /v1/orders/{ref}`):

```json
{
  "ok": true,
  "ref": "garena-a1b2c3d4e5f6",
  "partnerReferenceId": "ORD-20260801-ABC-cm123xyz",
  "status": "delivered",
  "progress": { "completedUnits": 1, "totalUnits": 1 },
  "displayId": "...",
  "failureReason": null
}
```

erosterz also accepts secret via query `?secret=` (copy URL from admin integrations panel).

**Poll fallback:** cron `GET /api/cron/garena-order-poll` every 15 min (DO `cron-15m` batch) if webhook missed.

---

## Product mapping

### erosterz `Product`

| Field | Example |
|-------|---------|
| `fulfillmentSupplier` | `GARENA` |
| `garenaGameKey` | `rov` |
| `requiresPlayerId` / `playerInputConfig` | UID → `playerUserId` |

### erosterz `ProductPackage`

| Field | Example |
|-------|---------|
| `packCode` | `"4587"` (termgame `item_id` as string) |

### Service `games.yaml`

| `gameKey` | `app_id` | `channel_id` | `packed_role_id` |
|-----------|----------|--------------|------------------|
| `rov` | 100055 | 207070 | 786432 |
| `freefire` | 100067 | 207070 | — |
| `deltaforce` | 100151 | 207070 | — |
| `hai` | 100153 | 207070 | — |
| `undraw` | 100105 | 207070 | — |

`garenaGameKey` on product **must** match `gameKey` here.

---

## End-to-end sequence

1. Customer pays on erosterz.
2. `submitGarenaOrder` → `POST /v1/orders` with session from DB.
3. Service enqueues job (`accepted`), returns `ref`.
4. erosterz sets line `processing`, stores `supplierRef = ref`.
5. Worker loops `quantity` × `termgame.com/api/shop/pay/init` (3s gap between units).
6. Terminal state → optional webhook to erosterz **or** cron poll picks it up.
7. erosterz maps status → `delivered` / `supplier_failed` / hold on `session_expired`.

---

## erosterz code references

| Area | Path |
|------|------|
| HTTP client | `src/lib/garena.ts` |
| Submit | `src/domain/orders/submit-garena.ts` |
| Poll | `src/domain/orders/poll-garena-orders.ts` |
| Webhook | `src/app/api/webhooks/garena/route.ts` |
| Status map | `src/lib/garena-order-status.ts` |
| Cron | `src/app/api/cron/garena-order-poll/route.ts` |

---

## Security

- HTTPS only between erosterz and service.
- Firewall: allow **only** erosterz egress IP(s) to service port 443.
- Never log `session`, cookies, or `otpSecret`.
- Rotate secrets from legacy `Garena-erosterz/_archive/` before production.
- Webhook: timing-safe secret compare on erosterz side.

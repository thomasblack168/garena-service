# Deploy — DigitalOcean Droplet

คู่มือ deploy **garena-service** บน VPS (แนะนำ DigitalOcean Droplet) สำหรับ production คู่กับ erosterz บน DO App Platform

---

## Prerequisites

| Item | Notes |
|------|-------|
| Droplet | Ubuntu 22.04/24.04, 1 GB RAM minimum |
| Domain (optional) | `garena-api.example.com` → A record to Droplet |
| erosterz egress IP | DO App Platform outbound IP — ใส่ใน firewall |
| API key | `openssl rand -base64 32` → ใช้ทั้ง service และ erosterz admin |
| Webhook secret | `openssl rand -base64 32` → erosterz admin + `GARENA_WEBHOOK_SECRET` |

---

## 1. Server bootstrap

```bash
ssh root@your-droplet-ip

apt update && apt upgrade -y
apt install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx ufw git

adduser --disabled-password --gecos "" garena
usermod -aG sudo garena
```

---

## 2. Install application

```bash
sudo -u garena -i
cd ~
git clone https://github.com/thomasblack168/garena-service.git
cd garena-service
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
mkdir -p data
exit
```

---

## 3. Environment file

```bash
sudo mkdir -p /etc/garena-service
sudo nano /etc/garena-service/env
```

```bash
GARENA_SERVICE_API_KEY=your-generated-api-key
EROSTERZ_WEBHOOK_BASE=https://erosterz.com
GARENA_WEBHOOK_SECRET=your-generated-webhook-secret
```

```bash
sudo chmod 600 /etc/garena-service/env
sudo chown garena:garena /etc/garena-service/env
```

| Variable | Description |
|----------|-------------|
| `GARENA_SERVICE_API_KEY` | Bearer token — **ต้องตรง** erosterz admin API Key |
| `EROSTERZ_WEBHOOK_BASE` | Public erosterz origin (no trailing `/`) |
| `GARENA_WEBHOOK_SECRET` | **ต้องตรง** erosterz admin Webhook secret |

---

## 4. systemd unit

```bash
sudo nano /etc/systemd/system/garena-service.service
```

```ini
[Unit]
Description=Garena Service (termgame top-up)
After=network.target

[Service]
Type=simple
User=garena
Group=garena
WorkingDirectory=/home/garena/garena-service
EnvironmentFile=/etc/garena-service/env
ExecStart=/home/garena/garena-service/.venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8099
Restart=always
RestartSec=5

# Hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable garena-service
sudo systemctl start garena-service
sudo systemctl status garena-service
```

Logs:

```bash
journalctl -u garena-service -f
```

---

## 5. nginx + TLS

```bash
sudo nano /etc/nginx/sites-available/garena-service
```

```nginx
server {
    listen 80;
    server_name garena-api.example.com;

    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/garena-service /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d garena-api.example.com
```

---

## 6. Firewall

```bash
# SSH — adjust port if non-default
sudo ufw allow OpenSSH

# HTTPS — restrict to erosterz App Platform egress IP only
sudo ufw allow from EROSTERZ_EGRESS_IP to any port 443 proto tcp

sudo ufw enable
sudo ufw status
```

**Important:** อย่าเปิด port 8099 สู่ public — bind ที่ `127.0.0.1` แล้วให้ nginx terminate TLS เท่านั้น

หา erosterz egress IP: DO App Platform → app → Settings → **Dedicated Egress IP** (ถ้ามี) หรือใช้ static outbound ตามที่ทีม infra กำหนด

---

## 7. Verify deployment

```bash
curl -s -H "Authorization: Bearer YOUR_API_KEY" \
  https://garena-api.example.com/v1/health | jq
```

Expected:

```json
{ "ok": true, "sessionProvided": false, "shellBalance": null }
```

From erosterz admin (after saving same API key + base URL `https://garena-api.example.com`):

- **Test connection** on Garena Direct tab

---

## 8. Configure erosterz

1. Admin → Settings → Integrations → **Garena Direct**
2. **Service URL:** `https://garena-api.example.com`
3. **API Key:** same as `GARENA_SERVICE_API_KEY`
4. **Webhook secret:** same as `GARENA_WEBHOOK_SECRET`
5. Paste session cookies/headers + OTP secret
6. Save → Test connection

Cron poll is already in erosterz `.do/app.yaml` (`garena-order-poll` in `cron-15m`).

---

## 9. Go-live checklist

- [ ] API key rotated (not dev key)
- [ ] Legacy `_archive/` secrets rotated
- [ ] Firewall limits 443 to erosterz IP only
- [ ] TLS valid (certbot auto-renew)
- [ ] systemd `Restart=always` verified after kill test
- [ ] erosterz admin test connection OK
- [ ] Staging order: submit → delivered (webhook or poll)
- [ ] `session_expired` path tested (re-paste session + resubmit)
- [ ] SQLite backup plan for `data/jobs.db` (or accept re-poll from erosterz for in-flight jobs)
- [ ] Monitoring: `journalctl` alerts or health check ping

---

## 10. Updates (deploy new version)

```bash
sudo -u garena -i
cd ~/garena-service
git pull
source .venv/bin/activate
pip install -e .
exit

sudo systemctl restart garena-service
```

If `games.yaml` changed, restart is required.

---

## 11. Local / staging (without Droplet)

```bash
export GARENA_SERVICE_API_KEY=dev-key
export EROSTERZ_WEBHOOK_BASE=http://localhost:3333
export GARENA_WEBHOOK_SECRET=dev-webhook-secret
uvicorn src.main:app --host 0.0.0.0 --port 8099 --reload
```

Point erosterz `garenaBaseUrl` to `http://host.docker.internal:8099` or tunnel (ngrok) if erosterz runs in Docker.

---

## 12. Limitations (v1)

| Topic | v1 behavior |
|-------|-------------|
| Job store | SQLite at `data/jobs.db` — single instance only |
| Session | Not persisted on service — sent per order from erosterz |
| Horizontal scale | Not supported — need shared job store first |
| Shell balance | Health endpoint returns `shellBalance: null` (not implemented) |

---

## Troubleshooting deploy

| Symptom | Check |
|---------|-------|
| `503 Service API key not configured` | `EnvironmentFile` loaded? `GARENA_SERVICE_API_KEY` set? |
| erosterz `401` on submit | API key mismatch service vs admin |
| Webhook never arrives | Both `EROSTERZ_WEBHOOK_BASE` and `GARENA_WEBHOOK_SECRET` set? erosterz can reach URL? |
| `502` from nginx | `systemctl status garena-service`, port 8099 listening on 127.0.0.1 |
| Jobs stuck `accepted` | Worker loop in same process as uvicorn — check logs for exceptions |

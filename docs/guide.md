# คู่มือการใช้งาน (Operations Guide)

คู่มือ day-to-day สำหรับทีม ops / admin ที่ใช้ **garena-service** คู่กับ **erosterz**

---

## ภาพรวมหน้าที่

| ระบบ | ทำอะไร |
|------|--------|
| **erosterz** | รับออเดอร์ลูกค้า, เก็บ session/OTP, ส่งคำสั่งเติม, อัปเดตสถานะบรรทัดออเดอร์ |
| **garena-service** | เรียก termgame.com แทน erosterz, คิวงาน, loop จำนวนชิ้น, callback สถานะ |

ลูกค้า **ไม่เห็น** ชื่อ Garena Service — แสดงแค่ชื่อเกม/แพ็คบน storefront

---

## ขั้นตอนตั้งค่าครั้งแรก

### 1. Deploy service

ทำตาม [deploy.md](./deploy.md) จนได้ URL เช่น `https://garena-api.example.com`

### 2. ตั้งค่า erosterz Admin

ไปที่ **Admin → Settings → Integrations → แท็บ Garena Direct**

| ช่อง | ค่า |
|------|-----|
| Service URL | `https://garena-api.example.com` (ไม่มี `/v1` ท้าย) |
| API Key | ตรงกับ `GARENA_SERVICE_API_KEY` บน Droplet |
| Webhook secret | ตรงกับ `GARENA_WEBHOOK_SECRET` บน Droplet |
| Session cookies | JSON จาก browser (ดูด้านล่าง) |
| Session headers | JSON — อย่างน้อย `User-Agent` |
| OTP secret | Base32 จาก authenticator (เดิมใช้ใน HOTP.py) |

กด **Save** แล้ว **Test connection**

### 3. สร้างสินค้าทดสอบ

ใน erosterz admin (สินค้า Manual / GARENA):

| Field | ตัวอย่าง |
|-------|----------|
| `fulfillmentSupplier` | `GARENA` |
| `garenaGameKey` | `rov` |
| แพ็ค `packCode` | `4587` (termgame `item_id`) |
| ต้องใส่ UID | เปิด `requiresPlayerId` |

### 4. ทดสอบออเดอร์

1. สั่งซื้อแพ็คทดสอบ (UID จริง)
2. ชำระเงิน
3. ตรวจ admin order — บรรทัดควรเป็น `processing` → `delivered`
4. ดู `supplierRef` = `garena-xxxxxxxxxxxx`

---

## วิธี export Session จาก termgame.com

Session หมดอายุบ่อย — ต้อง login ใหม่แล้ว paste ใน admin

### Cookies

1. Login merchant ที่ [termgame.com](https://termgame.com) ใน Chrome
2. DevTools → Application → Cookies → `termgame.com`
3. Copy เป็น JSON object เช่น:

```json
{
  "mspid2": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

วางใน admin **Session cookies**

### Headers

อย่างน้อย:

```json
{
  "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ..."
}
```

Copy จาก DevTools → Network → request ใดก็ได้ไป termgame → Request Headers (ไม่ต้องใส่ `Cookie` — แยกใน cookies แล้ว)

### OTP

- Secret แบบ Base32 จาก Google Authenticator / แอป TOTP เดิม
- **อย่า** commit หรือแชร์ใน chat

---

## สถานะออเดอร์ — ควรทำอย่างไร

| สถานะบรรทัด (erosterz) | ความหมาย | การดำเนินการ |
|------------------------|----------|--------------|
| `processing` | กำลังเติม / รอ session | รอ หรือตรวจ service logs |
| `delivered` | สำเร็จ | ไม่ต้องทำ |
| `supplier_failed` | UID ผิด / แพ็ค limit | คืนเงินลูกค้าตามนโยบาย |
| `submit_failed` | ข้อผิดพลาด upstream อื่น | ตรวจ log, retry manual |
| `processing` + session หมด | `failureReason: session_expired` | อัปเดต session ใน admin → resubmit จาก order detail |

---

## Session หมดอายุ (`session_expired`)

1. Login termgame.com ใหม่
2. Export cookies/headers ใหม่
3. Admin → Integrations → Garena Direct → Save
4. ไป order ที่ค้าง → **Resubmit** / advance fulfillment (ไม่ต้องให้ลูกค้าจ่ายใหม่)

แนะนำเปิด Telegram alert ใน erosterz IntegrationConfig เมื่อเติมล้มเหลว

---

## จำนวน (quantity > 1)

- erosterz ส่ง `quantity` ครั้งเดียว
- service loop เรียก termgame ทีละหน่วย — ห่าง **3 วินาที** ระหว่างหน่วย
- สำเร็จเมื่อ `completedUnits === totalUnits`
- ถ้าหน่วยที่ 2 ล้ม — บรรทัด `failed`, `completedUnits` แสดงความคืบหน้า

---

## เพิ่มเกมใหม่

### 1. หา `app_id` / `item_id`

จาก termgame merchant UI หรือ legacy `_archive/` config

### 2. แก้ `games.yaml` ใน repo นี้

```yaml
newgame:
  legacy_game_id: 9999
  app_id: 100999
  channel_id: 207070
  packed_role_id: 786432   # ถ้าเกมต้องการ — ลบ key ถ้าไม่ใช้
```

### 3. Deploy / restart service

```bash
sudo systemctl restart garena-service
```

### 4. สร้าง product บน erosterz

- `garenaGameKey` = `newgame` (ตรง key ใน yaml)
- แต่ละแพ็ค `packCode` = `item_id`

---

## คำสั่งที่ใช้บ่อย

### ตรวจ health

```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  https://garena-api.example.com/v1/health | jq
```

### ดูสถานะ job

```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  https://garena-api.example.com/v1/orders/garena-xxxxxxxxxxxx | jq
```

### ดู log บน server

```bash
journalctl -u garena-service -n 100 --no-pager
```

### รัน test ใน repo

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

### Poll จาก erosterz (manual)

```bash
curl -fsS -H "Authorization: Bearer $CRON_SECRET" \
  https://erosterz.com/api/cron/garena-order-poll
```

---

## ความแตกต่าง: เติมตรง vs Garena Shells การ์ด

| | Garena Direct (`GARENA`) | Reseller (WePay/MooGold/…) |
|--|---------------------------|----------------------------|
| ช่องทาง | termgame Shell โดยตรง | API ตัวแทนจำหน่าย |
| Service | garena-service | ไม่ใช้ repo นี้ |
| สินค้า | `fulfillmentSupplier=GARENA` | supplier อื่น |

อย่าสับสนชื่อ "Garena Shells" บน storefront — ดูที่ supplier ใน admin

---

## Checklist รายวัน / รายสัปดาห์

**รายวัน**

- [ ] ออเดอร์ `processing` ค้าง > 30 นาที — ตรวจ session / service up
- [ ] `journalctl` ไม่มี error loop

**รายสัปดาห์**

- [ ] Session ยังใช้ได้ (ทดสอบ connection ใน admin)
- [ ] TLS cert ยัง valid (`certbot certificates`)
- [ ] Backup `data/jobs.db` (ถ้าต้องการ audit)

---

## ห้ามทำ

- อย่า commit session / OTP / API key ลง git
- อย่ารัน script ใน `Garena-erosterz/_archive/` — secrets รั่วแล้ว
- อย่าเปิด port 8099 สู่ internet โดยไม่มี firewall
- อย่า log request body ที่มี `session` ใน production

---

## เอกสารที่เกี่ยวข้อง

- [Integration](./integration.md) — API + mapping ฝั่งเทคนิค
- [Deploy](./deploy.md) — systemd, nginx, firewall
- [erosterz garena-direct-integration.md](https://github.com/thomasblack168/erosterz/blob/main/docs/garena-direct-integration.md)

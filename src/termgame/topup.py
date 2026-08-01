from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TopupResult:
    ok: bool
    display_id: str | None
    failure_reason: str | None
    raw: dict[str, Any] | None = None


def map_termgame_response(body: dict[str, Any]) -> TopupResult:
    if body.get("error") == "error_require_login":
        return TopupResult(ok=False, display_id=None, failure_reason="session_expired", raw=body)
    if body.get("error") == "invalid_id" or body.get("result") == "error_params":
        return TopupResult(ok=False, display_id=None, failure_reason="invalid_player", raw=body)
    if body.get("result") == "error_limited_package_exceed_limit":
        return TopupResult(ok=False, display_id=None, failure_reason="pack_limit", raw=body)
    display_id = body.get("display_id")
    if body.get("result") and display_id:
        return TopupResult(ok=True, display_id=str(display_id), failure_reason=None, raw=body)
    error = body.get("error") or body.get("result") or "upstream_error"
    return TopupResult(ok=False, display_id=None, failure_reason=str(error), raw=body)


async def execute_topup_unit(
    *,
    app_id: int,
    channel_id: int,
    packed_role_id: int | None,
    item_id: str,
    player_id: str,
    cookies: dict[str, str],
    headers: dict[str, str],
    otp_secret: str,
    session_id: str | None = None,
) -> TopupResult:
    import httpx

    from src.termgame.otp import generate_otp

    otp = generate_otp(otp_secret)
    mspid2 = session_id or cookies.get("mspid2", "")

    json_data: dict[str, Any] = {
        "app_id": app_id,
        "channel_id": channel_id,
        "service": "pc",
        "item_id": int(item_id),
        "channel_data": {},
        "player_id": str(player_id),
        "revamp_experiment": {
            "session_id": str(mspid2),
            "group": "treatment2",
            "service_version": "mshop_frontend_20240816",
            "source": "pc",
            "domain": "termgame.com",
        },
    }
    if packed_role_id is not None:
        json_data["packed_role_id"] = packed_role_id

    req_headers = dict(headers)
    req_headers["Referer"] = (
        f"https://termgame.com/buy?app={app_id}&channel={channel_id}&item={item_id}"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://termgame.com/api/shop/pay/init",
            params={"region": "IN.TH", "language": "th"},
            cookies=cookies,
            headers=req_headers,
            json=json_data,
        )

    try:
        body = response.json()
    except Exception:
        return TopupResult(
            ok=False,
            display_id=None,
            failure_reason="upstream_error",
            raw={"status_code": response.status_code, "text": response.text[:500]},
        )

    if not isinstance(body, dict):
        return TopupResult(ok=False, display_id=None, failure_reason="upstream_error", raw={"body": body})

    _ = otp  # reserved for pay step when enabled
    return map_termgame_response(body)

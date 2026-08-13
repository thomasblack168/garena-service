from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("garena-topup")


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
    cookie_header: str | None = None,
) -> TopupResult:
    from src.termgame.http import build_cookie_header, normalize_termgame_headers, termgame_http_client
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

    referer = f"https://termgame.com/buy?app={app_id}&channel={channel_id}&item={item_id}"
    cookie_line = build_cookie_header(cookies, cookie_header)
    req_headers = normalize_termgame_headers(
        headers,
        referer=referer,
        cookie_header=cookie_line,
    )

    proxy_configured = bool(os.environ.get("TERMGAME_HTTP_PROXY", "").strip())
    logger.info(
        "pay/init request: proxy=%s cookie_keys=%s header_keys=%s ua=%s",
        proxy_configured,
        sorted(cookies.keys()),
        sorted(k for k in req_headers if k.lower() != "cookie"),
        req_headers.get("User-Agent", "")[:80],
    )

    try:
        async with termgame_http_client(timeout=20.0, follow_redirects=True) as client:
            response = await client.post(
                "https://termgame.com/api/shop/pay/init",
                params={"region": "IN.TH", "language": "th"},
                headers=req_headers,
                json=json_data,
            )
    except Exception as exc:
        logger.error("pay/init request failed before a response arrived: %s: %s", type(exc).__name__, exc)
        # Proxy/network failure (tunnel down, DNS, timeout) — report cleanly
        # instead of raising, so callers (worker loop, session probe) never
        # crash on a dead upstream and can show an actionable message.
        return TopupResult(
            ok=False,
            display_id=None,
            failure_reason="upstream_unreachable",
            raw={"error": "upstream_unreachable", "detail": str(exc)[:200]},
        )

    resp_headers = dict(response.headers)
    datadome_set_cookie = "set-cookie" in {k.lower() for k in resp_headers} and "datadome" in response.text[:2000].lower()
    logger.info(
        "pay/init response: status=%s server=%s cf-ray=%s content-type=%s datadome_mentioned=%s body_snippet=%r",
        response.status_code,
        resp_headers.get("server") or resp_headers.get("Server"),
        resp_headers.get("cf-ray") or resp_headers.get("Cf-Ray") or resp_headers.get("x-datadome") or resp_headers.get("X-DataDome"),
        resp_headers.get("content-type") or resp_headers.get("Content-Type"),
        datadome_set_cookie,
        response.text[:500],
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

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


def build_channel_data(otp: str, needs_otp: bool, garena_uid: int | None) -> dict[str, Any]:
    """Some games (freefire, deltaforce, hai, undraw) reject pay/init with
    result=error_params unless channel_data carries the merchant's own TOTP
    code + Garena account uid -- rov works fine with channel_data empty.
    See games.yaml needs_otp comment for how this was confirmed per game."""
    if not needs_otp:
        return {}
    data: dict[str, Any] = {"otp_code": str(otp)}
    if garena_uid is not None:
        data["garena_uid"] = garena_uid
    return data


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


async def player_id_login(
    *,
    app_id: int,
    player_id: str,
    cookies: dict[str, str],
    headers: dict[str, str],
    referer: str,
    cookie_header: str | None = None,
) -> str | None:
    """Registers player_id as the topup target for this session/app before
    pay/init. Legacy per-game scripts (rov/hai/undraw/deltaforce/freefire)
    disagree on whether this is needed -- rov's script builds the payload
    but never sends it, freefire's script never builds it at all, but
    hai/undraw/deltaforce all call it and treat a missing open_id in the
    response as an invalid player, before ever attempting pay/init. Returns
    the resolved open_id, or None if termgame doesn't recognize player_id
    for this app_id."""
    from src.termgame.http import build_cookie_header, normalize_termgame_headers, termgame_http_client

    cookie_line = build_cookie_header(cookies, cookie_header)
    req_headers = normalize_termgame_headers(headers, referer=referer, cookie_header=cookie_line)

    async with termgame_http_client(timeout=15.0, follow_redirects=True) as client:
        response = await client.post(
            "https://termgame.com/api/auth/player_id_login",
            headers=req_headers,
            json={"app_id": app_id, "login_id": str(player_id)},
        )
    try:
        body = response.json()
    except Exception:
        logger.error("player_id_login: non-JSON response status=%s text=%s", response.status_code, response.text[:300])
        return None
    if not isinstance(body, dict):
        logger.error("player_id_login: unexpected body shape: %r", body)
        return None
    logger.info("player_id_login response: app_id=%s player_id=%s body=%s", app_id, player_id, body)
    open_id = body.get("open_id")
    return str(open_id) if open_id else None


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
    needs_otp: bool = False,
    needs_player_login: bool = False,
    garena_uid: int | None = None,
    session_id: str | None = None,
    cookie_header: str | None = None,
) -> TopupResult:
    from src.termgame.http import build_cookie_header, normalize_termgame_headers, termgame_http_client
    from src.termgame.otp import generate_otp

    otp = generate_otp(otp_secret)
    mspid2 = session_id or cookies.get("mspid2", "")
    channel_data = build_channel_data(otp, needs_otp, garena_uid)

    if needs_player_login:
        login_referer = f"https://termgame.com/buy?app={app_id}&channel={channel_id}&item={item_id}"
        open_id = await player_id_login(
            app_id=app_id,
            player_id=player_id,
            cookies=cookies,
            headers=headers,
            referer=login_referer,
            cookie_header=cookie_header,
        )
        if not open_id:
            return TopupResult(
                ok=False,
                display_id=None,
                failure_reason="invalid_player",
                raw={"error": "player_id_login_failed", "player_id": player_id, "app_id": app_id},
            )

    json_data: dict[str, Any] = {
        "app_id": app_id,
        "channel_id": channel_id,
        "service": "pc",
        "item_id": int(item_id),
        "channel_data": channel_data,
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

    return map_termgame_response(body)

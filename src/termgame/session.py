from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.termgame.http import build_cookie_header, is_datadome_or_forbidden, normalize_termgame_headers, summarize_raw
from src.termgame.topup import execute_topup_unit

_GAMES = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "games.yaml").read_text(encoding="utf-8"),
)

# Cheap ROV pack used only for session probe (invalid UID on purpose).
_PROBE_GAME_KEY = "rov"
_PROBE_ITEM_ID = "4587"
_PROBE_PLAYER_ID = "1"


@dataclass
class SessionProbeResult:
    session_valid: bool
    session_expired: bool
    shell_balance: float | None
    raw: dict[str, Any] | None = None


def _parse_shell_balance(body: dict[str, Any]) -> float | None:
    candidates: list[Any] = [
        body.get("balance"),
        body.get("shell_balance"),
        body.get("shellBalance"),
    ]
    data = body.get("data")
    if isinstance(data, dict):
        candidates.extend(
            [
                data.get("balance"),
                data.get("shell_balance"),
                data.get("shellBalance"),
                data.get("shell"),
            ],
        )
        wallet = data.get("wallet")
        if isinstance(wallet, dict):
            candidates.extend([wallet.get("balance"), wallet.get("shell")])

    for value in candidates:
        if value is None:
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
        if isinstance(value, str):
            cleaned = re.sub(r"[^\d.]", "", value)
            if cleaned:
                try:
                    return float(cleaned)
                except ValueError:
                    continue
    return None


def _response_requires_login(body: dict[str, Any]) -> bool:
    if body.get("error") == "error_require_login":
        return True
    if body.get("result") == "error_require_login":
        return True
    message = str(body.get("message") or body.get("msg") or "").lower()
    return "login" in message and "require" in message


def _session_ok_from_topup_failure(reason: str | None) -> bool:
    if not reason:
        return False
    return reason in ("invalid_player", "pack_limit", "error_params")


async def probe_termgame_session(
    *,
    cookies: dict[str, str],
    headers: dict[str, str],
    cookie_header: str | None = None,
    otp_secret: str | None = None,
) -> SessionProbeResult:
    import httpx

    if not cookies and not (cookie_header and cookie_header.strip()):
        return SessionProbeResult(
            session_valid=False,
            session_expired=True,
            shell_balance=None,
            raw={"error": "missing_cookies"},
        )

    cookie_line = build_cookie_header(cookies, cookie_header)
    req_headers = normalize_termgame_headers(
        headers,
        referer="https://termgame.com/",
        cookie_header=cookie_line,
    )

    # Wallet endpoints are unreliable on termgame — probe via pay/init (real fulfillment path).
    game = _GAMES.get(_PROBE_GAME_KEY)
    if game:
        topup = await execute_topup_unit(
            app_id=int(game["app_id"]),
            channel_id=int(game["channel_id"]),
            packed_role_id=game.get("packed_role_id"),
            item_id=_PROBE_ITEM_ID,
            player_id=_PROBE_PLAYER_ID,
            cookies=cookies,
            headers=headers,
            otp_secret=otp_secret or "JBSWY3DPEHPK3PXP",
            cookie_header=cookie_line,
        )
        raw = topup.raw or {}
        if topup.failure_reason == "session_expired" or _response_requires_login(raw):
            return SessionProbeResult(
                session_valid=False,
                session_expired=True,
                shell_balance=None,
                raw=raw,
            )
        if is_datadome_or_forbidden(raw):
            return SessionProbeResult(
                session_valid=False,
                session_expired=False,
                shell_balance=None,
                raw=raw,
            )
        if topup.ok or _session_ok_from_topup_failure(topup.failure_reason):
            return SessionProbeResult(
                session_valid=True,
                session_expired=False,
                shell_balance=None,
                raw=raw,
            )
        detail = summarize_raw(raw)
        if is_datadome_or_forbidden(raw):
            return SessionProbeResult(
                session_valid=False,
                session_expired=False,
                shell_balance=None,
                raw=raw,
            )
        if "datadome" in detail.lower():
            return SessionProbeResult(
                session_valid=False,
                session_expired=False,
                shell_balance=None,
                raw=raw,
            )

    probe_urls = [
        "https://termgame.com/api/wallet/balance?region=IN.TH&language=th",
        "https://termgame.com/api/wallet/info?region=IN.TH&language=th",
        "https://termgame.com/api/user/profile?region=IN.TH&language=th",
    ]

    last_body: dict[str, Any] | None = None

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for url in probe_urls:
            try:
                response = await client.get(url, headers=req_headers)
            except Exception as exc:
                last_body = {"error": "upstream_error", "detail": str(exc)[:200]}
                continue

            try:
                body = response.json()
            except Exception:
                last_body = {"status_code": response.status_code, "text": response.text[:300]}
                continue

            if not isinstance(body, dict):
                last_body = {"body": body}
                continue

            last_body = body

            if _response_requires_login(body):
                return SessionProbeResult(
                    session_valid=False,
                    session_expired=True,
                    shell_balance=None,
                    raw=body,
                )

            balance = _parse_shell_balance(body)
            if response.status_code == 200 and (balance is not None or body.get("ok") is True):
                return SessionProbeResult(
                    session_valid=True,
                    session_expired=False,
                    shell_balance=balance,
                    raw=body,
                )

            if response.status_code == 200 and not _response_requires_login(body):
                return SessionProbeResult(
                    session_valid=True,
                    session_expired=False,
                    shell_balance=balance,
                    raw=body,
                )

    return SessionProbeResult(
        session_valid=False,
        session_expired=False,
        shell_balance=None,
        raw=last_body,
    )

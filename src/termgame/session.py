from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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


async def probe_termgame_session(
    *,
    cookies: dict[str, str],
    headers: dict[str, str],
) -> SessionProbeResult:
    import httpx

    if not cookies:
        return SessionProbeResult(
            session_valid=False,
            session_expired=True,
            shell_balance=None,
            raw={"error": "missing_cookies"},
        )

    req_headers = dict(headers)
    req_headers.setdefault("Accept", "application/json, text/plain, */*")
    req_headers.setdefault("Referer", "https://termgame.com/")

    probe_urls = [
        "https://termgame.com/api/wallet/balance?region=IN.TH&language=th",
        "https://termgame.com/api/wallet/info?region=IN.TH&language=th",
        "https://termgame.com/api/user/profile?region=IN.TH&language=th",
    ]

    last_body: dict[str, Any] | None = None

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for url in probe_urls:
            try:
                response = await client.get(
                    url,
                    cookies=cookies,
                    headers=req_headers,
                )
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
        session_expired=True,
        shell_balance=None,
        raw=last_body,
    )

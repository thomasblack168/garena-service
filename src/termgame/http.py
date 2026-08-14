from __future__ import annotations

import os
import re
from typing import Any

from curl_cffi.requests import AsyncSession

# Chrome TLS/JA3 impersonation target for curl_cffi. Kept for realism/parity
# with a real browser's TLS handshake, though the actual blocker turned out
# to be a missing header (see normalize_termgame_headers below) -- confirmed
# by A/B testing a real curl_cffi client with vs. without the x-csrf-token
# header: identical TLS fingerprint, identical everything else, and adding
# just that one header alone took every request from 403 to 200.
_IMPERSONATE_TARGET = "chrome124"


def build_cookie_header(cookies: dict[str, str], cookie_header: str | None = None) -> str:
    if cookie_header and cookie_header.strip():
        return cookie_header.strip().removeprefix("Cookie:").strip()
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _extract_cookie_value(cookie_header: str, name: str) -> str | None:
    for part in cookie_header.split(";"):
        piece = part.strip()
        if not piece:
            continue
        key, _, value = piece.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


def infer_client_hints_from_user_agent(user_agent: str) -> dict[str, str]:
    ua = user_agent or ""
    mobile = any(token in ua for token in ("Android", "iPhone", "Mobile"))
    if mobile:
        return {
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"' if "Android" in ua else '"iOS"',
        }
    return {
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }


def _chrome_major_version(user_agent: str) -> str:
    match = re.search(r"Chrome/(\d+)", user_agent or "")
    return match.group(1) if match else "124"


def termgame_http_client(**kwargs: Any) -> AsyncSession:
    proxy = os.environ.get("TERMGAME_HTTP_PROXY", "").strip()
    if proxy:
        kwargs.setdefault("proxy", proxy)
    if "follow_redirects" in kwargs:
        kwargs.setdefault("allow_redirects", kwargs.pop("follow_redirects"))
    kwargs.setdefault("impersonate", _IMPERSONATE_TARGET)
    return AsyncSession(**kwargs)


def normalize_termgame_headers(
    headers: dict[str, str],
    *,
    referer: str,
    cookie_header: str,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        if not key or not value:
            continue
        lower = key.lower()
        if lower in ("cookie", "content-length", "host"):
            continue
        out[key] = value

    out.setdefault("Accept", "application/json, text/plain, */*")
    out.setdefault("Accept-Language", "th-TH,th;q=0.9,en;q=0.8")
    out.setdefault("Origin", "https://termgame.com")

    ua = out.get("User-Agent", "")
    hints = infer_client_hints_from_user_agent(ua)
    if "sec-ch-ua-mobile" not in out:
        out["sec-ch-ua-mobile"] = hints["sec-ch-ua-mobile"]
    if "sec-ch-ua-platform" not in out:
        out["sec-ch-ua-platform"] = hints["sec-ch-ua-platform"]
    if "sec-ch-ua" not in out:
        chrome_v = _chrome_major_version(ua)
        out["sec-ch-ua"] = (
            f'"Not_A Brand";v="24", "Chromium";v="{chrome_v}", "Google Chrome";v="{chrome_v}"'
        )
    out.setdefault("Sec-Fetch-Dest", "empty")
    out.setdefault("Sec-Fetch-Mode", "cors")
    out.setdefault("Sec-Fetch-Site", "same-origin")
    out["Referer"] = referer
    out["Cookie"] = cookie_header

    # termgame requires the CSRF token to be echoed back as a request header
    # (double-submit pattern) -- their frontend reads it from the __csrf__
    # cookie via JS and re-sends it as x-csrf-token on every mutating
    # request. Without this, POST endpoints (pay/init etc.) reject with a
    # bare, unbranded 403 regardless of session validity, IP, or TLS
    # fingerprint -- this was the entire cause, confirmed by a controlled
    # A/B test (identical request, only this header differed).
    csrf_value = _extract_cookie_value(cookie_header, "__csrf__")
    if csrf_value:
        out["x-csrf-token"] = csrf_value

    return out


def summarize_raw(raw: dict[str, Any] | None) -> str:
    if not raw:
        return "no response"
    parts: list[str] = []
    for key in ("error", "result", "message", "msg", "status_code", "code"):
        if raw.get(key) is not None:
            parts.append(f"{key}={str(raw[key])[:120]}")
    if parts:
        return " · ".join(parts)
    text = str(raw.get("text") or raw)
    return text[:200]


def is_datadome_or_forbidden(raw: dict[str, Any] | None) -> bool:
    if not raw:
        return False
    status = raw.get("status_code")
    if status == 403 or status == "403":
        return True
    text = str(raw.get("text") or "").lower()
    if "403 forbidden" in text or "datadome" in text:
        return True
    detail = summarize_raw(raw).lower()
    return "status_code=403" in detail or "forbidden" in detail

from __future__ import annotations

from typing import Any


def build_cookie_header(cookies: dict[str, str], cookie_header: str | None = None) -> str:
    if cookie_header and cookie_header.strip():
        return cookie_header.strip().removeprefix("Cookie:").strip()
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


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
    out.setdefault("sec-ch-ua", '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"')
    out.setdefault("sec-ch-ua-mobile", "?0")
    out.setdefault("sec-ch-ua-platform", '"Windows"')
    out.setdefault("Sec-Fetch-Dest", "empty")
    out.setdefault("Sec-Fetch-Mode", "cors")
    out.setdefault("Sec-Fetch-Site", "same-origin")
    out["Referer"] = referer
    out["Cookie"] = cookie_header
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

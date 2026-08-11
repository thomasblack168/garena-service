#!/usr/bin/env python3
"""Quick probe pay/init status from server (no real session)."""
import asyncio
import httpx

UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
)


async def probe(label: str, extra: dict[str, str]) -> None:
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Origin": "https://termgame.com",
        "Referer": "https://termgame.com/",
        **extra,
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.post(
            "https://termgame.com/api/shop/pay/init",
            params={"region": "IN.TH", "language": "th"},
            headers=headers,
            json={
                "app_id": 100055,
                "channel_id": 207070,
                "service": "pc",
                "item_id": 4587,
                "player_id": "1",
            },
        )
    snippet = response.text[:100].replace("\n", " ")
    print(f"{label}: {response.status_code} {snippet}")


async def main() -> None:
    await probe(
        "desktop_hints",
        {"sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"'},
    )
    await probe(
        "mobile_hints",
        {"sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"Android"'},
    )
    await probe("no_hints", {})


if __name__ == "__main__":
    asyncio.run(main())

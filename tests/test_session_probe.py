import asyncio

from src.termgame.session import _parse_shell_balance, probe_termgame_session
from src.termgame.topup import TopupResult


def test_parse_shell_balance_nested():
    body = {"data": {"wallet": {"balance": 1234.5}}}
    assert _parse_shell_balance(body) == 1234.5


def test_probe_session_expired_via_pay_init(monkeypatch):
    async def fake_topup(**kwargs):
        return TopupResult(
            ok=False,
            display_id=None,
            failure_reason="session_expired",
            raw={"error": "error_require_login"},
        )

    monkeypatch.setattr("src.termgame.session.execute_topup_unit", fake_topup)

    result = asyncio.run(
        probe_termgame_session(
            cookies={"mspid2": "abc"},
            headers={"User-Agent": "test"},
        ),
    )
    assert result.session_expired is True
    assert result.session_valid is False


def test_probe_session_ok_via_invalid_player(monkeypatch):
    async def fake_topup(**kwargs):
        return TopupResult(
            ok=False,
            display_id=None,
            failure_reason="invalid_player",
            raw={"result": "error_params"},
        )

    monkeypatch.setattr("src.termgame.session.execute_topup_unit", fake_topup)

    result = asyncio.run(
        probe_termgame_session(
            cookies={"mspid2": "abc"},
            headers={"User-Agent": "test"},
        ),
    )
    assert result.session_valid is True
    assert result.session_expired is False


def test_probe_session_ok_with_balance(monkeypatch):
    async def fake_topup(**kwargs):
        return TopupResult(
            ok=False,
            display_id=None,
            failure_reason="upstream_error",
            raw={"error": "skip"},
        )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True, "data": {"balance": 999}}

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("src.termgame.session.execute_topup_unit", fake_topup)
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: FakeClient())

    result = asyncio.run(
        probe_termgame_session(
            cookies={"mspid2": "abc"},
            headers={"User-Agent": "test"},
        ),
    )
    assert result.session_valid is True
    assert result.shell_balance == 999.0

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

    async def fake_fetch_shell_balance(**kwargs):
        return 4200.0

    monkeypatch.setattr("src.termgame.session.execute_topup_unit", fake_topup)
    monkeypatch.setattr("src.termgame.session._fetch_shell_balance", fake_fetch_shell_balance)

    result = asyncio.run(
        probe_termgame_session(
            cookies={"mspid2": "abc"},
            headers={"User-Agent": "test"},
        ),
    )
    assert result.session_valid is True
    assert result.session_expired is False
    assert result.shell_balance == 4200.0


def test_fetch_shell_balance_parses_oauth_shell_balance(monkeypatch):
    from src.termgame.session import _fetch_shell_balance

    class FakeResponse:
        def json(self):
            return {"oauth": {"shell_balance": 1234.5, "username": "Erosterz-"}}

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("src.termgame.http.AsyncSession", lambda **kwargs: FakeClient())

    balance = asyncio.run(
        _fetch_shell_balance(cookies={"mspid2": "abc"}, headers={"User-Agent": "test"}, cookie_header=None),
    )
    assert balance == 1234.5


def test_fetch_shell_balance_none_when_oauth_missing(monkeypatch):
    from src.termgame.session import _fetch_shell_balance

    class FakeResponse:
        def json(self):
            return {"oauth": None}

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("src.termgame.http.AsyncSession", lambda **kwargs: FakeClient())

    balance = asyncio.run(
        _fetch_shell_balance(cookies={"mspid2": "abc"}, headers={"User-Agent": "test"}, cookie_header=None),
    )
    assert balance is None


def test_probe_reports_upstream_unreachable_without_raising(monkeypatch):
    async def fake_topup(**kwargs):
        return TopupResult(
            ok=False,
            display_id=None,
            failure_reason="upstream_unreachable",
            raw={"error": "upstream_unreachable", "detail": "Connection refused"},
        )

    monkeypatch.setattr("src.termgame.session.execute_topup_unit", fake_topup)

    result = asyncio.run(
        probe_termgame_session(
            cookies={"mspid2": "abc"},
            headers={"User-Agent": "test"},
        ),
    )
    assert result.session_valid is False
    assert result.session_expired is False
    assert result.raw["error"] == "upstream_unreachable"


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
    monkeypatch.setattr("src.termgame.http.AsyncSession", lambda **kwargs: FakeClient())

    result = asyncio.run(
        probe_termgame_session(
            cookies={"mspid2": "abc"},
            headers={"User-Agent": "test"},
        ),
    )
    assert result.session_valid is True
    assert result.shell_balance == 999.0

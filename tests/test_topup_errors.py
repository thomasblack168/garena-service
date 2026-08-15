import asyncio

from src.termgame.topup import build_channel_data, execute_topup_unit, map_termgame_response


def test_execute_topup_unit_fails_closed_when_player_login_returns_no_open_id(monkeypatch):
    async def fake_player_id_login(**kwargs):
        return None

    monkeypatch.setattr("src.termgame.topup.player_id_login", fake_player_id_login)

    result = asyncio.run(
        execute_topup_unit(
            app_id=100153,
            channel_id=207070,
            packed_role_id=772352,
            item_id="11001",
            player_id="1",
            cookies={},
            headers={},
            otp_secret="JBSWY3DPEHPK3PXP",
            needs_player_login=True,
        )
    )
    assert result.ok is False
    assert result.failure_reason == "invalid_player"


def test_channel_data_empty_when_otp_not_needed():
    assert build_channel_data("123456", False, 109836560) == {}


def test_channel_data_includes_otp_and_uid_when_needed():
    assert build_channel_data("123456", True, 109836560) == {
        "otp_code": "123456",
        "garena_uid": 109836560,
    }


def test_channel_data_omits_uid_when_unset():
    assert build_channel_data("123456", True, None) == {"otp_code": "123456"}


def test_maps_error_require_login():
    result = map_termgame_response({"error": "error_require_login"})
    assert result.failure_reason == "session_expired"
    assert result.ok is False


def test_maps_invalid_id():
    result = map_termgame_response({"error": "invalid_id"})
    assert result.failure_reason == "invalid_player"


def test_maps_success():
    result = map_termgame_response({"result": "ok", "display_id": "abc"})
    assert result.ok is True
    assert result.display_id == "abc"


def test_execute_topup_unit_reports_unreachable_instead_of_raising(monkeypatch):
    class ExplodingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise ConnectionRefusedError("connection refused")

    # execute_topup_unit imports termgame_http_client locally (inside the
    # function body) from src.termgame.http, so that's what must be patched.
    monkeypatch.setattr(
        "src.termgame.http.termgame_http_client",
        lambda **kwargs: ExplodingClient(),
    )

    result = asyncio.run(
        execute_topup_unit(
            app_id=1,
            channel_id=1,
            packed_role_id=None,
            item_id="1",
            player_id="1",
            cookies={},
            headers={},
            otp_secret="JBSWY3DPEHPK3PXP",
        )
    )
    assert result.ok is False
    assert result.failure_reason == "upstream_unreachable"

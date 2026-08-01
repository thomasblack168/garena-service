from src.termgame.topup import map_termgame_response


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

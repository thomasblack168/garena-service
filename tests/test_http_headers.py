from src.termgame.http import build_cookie_header, normalize_termgame_headers


def test_normalize_headers_echoes_csrf_cookie_as_header():
    cookies = {"mspid2": "abc", "__csrf__": "tok123", "datadome": "dd"}
    cookie_header = build_cookie_header(cookies)

    headers = normalize_termgame_headers(
        {"User-Agent": "test-agent"},
        referer="https://termgame.com/",
        cookie_header=cookie_header,
    )

    # This is the entire fix: termgame requires the __csrf__ cookie value to
    # also be sent as an x-csrf-token header (double-submit pattern) -- POST
    # requests without it get a bare 403 regardless of everything else.
    assert headers["x-csrf-token"] == "tok123"
    assert "__csrf__=tok123" in headers["Cookie"]


def test_normalize_headers_no_csrf_token_when_cookie_missing():
    cookie_header = build_cookie_header({"mspid2": "abc"})

    headers = normalize_termgame_headers(
        {"User-Agent": "test-agent"},
        referer="https://termgame.com/",
        cookie_header=cookie_header,
    )

    assert "x-csrf-token" not in headers

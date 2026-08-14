"""The ICE endpoint the browser builds its peer connections from.

The regression this guards is specific: the app shipped with two Google STUN
entries and no relay, which means peers behind symmetric NAT or a corporate
firewall could not connect at all. A test that only checked for a 200 would
have passed against that bug, so these assert that a *relay* is present and
carries credentials.
"""


def test_ice_config_offers_a_relay_not_just_stun(client):
    body = client.get("/api/ice").json()
    urls = [u for server in body["iceServers"] for u in server["urls"]]
    assert any(u.startswith("stun:") for u in urls), urls
    assert any(u.startswith(("turn:", "turns:")) for u in urls), urls


def test_relay_entries_carry_credentials(client):
    body = client.get("/api/ice").json()
    relays = [
        s
        for s in body["iceServers"]
        if any(u.startswith(("turn:", "turns:")) for u in s["urls"])
    ]
    assert relays, "no relay entry at all"
    for s in relays:
        # A TURN server without credentials is a TURN server that refuses the
        # allocation, which fails exactly like having no TURN at all.
        assert s.get("username"), s
        assert s.get("credential"), s


def test_stun_entries_omit_credential_keys(client):
    """The response is handed straight to `new RTCPeerConnection(...)`, so it
    should not carry `username: null` keys that mean nothing there."""
    body = client.get("/api/ice").json()
    for s in body["iceServers"]:
        if all(u.startswith("stun:") for u in s["urls"]):
            assert "username" not in s
            assert "credential" not in s


def test_config_is_usable_as_an_rtc_configuration(client):
    body = client.get("/api/ice").json()
    assert set(body) <= {"iceServers", "iceCandidatePoolSize"}
    assert isinstance(body["iceCandidatePoolSize"], int)
    assert body["iceServers"], "an empty list would silently disable ICE"


def test_the_dead_public_placeholder_is_flagged(client):
    """The relay plumbing is complete; the default relay behind it is not.

    Open Relay's public endpoint was measured on 2026-09-10 to answer a 401
    challenge and then refuse every Allocate with 400 - identically for the
    documented credentials, a wrong password and a nonexistent user, so it is
    not checking credentials at all. Its :443 certificate also does not match
    its hostname. Shipping that as a default is only acceptable if the code
    says so out loud, which is what this asserts.
    """
    from app import config

    assert config.TURN_IS_PLACEHOLDER is True, (
        "Defaults changed: if TURN now points at a real account, this test "
        "should assert False and the README's Known limits needs updating."
    )


def test_real_credentials_clear_the_placeholder_flag(monkeypatch):
    """The override path, which is how this actually gets fixed."""
    import importlib

    from app import config

    monkeypatch.setenv("TURN_URLS", "turn:relay.example.com:3478")
    monkeypatch.setenv("TURN_USERNAME", "a-real-account")
    monkeypatch.setenv("TURN_CREDENTIAL", "a-real-secret")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.TURN_IS_PLACEHOLDER is False
        assert reloaded.TURN_USERNAME == "a-real-account"
    finally:
        # Other tests share this module; leave it as they expect to find it.
        monkeypatch.undo()
        importlib.reload(config)

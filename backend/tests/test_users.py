"""The user-scoped router: contacts directory, profile, preferences.

This router had no coverage at all before Phase 6. Everything here goes
through the HTTP layer rather than calling crud directly, because the parts
worth protecting are the ones the frontend actually depends on: that the
directory never leaks the caller back to themselves, that a partial PATCH
leaves the fields it did not mention alone, and that none of it is reachable
without a token.
"""
from conftest import auth_header, signup, unique_email
from test_meetings import create_instant


# --------------------------------------------------------------------------
# auth gate
# --------------------------------------------------------------------------

def test_every_user_route_requires_a_token(client):
    assert client.get("/api/contacts").status_code == 401
    assert client.get("/api/preferences").status_code == 401
    assert client.patch("/api/profile", json={"name": "x"}).status_code == 401
    assert client.patch(
        "/api/preferences", json={"pref_hd_video": True}
    ).status_code == 401


# --------------------------------------------------------------------------
# contacts
# --------------------------------------------------------------------------

def test_contacts_exclude_the_caller(client):
    token, me = signup(client, unique_email("contact-self"))
    r = client.get("/api/contacts", headers=auth_header(token))
    assert r.status_code == 200, r.text
    assert me["id"] not in [c["id"] for c in r.json()]


def test_contacts_list_other_registered_users(client):
    a_token, _ = signup(client, unique_email("contact-a"), name="Amelia Contact")
    _, b_user = signup(client, unique_email("contact-b"), name="Bruno Contact")

    r = client.get("/api/contacts", headers=auth_header(a_token))
    assert r.status_code == 200, r.text
    assert b_user["id"] in [c["id"] for c in r.json()]


def test_contacts_are_sorted_by_name(client):
    token, _ = signup(client, unique_email("contact-sort"))
    names = [c["name"] for c in client.get(
        "/api/contacts", headers=auth_header(token)
    ).json()]
    assert names == sorted(names)


def test_a_contact_carries_presence_and_no_credentials(client):
    token, _ = signup(client, unique_email("contact-shape"))
    contacts = client.get("/api/contacts", headers=auth_header(token)).json()
    assert contacts, "the demo seed should leave somebody to list"

    entry = contacts[0]
    assert set(entry) == {"id", "name", "avatar_color", "avatar_url", "status"}
    assert entry["status"] in {"available", "in-meeting"}


def test_the_directory_does_not_hand_out_email_addresses(client):
    """The directory is every registered user, so an address here is every
    user's address. Anyone who can sign up could otherwise scrape the lot."""
    token, _ = signup(client, unique_email("contact-privacy"))
    other_email = unique_email("contact-private")
    signup(client, other_email)

    body = client.get("/api/contacts", headers=auth_header(token)).text
    assert other_email not in body
    for entry in client.get("/api/contacts", headers=auth_header(token)).json():
        assert "email" not in entry


def test_a_user_in_a_live_meeting_reads_as_in_meeting(client):
    watcher_token, _ = signup(client, unique_email("contact-watcher"))
    host_token, host = signup(client, unique_email("contact-host"), name="Zed Host")

    def status_of(user_id):
        contacts = client.get(
            "/api/contacts", headers=auth_header(watcher_token)
        ).json()
        return next(c["status"] for c in contacts if c["id"] == user_id)

    assert status_of(host["id"]) == "available"

    created = create_instant(client, host_token)
    client.post(
        f"/api/meetings/{created['meeting_number']}/join",
        json={"display_name": "Zed Host"},
        headers=auth_header(host_token),
    )

    assert status_of(host["id"]) == "in-meeting"

    client.post(
        f"/api/meetings/{created['meeting_number']}/end",
        headers=auth_header(host_token),
    )
    assert status_of(host["id"]) == "available"


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------

def test_updating_a_name_persists_and_is_visible_on_me(client):
    token, _ = signup(client, unique_email("profile"), name="Before")

    r = client.patch(
        "/api/profile", json={"name": "After"}, headers=auth_header(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "After"

    assert client.get("/auth/me", headers=auth_header(token)).json()["name"] == "After"


def test_a_profile_name_is_trimmed(client):
    token, _ = signup(client, unique_email("profile-trim"))
    r = client.patch(
        "/api/profile", json={"name": "   Padded Name   "}, headers=auth_header(token)
    )
    assert r.json()["name"] == "Padded Name"


def test_a_partial_profile_patch_leaves_other_fields_alone(client):
    token, _ = signup(client, unique_email("profile-partial"), name="Keep Me")
    before = client.get("/auth/me", headers=auth_header(token)).json()

    r = client.patch(
        "/api/profile", json={"avatar_color": "#123456"}, headers=auth_header(token)
    )
    assert r.status_code == 200, r.text

    after = r.json()
    assert after["avatar_color"] == "#123456"
    assert after["name"] == before["name"]
    assert after["email"] == before["email"]


def test_an_empty_profile_name_is_rejected(client):
    token, _ = signup(client, unique_email("profile-empty"))
    assert client.patch(
        "/api/profile", json={"name": ""}, headers=auth_header(token)
    ).status_code == 422


def test_clearing_an_avatar_url_stores_null_not_empty_string(client):
    token, _ = signup(client, unique_email("profile-avatar"))
    client.patch(
        "/api/profile",
        json={"avatar_url": "data:image/png;base64,AAAA"},
        headers=auth_header(token),
    )
    r = client.patch(
        "/api/profile", json={"avatar_url": ""}, headers=auth_header(token)
    )
    assert r.json()["avatar_url"] is None


def test_a_profile_patch_cannot_reach_another_account(client):
    a_token, _ = signup(client, unique_email("profile-a"), name="Mine")
    _, b_user = signup(client, unique_email("profile-b"), name="Theirs")

    r = client.patch(
        "/api/profile",
        json={"name": "Hijacked", "id": b_user["id"]},
        headers=auth_header(a_token),
    )
    assert r.status_code == 200
    # The id in the body is ignored: the token decides whose row moves.
    assert r.json()["id"] != b_user["id"]
    assert r.json()["name"] == "Hijacked"


# --------------------------------------------------------------------------
# preferences
# --------------------------------------------------------------------------

PREF_FIELDS = {
    "pref_video_on_join",
    "pref_join_muted",
    "pref_mirror_video",
    "pref_hd_video",
    "pref_notifications",
}


def test_preferences_come_back_as_booleans(client):
    token, _ = signup(client, unique_email("prefs"))
    body = client.get("/api/preferences", headers=auth_header(token)).json()
    assert set(body) == PREF_FIELDS
    assert all(isinstance(v, bool) for v in body.values())


def test_a_preference_round_trips(client):
    token, _ = signup(client, unique_email("prefs-rt"))
    before = client.get("/api/preferences", headers=auth_header(token)).json()
    flipped = not before["pref_hd_video"]

    r = client.patch(
        "/api/preferences",
        json={"pref_hd_video": flipped},
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["pref_hd_video"] is flipped

    after = client.get("/api/preferences", headers=auth_header(token)).json()
    assert after["pref_hd_video"] is flipped


def test_a_partial_preferences_patch_leaves_the_rest_alone(client):
    token, _ = signup(client, unique_email("prefs-partial"))
    before = client.get("/api/preferences", headers=auth_header(token)).json()

    after = client.patch(
        "/api/preferences",
        json={"pref_join_muted": not before["pref_join_muted"]},
        headers=auth_header(token),
    ).json()

    for field in PREF_FIELDS - {"pref_join_muted"}:
        assert after[field] == before[field], field


def test_preferences_are_per_account(client):
    a_token, _ = signup(client, unique_email("prefs-a"))
    b_token, _ = signup(client, unique_email("prefs-b"))

    b_before = client.get("/api/preferences", headers=auth_header(b_token)).json()
    client.patch(
        "/api/preferences",
        json={"pref_notifications": not b_before["pref_notifications"]},
        headers=auth_header(a_token),
    )

    b_after = client.get("/api/preferences", headers=auth_header(b_token)).json()
    assert b_after == b_before


def test_an_empty_preferences_patch_is_a_no_op(client):
    token, _ = signup(client, unique_email("prefs-noop"))
    before = client.get("/api/preferences", headers=auth_header(token)).json()
    assert client.patch(
        "/api/preferences", json={}, headers=auth_header(token)
    ).json() == before

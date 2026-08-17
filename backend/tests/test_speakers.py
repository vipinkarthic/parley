"""Phase 4: the active-speaker ranking, and its hysteresis.

`speakers.py` takes `now` on every entry point precisely so this file can
exist: the timing rules are the whole feature, and testing them by sleeping
would be slow, flaky, and would still only cover one set of timings.

The rules under test are the ones that stop video flickering. Without decay
and a minimum hold, a tile is dropped and re-added every time somebody says
"mm-hmm", and each of those is a replaceTrack on two machines.
"""
from app.speakers import (
    BROADCAST_INTERVAL_MS,
    HOLD_MS,
    MIN_RANK_HOLD_MS,
    RoomSpeakers,
)


def _room(*pids: int, now: float = 0.0) -> RoomSpeakers:
    room = RoomSpeakers()
    for pid in pids:
        room.add(pid, now)
    return room


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

def test_a_speaker_is_ranked_first_while_speaking():
    room = _room(1, 2, 3)
    room.report(2, on=True, level=80, now_ms=0)
    assert room.ranked(0)[0] == 2
    assert room.speaking_now(0) == [2]


def test_speaking_decays_rather_than_stopping_dead():
    """The gap between two sentences must not drop the tile."""
    room = _room(1, 2)
    room.report(2, on=True, level=80, now_ms=0)
    room.report(2, on=False, level=0, now_ms=100)

    # Still counted as speaking through the hold window.
    assert room.speaking_now(HOLD_MS - 1) == [2]
    # And only then released.
    assert room.speaking_now(HOLD_MS + 1) == []


def test_an_incumbent_keeps_its_rank_after_it_stops_speaking():
    """The minimum-duration gate. Losing the highlight is cosmetic; losing
    the video track is not, so the rank hold outlasts the speaking hold."""
    room = _room(1, 2)
    room.report(2, on=True, level=80, now_ms=0)
    room.report(2, on=False, level=0, now_ms=10)

    # Past the speaking window but inside the rank window: no longer
    # highlighted, still ahead of the silent peer.
    at = HOLD_MS + 100
    assert at < MIN_RANK_HOLD_MS
    assert room.speaking_now(at) == []
    assert room.ranked(at)[0] == 2

    # Past both: falls back to join order.
    assert room.ranked(MIN_RANK_HOLD_MS + 100) == [1, 2]


def test_a_louder_speaker_outranks_a_quieter_one():
    room = _room(1, 2, 3)
    room.report(1, on=True, level=30, now_ms=0)
    room.report(3, on=True, level=90, now_ms=0)
    assert room.ranked(0)[:2] == [3, 1]


def test_ranking_is_stable_for_equal_speakers():
    """Ties must not oscillate - an unstable sort here is a track swap."""
    room = _room(5, 6, 7)
    room.report(5, on=True, level=50, now_ms=0)
    room.report(6, on=True, level=50, now_ms=0)
    first = room.ranked(0)
    for _ in range(20):
        assert room.ranked(0) == first


def test_muted_reports_do_not_rank():
    """The client sends on:false when muted regardless of level."""
    room = _room(1, 2)
    room.report(2, on=False, level=99, now_ms=0)
    assert room.speaking_now(0) == []
    assert room.ranked(0) == [1, 2]


# ---------------------------------------------------------------------------
# Broadcast gating
# ---------------------------------------------------------------------------

def test_the_first_change_is_broadcast():
    room = _room(1, 2)
    room.report(2, on=True, level=80, now_ms=0)
    msg = room.due(0, video_budget=5)
    assert msg is not None
    assert msg["type"] == "active-speakers"
    assert msg["speaking"] == [2]


def test_an_unchanged_room_is_not_rebroadcast():
    room = _room(1, 2)
    room.report(2, on=True, level=80, now_ms=0)
    assert room.due(0, video_budget=5) is not None
    # Past the rate limit but still inside the hold window, so the state is
    # genuinely unchanged: nothing to say.
    later = BROADCAST_INTERVAL_MS * 2
    assert later < HOLD_MS
    assert room.due(later, video_budget=5) is None


def test_reordering_inside_the_budget_does_not_broadcast():
    """The suppression rule that matters most.

    Two peers swapping first and second place changes no client's
    subscription - both are inside the budget either way - so it must not
    trigger a message, let alone a track swap.
    """
    room = _room(1, 2, 3)
    room.report(1, on=True, level=90, now_ms=0)
    room.report(2, on=True, level=80, now_ms=0)
    assert room.due(0, video_budget=5) is not None

    later = BROADCAST_INTERVAL_MS * 3
    room.report(1, on=True, level=40, now_ms=later)
    room.report(2, on=True, level=95, now_ms=later)
    # 2 is now louder than 1, so the order flipped...
    assert room.ranked(later)[:2] == [2, 1]
    # ...but membership and the speaking set are identical, so: silence.
    assert room.due(later, video_budget=5) is None


def test_leaving_the_budget_does_broadcast():
    """The mirror of the test above: a membership change must get through."""
    room = _room(1, 2, 3, 4)
    room.report(1, on=True, level=90, now_ms=0)
    assert room.due(0, video_budget=1) is not None

    later = BROADCAST_INTERVAL_MS * 3
    room.report(4, on=True, level=99, now_ms=later)
    msg = room.due(later, video_budget=1)
    assert msg is not None
    assert msg["ranked"][0] == 4


def test_the_rate_limit_holds_a_change_back():
    room = _room(1, 2, 3)
    room.report(1, on=True, level=90, now_ms=0)
    assert room.due(0, video_budget=5) is not None
    # A real change, but too soon.
    room.report(2, on=True, level=95, now_ms=10)
    assert room.due(10, video_budget=5) is None
    # And it is delivered once the interval has passed, not dropped.
    assert room.due(BROADCAST_INTERVAL_MS + 1, video_budget=5) is not None


def test_membership_changes_invalidate_the_suppression():
    room = _room(1, 2)
    room.report(1, on=True, level=90, now_ms=0)
    assert room.due(0, video_budget=5) is not None
    assert room.due(BROADCAST_INTERVAL_MS * 2, video_budget=5) is None

    room.add(9, BROADCAST_INTERVAL_MS * 2)
    room.invalidate()
    assert room.due(BROADCAST_INTERVAL_MS * 3, video_budget=5) is not None


def test_ranked_is_capped():
    room = _room(*range(1, 30))
    assert len(room.ranked(0)) <= 8
    assert len(room.ranked(0, limit=3)) == 3


def test_removing_a_participant_drops_them_from_the_ranking():
    room = _room(1, 2)
    room.report(2, on=True, level=80, now_ms=0)
    room.remove(2)
    assert room.ranked(0) == [1]
    assert room.speaking_now(0) == []

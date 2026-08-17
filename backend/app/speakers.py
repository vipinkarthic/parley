"""Server-authoritative active-speaker ranking, with hysteresis.

Why the server owns this
------------------------
Clients used to each run an ``AnalyserNode`` over every remote stream and pick
the loudest for themselves. That has two problems, and the second one is
fatal to active-speaker paging:

* independent rankings disagree, so two people looking at the same meeting see
  different grids, and tracks thrash as each client subscribes to a different
  set;
* **you cannot measure the audio level of a peer whose track you dropped.**
  The moment paging works, client-side ranking stops being able to see the
  people it is supposed to be ranking.

So each client reports only its **own** microphone, and the server is the
single source of the ordering. Every client derives the same desired set from
the same list, which is what stops the thrash.

Why hysteresis is not optional
------------------------------
Speech is not a step function. Without decay and a minimum hold, a tile is
dropped and re-added every time someone says "mm-hmm", and each of those is a
``replaceTrack`` on both ends. Three separate guards, doing three different
jobs:

``HOLD_MS``
    How long someone counts as *speaking* after they stop. This is the decay,
    and it is what absorbs the gaps between words.

``MIN_RANK_HOLD_MS``
    How long someone keeps their place in the ranking after they stop. An
    incumbent cannot be displaced before this elapses, even by someone louder.
    This is the minimum-duration gate.

``BROADCAST_INTERVAL_MS``
    A floor on how often the room is told anything at all.

And one suppression rule that matters as much as the timers: a broadcast only
goes out when the **membership** of the top-K changes, or when the set of
currently-speaking peers changes. Reordering *within* the top-K changes nobody's
subscription, so it must not be allowed to trigger one.

This module holds no I/O and no framework types, which is what makes the
timing rules testable without a websocket or a clock to sleep on: every entry
point takes ``now``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A speaker stays "speaking" this long after their last positive report. Two
# seconds is long enough to bridge the pause between sentences and short
# enough that a finished speaker yields the tile promptly.
HOLD_MS = 2_000

# A speaker keeps their rank position this long after last speech, even if
# somebody louder wants it. Longer than HOLD_MS on purpose: losing the
# "speaking" highlight is cosmetic, losing the video track is not.
MIN_RANK_HOLD_MS = 3_000

# Floor on how often the room is told about a change.
BROADCAST_INTERVAL_MS = 500

# Past this there is nothing a client can do with the extra ranks - it is well
# beyond any sane video budget.
RANK_LIMIT = 8

# A client that goes away without saying so stops mattering after this.
REPORT_STALE_MS = 10_000


@dataclass
class _Report:
    level: int = 0
    speaking: bool = False
    # Last time this participant reported speaking, or None if never. It has
    # to be None rather than 0: `now` is a monotonic clock that legitimately
    # starts near zero, and a falsy-check against 0.0 reads "spoke at the
    # first instant" as "has never spoken".
    last_spoke_ms: float | None = None
    last_report_ms: float = 0.0
    # Monotonic tiebreak so equal-ranked peers keep a stable order rather
    # than swapping places on every recomputation.
    joined_seq: int = 0


@dataclass
class RoomSpeakers:
    """Ranking state for one meeting."""

    reports: dict[int, _Report] = field(default_factory=dict)
    _seq: int = 0
    # -inf, not 0: the first broadcast must never be swallowed by the rate
    # limit, and with a monotonic clock 0 is a time that actually occurs.
    _last_broadcast_ms: float = float("-inf")
    _last_sent: tuple[tuple[int, ...], tuple[int, ...]] | None = None

    # -- membership ---------------------------------------------------------

    def add(self, pid: int, now_ms: float) -> None:
        if pid not in self.reports:
            self._seq += 1
            self.reports[pid] = _Report(
                joined_seq=self._seq, last_report_ms=now_ms
            )

    def remove(self, pid: int) -> None:
        self.reports.pop(pid, None)

    def __bool__(self) -> bool:
        return bool(self.reports)

    # -- input --------------------------------------------------------------

    def report(self, pid: int, on: bool, level: int, now_ms: float) -> None:
        """Record one client's report about its own microphone."""
        self.add(pid, now_ms)
        entry = self.reports[pid]
        entry.last_report_ms = now_ms
        entry.level = max(0, min(100, level))
        if on:
            entry.speaking = True
            entry.last_spoke_ms = now_ms
        else:
            # Not cleared here. `speaking` decays in ranked(); clearing it on
            # report would make HOLD_MS depend on the client bothering to send
            # an "off", which is exactly the message most likely to be lost.
            entry.speaking = False

    # -- output -------------------------------------------------------------

    def _prune(self, now_ms: float) -> None:
        stale = [
            pid
            for pid, r in self.reports.items()
            if now_ms - r.last_report_ms > REPORT_STALE_MS
            and (
                r.last_spoke_ms is None
                or now_ms - r.last_spoke_ms > REPORT_STALE_MS
            )
        ]
        for pid in stale:
            # Only drop the *report*, never the participant: someone who has
            # simply not spoken is still in the room and still rankable.
            self.reports[pid].level = 0
            self.reports[pid].speaking = False

    def speaking_now(self, now_ms: float) -> list[int]:
        """Who counts as speaking, after decay."""
        return sorted(
            pid
            for pid, r in self.reports.items()
            if r.last_spoke_ms is not None
            and now_ms - r.last_spoke_ms <= HOLD_MS
        )

    def ranked(self, now_ms: float, limit: int = RANK_LIMIT) -> list[int]:
        """The authoritative order, most deserving of video first.

        Three tiers, and the sort key is total so the result is deterministic
        for a given state - which is the whole point of ranking server-side.

        1. speaking now, loudest first
        2. spoke recently enough to still hold their place, most recent first
        3. everyone else, in join order
        """
        self._prune(now_ms)
        speaking = []
        holding = []
        idle = []
        for pid, r in self.reports.items():
            since = (
                None if r.last_spoke_ms is None else now_ms - r.last_spoke_ms
            )
            if since is not None and since <= HOLD_MS:
                speaking.append((-r.level, r.joined_seq, pid))
            elif since is not None and since <= MIN_RANK_HOLD_MS:
                holding.append((since, r.joined_seq, pid))
            else:
                idle.append((r.joined_seq, pid))

        order = (
            [pid for *_, pid in sorted(speaking)]
            + [pid for *_, pid in sorted(holding)]
            + [pid for _, pid in sorted(idle)]
        )
        return order[:limit]

    def snapshot(self, now_ms: float, limit: int = RANK_LIMIT) -> dict:
        return {
            "type": "active-speakers",
            "ranked": self.ranked(now_ms, limit),
            "speaking": self.speaking_now(now_ms),
        }

    # -- broadcast gating ---------------------------------------------------

    def due(self, now_ms: float, video_budget: int, limit: int = RANK_LIMIT):
        """Return a message to broadcast, or None.

        Two independent gates. The rate limit stops a busy room generating a
        message per report. The membership check stops a *quiet* room
        generating one at all: reordering inside the top-K changes nobody's
        subscription, so re-sending for it would cost every client a
        recomputation and buy nothing.

        `video_budget` is the client-side K. Membership is compared over the
        first `video_budget` entries, because that is the prefix that actually
        decides who gets subscribed to.
        """
        ranked = self.ranked(now_ms, limit)
        speaking = self.speaking_now(now_ms)
        # Order-insensitive within the budget: only who is in it matters.
        key = (tuple(sorted(ranked[:video_budget])), tuple(speaking))
        if key == self._last_sent:
            return None
        if now_ms - self._last_broadcast_ms < BROADCAST_INTERVAL_MS:
            return None
        self._last_broadcast_ms = now_ms
        self._last_sent = key
        return {
            "type": "active-speakers",
            "ranked": ranked,
            "speaking": speaking,
        }

    def invalidate(self) -> None:
        """Force the next `due()` to send.

        Called when the room's membership changes: somebody joining or leaving
        changes what the ranking means even if no level moved.
        """
        self._last_sent = None

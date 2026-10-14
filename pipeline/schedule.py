"""Posting schedule: which episodes are made, and when they go out.

config/shows.yaml →

    schedule:
      morning:
        at: "07:00"          # KST posting time
        until: "12:00"       # the chat bot gives up on a post after this (phone off, …)
        count: 2             # episodes per occasion
        shows: [daybreak-us, big-take]                      # newest new episode of each, in this order
        fallback: [trumponomics, everybodys-business, zero] # fill the places the shows above leave empty
      evening:
        at: "21:00"
        count: 1
        shows: [think-fast-talk-smart, stuff-you-should-know]
        catalog: [think-fast-talk-smart]                    # still empty → an older episode from the archive

An *occasion* is one slot on one KST date ("2026-10-15-morning", posted at 07:00). Every pipeline run works
for exactly one occasion per slot: the next one whose posting time plus GRACE is still ahead, so episodes that
finish a little late still join it.

Only as many episodes as the occasion needs are made. A primary show that usually publishes in the 24 h before
this weekday's posting time (learned from its feed) holds its place until shortly after the posting time;
the other places are filled from the fallback shows / the archive straight away.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
GRACE = timedelta(hours=3)            # late episodes may still join an occasion this long after its posting time
FRESH = timedelta(hours=48)           # a primary show's episode is "new" for this long before the posting time
FALLBACK_FRESH = timedelta(days=7)    # fallback shows are weekly
EXPECT_WEEKS = 4                      # how many past weeks decide whether a show is expected on this weekday
EXPECT_MIN_HITS = 2


@dataclass
class Slot:
    name: str
    at: str = "07:00"
    until: str | None = None
    count: int = 1
    label: str = ""
    shows: list[str] = field(default_factory=list)
    fallback: list[str] = field(default_factory=list)
    catalog: list[str] = field(default_factory=list)
    hold_minutes: int = 15            # an expected primary show keeps its place until posting time + this

    @property
    def hm(self) -> tuple[int, int]:
        h, m = self.at.split(":")
        return int(h), int(m)

    def all_shows(self) -> list[str]:
        out: list[str] = []
        for s in self.shows + self.fallback + self.catalog:
            if s not in out:
                out.append(s)
        return out

    def order_of(self, show: str) -> int:
        lst = self.all_shows()
        return lst.index(show) if show in lst else len(lst)


def load_slots(cfg: dict) -> list[Slot]:
    sched = cfg.get("schedule") or {}
    slots = []
    for name, sc in sched.items():
        sc = dict(sc or {})
        slots.append(Slot(name=name, at=str(sc.get("at", "07:00")), until=sc.get("until"), count=int(sc.get("count", 1)),
                          label=sc.get("label", ""), shows=list(sc.get("shows") or []), fallback=list(sc.get("fallback") or []),
                          catalog=list(sc.get("catalog") or []), hold_minutes=int(sc.get("hold_minutes", 15))))
    slots.sort(key=lambda s: s.hm)
    return slots


def occasion(slot: Slot, now: datetime) -> datetime:
    """Posting time (KST) of the occasion a run at `now` works for."""
    now_k = now.astimezone(KST)
    h, m = slot.hm
    o = now_k.replace(hour=h, minute=m, second=0, microsecond=0)
    if o + GRACE <= now_k:
        o += timedelta(days=1)
    elif o - timedelta(days=1) + GRACE > now_k:
        o -= timedelta(days=1)
    return o


def occasion_key(slot: Slot, o: datetime) -> str:
    return f"{o.astimezone(KST).strftime('%Y-%m-%d')}-{slot.name}"


def occasion_from_key(slot: Slot, key: str) -> datetime:
    d = datetime.strptime(key[:10], "%Y-%m-%d")
    h, m = slot.hm
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KST)


def until(slot: Slot, o: datetime) -> datetime:
    """Last moment the chat bot may still post this occasion's messages."""
    if slot.until:
        h, m = (int(x) for x in str(slot.until).split(":"))
        u = o.replace(hour=h, minute=m)
        if u <= o:
            u += timedelta(days=1)
        return u
    return o + timedelta(hours=4)


def expected(published: list[datetime], o: datetime) -> bool:
    """Does this show usually publish something in the 24 h before this weekday's posting time?"""
    hits = 0
    for w in range(1, EXPECT_WEEKS + 1):
        end = o - timedelta(days=7 * w)
        start = end - timedelta(hours=24)
        if any(start < p <= end for p in published):
            hits += 1
    return hits >= EXPECT_MIN_HITS


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def same_story(a: str, b: str) -> bool:
    """Cross-posted episodes ("Big Take Asia" in the Big Take feed, "…: Big Take" in Zero)."""
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return False
    short, long_ = sorted((na, nb), key=len)
    return len(short) >= 20 and long_.startswith(short)


@dataclass
class Cand:
    show: str
    key: str
    title: str
    published: datetime
    ready: bool = True       # transcript available (or a web-transcript show)
    done: bool = False       # already built — joining the occasion costs nothing
    ep: object = None


@dataclass
class Plan:
    picks: list[tuple[Cand, str]] = field(default_factory=list)   # (candidate, why: new / fallback / catalog)
    waiting: list[str] = field(default_factory=list)             # primary shows holding a place


def plan(slot: Slot, o: datetime, now: datetime, assigned: list[Cand], pools: dict[str, list[Cand]],
         expected_by_show: dict[str, bool]) -> Plan:
    """Choose what to add to occasion `o`. `assigned` = episodes it already has; `pools[show]` = that show's
    eligible episodes (not posted, not taken by another occasion), newest first."""
    p = Plan()
    need = slot.count - len(assigned)
    if need <= 0:
        return p
    used_shows = {c.show for c in assigned}
    titles = [c.title for c in assigned]

    def fresh_ok(c: Cand, window: timedelta) -> bool:
        return o - window <= c.published <= now and not any(same_story(c.title, t) for t in titles)

    holding_time = now < o + timedelta(minutes=slot.hold_minutes)
    for s in slot.shows:
        if need <= 0:
            break
        if s in used_shows:
            continue
        fresh = [c for c in pools.get(s, []) if fresh_ok(c, FRESH)]
        holding = bool(expected_by_show.get(s)) and holding_time
        if holding:
            # the show usually publishes in the 24 h before posting time: wait for that one rather than
            # taking an older episode now (yesterday's news briefing when today's is due tonight)
            ready = [c for c in fresh if c.ready and c.published > o - timedelta(hours=24)]
        else:
            ready = [c for c in fresh if c.ready]
        if ready:
            p.picks.append((ready[0], "new"))
            used_shows.add(s)
            titles.append(ready[0].title)
            need -= 1
        elif holding or fresh:
            p.waiting.append(s)          # due before posting time, or announced without a transcript yet

    hold = len(p.waiting) if holding_time else 0
    free = need - hold
    for s in slot.fallback:
        if free <= 0:
            break
        if s in used_shows:
            continue
        fresh = [c for c in pools.get(s, []) if c.ready and fresh_ok(c, FALLBACK_FRESH)]
        if fresh:
            p.picks.append((fresh[0], "fallback"))
            used_shows.add(s)
            titles.append(fresh[0].title)
            free -= 1
    for s in slot.catalog:
        if free <= 0:
            break
        older = [c for c in pools.get(s, []) if c.ready and c.published <= now and not any(same_story(c.title, t) for t in titles)
                 and all(c is not q for q, _ in p.picks)]
        if older:
            p.picks.append((older[0], "catalog"))
            titles.append(older[0].title)
            free -= 1
    return p

"""Push notifications through Expo's push service (the app registers Expo push tokens in public.push_tokens).

- study_ready(db, episode_id): the study material someone asked for is done
- new_episodes(db): new episodes of shows people follow (hourly, after the feeds are refreshed)
Each respects the user's switch in profiles (notify_study / notify_new_eps) and is sent once.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)
EXPO_PUSH = "https://exp.host/--/api/v2/push/send"


def _send(messages: list[dict]) -> None:
    for k in range(0, len(messages), 100):                       # Expo takes up to 100 per request
        try:
            r = requests.post(EXPO_PUSH, json=messages[k:k + 100], timeout=30,
                              headers={"Accept": "application/json", "Content-Type": "application/json"})
            bad = [m for m in (r.json().get("data") or []) if m.get("status") == "error"]
            if bad:
                log.warning("push: %d error(s), e.g. %s", len(bad), bad[0].get("message"))
        except Exception as e:  # noqa: BLE001  (a failed push never fails the job)
            log.warning("push failed: %s", e)


def _tokens(db, user_ids: set[str], switch: str) -> dict[str, list[str]]:
    if not user_ids:
        return {}
    ids = ",".join(sorted(user_ids))
    on = {p["user_id"] for p in db.select("profiles", f"select=user_id&{switch}=eq.true&user_id=in.({ids})")}
    out: dict[str, list[str]] = {}
    for t in db.select("push_tokens", f"select=token,user_id&user_id=in.({ids})"):
        if t["user_id"] in on:
            out.setdefault(t["user_id"], []).append(t["token"])
    return out


def study_ready(db, episode_id: str, title: str) -> int:
    rows = db.select("unlocks", f"select=user_id&episode_id=eq.{episode_id}&ready_pushed_at=is.null&opened_at=is.null")
    users = {r["user_id"] for r in rows}
    toks = _tokens(db, users, "notify_study")
    msgs = [{"to": tok, "title": "학습자료가 준비됐어요", "body": title[:120], "sound": "default", "channelId": "default",
             "data": {"episode": episode_id, "study": "1"}} for u in toks for tok in toks[u]]
    _send(msgs)
    now = datetime.now(timezone.utc).isoformat()
    for u in users:
        db.update("unlocks", f"episode_id=eq.{episode_id}&user_id=eq.{u}", {"ready_pushed_at": now})
    log.info("push study-ready %s: %d message(s)", title, len(msgs))
    return len(msgs)


def new_episodes(db, max_per_user: int = 3) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
    eps = db.select("episodes", "select=id,title,show_id,shows(title)&notified_at=is.null"
                                f"&published_at=gte.{since}&order=published_at.desc&limit=200")
    if not eps:
        return 0
    show_ids = ",".join(sorted({e["show_id"] for e in eps}))
    subs: dict[str, set[str]] = {}
    for s in db.select("subscriptions", f"select=user_id,show_id&show_id=in.({show_ids})"):
        subs.setdefault(s["show_id"], set()).add(s["user_id"])
    toks = _tokens(db, set().union(*subs.values()) if subs else set(), "notify_new_eps")
    msgs, per_user = [], {}
    for e in eps:
        for u in subs.get(e["show_id"], ()):
            if u not in toks or per_user.get(u, 0) >= max_per_user:
                continue
            per_user[u] = per_user.get(u, 0) + 1
            show = (e.get("shows") or {}).get("title") or "새 에피소드"
            msgs += [{"to": tok, "title": f"{show} 새 에피소드", "body": e["title"][:120], "sound": "default",
                      "channelId": "default", "data": {"episode": e["id"]}} for tok in toks[u]]
    _send(msgs)
    now = datetime.now(timezone.utc).isoformat()
    for e in eps:
        db.update("episodes", f"id=eq.{e['id']}", {"notified_at": now})
    # anything older that slipped through is marked too, so it is never announced late
    db.update("episodes", f"notified_at=is.null&published_at=lt.{since}", {"notified_at": now})
    log.info("push new-episodes: %d episode(s), %d message(s)", len(eps), len(msgs))
    return len(msgs)

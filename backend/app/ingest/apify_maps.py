"""Apify data collection layer: Google Maps scraper (compass/crawler-google-places) with token switching.

Ported from leadgen/leadgen/sources/apify.py:
- picks the account with the most real credit, switches on HTTP 401/402/403 or a failed run;
- async run + poll (max 5 min, then abort and keep what was found);
- never falls back silently: no credit -> NoApifyCredit with the reason per token.
"""
from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

from . import apify_tokens as tk
from .gulf import COUNTRIES, INDUSTRIES
from .normalize import format_phone, normalize_url

ACTOR = "compass~crawler-google-places"
SOURCE_TYPE = "apify:compass/crawler-google-places"
PRICE_PER_PLACE = 0.004    # FREE plan, read from the actor's pricing on 30 Oct 2026
PRICE_PER_REVIEW = 0.0005
MIN_RUN_USD = 0.5          # the actor refuses runs capped below this
RUN_TIMEOUT_SECONDS = 300
POLL_SECONDS = 5
MIN_REVIEWS, MAX_REVIEWS = 50, 1000  # default review range, every industry (the search form can change it)
MAX_PARALLEL = 6           # Apify runs at the same time (each city x industry is its own cloud run)
ACCOUNT_FULL_WAIT = 15     # seconds to wait when an account already runs as many actors as its plan allows
ACCOUNT_FULL_RETRIES = 40
LOG_DRAIN_SECONDS = 2
DONE = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}

Log = Callable[[str], None]


class NoApifyCredit(Exception):
    pass


@dataclass(frozen=True)
class StandardRecord:
    """One business as collected, before it is saved. Field sources travel with it."""
    name: str
    country: str
    city: str
    industry: str
    category: str = ""
    area: str = ""
    website_url: str = ""
    phone: str = ""
    phone_type: str = ""
    email: str = ""
    maps_url: str = ""
    place_id: str = ""
    rating: float | None = None
    review_count: int | None = None
    last_review_date: str = ""
    opening_hours: tuple[str, ...] = ()
    social_links: tuple[str, ...] = ()
    lat: float | None = None
    lon: float | None = None
    temporarily_closed: bool = False
    source_url: str = ""
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CollectResult:
    records: tuple[StandardRecord, ...]
    spent_usd: float
    problem: str = ""
    runs: tuple[dict, ...] = ()   # {run_id, account, status, items, cost} per actor run


class TokenPool:
    """Shared by the parallel runs: spreads them over accounts (least busy first, then most credit)."""

    def __init__(self, log: Log = print):
        self.log = log
        self.dead: dict[str, str] = {}
        self.busy: dict[str, int] = {}
        self.lock = threading.Lock()

    def pick(self, need_usd: float = MIN_RUN_USD) -> tuple[str, tk.TokenStatus]:
        with self.lock:
            best: tuple[str, tk.TokenStatus] | None = None
            for t in tk.tokens():
                if t in self.dead:
                    continue
                st = tk.status(t, fresh=True)
                if not st.ok:
                    self.dead[t] = st.message
                elif (st.remaining_usd or 0) < need_usd:
                    self.dead[t] = f"only ${st.remaining_usd} left"
                elif not best or (self.busy.get(t, 0), -(st.remaining_usd or 0)) < \
                        (self.busy.get(best[0], 0), -(best[1].remaining_usd or 0)):
                    best = (t, st)
            if not best:
                why = "; ".join(f"{tk.mask(t)}: {r}" for t, r in self.dead.items()) or "no Apify token saved"
                raise NoApifyCredit(why)
            self.busy[best[0]] = self.busy.get(best[0], 0) + 1
            return best

    def done(self, token: str) -> None:
        with self.lock:
            self.busy[token] = max(0, self.busy.get(token, 0) - 1)

    def kill(self, token: str, why: str) -> None:
        with self.lock:
            self.dead[token] = why
        self.log(f"apify: account {tk.mask(token)} switched off ({why}), trying the next one")


def _cost(run: dict, n_items: int) -> float:
    ev = run.get("chargedEventCounts") or {}
    if ev:
        return ev.get("place-scraped", 0) * PRICE_PER_PLACE + ev.get("review-scraped", 0) * PRICE_PER_REVIEW
    return n_items * (PRICE_PER_PLACE + PRICE_PER_REVIEW)


def _wait(token: str, run: dict, log: Log) -> dict:
    t0, last = time.time(), ""
    aborted = False
    while run["status"] not in DONE:
        if not aborted and time.time() - t0 > RUN_TIMEOUT_SECONDS:
            log("apify: 5 minutes passed, stopping the run and keeping what it found")
            tk.apify_post(token, f"/actor-runs/{run['id']}/abort")
            aborted = True
        if time.time() - t0 > RUN_TIMEOUT_SECONDS + 60:
            break
        time.sleep(POLL_SECONDS)
        g = tk.apify_get(token, f"/actor-runs/{run['id']}")
        if g.status_code == 200:
            run = g.json()["data"]
        msg = run.get("statusMessage") or run["status"]
        if msg != last:
            log(f"apify: {run['status']} - {msg[:120]}")
            last = msg
    return run


def run_actor(pool: TokenPool, run_input: dict, cap_usd: float, log: Log = print) -> tuple[list[dict], float, dict]:
    """Run once, switching accounts until one starts. Returns (items, approx USD, run info)."""
    full_waits = 0
    while True:
        token, st = pool.pick(min(cap_usd, MIN_RUN_USD))
        try:
            cap = round(max(MIN_RUN_USD, min(cap_usd, st.remaining_usd or 0)), 2)
            r = tk.apify_post(token, f"/acts/{ACTOR}/runs", params={"maxTotalChargeUsd": cap}, json=run_input)
            err = (r.json().get("error", {}).get("type", "") if r.content and r.status_code >= 400 else "") or ""
            if r.status_code in (402, 429) and ("memory" in err or "concurrent" in err) and full_waits < ACCOUNT_FULL_RETRIES:
                full_waits += 1  # the account is running as many actors as its plan allows: wait for a free slot
                log(f"apify: account {st.username or tk.mask(token)} is full ({err}), waiting {ACCOUNT_FULL_WAIT}s")
                time.sleep(ACCOUNT_FULL_WAIT)
                continue
            if r.status_code in (401, 402, 403):
                pool.kill(token, f"HTTP {r.status_code} {err}".strip())
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Apify refused the run: HTTP {r.status_code} {r.text[:200]}")
            run = r.json()["data"]
            who = st.username or tk.mask(token)
            log(f"apify: run {run['id']} started on account {who} (cap ${cap}, ${st.remaining_usd} left)")
            run = _wait(token, run, log)
            ds = tk.apify_get(token, f"/datasets/{run['defaultDatasetId']}/items?clean=true&format=json", timeout=120)
            items = ds.json() if ds.status_code == 200 else []
            spent = _cost(run, len(items))
            tk.status(token, fresh=True)  # refresh the real balance shown in the dashboard
        finally:
            pool.done(token)
        info = {"run_id": run["id"], "account": who, "status": run["status"], "items": len(items),
                "cost_usd": round(spent, 4)}
        if run["status"] == "FAILED" and not items:
            pool.kill(token, f"run failed: {(run.get('statusMessage') or '')[:80]}")
            continue
        log(f"apify: {run['status']}, {len(items)} places, about ${spent:.2f}")
        return items, spent, info


def _city_of(item: dict, country: str, fallback: str) -> str:
    """City from the item's own address, matched to our city list when possible."""
    item_city = (item.get("city") or item.get("state") or "").strip()
    if not item_city:
        return fallback
    known = COUNTRIES[country]["cities"]
    return next((c for c in known if c.lower() in item_city.lower() or item_city.lower() in c.lower()), item_city)


def to_record(item: dict, country: str, city: str, industry: str) -> StandardRecord | None:
    if item.get("permanentlyClosed") or not (item.get("title") or "").strip():
        return None
    phone, kind = format_phone(item.get("phoneUnformatted") or item.get("phone"), country)
    reviews = item.get("reviews") or []
    loc = item.get("location") or {}
    hours = tuple(f"{h.get('day', '')}: {h.get('hours', '')}" for h in (item.get("openingHours") or []) if h)
    socials = tuple(dict.fromkeys(
        v for k, v in item.items()
        if isinstance(v, str) and k in ("facebook", "instagram", "linkedin", "twitter", "youtube", "tiktok") and v
    ))
    return StandardRecord(
        name=item["title"].strip(), country=country, city=_city_of(item, country, city), industry=industry,
        category=item.get("categoryName") or "", area=item.get("neighborhood") or item.get("street") or "",
        website_url=normalize_url(item.get("website")), phone=phone, phone_type=kind,
        email=(item.get("emails") or [""])[0] if isinstance(item.get("emails"), list) else "",
        maps_url=item.get("url") or "", place_id=item.get("placeId") or "",
        rating=item.get("totalScore"), review_count=item.get("reviewsCount"),
        last_review_date=max((r.get("publishedAtDate") or "" for r in reviews), default="")[:10],
        opening_hours=hours, social_links=socials, lat=loc.get("lat"), lon=loc.get("lng"),
        temporarily_closed=bool(item.get("temporarilyClosed")), source_url=item.get("url") or "",
    )


def estimate_usd(n_cities: int, industries: list[str], per_search: int) -> float:
    places = sum(len(INDUSTRIES[i]["search_terms"]) for i in industries) * per_search * n_cities
    return round(places * (PRICE_PER_PLACE + PRICE_PER_REVIEW), 2)


def _run_input(country: str, city: str, ind: str, per_search: int) -> dict:
    return {
        "searchStringsArray": INDUSTRIES[ind]["search_terms"],
        "locationQuery": f"{city}, {COUNTRIES[country]['name']}",
        "maxCrawledPlacesPerSearch": per_search,
        "language": "en",
        "maxReviews": 1,
        "reviewsSort": "newest",
        "scrapeReviewsPersonalData": False,
    }


def collect(targets: list[tuple[str, str]], industries: list[str], budget_usd: float, per_search: int = 40,
            log: Log = print, *, min_reviews: int = MIN_REVIEWS, max_reviews: int = MAX_REVIEWS,
            parallel: int = MAX_PARALLEL,
            on_batch: Callable[[list[StandardRecord], dict], None] | None = None) -> CollectResult:
    """All (country, city) x industries, one actor run each, up to `parallel` at the same time.

    Each run reserves its own share of the budget before it starts, so parallel runs never overspend the cap;
    what a run did not use goes back for the next one. `on_batch` gets every finished run's places at once
    (on the calling thread), so the caller can save results while other cities are still running.
    """
    if budget_usd < MIN_RUN_USD:
        return CollectResult((), 0.0, f"Budget must be at least ${MIN_RUN_USD}")
    msgs: queue.Queue[str] = queue.Queue()  # worker threads only queue log lines; the caller's log runs here

    def drain() -> None:
        while not msgs.empty():
            log(msgs.get_nowait())

    pool = TokenPool(msgs.put)
    todo = [(cc, city, ind) for cc, city in targets for ind in industries]
    per_run = {ind: len(INDUSTRIES[ind]["search_terms"]) * per_search * (PRICE_PER_PLACE + PRICE_PER_REVIEW)
               for ind in industries}
    records: list[StandardRecord] = []
    runs: list[dict] = []
    spent = reserved = 0.0
    problem = ""
    active: dict[Future, tuple[str, str, str, float]] = {}
    log(f"apify: {len(todo)} runs, up to {parallel} at the same time")
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        while todo or active:
            while todo and not problem and len(active) < parallel:
                cc, city, ind = todo[0]
                left = budget_usd - spent - reserved
                share = min(left, max(MIN_RUN_USD, per_run[ind]))
                if share < MIN_RUN_USD:
                    break  # wait for a running city to give back what it did not use
                todo.pop(0)
                reserved += share
                msgs.put(f"apify: {city} / {ind}: {len(INDUSTRIES[ind]['search_terms'])} searches x {per_search} places")
                active[ex.submit(run_actor, pool, _run_input(cc, city, ind, per_search), share, msgs.put)] = (cc, city, ind, share)
            if not active:
                if todo and not problem:
                    msgs.put(f"apify: budget used up (${spent:.2f} of ${budget_usd}), {len(todo)} run(s) not started")
                break
            finished, _ = wait(active, timeout=LOG_DRAIN_SECONDS, return_when=FIRST_COMPLETED)
            drain()
            for fut in finished:
                cc, city, ind, share = active.pop(fut)
                reserved -= share
                try:
                    items, cost, info = fut.result()
                except NoApifyCredit as e:
                    msgs.put(f"apify: NO CREDIT on any account ({e})")
                    problem = problem or f"No Apify credit: {e}"
                    continue
                except (RuntimeError, requests.RequestException) as e:
                    msgs.put(f"apify: ERROR {city} / {ind}: {e}")
                    problem = problem or f"Apify error: {e}"
                    continue
                spent += cost
                info = {**info, "city": city, "country": cc, "industry": ind}
                runs.append(info)
                found = [r for r in (to_record(it, cc, city, ind) for it in items) if r]
                kept = [r for r in found if min_reviews <= (r.review_count or 0) <= max_reviews]
                if len(kept) < len(found):
                    msgs.put(f"apify: {city} / {ind}: {len(found) - len(kept)} places skipped "
                             f"(reviews outside {min_reviews}-{max_reviews})")
                records += kept
                drain()
                if on_batch and kept:
                    on_batch(kept, info)
    drain()
    return CollectResult(tuple(records), spent, problem, tuple(runs))

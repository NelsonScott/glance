#!/usr/bin/env python3
"""Browserless comedy showtimes — a drop-in replacement for comedy.py's get_comedy().

POC (branch poc/browserless-backend): proves the three comedy venues can be scraped
with plain `requests` + stdlib, NO Playwright/Chromium. This matters for moving the
feed service onto the Khadas (HAOS, ~1.8 GB RAM free, already swapping) or a Pi —
headless Chromium is the one dependency that box can't comfortably host.

Data paths reverse-engineered from the live sites:
  * Second City  — Next.js page embeds __NEXT_DATA__; each show's detail page carries
    entityResolver.patronticketData = base64(JSON) whose .instances[] hold the
    showtimes as .formattedDates.ISO8601 (UTC). (PatronTicket / Salesforce backend.)
  * Flop House   — the Vue app fetches a static CloudFront JSON per venue:
    https://d1qsplg11xrlby.cloudfront.net/venues/<venueId>_events.json
    Each event has startTime as epoch-ms. Williamsburg venueId is the color-"" one.
  * Old Man Hustle — donyc.com server-renders .ds-listing cards with [datetime] attrs;
    the times are in the static HTML (no JS needed), so a regex pass is enough.

Output shape matches comedy.py exactly:
    {"venues": [{"venue": ..., "shows": [{"title","time","date"}, ...]}, ...],
     "updated": "HH:MM"}
A venue that fails or finds nothing returns an empty `shows` list plus a `note`.
"""
import re
import json
import time
import base64
import pathlib
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import requests

NY = ZoneInfo("America/New_York")
HERE = pathlib.Path(__file__).resolve().parent
CACHE_FILE = HERE / "comedy-cache.json"      # same cache file/shape as comedy.py
CACHE_TTL_SEC = 60 * 30
MAX_SHOWS = 4
TIMEOUT = 20

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})


def _now():
    return dt.datetime.now(NY).strftime("%H:%M")


def _today():
    return dt.datetime.now(NY).date()


def _fmt_time(d: dt.datetime) -> str:
    """datetime (NY-aware) -> '9:30pm' (lowercase, no leading zero)."""
    return d.strftime("%-I:%M%p").lower()


def _next_data(html: str):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Second City NY  (Next.js + PatronTicket)
# ---------------------------------------------------------------------------
SC_LIST = "https://www.secondcity.com/shows/new-york"
SC_BASE = "https://www.secondcity.com"
SC_MAX_DETAIL = 14   # detail pages to fetch before giving up (cheap HTTP GETs now)


def _sc_show_uris(html: str):
    nd = _next_data(html)
    if not nd:
        return []
    qs = nd.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    shows = next((q for q in qs if q.get("queryKey", [None])[0] == "shows"), None)
    if not shows:
        return []
    nodes = shows.get("state", {}).get("data", {}).get("nodes", []) or []
    uris = []
    for n in nodes:
        uri = n.get("uri")
        if uri and uri.count("/") > 2 and uri not in uris:   # skip the list root
            uris.append(uri)
    return uris


def _sc_instances(detail_html: str):
    """Return (show_name, [NY-aware datetimes]) from a detail page's patronticketData."""
    nd = _next_data(detail_html)
    if not nd:
        return None, []
    qs = nd.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    er = next((q for q in qs if q.get("queryKey", [None])[0] == "entityResolver"), None)
    if not er:
        return None, []
    data = er.get("state", {}).get("data", {}) or {}
    name = data.get("title")
    ptd = (data.get("patronticketData") or {}).get("patronticketData")
    if not ptd:
        return name, []
    try:
        pt = json.loads(base64.b64decode(ptd))
    except Exception:
        return name, []
    name = pt.get("name") or name
    out = []
    for inst in pt.get("instances", []) or []:
        iso = (inst.get("formattedDates") or {}).get("ISO8601")
        if not iso:
            continue
        try:
            d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(NY)
        except ValueError:
            continue
        out.append(d)
    return name, out


def scrape_second_city():
    shows, note = [], None
    try:
        r = SESSION.get(SC_LIST, timeout=TIMEOUT)
        r.raise_for_status()
        uris = _sc_show_uris(r.text)[:SC_MAX_DETAIL]
        today = _today()
        by_date = {}   # iso -> [show dicts]

        def _fetch(uri):
            url = SC_BASE + uri if uri.startswith("/") else uri
            try:
                dr = SESSION.get(url, timeout=TIMEOUT)
                dr.raise_for_status()
                return _sc_instances(dr.text)
            except Exception:
                return None, []

        # detail pages are independent cheap GETs — fetch them concurrently
        with ThreadPoolExecutor(max_workers=8) as pool:
            for name, times in pool.map(_fetch, uris):
                for d in times:
                    if d.date() < today:
                        continue
                    iso = d.date().isoformat()
                    by_date.setdefault(iso, []).append(
                        {"title": name or "Second City Show", "time": _fmt_time(d), "date": iso})
        if by_date:
            soonest = min(by_date)
            shows = sorted(by_date[soonest], key=lambda s: s["time"])[:MAX_SHOWS]
        else:
            note = "no upcoming showtimes found in patronticketData"
    except Exception as e:
        note = f"scrape error: {type(e).__name__}: {str(e)[:80]}"
    out = {"venue": "Second City", "shows": shows}
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Flop House  (static Vue build — the real schedule is baked into the JS bundle)
# ---------------------------------------------------------------------------
# flophousecomedy.com is a static Vue SPA: the homepage HTML is an empty shell,
# and the show list is hardcoded into /js/app.<hash>.js at build time as objects
# like {title:"..",description:"web-..",startTime:<epoch-ms>,endTime:..,url:"..",color:".."}.
# (The per-venue _events.json on CloudFront exists but currently holds only test
# data — the baked array is what the site actually renders.) The bundle hash
# changes on each rebuild, so resolve it from the homepage each time.
# color "9" == East Village (83 1st Ave); anything else == 362 Grand St (Williamsburg).
FLOP_HOME = "https://flophousecomedy.com/"
_FLOP_OBJ = re.compile(
    r'\{title:"((?:[^"\\]|\\.)*)",description:"web-[0-9a-f\-]+",'
    r'startTime:([0-9.e+]+),endTime:[0-9.e+]+,url:"[^"]*"(.*?)\}', re.S)


def scrape_flop_house():
    shows, note = [], None
    try:
        home = SESSION.get(FLOP_HOME, timeout=TIMEOUT)
        home.raise_for_status()
        m = re.search(r'src="(/js/app\.[0-9a-f]+\.js)"', home.text)
        if not m:
            raise RuntimeError("could not find app.js bundle in homepage")
        bundle = SESSION.get(FLOP_HOME.rstrip("/") + m.group(1), timeout=TIMEOUT)
        bundle.raise_for_status()
        today = _today()
        rows = []
        for title, st, rest in _FLOP_OBJ.findall(bundle.text):
            color = re.search(r'color:"([^"]*)"', rest)
            if color and color.group(1) == "9":       # East Village — skip
                continue
            try:
                d = dt.datetime.fromtimestamp(float(st) / 1000, NY)
            except (ValueError, OverflowError):
                continue
            if d.date() < today:
                continue
            title = title.encode().decode("unicode_escape")
            rows.append({"title": title[:90], "time": _fmt_time(d),
                         "date": d.date().isoformat(), "_dt": d})
        if rows:
            rows.sort(key=lambda s: s["_dt"])
            soonest = rows[0]["date"]
            shows = [{k: v for k, v in s.items() if k != "_dt"}
                     for s in rows if s["date"] == soonest][:MAX_SHOWS]
        else:
            note = "no upcoming Williamsburg shows in bundle"
    except Exception as e:
        note = f"scrape error: {type(e).__name__}: {str(e)[:80]}"
    out = {"venue": "Flop House", "shows": shows}
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Old Man Hustle / BKLYN Comedy Club  (donyc, static HTML)
# ---------------------------------------------------------------------------
OMH_URL = "https://donyc.com/venues/old-man-hustle-bklyn-comedy-club"


def scrape_old_man_hustle():
    shows, note = [], None
    try:
        r = SESSION.get(OMH_URL, timeout=TIMEOUT)
        r.raise_for_status()
        h = r.text
        today_iso = _today().isoformat()
        rows, seen = [], set()
        # donyc renders each event as: a .ds-listing-event-title-text span (the title),
        # then a <meta itemprop="startDate" datetime="YYYY-MM-DDTHH:MM-0400">. Pair each
        # title with the next startDate after it. Both are in the static HTML.
        titles = [(m.start(), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip())
                  for m in re.finditer(
                      r'class="ds-listing-event-title-text"[^>]*>(.*?)</span>', h, re.S)]
        for pos, title in titles:
            sm = re.search(r'itemprop="startDate"[^>]*datetime="(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})',
                           h[pos:pos + 1500])
            if not sm:
                continue
            date, hh, mm = sm.group(1), int(sm.group(2)), int(sm.group(3))
            if date < today_iso:
                continue
            ampm = "am" if hh < 12 else "pm"
            time_txt = f"{hh % 12 or 12}:{mm:02d}{ampm}"
            title = re.sub(r"\s*\d{1,2}/\d{1,2}\s*$", "", title).strip() or "Comedy Show"
            key = (title, date, time_txt)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"title": title[:90], "time": time_txt, "date": date})
        if rows:
            rows.sort(key=lambda s: (s["date"], s["time"]))
            soonest = rows[0]["date"]
            shows = [s for s in rows if s["date"] == soonest][:MAX_SHOWS]
        else:
            note = "no upcoming events with datetime found"
    except Exception as e:
        note = f"scrape error: {type(e).__name__}: {str(e)[:80]}"
    out = {"venue": "Old Man Hustle", "shows": shows}
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Public entrypoint (mirrors comedy.get_comedy)
# ---------------------------------------------------------------------------
def _read_cache():
    try:
        data = json.loads(CACHE_FILE.read_text())
        if time.time() - data.get("_cached_at", 0) < CACHE_TTL_SEC:
            return data.get("payload")
    except Exception:
        pass
    return None


def _write_cache(payload):
    try:
        CACHE_FILE.write_text(json.dumps({"_cached_at": time.time(), "payload": payload}))
    except Exception:
        pass


def get_comedy(use_cache=True):
    if use_cache:
        cached = _read_cache()
        if cached:
            return cached
    venues = []
    for scraper in (scrape_second_city, scrape_flop_house, scrape_old_man_hustle):
        try:
            venues.append(scraper())
        except Exception as e:
            name = scraper.__name__.replace("scrape_", "").replace("_", " ").title()
            venues.append({"venue": name, "shows": [],
                           "note": f"fatal: {type(e).__name__}: {str(e)[:80]}"})
    payload = {"venues": venues, "updated": _now()}
    _write_cache(payload)
    return payload


if __name__ == "__main__":
    t0 = time.time()
    result = get_comedy(use_cache=False)
    print(json.dumps(result, indent=2))
    print(f"\n# browserless scrape took {time.time() - t0:.1f}s", flush=True)

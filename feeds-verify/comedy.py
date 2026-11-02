#!/usr/bin/env python3
"""Comedy showtimes for three Williamsburg venues, for the glance dashboard.

All three target sites are PUBLIC (no login), so this uses STANDALONE Playwright
in the project's own venv — not OpenClaw's managed Chrome over CDP. (The CDP-attach
pattern in the OpenClaw watchers — amazon-package-watcher / cryobank-watcher etc. —
is specifically for AUTH-WALLED pages that need the logged-in OpenClaw session;
the documented rule is "don't share a Chrome profile between Playwright and
OpenClaw, attach over CDP instead" — which does NOT apply to public pages.)

Conventions mirrored from the prior art (notebooklm / content-miner / the watchers)
and from this project's own nitehawk.py:
  * structured JSON output, error strings capped (str(e)[:N]) like providers.py
  * graceful per-venue try/except — one venue failing never kills the others
  * on-failure debug capture (screenshot + a note) under comedy-debug/
  * result caching to comedy-cache.json (a full scrape is slow; see __main__ timing)
  * TZ = America/New_York as UTC-4 and an _now() "HH:MM" stamp, like providers.py
  * "tonight, else roll to the next day with shows" — same idea as nitehawk's
    get_next_showtimes()

Venues:
  * Second City NY  — secondcity.com (Next.js + react-datepicker; showtimes render
    client-side into a "Next Available Showtimes" block on each show's detail page).
  * Flop House      — flophousecomedy.com/shows (JS-rendered; .card-container cards).
  * Old Man Hustle / BKLYN Comedy Club — donyc.com aggregator (events carry
    [datetime] attrs inside .ds-listing-details).

Runnable standalone: `python comedy.py` prints get_comedy() as JSON.
"""
import re
import json
import time
import pathlib
import datetime as dt

from playwright.sync_api import sync_playwright

TZ = dt.timezone(dt.timedelta(hours=-4))  # America/New_York (EDT), matches providers.py
HERE = pathlib.Path(__file__).resolve().parent
DEBUG_DIR = HERE / "comedy-debug"
CACHE_FILE = HERE / "comedy-cache.json"
CACHE_TTL_SEC = 60 * 30  # 30 min — the dashboard caches; a scrape is too slow per-hit

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MAX_SHOWS = 4  # cap per venue


def _now():
    return dt.datetime.now(TZ).strftime("%H:%M")


def _today():
    return dt.datetime.now(TZ).date()


def _norm_time(s):
    """'7:00 PM' / '8:00pm' -> '8:00pm' (lowercase, no spaces)."""
    m = re.search(r"\d{1,2}:\d{2}\s*[ap]\.?m\.?", s, re.I)
    if not m:
        return None
    return re.sub(r"[.\s]", "", m.group(0)).lower()


def _save_debug(page, venue):
    """Best-effort screenshot on failure, like the watchers' debug/<reason> capture."""
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        stamp = dt.datetime.now(TZ).strftime("%Y%m%dT%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", venue.lower()).strip("-")
        path = DEBUG_DIR / f"{stamp}-{slug}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Second City NY
# ---------------------------------------------------------------------------
SC_LIST = "https://www.secondcity.com/shows/new-york"
SC_BASE = "https://www.secondcity.com"
# How many detail pages to open before giving up (each is a slow render).
SC_MAX_DETAIL = 12

# Parses the rendered "Next Available Showtimes" block, e.g.:
#   "Next Available Showtimes  SUNDAY • JUNE 07, 2026  Tickets starting at $10
#    7:00 PM - BUY NOW  9:30 PM - BUY NOW"
_SC_DATEHDR = re.compile(
    r"(MON|TUE|WED|THU|FRI|SAT|SUN)[A-Z]*\s*[•\-–]\s*"
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2}),?\s*(\d{4})",
    re.I,
)
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _sc_parse_detail(page):
    """From a rendered Second City show detail page, return (iso_date, [times]) for
    the next available showtimes block, or (None, []) if none are scheduled."""
    txt = page.evaluate("() => document.body.innerText")
    i = txt.lower().find("next available showtimes")
    if i < 0:
        return None, []
    seg = txt[i:i + 600]
    m = _SC_DATEHDR.search(seg)
    iso = None
    if m:
        mon = _MONTHS.get(m.group(2)[:3].lower())
        if mon:
            try:
                iso = dt.date(int(m.group(4)), mon, int(m.group(3))).isoformat()
            except ValueError:
                iso = None
    # times appear as "7:00 PM - BUY NOW"; only take ones tied to BUY/SOLD
    times = []
    for tm in re.finditer(r"(\d{1,2}:\d{2}\s*[ap]m)\s*[-–]\s*(BUY NOW|SOLD OUT|TICKETS?)",
                          seg, re.I):
        t = _norm_time(tm.group(1))
        if t and t not in times:
            times.append(t)
    if not times:  # fallback: any time token in the block
        for tm in re.finditer(r"\d{1,2}:\d{2}\s*[ap]m", seg, re.I):
            t = _norm_time(tm.group(0))
            if t and t not in times:
                times.append(t)
    return iso, times


def _scrape_second_city(browser):
    shows, note = [], None
    page = browser.new_page(user_agent=UA)
    try:
        page.goto(SC_LIST, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        # collect detail-page slugs + their list-card titles
        cards = page.evaluate(r"""() => {
          const seen = new Set(); const out = [];
          document.querySelectorAll('a[href*="/shows/new-york/"]').forEach(a => {
            const href = a.getAttribute('href');
            if (!href || href.split('/').length <= 3) return;     // skip the list root
            if (seen.has(href)) return; seen.add(href);
            // climb to a card to grab the show title
            let n = a, title = '', depth = 0;
            while (n && depth < 6) {
              const h = n.querySelector && n.querySelector('h1,h2,h3');
              if (h && h.innerText.trim()) { title = h.innerText.trim(); break; }
              n = n.parentElement; depth++;
            }
            if (!title) title = a.innerText.trim();
            out.push({ href, title });
          });
          return out;
        }""")
        today = _today()
        best_by_date = {}  # iso -> list of show dicts (keep all, sort later)
        for c in cards[:SC_MAX_DETAIL]:
            # Stop early only when tonight is already fully populated — a later page
            # can't beat today. Otherwise keep scanning the budget (an unscanned show
            # might reveal an earlier date than the best one found so far).
            today_iso = today.isoformat()
            if best_by_date.get(today_iso) and len(best_by_date[today_iso]) >= MAX_SHOWS:
                break
            href = c["href"]
            url = SC_BASE + href if href.startswith("/") else href
            try:
                page.goto(url, wait_until="networkidle", timeout=40000)
                page.wait_for_timeout(2200)
            except Exception:
                continue
            iso, times = _sc_parse_detail(page)
            if not iso or not times:
                continue
            d = dt.date.fromisoformat(iso)
            if d < today:
                continue
            title = (page.evaluate("() => { const h=document.querySelector('h1'); return h?h.innerText.trim():''; }")
                     or c["title"])
            for t in times:
                best_by_date.setdefault(iso, []).append(
                    {"title": title, "time": t, "date": iso})
        if best_by_date:
            # pick the soonest date that has shows (tonight, else next day) — nitehawk logic
            soonest = min(best_by_date)
            picked = best_by_date[soonest][:MAX_SHOWS]
            shows = picked
        else:
            note = "no upcoming showtimes rendered on any NY show detail page"
    except Exception as e:
        note = f"scrape error: {type(e).__name__}: {str(e)[:80]}"
        dbg = _save_debug(page, "second-city")
        if dbg:
            note += f" (debug: {dbg})"
    finally:
        page.close()
    out = {"venue": "Second City", "shows": shows}
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Flop House Comedy
# ---------------------------------------------------------------------------
FLOP_URL = "https://flophousecomedy.com/shows"


def _scrape_flop_house(browser):
    shows, note = [], None
    page = browser.new_page(user_agent=UA)
    try:
        page.goto(FLOP_URL, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        # Cards look like: "Jun 4 Hannah Jones & Friends 8:00pm - 9:29pm Location: 362 Grand Street ..."
        raw = page.evaluate(r"""() => {
          const out = []; const seen = new Set();
          document.querySelectorAll('.card-container, [class*="card-container"]').forEach(c => {
            const t = c.innerText.replace(/\s+/g, ' ').trim();
            if (!t || seen.has(t)) return; seen.add(t);
            if (!/\d{1,2}:\d{2}\s*[ap]m/i.test(t)) return;
            out.push(t);
          });
          return out;
        }""")
        year = _today().year
        parsed = []
        for t in raw:
            # date: "Jun 4"
            dm = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\b", t, re.I)
            tm = re.search(r"(\d{1,2}:\d{2}\s*[ap]m)", t, re.I)
            if not dm or not tm:
                continue
            mon = _MONTHS.get(dm.group(1)[:3].lower())
            try:
                d = dt.date(year, mon, int(dm.group(2)))
            except ValueError:
                continue
            # roll year forward if the listing wrapped past December
            if d < _today() - dt.timedelta(days=120):
                d = d.replace(year=year + 1)
            time_txt = _norm_time(tm.group(1))
            # title = text between the date token and the time token
            seg = t[dm.end():tm.start()].strip(" -–·,")
            title = re.split(r"\bLocation:?\b", seg, flags=re.I)[0].strip(" -–·,")
            title = re.sub(r"\s+", " ", title).strip()
            # Flop House renders two card variants per show; the "Jun 2, 8:00pm - ..."
            # summary variant has no title between date and time. Skip those — the
            # titled variant (handled here) carries the real name. Drop empties.
            if not title or not re.search(r"[A-Za-z]{3}", title):
                continue
            parsed.append({"title": title[:90], "time": time_txt, "date": d.isoformat()})
        # dedupe (title,date,time)
        seen = set()
        dedup = []
        for s in parsed:
            k = (s["title"], s["date"], s["time"])
            if k in seen:
                continue
            seen.add(k)
            dedup.append(s)
        today_iso = _today().isoformat()
        upcoming = sorted([s for s in dedup if s["date"] >= today_iso],
                          key=lambda s: (s["date"], s["time"]))
        if upcoming:
            soonest = upcoming[0]["date"]
            shows = [s for s in upcoming if s["date"] == soonest][:MAX_SHOWS]
        else:
            note = "no upcoming Williamsburg shows parsed"
    except Exception as e:
        note = f"scrape error: {type(e).__name__}: {str(e)[:80]}"
        dbg = _save_debug(page, "flop-house")
        if dbg:
            note += f" (debug: {dbg})"
    finally:
        page.close()
    out = {"venue": "Flop House", "shows": shows}
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Old Man Hustle / BKLYN Comedy Club (via donyc aggregator)
# ---------------------------------------------------------------------------
OMH_URL = "https://donyc.com/venues/old-man-hustle-bklyn-comedy-club"


def _scrape_old_man_hustle(browser):
    shows, note = [], None
    page = browser.new_page(user_agent=UA)
    try:
        page.goto(OMH_URL, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        # Each event row is a .ds-listing.event-card; the showtime is a [datetime]
        # in its .ds-listing-details, and the title is the /events/ link on the card.
        raw = page.evaluate(r"""() => {
          const out = [];
          document.querySelectorAll('.ds-listing.event-card, .ds-listing.ds-event-card').forEach(card => {
            const dt = card.querySelector('[datetime]');
            const iso = dt ? dt.getAttribute('datetime') : null;
            if (!iso) return;
            // title: the event link (skip nav links like Today/Tomorrow/Add Event/venue)
            let title = '';
            card.querySelectorAll('a[href*="/events/"]').forEach(a => {
              const h = a.getAttribute('href') || '';
              if (/\/events\/(today|tomorrow|new|this-|free|giveaways)/i.test(h)) return;
              const t = a.innerText.replace(/\s+/g, ' ').trim();
              if (t && !title) title = t;
            });
            if (!title) {
              const te = card.querySelector('.ds-listing-event-title, h2, h3');
              if (te) title = te.innerText.replace(/\s+/g, ' ').trim();
            }
            out.push({ iso, title });
          });
          return out;
        }""")
        today_iso = _today().isoformat()
        parsed = []
        for r in raw:
            iso = r["iso"]
            # datetime like "2026-06-04T20:00-0400"
            m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", iso)
            if not m:
                continue
            date = m.group(1)
            if date < today_iso:
                continue
            h, mn = int(m.group(2)), int(m.group(3))
            ampm = "am" if h < 12 else "pm"
            h12 = h % 12 or 12
            time_txt = f"{h12}:{mn:02d}{ampm}"
            title = r["title"] or "Comedy Show"
            # donyc titles often carry the venue name / a trailing date — trim
            title = re.sub(r"\s*OLD MAN HUSTLE.*$", "", title, flags=re.I).strip()
            title = re.sub(r"\s*\d{1,2}/\d{1,2}\s*$", "", title).strip()
            title = re.split(r"\b\d{1,2}:\d{2}\s*[AP]M\b", title)[0].strip(" -–·")
            if not title:
                title = "Comedy Show"
            parsed.append({"title": title[:90], "time": time_txt, "date": date})
        # dedupe
        seen = set()
        dedup = []
        for s in parsed:
            k = (s["title"], s["date"], s["time"])
            if k in seen:
                continue
            seen.add(k)
            dedup.append(s)
        dedup.sort(key=lambda s: (s["date"], s["time"]))
        if dedup:
            soonest = dedup[0]["date"]
            shows = [s for s in dedup if s["date"] == soonest][:MAX_SHOWS]
        else:
            note = "no upcoming events with datetime found on donyc page"
    except Exception as e:
        note = f"scrape error: {type(e).__name__}: {str(e)[:80]}"
        dbg = _save_debug(page, "old-man-hustle")
        if dbg:
            note += f" (debug: {dbg})"
    finally:
        page.close()
    out = {"venue": "Old Man Hustle", "shows": shows}
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
def _read_cache():
    try:
        data = json.loads(CACHE_FILE.read_text())
        if time.time() - data.get("_cached_at", 0) < CACHE_TTL_SEC:
            payload = data.get("payload")
            if payload:
                return payload
    except Exception:
        pass
    return None


def _write_cache(payload):
    try:
        CACHE_FILE.write_text(json.dumps({"_cached_at": time.time(), "payload": payload}))
    except Exception:
        pass


def get_comedy(use_cache=True):
    """Return tonight's (or the next available day's) comedy lineups for the three
    Williamsburg venues. Shape:
        {"venues": [
            {"venue": "Second City",    "shows": [{"title","time","date"}, ...]},
            {"venue": "Flop House",     "shows": [...]},
            {"venue": "Old Man Hustle", "shows": [...]}],
         "updated": "HH:MM"}
    A venue that fails or finds nothing returns an empty `shows` list plus a `note`.
    """
    if use_cache:
        cached = _read_cache()
        if cached:
            return cached

    venues = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for scraper in (_scrape_second_city, _scrape_flop_house, _scrape_old_man_hustle):
                try:
                    venues.append(scraper(browser))
                except Exception as e:
                    # belt-and-suspenders: a scraper raising before its own try/except
                    name = scraper.__name__.replace("_scrape_", "").replace("_", " ").title()
                    venues.append({"venue": name, "shows": [],
                                   "note": f"fatal: {type(e).__name__}: {str(e)[:80]}"})
        finally:
            browser.close()

    payload = {"venues": venues, "updated": _now()}
    _write_cache(payload)
    return payload


if __name__ == "__main__":
    t0 = time.time()
    result = get_comedy(use_cache=False)
    elapsed = time.time() - t0
    print(json.dumps(result, indent=2))
    print(f"\n# scrape took {elapsed:.1f}s", flush=True)

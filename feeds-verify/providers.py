#!/usr/bin/env python3
"""Extra data providers for the glance dashboard:
   Citi Bike · Air Quality · Knicks · Local events (Gmail) · MTA L alerts.
   Each returns a plain dict; failures degrade gracefully.
"""
import json, math, subprocess, os, re, time, html as ihtml, datetime as dt
import xml.etree.ElementTree as ET
import requests
from google.transit import gtfs_realtime_pb2

LAT, LON = 40.7222, -73.9573          # general North Williamsburg (weather/AQI)
HOME_LAT, HOME_LON = 40.7205, -73.9628  # by Kent Ave & N 5 St (Scott's usual = N 5 St & Northside Piers)
TZ = dt.timezone(dt.timedelta(hours=-4))
UA = {"User-Agent": "Mozilla/5.0"}
def _now(): return dt.datetime.now(TZ).strftime("%H:%M")

# --------------------------------------------------------------- Citi Bike
PREFERRED_STATION = "N 5 St & Northside Piers"  # Scott's go-to — always pinned first
_cb_info = {"ts": 0, "stations": None}  # station list is ~static; cache it 1h, only poll live status
def citibike(n=3):
    now = time.time()
    if _cb_info["stations"] is None or now - _cb_info["ts"] > 3600:
        _cb_info["stations"] = requests.get(
            "https://gbfs.citibikenyc.com/gbfs/en/station_information.json", timeout=10).json()["data"]["stations"]
        _cb_info["ts"] = now
    info = _cb_info["stations"]
    status = {s["station_id"]: s for s in requests.get(
        "https://gbfs.citibikenyc.com/gbfs/en/station_status.json", timeout=10).json()["data"]["stations"]}
    def dist(s): return math.hypot(s["lat"] - HOME_LAT, (s["lon"] - HOME_LON) * 0.76)
    pref = next((s for s in info if s["name"] == PREFERRED_STATION), None)
    others = sorted((s for s in info if s is not pref), key=dist)
    near = (([pref] if pref else []) + others)[:n]
    out = []
    for s in near:
        st = status.get(s["station_id"], {})
        miles = math.hypot((s["lat"] - HOME_LAT) * 69, (s["lon"] - HOME_LON) * 52.3)
        out.append({"name": s["name"].replace(" Ave", " Av"),
                    "dist": round(miles, 1),
                    "bikes": st.get("num_bikes_available", 0),
                    "ebikes": st.get("num_ebikes_available", 0),
                    "docks": st.get("num_docks_available", 0)})
    return {"stations": out, "updated": _now()}

# ------------------------------------------------------------- Air Quality
_AQI = [(50, "Good"), (100, "Moderate"), (150, "Unhealthy (sensitive)"),
        (200, "Unhealthy"), (300, "Very Unhealthy"), (9999, "Hazardous")]
def airquality():
    j = requests.get("https://air-quality-api.open-meteo.com/v1/air-quality"
                     "?latitude=%s&longitude=%s&current=us_aqi,pm2_5&timezone=America/New_York"
                     % (LAT, LON), timeout=12).json()["current"]
    aqi = round(j["us_aqi"])
    cat = next(label for cap, label in _AQI if aqi <= cap)
    return {"aqi": aqi, "pm25": round(j["pm2_5"], 1), "category": cat, "updated": _now()}

# ------------------------------------------------------------------ Knicks
def _knicks_game(e):
    comp = e["competitions"][0]; cs = comp["competitors"]
    home = next(c for c in cs if c["homeAway"] == "home")
    away = next(c for c in cs if c["homeAway"] == "away")
    stt = (e.get("status") or comp["status"])["type"]  # scoreboard: top-level; schedule: under comp
    return {"matchup": f'{away["team"]["abbreviation"]} @ {home["team"]["abbreviation"]}',
            "detail": stt["detail"], "state": stt["state"],
            "score": (f'{away["team"]["abbreviation"]} {away.get("score","")} - '
                      f'{home["team"]["abbreviation"]} {home.get("score","")}'
                      if stt["state"] != "pre" else None)}

def knicks(n=2):
    try:
        games, seen = [], set()
        # live / today first
        sb = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
                          timeout=12).json()
        for e in sb.get("events", []):
            if any("Knick" in c["team"]["displayName"] for c in e["competitions"][0]["competitors"]):
                if e["status"]["type"]["state"] in ("in", "pre"):
                    g = _knicks_game(e); games.append(g); seen.add(e["id"])
        # then upcoming from team schedule
        sch = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/ny/schedule",
                           timeout=12).json()
        for ev in sch.get("events", []):
            if ev["id"] in seen:
                continue
            if ev["competitions"][0]["status"]["type"]["state"] == "pre":
                games.append(_knicks_game(ev))
        games = games[:n]
        return {"games": games, "updated": _now()} if games else \
               {"games": [], "detail": "No upcoming game", "updated": _now()}
    except Exception as e:
        return {"games": [], "error": str(e)[:80], "updated": _now()}

# ------------------------------------------------------------ Local events
# Sender allowlist = real event signal (keyword search is too noisy with retail sales).
EVENT_SENDERS = ("ticketmaster.com", "email.livenation.com", "eventbrite.com",
                 "dice.fm", "ra.co", "seatgeek.com", "mail.stubhub.com",
                 "bandsintown.com", "songkick.com", "movies.fandango.com",
                 "othership.us", "nitehawkcinema.com", "brooklynvegan.com")
# domain substring -> (emoji, short "what it is" tag) so each entry explains itself
EVENT_KIND = {
    "ticketmaster": ("🎟️", "Tickets"), "stubhub": ("🎟️", "Resale tickets"),
    "seatgeek": ("🎟️", "Tickets"), "livenation": ("🎤", "Concert"),
    "eventbrite": ("🎉", "Local event"), "dice.fm": ("🎶", "Gig / nightlife"),
    "ra.co": ("🔊", "Club / dance"), "bandsintown": ("🎸", "Live music"),
    "songkick": ("🎸", "Live music"), "fandango": ("🎬", "Movie tickets"),
    "othership": ("🧖", "Sauna social · Wburg"), "nitehawk": ("🍿", "Nitehawk cinema"),
    "brooklynvegan": ("📰", "BK music news"),
}
def _kind(frm):
    f = frm.lower()
    for key, val in EVENT_KIND.items():
        if key in f:
            return val
    return ("📌", "Event")

def _gmail_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", timeout=12, data={
        "client_id": os.environ["GMAIL_CLIENT_ID"],
        "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
        "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
        "grant_type": "refresh_token"})
    r.raise_for_status()
    return r.json()["access_token"]

def _gmail_search(q, max_results=20, want=12):
    """Gmail API equivalent of `gog gmail search` -> [{from, subject, date}].
       Used in the HA add-on (GMAIL_* env set from add-on options); one thread per row."""
    at = _gmail_access_token()
    h = {"Authorization": f"Bearer {at}"}
    base = "https://gmail.googleapis.com/gmail/v1/users/me"
    lst = requests.get(f"{base}/messages", headers=h,
                       params={"q": q, "maxResults": max_results}, timeout=15).json()
    out, seen = [], set()
    for m in lst.get("messages", []):
        tid = m.get("threadId")
        if tid in seen:
            continue
        seen.add(tid)
        msg = requests.get(f"{base}/messages/{m['id']}", headers=h, timeout=12,
                           params={"format": "metadata",
                                   "metadataHeaders": ["From", "Subject", "Date"]}).json()
        hdrs = {d["name"].lower(): d["value"] for d in msg.get("payload", {}).get("headers", [])}
        ms = msg.get("internalDate")
        date = dt.datetime.fromtimestamp(int(ms) / 1000, TZ).strftime("%Y-%m-%d") if ms else ""
        out.append({"from": hdrs.get("from", ""), "subject": hdrs.get("subject", ""), "date": date})
        if len(out) >= want:
            break
    return out

def events(n=6):
    q = "newer_than:12d from:(%s)" % " OR ".join(EVENT_SENDERS)
    try:
        if os.environ.get("GMAIL_REFRESH_TOKEN"):     # HA add-on: read-only Gmail API
            threads = _gmail_search(q, 20)
        else:                                          # Mac/dev fallback: gog CLI
            out = subprocess.run(["gog", "gmail", "search", q, "--max", "20", "--json"],
                                 capture_output=True, text=True, timeout=25)
            threads = json.loads(out.stdout).get("threads", [])
    except Exception as e:
        return {"items": [], "error": str(e)[:80], "updated": _now()}
    items, seen = [], set()
    for t in threads:
        frm = t.get("from", "")
        src = frm.split("<")[0].strip().strip('"') or frm
        subj = t.get("subject", "").strip()
        key = subj.lower()[:40]
        if not subj or key in seen:
            continue
        seen.add(key)
        emoji, kind = _kind(frm)
        items.append({"source": src, "subject": subj, "date": t.get("date", "")[:10],
                      "emoji": emoji, "kind": kind})
        if len(items) >= n:
            break
    return {"items": items, "updated": _now()}

# --------------------------------------------------------------- L alerts
def l_alerts():
    try:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(requests.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts",
            timeout=15).content)
        msgs = []
        for e in feed.entity:
            if not e.HasField("alert"):
                continue
            a = e.alert
            if not any(ie.route_id == "L" for ie in a.informed_entity):
                continue
            hdr = (a.header_text.translation[0].text if a.header_text.translation else "").strip()
            if hdr and hdr not in msgs:
                msgs.append(hdr)
        return {"count": len(msgs), "alerts": msgs[:3], "updated": _now()}
    except Exception as e:
        return {"count": 0, "alerts": [], "error": str(e)[:80], "updated": _now()}

# ----------------------------------------------------- NY sports (Y/M/R)
def _espn_next(slug, label):
    try:
        d = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{slug}/schedule",
                         timeout=12).json()
        for ev in d.get("events", []):
            comp = ev["competitions"][0]
            stt = (ev.get("status") or comp["status"])["type"]
            if stt["state"] in ("in", "pre"):
                cs = comp["competitors"]
                a = next(c for c in cs if c["homeAway"] == "away")
                h = next(c for c in cs if c["homeAway"] == "home")
                sa, sh = str(a.get("score", "")), str(h.get("score", ""))
                score = (f'{a["team"]["abbreviation"]} {sa}–{sh} {h["team"]["abbreviation"]}'
                         if stt["state"] == "in" and sa and sh else None)
                detail = stt["detail"]
                if stt["state"] == "pre" and ev.get("date"):  # schedule detail is just "Scheduled" — use the time
                    try:
                        detail = (dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
                                  .astimezone(TZ).strftime("%a %-I:%M %p"))
                    except Exception:
                        pass
                return {"team": label, "matchup": ev.get("shortName", ""),
                        "detail": detail, "state": stt["state"], "score": score}
        return {"team": label, "matchup": None, "detail": "Offseason / no game", "state": "off", "score": None}
    except Exception as e:
        return {"team": label, "matchup": None, "detail": "n/a", "state": "off", "score": None, "error": str(e)[:60]}

def sports():
    return {"teams": [_espn_next("baseball/mlb/teams/nyy", "Yankees"),
                      _espn_next("baseball/mlb/teams/nym", "Mets"),
                      _espn_next("hockey/nhl/teams/nyr",   "Rangers")],
            "updated": _now()}

# ----------------------------------------------------- word of the day
# Curated interesting words; one per day (by day-of-year), defined via keyless dictionary API.
# Curated words paired with concise definitions. The free dictionary API lacks many of
# these coined/obscure words (sonder, vellichor, limerence, …), so definitions are bundled
# here as the source of truth; the API is queried only for optional pronunciation/part-of-
# speech. Insertion order is the rotation order (one word per day-of-year) — keep it stable.
WORD_DEFS = {
    "petrichor": "the earthy scent produced when rain falls on dry soil",
    "sonorous": "deep, full, and resonant in sound",
    "ephemeral": "lasting for a very short time; fleeting",
    "serendipity": "the occurrence of happy or beneficial discoveries by chance",
    "defenestration": "the act of throwing someone or something out of a window",
    "limerence": "the involuntary state of intense romantic infatuation and longing for another person",
    "sonder": "the realization that each passerby is living a life as vivid and complex as your own",
    "susurrus": "a soft, whispering or rustling sound",
    "mellifluous": "sweet and smooth to the ear; pleasingly flowing",
    "halcyon": "denoting a past time that was idyllically happy and peaceful",
    "ineffable": "too great or beautiful to be expressed in words",
    "vellichor": "the wistful, melancholy atmosphere of a used bookstore",
    "saudade": "a deep, bittersweet longing for something or someone absent",
    "apricity": "the warmth of the sun in winter",
    "gloaming": "the soft light of twilight; dusk",
    "numinous": "having a strong spiritual or otherworldly, awe-inspiring quality",
    "eunoia": "beautiful thinking; a well or healthy mind",
    "psithurism": "the sound of wind whispering through the trees",
    "clinomania": "an excessive desire to stay in bed",
    "nyctophilia": "a love of night or darkness",
    "sempiternal": "everlasting and unchanging; eternal",
    "luminescence": "a soft emission of light not caused by heat",
    "effervescent": "bubbly and vivacious; full of lively high spirits",
    "quintessence": "the most perfect or typical example of a quality or class",
    "epiphany": "a sudden, striking moment of realization or insight",
    "labyrinthine": "intricate and confusing, like a maze",
    "nebulous": "vague, hazy, or ill-defined",
    "ethereal": "delicate and light, seeming almost too perfect for this world",
    "incandescent": "glowing with intense heat or light; brilliantly radiant",
    "perspicacious": "having keen insight and sharp understanding",
    "sanguine": "cheerfully optimistic, especially in a difficult situation",
    "ebullient": "cheerful and bubbling over with energy",
    "mercurial": "prone to sudden, unpredictable changes of mood",
    "lugubrious": "looking or sounding mournful and dismal",
    "obstreperous": "noisy and difficult to control",
    "fastidious": "meticulous, very attentive to detail, and hard to please",
    "querulous": "complaining in a petulant or whining manner",
    "taciturn": "reserved and saying little; uncommunicative",
    "verdant": "lush and green with vegetation",
    "wanderlust": "a strong desire to travel and explore the world",
    "zephyr": "a soft, gentle breeze",
    "aurora": "a natural light display in the sky; also, the dawn",
    "solitude": "the peaceful state of being alone",
    "reverie": "a state of pleasant, dreamy musing",
    "cascade": "a small waterfall; something that happens in a chain of stages",
    "evanescent": "quickly fading from sight or memory; fleeting",
    "tessellate": "to cover a surface with repeated shapes leaving no gaps",
    "umbra": "the fully shaded inner region of a shadow",
    "vesper": "an evening prayer or song; also, the evening star",
    "wistful": "full of vague, regretful longing",
}
WORDS = list(WORD_DEFS)  # rotation order = insertion order
WORD_OVERRIDE = {"2026-06-04": "halcyon"}  # one-off manual picks by date; auto-reverts the next day
def word_of_day():
    today = dt.datetime.now(TZ).date().isoformat()
    word = WORD_OVERRIDE.get(today) or WORDS[dt.datetime.now(TZ).timetuple().tm_yday % len(WORDS)]
    pos = ipa = ""
    try:  # best-effort pronunciation/part-of-speech; never let the API fail the tile
        d = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=8).json()
        if isinstance(d, list) and d:
            m = d[0]["meanings"][0]
            pos = m.get("partOfSpeech", "")
            ipa = d[0].get("phonetic") or next((p.get("text") for p in d[0].get("phonetics", []) if p.get("text")), "")
    except Exception:
        pass
    return {"word": word, "pos": pos, "ipa": ipa,
            "definition": WORD_DEFS.get(word, "(definition unavailable)"), "updated": _now()}

# ----------------------------------------------------- on this day (history)
def on_this_day():
    try:
        now = dt.datetime.now(TZ)
        d = requests.get(f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected/"
                         f"{now.month:02d}/{now.day:02d}", timeout=12,
                         headers={"User-Agent": "glance-dashboard/1.0 (personal)"}).json()
        evs = [e for e in d.get("selected", []) if e.get("text")]
        if not evs:
            return {"text": None, "updated": _now()}
        # vary by day-of-year so it's not always the same one
        e = evs[now.timetuple().tm_yday % len(evs)]
        return {"year": e.get("year"), "text": e["text"][:240],
                "date": now.strftime("%b %-d"), "updated": _now()}
    except Exception as e:
        return {"text": None, "error": str(e)[:60], "updated": _now()}

# ----------------------------------------------------- next cal event + commute
def _gmaps_key():
    k = os.environ.get("GOOGLE_MAPS_KEY")
    if k:
        return k
    try:  # macOS Keychain
        return subprocess.run(["security", "find-generic-password", "-s", "google-maps-key", "-w"],
                              capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None

# Which HA calendars Next Up should consider (entity_ids). Empty set = all calendars.
# Kept to the ones with real plans-you'd-go-to; excludes birthdays/holidays (also all-day,
# so already skipped), trash/workouts/miami/family.
NEXT_EVENT_CALENDARS = {"calendar.scottdnelson_coffee_gmail_com", "calendar.partiful"}

def _next_cal_event_ha(token, base=None):
    """Soonest upcoming timed event across the allowlisted Home Assistant calendars.
       HA owns the Google OAuth; we just read calendar.* over HA's core REST API.
       base defaults to the supervisor-proxied path (HA add-on mode); pass a real
       HA URL + long-lived token (HA_URL/HA_TOKEN) when running as a standalone service."""
    base = base or "http://supervisor/core/api"
    h = {"Authorization": f"Bearer {token}"}
    now = dt.datetime.now(TZ)
    cals = requests.get(f"{base}/calendars", headers=h, timeout=12).json()
    params = {"start": now.isoformat(), "end": (now + dt.timedelta(days=14)).isoformat()}
    best = None
    for c in cals:
        eid = c.get("entity_id")
        if not eid or (NEXT_EVENT_CALENDARS and eid not in NEXT_EVENT_CALENDARS):
            continue
        try:
            evs = requests.get(f"{base}/calendars/{eid}", headers=h, params=params, timeout=12).json()
        except Exception:
            continue
        for e in evs if isinstance(evs, list) else []:
            s = e.get("start")
            if isinstance(s, dict):
                s = s.get("dateTime") or s.get("date")
            if not s or "T" not in s:   # skip all-day (holidays/birthdays)
                continue
            try:
                start = dt.datetime.fromisoformat(s)
            except ValueError:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=TZ)
            if start > now and (best is None or start < best["start"]):
                best = {"summary": e.get("summary", "(busy)"), "start": start,
                        "location": e.get("location", "") or ""}
    return best

def _next_cal_event():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:   # running inside Home Assistant — read HA's calendars via the supervisor proxy
        return _next_cal_event_ha(token)
    ha_token = os.environ.get("HA_TOKEN")
    if ha_token:   # standalone service (e.g. PC systemd unit) — talk to HA's real REST API
        base = os.environ.get("HA_URL", "http://192.168.0.128:8123").rstrip("/") + "/api"
        return _next_cal_event_ha(ha_token, base=base)
    # Mac/dev fallback: the gog CLI
    out = subprocess.run(["gog", "calendar", "events", "--max", "8", "--json"],
                         capture_output=True, text=True, timeout=25)
    now = dt.datetime.now(TZ)
    for e in json.loads(out.stdout).get("events", []):
        s = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date")
        if not s:
            continue
        start = dt.datetime.fromisoformat(s) if "T" in s else None
        if start and start > now:
            return {"summary": e.get("summary", "(busy)"), "start": start,
                    "location": e.get("location", "")}
    return None

def _geocode(addr, key):
    if key:
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                         params={"address": addr, "key": key}, timeout=12).json()
        if r.get("results"):
            loc = r["results"][0]["geometry"]["location"]; return loc["lat"], loc["lng"]
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q": addr, "format": "json", "limit": 1},
                     headers={"User-Agent": "glance-dashboard/1.0"}, timeout=12).json()
    return (float(r[0]["lat"]), float(r[0]["lon"])) if r else None

def _osrm_min(profile, o, d):
    host = ("router.project-osrm.org/route/v1/driving" if profile == "car"
            else "routing.openstreetmap.de/routed-bike/route/v1/driving")
    r = requests.get(f"https://{host}/{o[1]},{o[0]};{d[1]},{d[0]}?overview=false", timeout=12).json()
    return round(r["routes"][0]["duration"] / 60) if r.get("routes") else None

def next_event():
    try:
        ev = _next_cal_event()
    except Exception as e:
        return {"event": None, "error": str(e)[:60], "updated": _now()}
    if not ev:
        return {"event": None, "updated": _now()}
    now = dt.datetime.now(TZ)
    start = ev["start"]
    res = {"event": {"summary": ev["summary"], "location": ev["location"],
                     "when": start.strftime("%a %-I:%M %p"),
                     "mins_until": round((start - now).total_seconds() / 60)},
           "modes": [], "updated": _now()}
    if not ev["location"]:
        return res
    key = _gmaps_key()
    origin = (HOME_LAT, HOME_LON)
    modes = []
    if key:  # Google Directions accepts the address string directly — no Geocoding API needed
        for gmode, label, buf in [("transit", "🚆 Train", 2), ("driving", "🚗 Uber", 5), ("bicycling", "🚲 e-bike", 0)]:
            try:
                r = requests.get("https://maps.googleapis.com/maps/api/directions/json",
                                 params={"origin": f"{origin[0]},{origin[1]}",
                                         "destination": ev["location"], "mode": gmode,
                                         "arrival_time": int(start.timestamp()), "key": key}, timeout=12).json()
                leg = r["routes"][0]["legs"][0]
                mins = round(leg["duration"]["value"] / 60)
                if gmode == "bicycling":
                    mins = round(mins * 0.75)  # e-bike faster than pedal
                modes.append({"mode": label, "mins": mins + buf})
            except Exception:
                pass
    else:  # keyless fallback: Nominatim geocode + OSRM
        dest = _geocode(ev["location"], None)
        if dest:
            car = _osrm_min("car", origin, dest); bike = _osrm_min("bike", origin, dest)
            if car: modes.append({"mode": "🚗 Uber", "mins": car + 5})
            if bike: modes.append({"mode": "🚲 e-bike", "mins": round(bike * 0.75)})
            if car: modes.append({"mode": "🚆 Train*", "mins": round(car * 1.6)})  # rough est (no key)
    # leave-by + urgency color per mode
    for m in modes:
        leave_in = round((start - now).total_seconds() / 60) - m["mins"]
        m["leave_by"] = (start - dt.timedelta(minutes=m["mins"])).strftime("%-I:%M %p")
        m["leave_in_min"] = leave_in
        m["color"] = "green" if leave_in > 30 else "yellow" if leave_in > 10 else "red"
    res["modes"] = modes
    return res

if __name__ == "__main__":
    for fn in (citibike, airquality, knicks, events, l_alerts,
               sports, word_of_day, on_this_day, next_event):
        print(f"\n=== {fn.__name__} ===")
        print(json.dumps(fn(), indent=1, default=str))

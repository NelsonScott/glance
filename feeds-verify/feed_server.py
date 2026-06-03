#!/usr/bin/env python3
"""Glance-dashboard feed normalizer. Serves clean JSON consumed by BOTH
   the MagicMirror and Home Assistant dashboards.

   GET /weather  -> current + 3-day forecast (Open-Meteo)
   GET /ltrain   -> next Bedford Av L arrivals, both directions (MTA GTFS-RT)
   GET /ferry    -> next North/South Williamsburg departures (NYC Ferry GTFS + RT)
   GET /all      -> all three in one payload
   GET /health   -> ok

   Run:  ./.venv/bin/python feed_server.py   (binds 0.0.0.0:8090)
"""
import io, os, time, zipfile, csv, threading, datetime as dt
import requests
from flask import Flask, jsonify, send_from_directory
from google.transit import gtfs_realtime_pb2
import providers
from nitehawk import get_showtimes, get_next_showtimes
from comedy import get_comedy

app = Flask(__name__)
LAT, LON = 40.7222, -73.9573
TZ = dt.timezone(dt.timedelta(hours=-4))  # America/New_York (EDT in June)

# ----------------------------------------------------------------- weather
WMO = {0:"Clear",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Fog",48:"Rime fog",
       51:"Light drizzle",53:"Drizzle",55:"Heavy drizzle",61:"Light rain",63:"Rain",
       65:"Heavy rain",71:"Light snow",73:"Snow",75:"Heavy snow",80:"Rain showers",
       81:"Rain showers",82:"Violent showers",95:"Thunderstorm",96:"Thunderstorm+hail"}

@app.route("/weather")
def weather():
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,relative_humidity_2m"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset,uv_index_max"
           "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America/New_York&forecast_days=3"
           % (LAT, LON))
    j = requests.get(url, timeout=15).json()
    c = j["current"]; d = j["daily"]
    days = [{"date": d["time"][i], "min": round(d["temperature_2m_min"][i]),
             "max": round(d["temperature_2m_max"][i]), "precip": d["precipitation_probability_max"][i],
             "code": d["weather_code"][i], "desc": WMO.get(d["weather_code"][i], "?")} for i in range(3)]
    dirs = ["N","NE","E","SE","S","SW","W","NW"]
    wdir = dirs[round((c.get("wind_direction_10m", 0) % 360) / 45) % 8]
    uv = round(d.get("uv_index_max", [0])[0])
    uv_cat = "Low" if uv < 3 else "Moderate" if uv < 6 else "High" if uv < 8 else "Very High" if uv < 11 else "Extreme"
    return jsonify({"temp": round(c["temperature_2m"]), "feels": round(c["apparent_temperature"]),
                    "humidity": c["relative_humidity_2m"], "wind": round(c["wind_speed_10m"]), "wind_dir": wdir,
                    "desc": WMO.get(c["weather_code"], "?"), "code": c["weather_code"],
                    "high": days[0]["max"], "low": days[0]["min"],
                    "uv": uv, "uv_cat": uv_cat,
                    "sunrise": d["sunrise"][0][-5:], "sunset": d["sunset"][0][-5:],
                    "forecast": days, "updated": dt.datetime.now(TZ).strftime("%H:%M")})

# ------------------------------------------------------------------ L train
@app.route("/ltrain")
def ltrain():
    now = int(time.time())
    url = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l"
    feed = gtfs_realtime_pb2.FeedMessage(); feed.ParseFromString(requests.get(url, timeout=20).content)
    north, south = [], []
    for e in feed.entity:
        if not e.HasField("trip_update"): continue
        for stu in e.trip_update.stop_time_update:
            if stu.stop_id.startswith("L08"):
                t = stu.arrival.time or stu.departure.time
                if not t: continue
                m = round((t - now) / 60)
                if m < 0: continue
                (north if stu.stop_id.endswith("N") else south).append(m)
    north.sort(); south.sort()
    al = providers.l_alerts()
    return jsonify({"station": "Bedford Av",
                    "manhattan": north[:4], "brooklyn": south[:4],
                    "alerts": al.get("alerts", []), "alert_count": al.get("count", 0),
                    "updated": dt.datetime.now(TZ).strftime("%H:%M")})

# -------------------------------------------------------------------- ferry
_ferry_cache = {"ts": 0, "data": None}
_ferry_lock = threading.Lock()

def _load_ferry_static():
    """Parse static GTFS into {stop_id: [(secs_since_midnight, route, headsign, service_id)]}."""
    z = zipfile.ZipFile(io.BytesIO(requests.get(
        "http://nycferry.connexionz.net/rtt/public/utility/gtfs.aspx", timeout=30).content))
    def rd(n): return list(csv.DictReader(io.TextIOWrapper(z.open(n), "utf-8-sig")))
    trips = {t["trip_id"]: t for t in rd("trips.txt")}
    cal = {c["service_id"]: c for c in rd("calendar.txt")} if "calendar.txt" in z.namelist() else {}
    exc = {}
    if "calendar_dates.txt" in z.namelist():
        for r in rd("calendar_dates.txt"):
            exc.setdefault(r["service_id"], {})[r["date"]] = r["exception_type"]
    by_stop = {}
    for st in rd("stop_times.txt"):
        sid = st["stop_id"]
        if sid not in ("19", "8"):  # North / South Williamsburg
            continue
        tr = trips.get(st["trip_id"], {})
        hms = st["departure_time"] or st["arrival_time"]
        if not hms: continue
        h, m, s = (int(x) for x in hms.split(":"))
        by_stop.setdefault(sid, []).append(
            (h*3600+m*60+s, tr.get("route_id",""), tr.get("trip_headsign",""), tr.get("service_id","")))
    return {"by_stop": by_stop, "cal": cal, "exc": exc}

def _service_active(sid, static, today):
    wd = today.strftime("%A").lower()
    ds = today.strftime("%Y%m%d")
    if sid in static["exc"]:
        et = static["exc"][sid].get(ds)
        if et == "2": return False
        if et == "1": return True
    c = static["cal"].get(sid)
    if not c: return True  # no calendar -> assume runs (validate later)
    if not (c.get("start_date","0") <= ds <= c.get("end_date","99999999")): return False
    return c.get(wd, "0") == "1"

def _ferry_rt_overlay():
    try:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(requests.get(
            "http://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate", timeout=15).content)
        now = int(time.time()); out = {"19": [], "8": []}
        for e in feed.entity:
            if not e.HasField("trip_update"): continue
            for stu in e.trip_update.stop_time_update:
                if stu.stop_id in out:
                    t = stu.departure.time or stu.arrival.time
                    if t and (t-now) >= -120: out[stu.stop_id].append(round((t-now)/60))
        return out
    except Exception:
        return {"19": [], "8": []}

@app.route("/ferry")
def ferry():
    with _ferry_lock:
        if time.time() - _ferry_cache["ts"] > 3600 or _ferry_cache["data"] is None:
            _ferry_cache["data"] = _load_ferry_static(); _ferry_cache["ts"] = time.time()
    static = _ferry_cache["data"]
    now = dt.datetime.now(TZ)
    secs_now = now.hour*3600 + now.minute*60 + now.second
    rt = _ferry_rt_overlay()
    tomorrow = now + dt.timedelta(days=1)
    def _hhmm(s):
        h = (s // 3600) % 24; m = (s % 3600) // 60
        return f"{(h % 12) or 12}:{m:02d}{'am' if h < 12 else 'pm'}"
    def nexts(sid):
        # today's remaining departures
        today = sorted({r[0] for r in static["by_stop"].get(sid, [])
                        if _service_active(r[3], static, now) and r[0] >= secs_now - 60})
        out = [{"in_min": round((s - secs_now)/60), "time": _hhmm(s), "day": "today"} for s in today]
        # roll into tomorrow's earliest if today is short
        if len(out) < 4:
            tmw = sorted({r[0] for r in static["by_stop"].get(sid, [])
                          if _service_active(r[3], static, tomorrow)})
            for s in tmw[:4 - len(out)]:
                out.append({"in_min": round((s + 86400 - secs_now)/60), "time": _hhmm(s), "day": "tomorrow"})
        return out[:4]
    def last_dep(sid, when):
        times = sorted({r[0] for r in static["by_stop"].get(sid, []) if _service_active(r[3], static, when)})
        return times[-1] if times else None
    def direction(sid):
        sched = nexts(sid)
        day_ctx = sched[0]["day"] if sched else "today"
        ls = last_dep(sid, tomorrow if day_ctx == "tomorrow" else now)
        return {"scheduled": sched, "realtime_min": sorted(rt[sid])[:4],
                "last": {"time": _hhmm(ls), "day": day_ctx} if ls is not None else None}
    return jsonify({"north_williamsburg": direction("19"),
                    "south_williamsburg": direction("8"),
                    "updated": now.strftime("%H:%M")})

# ----------------------------------------------------- new widgets (round 2)
_cache = {}
def _cached(key, ttl, fn):
    e = _cache.get(key)
    if e and time.time() - e[0] < ttl:
        return e[1]
    try:
        val = fn(); _cache[key] = (time.time(), val)
        return val
    except Exception:
        if e:            # stale-while-error: a transient upstream timeout shouldn't blank the widget
            return e[1]
        raise

@app.route("/nitehawk")
def nitehawk():  return jsonify(_cached("nitehawk", 1800, get_next_showtimes))
@app.route("/citibike")
def citibike():  return jsonify(_cached("citibike", 60, providers.citibike))
@app.route("/airquality")
def airquality(): return jsonify(_cached("aqi", 600, providers.airquality))
@app.route("/knicks")
def knicks():    return jsonify(_cached("knicks", 120, providers.knicks))
@app.route("/events")
def events():    return jsonify(_cached("events", 900, providers.events))
@app.route("/sports")
def sports():    return jsonify(_cached("sports", 120, providers.sports))
@app.route("/word")
def word():      return jsonify(_cached("word", 3600, providers.word_of_day))
@app.route("/history")
def history():   return jsonify(_cached("history", 3600, providers.on_this_day))
@app.route("/nextevent")
def nextevent(): return jsonify(_cached("nextevent", 180, providers.next_event))
@app.route("/comedy")
def comedy():  # cache-only — the ~2min Playwright scrape runs in the warmer thread, never on request
    e = _cache.get("comedy")
    return jsonify(e[1] if e else {"venues": [], "updated": "—", "note": "warming up"})

@app.route("/all")
def all_feeds():
    with app.test_request_context():
        return jsonify({"weather": weather().json, "ltrain": ltrain().json, "ferry": ferry().json,
                        "nitehawk": nitehawk().json, "citibike": citibike().json,
                        "airquality": airquality().json, "knicks": knicks().json, "events": events().json,
                        "sports": sports().json, "word": word().json, "history": history().json,
                        "nextevent": nextevent().json, "comedy": comedy().json})

@app.route("/citycam")
def citycam():
    # Rotating live city webcams (YouTube embeds). Served as a parent HTML page so the
    # embeds get a valid http origin (avoids YouTube error 153). Swaps every 45s.
    # cams: [video_id, share_token, label]
    html = """<!doctype html><html><head><meta charset=utf-8>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
iframe{width:100%;height:100%;border:0;display:block}
#lbl{position:absolute;top:8px;left:10px;z-index:3;color:#fff;
font:600 14px system-ui,-apple-system,sans-serif;background:rgba(0,0,0,.55);
padding:3px 10px;border-radius:8px}</style></head>
<body><div id=lbl></div>
<iframe id=f allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
 allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>
<script>
var cams=[["z-jYdOIKcTQ","CAScdLG46NEQJ3yB","\\uD83D\\uDDFD Times Square"],
          ["JPxiYF2fSC8","kFZZOaUWpTsQkV3L","\\uD83C\\uDF33 Bryant Park"],
          ["DjdUEyjx8GM","sEgL6jRgTeyB_VW0","\\uD83C\\uDFEE Shinjuku, Tokyo"],
          ["dfVK7ld38Ys","6RgiUpH6Z4-WdAVl","\\uD83D\\uDEA6 Shibuya, Tokyo"]];
var i=0,f=document.getElementById('f'),l=document.getElementById('lbl');
function show(){var c=cams[i];
 f.src="https://www.youtube.com/embed/"+c[0]+"?si="+c[1]+"&autoplay=1&mute=1&playsinline=1&rel=0";
 l.textContent=c[2];i=(i+1)%cams.length;}
show();setInterval(show,45000);
</script></body></html>"""
    return app.response_class(html, mimetype="text/html")

# ----------------------------------------------------- web app (Claude Design frontend)
WEBAPP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
@app.route("/")
def dash_index(): return send_from_directory(WEBAPP, "index.html")
@app.route("/<path:fn>")
def dash_static(fn): return send_from_directory(WEBAPP, fn)

@app.route("/health")
def health(): return jsonify({"ok": True})

def _warm():
    """Pre-populate slow caches (events shells out to gog; nitehawk scrapes) so
       HTTP responses are always instant — prevents HA rest setup-time timeouts."""
    import traceback
    while True:
        for key, ttl, fn in [("events", 900, providers.events), ("nitehawk", 1800, get_next_showtimes),
                             ("nextevent", 180, providers.next_event),
                             ("comedy", 1800, lambda: get_comedy(use_cache=True))]:
            try:
                _cache[key] = (time.time(), fn())
            except Exception:
                traceback.print_exc()
        try:  # pre-load ferry static GTFS so HA's first poll after a restart never 500s
            with _ferry_lock:
                _ferry_cache["data"] = _load_ferry_static(); _ferry_cache["ts"] = time.time()
        except Exception:
            traceback.print_exc()
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=_warm, daemon=True).start()
    app.run(host="0.0.0.0", port=8090, threaded=True)

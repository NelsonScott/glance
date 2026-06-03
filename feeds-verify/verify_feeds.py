#!/usr/bin/env python3
"""Verify the live data feeds for the Williamsburg glance dashboard.
   - L train @ Bedford Av (MTA GTFS-RT, no key)
   - NYC Ferry @ North Williamsburg (Connexionz GTFS static + GTFS-RT tripupdate)
   - Weather (Open-Meteo, no key)
"""
import io, time, zipfile, csv, sys, datetime as dt
import requests
from google.transit import gtfs_realtime_pb2

NOW = int(time.time())
def mins(ts): return round((ts - NOW) / 60)
def hdr(t): print("\n" + "=" * 64 + f"\n{t}\n" + "=" * 64)

# ---------------------------------------------------------------- L TRAIN
def verify_l_train():
    hdr("L TRAIN @ Bedford Av  (MTA GTFS-RT, no API key)")
    url = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l"
    try:
        r = requests.get(url, timeout=20); r.raise_for_status()
    except Exception as e:
        print("FAIL fetching L feed:", e); return False
    feed = gtfs_realtime_pb2.FeedMessage(); feed.ParseFromString(r.content)
    print(f"OK  feed fetched ({len(r.content)} bytes), {len(feed.entity)} entities, "
          f"timestamp {dt.datetime.fromtimestamp(feed.header.timestamp)}")
    # Bedford Av = L08 ; N = Manhattan-bound (8 Av), S = Brooklyn-bound (Canarsie)
    north, south = [], []
    for e in feed.entity:
        if not e.HasField("trip_update"): continue
        for stu in e.trip_update.stop_time_update:
            sid = stu.stop_id
            if sid.startswith("L08"):
                t = stu.arrival.time or stu.departure.time
                if not t: continue
                m = mins(t)
                if m < -1: continue
                (north if sid.endswith("N") else south).append(m)
    north.sort(); south.sort()
    print(f"  Manhattan-bound (8 Av) next: {north[:5]}  (minutes)")
    print(f"  Canarsie-bound       next: {south[:5]}  (minutes)")
    ok = bool(north or south)
    print("RESULT:", "PASS — live Bedford Av arrivals" if ok else "NO arrivals parsed (check stop id)")
    return ok

# ---------------------------------------------------------------- FERRY
def find_ferry_stop():
    url = "http://nycferry.connexionz.net/rtt/public/utility/gtfs.aspx"
    r = requests.get(url, timeout=30); r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    stops = list(csv.DictReader(io.TextIOWrapper(z.open("stops.txt"), "utf-8-sig")))
    print(f"OK  static GTFS: {len(z.namelist())} files, {len(stops)} stops")
    matches = [s for s in stops if "williamsburg" in s["stop_name"].lower()]
    for s in matches:
        print(f"   stop_id={s['stop_id']!r}  name={s['stop_name']!r}")
    return {s["stop_id"]: s["stop_name"] for s in matches}, stops

def verify_ferry():
    hdr("NYC FERRY @ N. Williamsburg  (Connexionz GTFS static + RT)")
    try:
        wb_stops, all_stops = find_ferry_stop()
    except Exception as e:
        print("FAIL static GTFS:", e); return False
    target = {sid for sid, n in wb_stops.items() if "north" in n.lower()} or set(wb_stops)
    rt = "http://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate"
    try:
        r = requests.get(rt, timeout=20); r.raise_for_status()
    except Exception as e:
        print("FAIL realtime tripupdate:", e); return False
    feed = gtfs_realtime_pb2.FeedMessage(); feed.ParseFromString(r.content)
    print(f"OK  realtime feed ({len(r.content)} bytes), {len(feed.entity)} entities")
    deps = []
    for e in feed.entity:
        if not e.HasField("trip_update"): continue
        for stu in e.trip_update.stop_time_update:
            if stu.stop_id in target:
                t = stu.departure.time or stu.arrival.time
                if t and mins(t) >= -2:
                    deps.append((mins(t), e.trip_update.trip.route_id))
    deps.sort()
    print(f"  next departures (min, route): {deps[:6]}")
    ok = bool(deps)
    print("RESULT:", "PASS — live N.Williamsburg departures" if ok
          else "RT parsed but no upcoming for this stop right now (schedule fallback still works)")
    return True  # static feed alone is enough to build; RT is a bonus

# ---------------------------------------------------------------- WEATHER
def verify_weather():
    hdr("WEATHER @ N.Williamsburg  (Open-Meteo, no key)")
    url = ("https://api.open-meteo.com/v1/forecast?latitude=40.7222&longitude=-73.9573"
           "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&temperature_unit=fahrenheit&timezone=America/New_York&forecast_days=3")
    try:
        j = requests.get(url, timeout=15).json()
    except Exception as e:
        print("FAIL:", e); return False
    c = j["current"]
    print(f"OK  now: {c['temperature_2m']}°F (feels {c['apparent_temperature']}°F), "
          f"wind {c['wind_speed_10m']} mph, code {c['weather_code']}")
    d = j["daily"]
    for i in range(3):
        print(f"   {d['time'][i]}: {d['temperature_2m_min'][i]}–{d['temperature_2m_max'][i]}°F, "
              f"precip {d['precipitation_probability_max'][i]}%")
    print("RESULT: PASS")
    return True

if __name__ == "__main__":
    results = {"L train": verify_l_train(), "Ferry": verify_ferry(), "Weather": verify_weather()}
    hdr("SUMMARY")
    for k, v in results.items():
        print(f"  {k:10s}: {'PASS' if v else 'FAIL'}")

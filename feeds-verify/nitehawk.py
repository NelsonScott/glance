#!/usr/bin/env python3
"""Scrape Nitehawk WILLIAMSBURG showtimes from the server-rendered page.
   No JS / Playwright needed — the page is static HTML.
   URL pattern: https://nitehawkcinema.com/williamsburg/{YYYY-MM-DD}/{offset}/
"""
import re, html as ihtml, datetime as dt
import requests

TZ = dt.timezone(dt.timedelta(hours=-4))
BASE = "https://nitehawkcinema.com/williamsburg"

def _clean(s): return ihtml.unescape(re.sub(r"<[^>]+>", "", s)).strip()

def get_showtimes(date=None, only_upcoming=True):
    if date is None:
        date = dt.datetime.now(TZ).date().isoformat()
    url = f"{BASE}/{date}/0/"
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    h = r.text
    films = []
    # Each film card: a "(Full details)" button carries the title, followed by a
    # .showtimes-container with the <li> showtime buttons.
    for cm in re.finditer(r'aria-label="([^"]+?)\s*\(Full details\)"', h):
        title = _clean(cm.group(1))
        sc = re.search(r'showtimes-container.*?<ul[^>]*>(.*?)</ul>', h[cm.end():cm.end()+6000], re.S)
        if not sc:
            continue
        shows = []
        for li in re.finditer(r'<(?:a|span)[^>]*class="showtime([^"]*)"[^>]*>(.*?)</(?:a|span)>',
                              sc.group(1), re.S):
            classes, inner = li.group(1), li.group(2)
            txt = _clean(inner)
            tm = re.search(r'\d{1,2}:\d{2}\s*[ap]m', txt, re.I)
            if not tm:
                continue
            time_txt = re.sub(r'\s+', '', tm.group(0)).lower()  # "9:30pm"
            tag = _clean(re.sub(r'\d{1,2}:\d{2}\s*[ap]m', '', txt, flags=re.I)).replace("Sold Out", "").strip()
            status = ("past" if "past" in classes else
                      "sold_out" if "sold-out" in classes else "available")
            if only_upcoming and status == "past":
                continue
            show = {"time": time_txt, "status": status}
            if tag:  # e.g. "OC" (open caption)
                show["tag"] = tag
            shows.append(show)
        if shows or not only_upcoming:
            films.append({"title": title, "showtimes": shows})
    # drop films whose showings are all in the past (empty after filter)
    films = [f for f in films if f["showtimes"]]
    return {"date": date, "venue": "Nitehawk Williamsburg", "films": films,
            "updated": dt.datetime.now(TZ).strftime("%H:%M")}

def get_next_showtimes(max_days=4):
    """Today's remaining showtimes; if today is exhausted, roll to the next day
       that has showings. Adds a friendly 'label' (Today / Tomorrow / weekday)."""
    today = dt.datetime.now(TZ).date()
    for off in range(max_days):
        d = (today + dt.timedelta(days=off)).isoformat()
        data = get_showtimes(date=d)
        if data["films"]:
            data["label"] = ("Today" if off == 0 else "Tomorrow" if off == 1
                             else (today + dt.timedelta(days=off)).strftime("%a %b %-d"))
            return data
    data["label"] = "Today"
    return data

if __name__ == "__main__":
    import json
    print(json.dumps(get_next_showtimes(), indent=2))

#!/usr/bin/env python3
"""Explore the rendered Nitehawk Williamsburg showtimes DOM to find selectors,
   and sniff any XHR/fetch the page makes for showtime JSON."""
from playwright.sync_api import sync_playwright

URL = "https://nitehawkcinema.com/williamsburg/showtimes/"
api_calls = []

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(user_agent="Mozilla/5.0")
    pg.on("response", lambda r: api_calls.append((r.status, r.url))
          if any(k in r.url.lower() for k in ["showtime", "filmbot", "api", "listing", "/nj/", ".json"]) else None)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(4000)
    print("=== candidate XHR/API calls the page made ===")
    for st, u in api_calls[:40]:
        print(st, u)
    print("\n=== showtime-ish elements (selector survey) ===")
    js = """() => {
      const out = {};
      for (const sel of ['.showtime','.show-time','[class*=showtime]','[class*=showing]',
                         '.film','.movie','[class*=film-]','article',
                         'a[href*=tickets]','a[href*=showtime]','time','.time']) {
        out[sel] = document.querySelectorAll(sel).length;
      }
      return out;
    }"""
    counts = pg.evaluate(js)
    for k, v in counts.items():
        if v: print(f"  {k}: {v}")
    # Dump a chunk of the visible text to see how showtimes are laid out
    print("\n=== visible text sample (first 1500 chars of main) ===")
    txt = pg.evaluate("() => (document.querySelector('main')||document.body).innerText")
    print(txt[:1500])
    b.close()

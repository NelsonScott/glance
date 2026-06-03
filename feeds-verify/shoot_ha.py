#!/usr/bin/env python3
"""Screenshot the live HA Glance dashboard by injecting the long-lived token
   into localStorage (hassTokens) before the frontend boots."""
import os, sys, json
from playwright.sync_api import sync_playwright

HA = "http://192.168.0.214:8123"
TOK = os.environ["HASS_TOKEN"]
URL = HA + "/glance-dashboard/home"
OUT = "/Users/scottnelson/Sandbox/glance-dashboard/ha-dashboard-preview.png"

hass_tokens = {
    "access_token": TOK, "token_type": "Bearer",
    "expires_in": 315360000, "hassUrl": HA, "clientId": None,
    "expires": 9999999999999, "refresh_token": "",
}
init = "window.localStorage.setItem('hassTokens', %s);" % json.dumps(json.dumps(hass_tokens))

with sync_playwright() as p:
    try:
        b = p.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
    except Exception:
        b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto(HA, wait_until="domcontentloaded")
    pg.evaluate(init)
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_timeout(12000)
    # bail if we got bounced to a login form
    body = pg.content().lower()
    if "ha-authorize" in body or "name=\"username\"" in body or "data-auth" in body and "markdown" not in body:
        print("LOGIN_WALL", file=sys.stderr)
    pg.screenshot(path=OUT, full_page=True)
    b.close()
print(OUT)

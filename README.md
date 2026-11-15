# Glance

A personal at-a-glance "life dashboard" for Williamsburg, Brooklyn — weather, transit,
neighborhood, and personal info on one full-screen view. Runs as a Mac app and serves to
any device on the LAN.

![status](https://img.shields.io/badge/status-live-brightgreen)

## Quick start

The feed service runs on an always-on machine as a systemd user unit (`glance-feed.service`). Other devices only run a viewer pointed at it.

```bash
# on a viewer machine
open http://<glance-host>:8090/           # any browser, or…
open /Applications/Glance.app            # the packaged Mac app

# local dev server instead:
cd feeds-verify && ./.venv/bin/python feed_server.py   # serves http://localhost:8090
GLANCE_URL=http://localhost:8090/ open /Applications/Glance.app
```

LAN access from a phone / TV browser: `http://<glance-host>:8090/`

## Architecture

Three layers:

1. **Feed service** — `feeds-verify/feed_server.py` (Flask, port 8090). Normalizes every
   source into one JSON payload at `/all`; also serves the web app and the rotating-cam
   page (`/citycam`). A startup `_warm()` thread pre-caches the slow scrapers.
2. **Web frontend** — `feeds-verify/webapp/` (`index.html` + `live.js`). Shell generated in
   Claude Design; `live.js` fetches `/all` every 60s and renders each tile. Aurora gradient
   + glass tiles, auto-scales 1920×1080 to any screen.
3. **Electron wrapper** — `electron/` → packaged to `/Applications/Glance.app`.
   Fullscreen, menu-bar tray, `Ctrl+Cmd+D` toggle, `Esc`/`Cmd+W` hide, `Cmd+Q` quit,
   and **auto-popup after 5 min idle** (hides when you return).

```
feed_server.py ──/all──► live.js ──renders──► tiles
       ├── /citycam (rotating YouTube cams, iframed by the cam tile)
       └── serves webapp/index.html + live.js
```

## Project layout

| path | what |
|---|---|
| `feeds-verify/feed_server.py` | Flask service: `/all`, per-feed endpoints, web app, `/citycam` |
| `feeds-verify/providers.py`   | Citi Bike · AQI · Knicks · NY sports · word · history · events · next-event/commute |
| `/upcoming` · `/travel`       | calendar for the next hours and travel time per mode (`/travel?dest=&arrive=ISO[&origin=lat,lon]`); meant for a script that sends "time to leave" alerts |
| `/picks`                      | "This week for you": the best-scored upcoming items from `feeds-verify/picks.json`, a git-ignored file written by a separate job (shape in `providers.py`) |
| `/cams`                       | which of the configured YouTube live cams are live right now; the page rotates through only those |
| `feeds-verify/nitehawk.py` · `comedy.py` | Playwright/HTTP scrapers for showtimes |
| `feeds-verify/webapp/`        | the dashboard UI (`index.html`, `live.js`) |
| `feeds-verify/verify_feeds.py` | one-off feed test helper |
| `feeds-verify/shoot_ha.py`     | vestigial — screenshot helper for the old HA Lovelace "Glance" dashboard, which this app replaced; not part of the active pipeline |
| `electron/`                   | Electron app + `Glance.command` launcher; packaged into `dist/` |
| `requirements.txt`            | Python deps (recreate venv: `python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`) |

## Tiles & data sources

Weather/AQI/UV (Open-Meteo) · L train (MTA GTFS-RT) · NYC Ferry (NYC Ferry GTFS) ·
Citi Bike (GBFS) · live city cams (YouTube) · Knicks / Yankees / Mets / Rangers (ESPN) ·
Nitehawk + comedy showtimes (scrape) · Word of the Day (dictionary API) ·
Around Town · Next Up with train/Uber/e-bike "leave by" times.

## Notes

- Only launch `/Applications/Glance.app` — running `npm start` shows a duplicate "Electron" app.
- Electron catches `SIGTERM`; use `pkill -9` to kill stray instances.

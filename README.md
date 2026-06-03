# Glance Dashboard — Sandbox (2026-06-01)

Two working prototypes of the Williamsburg "life dashboard", plus the shared
feed service they both consume. Built to compare **MagicMirror²** vs
**Home Assistant / Lovelace** side by side.

## Architecture (shared)
A single feed-normalizer service turns messy transit/weather feeds into clean JSON.
Both dashboards consume it. In production it moves to an always-on host (Pi/Khadas).

```
feeds-verify/feed_server.py   ->  http://<host>:8090/{weather,ltrain,ferry,all}
        |                                   |
   MagicMirror²  (node_helpers)        Home Assistant (rest: sensors)
```

### Feed service
- `feeds-verify/verify_feeds.py` — one-shot proof that the 3 transit/weather feeds work from Scott's exact stops.
- `feeds-verify/feed_server.py`  — the live JSON service (Flask, port 8090, binds 0.0.0.0). Has a startup `_warm()` thread that pre-caches the slow endpoints (events/nitehawk) so HA never hits a cold poll.
- `feeds-verify/nitehawk.py`     — Nitehawk Williamsburg showtime scraper (server-rendered HTML, no JS).
- `feeds-verify/providers.py`    — Citi Bike · Air Quality · Knicks · Events(Gmail/gog) · L-alerts.
- Run: `cd feeds-verify && ./.venv/bin/python feed_server.py`

### Endpoints (all live, no paid keys)
| endpoint | source |
|---|---|
| /weather   | Open-Meteo (+ sunrise/sunset) |
| /ltrain    | MTA GTFS-RT (L @ Bedford) + service alerts |
| /ferry     | NYC Ferry GTFS + RT (N/S Williamsburg) |
| /nitehawk  | nitehawkcinema.com/williamsburg/{date}/0/ (scrape) |
| /citibike  | Citi Bike GBFS (4 nearest stations) |
| /airquality| Open-Meteo Air Quality (US AQI) |
| /knicks    | ESPN unofficial NBA API |
| /events    | Gmail via `gog`, sender allowlist (Ticketmaster/Eventbrite/Dice/StubHub/Othership/Nitehawk/…) |

### Gotchas hit (so we don't re-trip them)
- HA REST + a JSON key literally named `items`: `value_json.items` resolves to dict's `.items()` method in Jinja → use `value_json['items']`.
- MagicMirror custom modules can't client-fetch localhost (CORS + MM SSRF guard) → use a `node_helper.js` server-side fetch.
- HA rest setup-time fetch can time out on slow endpoints and won't retry for `scan_interval`; fix = pre-warm the server + `rest.reload` service (no full restart).
- Events = Gmail SENDER allowlist, not keyword search (keyword search drowns in retail "ends tonight" sales).

## Option A — MagicMirror²
- Lives in `magicmirror/MagicMirror/`. Launch native app: `npm start`. Serve only: `node serveronly` (→ :8080).
- Custom modules `MMM-LTrain` + `MMM-Ferry` (fetch via node_helper to dodge CORS); weather is built-in Open-Meteo.
- Preview: `../magicmirror-preview.png`. Details: `magicmirror/MagicMirror/LAUNCH.md`.

## Option B — Home Assistant / Lovelace
- LIVE on Scott's HA now: http://192.168.0.214:8123/glance-dashboard/home (sidebar "Glance").
- `home-assistant/glance_dashboard.yaml`  -> deployed to /config/packages/ (REST sensors).
- `home-assistant/glance-dashboard.yaml`  -> deployed to /config/ (YAML dashboard).
- `home-assistant/configuration.yaml.new` -> what was merged into /config/configuration.yaml
  (original backed up on the HA host as configuration.yaml.bak-glance-20260601).

### To fully remove Option B from HA
1. Remove the `glance-dashboard:` block from /config/configuration.yaml (or restore the .bak).
2. Delete /config/glance-dashboard.yaml and /config/packages/glance_dashboard.yaml.
3. `ha core restart`.

## Known caveat (both)
The feed service currently runs on Scott's Mac (192.168.0.79:8090). HA sensors will go
`unavailable` when the Mac sleeps. Productionizing = run feed_server.py on an always-on
host (the Pi or Khadas) and update the IP in the HA package / MM modules.

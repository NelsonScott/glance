# Browserless backend → deployed to the Khadas (Home Assistant)

Branch: `poc/browserless-backend`. Goal: move the feed service off the Mac so the
dashboard survives sleep/logout. Two parts, both **done and verified**:
1. Drop the one heavy dependency (headless Chromium / Playwright) so the service is light
   enough to run next to Home Assistant.
2. Run it on the Khadas as a Home Assistant add-on; repoint the Mac to it; kill the Mac backend.

## What changed

- **`feeds-verify/comedy_lite.py`** (new) — browserless drop-in for `comedy.py`'s
  `get_comedy()`. Plain `requests` + stdlib, **~2 min → ~0.9 s**.
  - Old Man Hustle: donyc static HTML (`.ds-listing-event-title-text` + `startDate` meta).
  - Flop House: schedule is **baked into the Vue bundle** `app.<hash>.js` as
    `{title,startTime:<epoch-ms>,…,color}` objects (resolve the hash from the homepage each
    run; `color:"9"` = East Village, else 362 Grand St). *(The per-venue CloudFront
    `_events.json` was a red herring — it only holds test data.)*
  - Second City: Next.js `__NEXT_DATA__` → each detail page's
    `entityResolver.patronticketData` = base64(JSON) → `.instances[].formattedDates.ISO8601`.
    Detail pages fetched concurrently.
- **`feeds-verify/feed_server.py`** — one line: `from comedy_lite import get_comedy`.
- **`feeds-verify/requirements-lite.txt`** (new) — deps minus `playwright`.
- **`feeds-verify/Dockerfile` + `.dockerignore`** (new) — generic container (Pi or local).
- **`deploy/ha-addon/`** (new) — the Home Assistant add-on definition + deploy README.
- **`electron/main.js`** — default `DASH_URL` now `http://192.168.0.214:8090/` (was
  localhost). The **installed `/Applications/Glance.app`** was also repointed (its
  `app.asar` repacked; original backed up to `/tmp/app.asar.glance-backup`).

## Deployed state (verified June 2026)

- Add-on **`local_glance_feeds`** built & running on the Khadas (HAOS, aarch64). Serves
  `http://192.168.0.214:8090/`. `boot: auto`, Google Maps key set via add-on options.
- Local Docker build tested on the Mac first (image `glance-feeds:poc`, ran on :8091).
- `GET /health`, `/all` (all 13 tiles), `/comedy` (3 venues browserless), `/`, `/live.js`
  all 200 from the Mac.
- Old Mac `feed_server.py` (PID 58795) **killed**; Mac :8090 free.
- `Glance.app` relaunched → Khadas logs show the Mac (192.168.0.79) fetching `/`, `/live.js`,
  `/all`. The Mac is now a pure thin client.

## Known gaps / follow-ups

- **`gog`-dependent tiles** (Around Town / Gmail, Next Up calendar event) are empty on the
  Khadas — `gog` CLI isn't in the container. Commute times work (Maps key). Port `gog` or
  replace those two with an API. See `deploy/ha-addon/README.md`.
- **Flask dev server** is used (fine for one LAN client; swap to gunicorn if desired).
- **Screensaver / login-window** piece is still untouched (the other half of the goal).
- `comedy.py` (Playwright) left in place as reference; `requirements.txt` still lists
  `playwright`. Drop both if we keep this.

## Cleanup / rollback

- Mac app: `cp /tmp/app.asar.glance-backup /Applications/Glance.app/Contents/Resources/app.asar`
  (restores localhost), or `git checkout main` for the source.
- Khadas add-on: `ssh hass 'ha addons uninstall local_glance_feeds'` + `rm -rf /addons/glance_feeds`.
- Restart Mac backend: `cd feeds-verify && ./.venv/bin/python feed_server.py`.
- Branch: `git checkout main && git branch -D poc/browserless-backend`.

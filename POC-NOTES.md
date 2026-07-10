# Browserless backend → deployed to the Khadas (Home Assistant)

## 2026-07-10: moved again — Khadas → PC (Khadas decommissioned/sold)

The Khadas (192.168.0.214) that hosted the `local_glance_feeds` HA add-on is gone —
Home Assistant itself already migrated off it 2026-07-01 to a PC libvirt VM
(`192.168.0.128:8123`), and Khadas is being sold. Rather than reinstalling the add-on on the
new HA VM, the feed service is now a plain **systemd `--user` unit on the always-on PC**
(`glance-feed.service`, `~/projects/glance-dashboard/feeds-verify`) — no HA add-on wrapper
at all, since HA involvement was only ever for always-on hosting, not function.

**Code change required:** `_next_cal_event_ha()` in `providers.py` hardcoded
`http://supervisor/core/api`, which only resolves inside HA's Supervisor-managed Docker
network — it silently would have returned nothing outside an add-on. Added a real
`HA_TOKEN`/`HA_URL` env-var path (uses HA's normal REST API + a long-lived token) as a third
branch alongside the old Supervisor-proxy mode and the Mac/`gog` dev fallback.

- `electron/main.js` `DASH_URL` default → `http://192.168.0.66:8090/` (the PC).
- Repo moved on the Mac from `~/Sandbox/glance-dashboard` → `~/projects/glance-dashboard`.
- `deploy/ha-addon/` and `home-assistant/*.yaml` are now vestigial (kept for reference/rollback,
  not the active deployment path).
- ⚠️ **Gmail ("Around Town") tile still needs `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET`/
  `GMAIL_REFRESH_TOKEN` re-provisioned on the PC** — these lived only in the Khadas add-on's
  options and 1Password; not recoverable from this Mac's Keychain. Tile degrades gracefully
  (returns `{"items": [], "error": ...}`) rather than crashing the service, so this isn't a
  blocker, just a known gap until those values are pulled from 1Password.

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
- **Idle popup can go blank (App Nap)** — pre-existing: when the kiosk window sits
  backgrounded, macOS App Nap suspends the renderer's 60s fetch loop, so the 5-min idle
  popup can snap fullscreen showing a stale/blank dark frame. ⚠️ Do NOT "fix" this with
  Chromium switches (`disable-renderer-backgrounding` etc.) or `app.disableHardwareAcceleration()`
  — on this Mac (macOS 26, Apple Silicon) those FROZE the compositor: DOM rendered fine
  but no frames were produced → fully black window (verified via CDP: rAF never fired).
  Reverted. Safer approaches to try next, one at a time with a screenshot check:
  `powerSaveBlocker('prevent-app-suspension')` alone, or the OS-level
  `defaults write <bundleid> NSAppSleepDisabled -bool YES`.
- `comedy.py` (Playwright) left in place as reference; `requirements.txt` still lists
  `playwright`. Drop both if we keep this.

## Cleanup / rollback

- Mac app: `cp /tmp/app.asar.glance-backup /Applications/Glance.app/Contents/Resources/app.asar`
  (restores localhost), or `git checkout main` for the source.
- Khadas add-on: `ssh hass 'ha addons uninstall local_glance_feeds'` + `rm -rf /addons/glance_feeds`.
- Restart Mac backend: `cd feeds-verify && ./.venv/bin/python feed_server.py`.
- Branch: `git checkout main && git branch -D poc/browserless-backend`.

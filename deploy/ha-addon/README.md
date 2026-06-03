# Glance Feeds — Home Assistant add-on

Runs the Glance feed service (`feeds-verify/feed_server.py`, browserless via
`comedy_lite.py`) as a local Home Assistant add-on on the Khadas VIM3 (HAOS), so the
dashboard's data survives the Mac sleeping / logging out. The Mac's `Glance.app` and
the screensaver just point at `http://<khadas-ip>:8090/`.

This folder holds the add-on **definition** (`config.yaml`, `Dockerfile`, `run.sh`).
The app code is shared from `../../feeds-verify/`; the deploy step copies both into one
folder under the Khadas's local add-ons share (`/addons/glance_feeds/`).

## Why an add-on (not `docker run`)

HAOS doesn't expose the host Docker daemon to SSH sessions; the Supervisor manages all
containers. A *local add-on* is the supported, persistent, reboot-surviving way to run a
custom container. Supervisor builds the image from `Dockerfile` and injects the
`google_maps_key` option into `/data/options.json`, which `run.sh` exports as
`GOOGLE_MAPS_KEY` (providers.py reads env before the macOS Keychain).

## Deploy / update

```bash
# 1. assemble add-on dir = definition + app code (run from repo root)
A=/tmp/glance_feeds_addon; rm -rf "$A"; mkdir -p "$A/webapp"
cp feeds-verify/{feed_server.py,providers.py,nitehawk.py,comedy_lite.py,requirements-lite.txt} "$A/"
cp feeds-verify/webapp/{index.html,live.js} "$A/webapp/"
cp deploy/ha-addon/{config.yaml,Dockerfile,run.sh} "$A/"

# 2. push to the Khadas local add-ons share (ssh alias `hass` = root@192.168.0.214)
tar czf - -C "$A" . | ssh hass 'rm -rf /addons/glance_feeds && mkdir -p /addons/glance_feeds && tar xzf - -C /addons/glance_feeds'

# 3. install / rebuild via Supervisor
ssh hass 'ha store reload && ha addons rebuild local_glance_feeds && ha addons restart local_glance_feeds'
#   (first time: `ha addons install local_glance_feeds` then `ha addons start local_glance_feeds`)

# 4. set the Google Maps key (key via stdin so it isn't in a process arg list)
MK=$(security find-generic-password -s google-maps-key -w)
printf '{"options":{"google_maps_key":"%s"}}' "$MK" | \
  ssh hass 'curl -sX POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" -H "Content-Type: application/json" -d @- http://supervisor/addons/local_glance_feeds/options'
ssh hass 'ha addons restart local_glance_feeds'
```

Verify: `curl http://192.168.0.214:8090/health` → `{"ok":true}`.

## Known gap

The **Around Town** (Gmail) and **Next Up calendar** tiles shell out to the `gog` CLI,
which isn't installed in this container — they degrade to empty on the Khadas. Commute
times (Google Maps) work via the key. Porting `gog` (or replacing those two with an API)
to the Khadas is a follow-up.

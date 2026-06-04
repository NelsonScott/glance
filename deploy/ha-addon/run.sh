#!/bin/sh
# Export add-on options (/data/options.json) as env vars for the feed service.
opt() { python -c "import json,sys;print(json.load(open('/data/options.json')).get('$1',''))" 2>/dev/null; }
export GOOGLE_MAPS_KEY="$(opt google_maps_key)"
export GMAIL_CLIENT_ID="$(opt gmail_client_id)"
export GMAIL_CLIENT_SECRET="$(opt gmail_client_secret)"
export GMAIL_REFRESH_TOKEN="$(opt gmail_refresh_token)"
echo "glance-feeds starting (maps:$([ -n "$GOOGLE_MAPS_KEY" ] && echo set || echo unset) gmail:$([ -n "$GMAIL_REFRESH_TOKEN" ] && echo set || echo unset))"
exec python feed_server.py

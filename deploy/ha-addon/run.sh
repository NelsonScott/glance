#!/bin/sh
export GOOGLE_MAPS_KEY="$(python -c "import json;print(json.load(open('/data/options.json')).get('google_maps_key',''))" 2>/dev/null)"
echo "glance-feeds starting (maps key: $([ -n "$GOOGLE_MAPS_KEY" ] && echo set || echo unset))"
exec python feed_server.py

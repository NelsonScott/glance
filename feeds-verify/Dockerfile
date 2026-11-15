# POC Dockerfile for the Glance feed service (branch poc/browserless-backend).
#
# Goal: prove the service packages into a small container with NO Chromium/Playwright,
# so it can run as a Home Assistant add-on on the Khadas (HAOS) or a plain container
# on the Pi. Multi-arch base → builds for arm64 (Khadas VIM3 / Raspberry Pi) and amd64.
#
# Build + run locally (Docker Desktop must be running):
#   cd feeds-verify
#   docker build -t glance-feeds:poc .
#   docker run --rm -p 8090:8090 -e GOOGLE_MAPS_KEY=... glance-feeds:poc
#   # then open http://localhost:8090/
#
# GOOGLE_MAPS_KEY: on macOS the service reads it from the Keychain; in a Linux
# container there's no Keychain, so pass it via this env var (providers.py checks
# env first). Without it, every tile works except commute "leave by" times.
FROM python:3.12-slim

WORKDIR /app

# Only the lite (browserless) deps — no playwright, no system chromium.
COPY requirements-lite.txt .
RUN pip install --no-cache-dir -r requirements-lite.txt

# App code. comedy_lite.py is the browserless comedy scraper; feed_server.py
# imports get_comedy from it on this branch.
COPY . .

EXPOSE 8090
# Flask dev server is fine for a single-user LAN dashboard; swap for gunicorn if desired.
CMD ["python", "feed_server.py"]

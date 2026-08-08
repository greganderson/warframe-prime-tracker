# Warframe Prime Tracker

A local-first Raspberry Pi dashboard for tracking Prime parts, equipment progress, and fissure rewards. Relics are selected only to populate the squad reward matrix; relic ownership is not recorded. It exposes a touch-first `1280×800` display at `/display` and a desktop management UI at `/manage`.

## Development

Requirements: Python 3.11+, Node 20+.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to port 8000. The production backend serves `frontend/dist` when built.

## Raspberry Pi

Use a Pi 5 with at least 2 GB RAM (4 GB recommended), Raspberry Pi OS 64-bit, and Chromium. The SunFounder TS-10 connects by HDMI for video and USB for touch. Its included 12 V adapter powers the display, whose 5.1 V/5 A USB-C output then powers the Pi. Pi Zero is unsupported for the intended Chromium kiosk workload.

See [deploy/README.md](deploy/README.md). Keep the device on a trusted private LAN and **do not enable router port forwarding**. The service has no authentication.

## Data safety

The SQLite database defaults to `data/tracker.db`, uses WAL mode, and all reward confirmation changes are atomic and reversible. JSON backup/restore and CSV inventory import/export are available in the management interface. Upstream refreshes retain the last valid dataset on failure. Before production use, replace the included demonstration catalog through the sync/import pipeline.

# Warframe Prime Tracker

A tool that runs on a small touch screen to help track prime items in [Warframe](https://www.warframe.com/en).

## Table of Contents

- [Food-blog Description](#food-blog-description)
- [AI's Description](#ais-description)
  - [Development](#development)
  - [Raspberry Pi](#raspberry-pi)
  - [Data safety](#data-safety)

## Food-blog Description

As a long-time warframe player, I've always struggled with keeping track of what prime parts I have and what I still need. There were improvements made to the rewards screen for relic missions, but it still wasn't what I needed. It shows if you have a copy of that part and if you have one built, but what if I need two? What if I built the prime item, and now don't need the part on the reward screen? Should I get it for ducats/platinum, or do I need it for a prime item I don't have yet?

Not ideal.

I've long wanted an app that would help with tracking my prime parts. I've started a couple apps, but never went very far with them (usually due to laziness). The main problem is that we aren't allowed to directly access player data with a program. You'd have to keep track of everything manually. Some people did this with spreadsheets, but in the end there really was just no good option.

Now fast forward a couple years to the last couple months. I went to class one day and one of my students showed me how he got a small touch screen to manage some home server stuff. I've seen those before, and they've always seemed really cool, but I've never had a use for one myself. Then I realized that could be just what I needed for prime tracking. I got a touch screen, then let AI build an app to run in kiosk mode that would track prime items for me. I'd just put in what relics were being cracked that mission, then it would go track down current platinum prices, see what I currently owned, then show me a summarized rewards screen for me (including if any of the relics being cracked are vaulted) so I could decide what I wanted _before_ the round was over. One it was over, I would make my selection, then tap that option on the touch screen, which would record it for me.

It was a dream come true right from the beginning. One thing I noticed was in some missions like omni fissure void cascade, putting in everyone's relics quickly while trying not to die was...hard. That's when the voice control feature was born. Now I tap a button, say what relics everyone has, and they are populated almost immediately. It's _so easy_.

"But surely it can't be _that_ good, what are the drawbacks?"

The main problem I face now is forgetting to change what I have if I sell items for ducats or platinum. If things get out of sync, you have to figure out how to get back in sync, which could mean going through all of your items and making sure everything is right. There's also the fact you have to go through all your items once in the very beginning. It's a very painful process and I'm trying to figure out a reasonable way to keep things in sync without actually touching player data directly.

Other than that though, yeah it's that good.

## AI's Description

A local-first Raspberry Pi dashboard for tracking Prime parts, equipment progress, and fissure rewards. Relics are selected only to populate the squad reward matrix; relic ownership is not recorded. It exposes a touch-first `1280×800` display at `/display` and a desktop management UI at `/manage`.

### Development

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

### Raspberry Pi

Use a Pi 5 with at least 2 GB RAM (4 GB recommended), Raspberry Pi OS 64-bit, and Chromium. The SunFounder TS-10 connects by HDMI for video and USB for touch. Its included 12 V adapter powers the display, whose 5.1 V/5 A USB-C output then powers the Pi. Pi Zero is unsupported for the intended Chromium kiosk workload.

See [deploy/README.md](deploy/README.md). Keep the device on a trusted private LAN and **do not enable router port forwarding**. The service has no authentication.

### Data safety

The SQLite database defaults to `data/tracker.db`, uses WAL mode, and all reward confirmation changes are atomic and reversible. JSON backup/restore and CSV inventory import/export are available in the management interface. **Refresh catalog** imports every Lith, Meso, Neo, and Axi relic plus buildable Prime Warframes, Archwings, primary, secondary, melee, Archguns, and companions from Warframe's official Public Export and caches the result for offline use. The management page can filter these types, hide mastered equipment, and sort by missing parts. Run mode highlights vaulted relics and refreshes recent PC median prices from Warframe.Market. A failed refresh retains the last valid dataset.

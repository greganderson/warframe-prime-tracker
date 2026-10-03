# Raspberry Pi deployment

1. Install Raspberry Pi OS 64-bit on a Pi 5. With power disconnected, mount the Pi to the SunFounder TS-10, then connect the included HDMI cable for video, USB cable for touch, and USB-C power lead from the display's 5.1 V/5 A output to the Pi. Finally connect the display's included 12 V/5 A adapter. No DSI cable or separate Pi power adapter is required.
2. Copy this repository to `/opt/warframe-tracker`, build the frontend, and create a Python virtual environment:

   ```bash
   cd /opt/warframe-tracker/frontend && npm ci && npm run build
   cd .. && python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
   sudo cp deploy/warframe-tracker.service /etc/systemd/system/
   sudo cp deploy/warframe-kiosk.desktop /etc/xdg/autostart/
   sudo systemctl daemon-reload && sudo systemctl enable --now warframe-tracker
   ```

3. Install the offline voice model used by **Speak relics** on the run screen (about 70 MB) and plug in a USB microphone:

   ```bash
   cd /opt/warframe-tracker && mkdir -p models && cd models
   curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip vosk-model-small-en-us-0.15.zip && rm vosk-model-small-en-us-0.15.zip
   sudo systemctl restart warframe-tracker
   ```

   Set `VOSK_MODEL` in the service file to use a model stored elsewhere. The microphone only works in the kiosk browser on the Pi (`http://127.0.0.1`); browsers block microphone access on plain `http://` pages opened from other machines. The button is hidden when the model is missing.
4. Make the touchscreen behave as a touchscreen. Recent Raspberry Pi OS releases use the labwc window manager, which can pass touches to apps as mouse input; Chromium then selects text when you drag instead of scrolling. Check with `grep -ri touch ~/.config/labwc /etc/xdg/labwc`. If you see `mouseEmulation="yes"`, or touch drags select text, copy `/etc/xdg/labwc/rc.xml` to `~/.config/labwc/rc.xml` if it is not there yet, then set `mouseEmulation="no"` on the `<touch>` line. If there is no `<touch>` line, add one just before `</openbox_config>`:

   ```xml
   <touch deviceName="ILITEK ILITEK-TP" mouseEmulation="no" />
   ```

   `ILITEK ILITEK-TP` is the TS-10's touch controller; `sudo libinput list-devices` (from `libinput-tools`) lists device names. Reboot afterwards. Dragging should then scroll and a long press selects text.
5. Install Avahi (`sudo apt install avahi-daemon`) so PCs can open `http://warframe-tracker.local:8000/manage`. If mDNS is unavailable, use the Pi's IP address shown by `hostname -I`.
6. Configure the desktop for landscape 1280×800 and verify that USB touch maps to the HDMI display. Chromium opens `/display` automatically after login. The application fills the detected viewport, so it remains usable if Raspberry Pi OS initially chooses a different mode.

## Updating

```bash
cd /opt/warframe-tracker && git pull
cd frontend && npm ci && npm run build
cd .. && .venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart warframe-tracker
```

The page is served with `Cache-Control: no-cache`, so the kiosk loads the new build the next time it opens or reloads a page. If `npm run build` fails, the previous build stays in place; check its output. To confirm a change reached the Pi, look for its code in `frontend/dist/assets/*.css` or `*.js`. Changes to `deploy/warframe-kiosk.desktop` take effect only after copying it to `/etc/xdg/autostart/` again and logging back in.

## Security

The service listens on the LAN. There is deliberately no login: keep it on a trusted home network, configure the host/router firewall appropriately, and never forward port 8000 from the internet.

## Backups and power loss

`warframe-tracker-backup.timer` makes seven rotating SQLite snapshots under `/var/backups/warframe-tracker`. Install both timer files and enable the timer. The database uses WAL and reward changes are transactional, but clean shutdown and a UPS are still recommended.

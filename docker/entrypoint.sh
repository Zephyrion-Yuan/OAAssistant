#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8787}"
export NOVNC_PORT="${NOVNC_PORT:-7900}"
export VNC_PORT="${VNC_PORT:-5900}"
export MEGANT_DOCKER="${MEGANT_DOCKER:-1}"
export MEGANT_EDGE_PROFILE_MODE="${MEGANT_EDGE_PROFILE_MODE:-isolated}"
export MEGANT_BROWSER_CHANNEL="${MEGANT_BROWSER_CHANNEL:-msedge}"
export MEGANT_BROWSER_ARGS="${MEGANT_BROWSER_ARGS:---no-sandbox,--disable-dev-shm-usage}"

mkdir -p /app/.runtime /tmp/.X11-unix

Xvfb "$DISPLAY" -screen 0 "${XVFB_WHD:-1440x960x24}" -nolisten tcp >/tmp/xvfb.log 2>&1 &
sleep 0.5
openbox >/tmp/openbox.log 2>&1 &
x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport "$VNC_PORT" >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc/ "$NOVNC_PORT" "localhost:$VNC_PORT" >/tmp/novnc.log 2>&1 &

node src/server.js

FROM mcr.microsoft.com/playwright:v1.52.0-noble

WORKDIR /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8787 \
    DISPLAY=:99 \
    NOVNC_PORT=7900 \
    VNC_PORT=5900 \
    MEGANT_DOCKER=1 \
    MEGANT_EDGE_PROFILE_MODE=isolated \
    MEGANT_BROWSER_CHANNEL=msedge \
    MEGANT_BROWSER_ARGS=--no-sandbox,--disable-dev-shm-usage

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      dbus-x11 \
      fonts-noto-cjk \
      fonts-wqy-zenhei \
      novnc \
      openbox \
      websockify \
      x11vnc \
      xdg-utils \
      xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --omit=dev \
    && npx playwright install msedge

COPY . .
RUN chmod +x docker/entrypoint.sh

EXPOSE 8787 7900

ENTRYPOINT ["docker/entrypoint.sh"]

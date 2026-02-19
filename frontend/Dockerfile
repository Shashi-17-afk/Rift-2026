# ── Frontend Dockerfile ─────────────────────────────────────────────
# Serves static files (HTML/CSS/JS) via nginx:alpine
# ──────────────────────────────────────────────────────────────────

FROM nginx:1.25-alpine

LABEL maintainer="PharmaGuard Team"
LABEL description="PharmaGuard frontend — served by nginx"

# Remove default nginx site
RUN rm -rf /usr/share/nginx/html/*

# Copy frontend assets
COPY index.html style.css app.js /usr/share/nginx/html/

# Custom nginx config:
# - Serve on port 3000
# - Proxy /api/* and /health to the backend (resolved by docker compose service name)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

HEALTHCHECK --interval=20s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:3000/ || exit 1

CMD ["nginx", "-g", "daemon off;"]

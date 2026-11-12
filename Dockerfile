# Public demo image (used by Render). Builds the dashboard, then builds the synthetic demo world once at image
# build time so a cold start only has to load it. Nothing secret is baked in: the shared demo password is public
# by design, and the optional Anthropic / PayPal keys are set as environment variables on the host.
FROM node:20-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG DEMO_PASSWORD=sentinel-demo
ENV VITE_DEMO_PASSWORD=$DEMO_PASSWORD
RUN npm run build

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY scripts ./scripts
COPY --from=web /app/frontend/dist ./frontend/dist
ARG DEMO_PASSWORD=sentinel-demo
ENV SENTINEL_DEMO_PASSWORD=$DEMO_PASSWORD \
    SENTINEL_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1
RUN python scripts/serve.py --build-only --seed-paypal-sample --home /app/data
EXPOSE 8000
CMD ["python", "scripts/serve.py", "--home", "/app/data", "--demo-password", "sentinel-demo"]

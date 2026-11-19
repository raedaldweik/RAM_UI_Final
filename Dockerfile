# check=skip=SecretsUsedInArgOrEnv
# (The only "key" passed as a build argument is the TomTom map key, which is
# shipped to the browser anyway. Real secrets are runtime variables, never ARGs.)

# One image, one port: the React frontend is built in stage 1 and served by the
# FastAPI backend in stage 2. Railway builds this file (see railway.toml).

# ─── Stage 1: build the React frontend ─────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-fund --no-audit

COPY frontend/ ./

# Optional, and only for the interactive map card. Vite inlines these at build
# time, so they are build arguments, not runtime settings. On Railway, a service
# variable with the same name is passed in here; locally use --build-arg.
ARG VITE_TOMTOM_API_KEY=""
ARG VITE_MAP_STYLE_URL=""
ARG VITE_MAP_RASTER=""
RUN npm run build


# ─── Stage 2: Python backend + the built frontend ──────────────────
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r backend/requirements.txt

COPY backend/ backend/
COPY --from=frontend-build /app/frontend/dist frontend/dist

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app/backend
EXPOSE 8000

# Railway sets PORT; a plain `docker run` gets the 8000 default above.
# exec: uvicorn receives the stop signal itself and shuts down cleanly on a redeploy.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

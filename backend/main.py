"""
SAS Retrieval Agent Assistant — FastAPI backend.

Local dev:
    uvicorn main:app --reload --port 8000        (frontend: npm run dev, on :5173)

Production (Docker / Railway):
    uvicorn main:app --host 0.0.0.0 --port $PORT
    The Dockerfile builds the frontend into ../frontend/dist and this app serves
    it from "/", so the whole thing is one service on one port.

Settings come from the process environment (the Variables tab on Railway) or,
for a local run, from backend/.env. See backend/.env.example.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BACKEND_DIR = Path(__file__).resolve().parent
# Before the service import below: it reads its settings at import time. Real
# environment variables win over the file, so a stray .env never overrides Railway.
load_dotenv(BACKEND_DIR / ".env")

from routers import ram as ram_router  # noqa: E402
from services import ram as ram_service  # noqa: E402

log = logging.getLogger("uvicorn.error")
FRONTEND_DIST = (BACKEND_DIR.parent / "frontend" / "dist").resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("RAM connection: %s", ram_service.status())
    if ram_service.RAM_API_URL and ram_service.ADDRESS_SOURCE != "RAM_API_URL":
        log.info("RAM address taken from %s", ram_service.ADDRESS_SOURCE)
    if ram_service.MOCK_REQUESTED and not ram_service.MOCK:
        log.info("RAM_MOCK=true is ignored: a RAM address is set, so the app talks to that RAM")
    elif ram_service.MOCK:
        log.info("Demo mode (RAM_MOCK=true): made-up agents and answers. Set RAM_API_URL to connect to a RAM")
    elif not ram_service.RAM_API_URL:
        log.warning("Not connected to a RAM: set RAM_API_URL (or RAM_MOCK=true for a demo)")
    if FRONTEND_DIST.is_dir():
        log.info("Serving the frontend from %s", FRONTEND_DIST)
    else:
        log.info("No frontend build at %s: API only (run the Vite dev server on :5173)", FRONTEND_DIST)
    # Refresh every signed-in RAM session before it expires, for as long as the app runs.
    keepalive = asyncio.create_task(ram_service.keepalive_loop())
    try:
        yield
    finally:
        keepalive.cancel()


app = FastAPI(
    title="SAS Retrieval Agent Assistant",
    description="Chat UI for SAS Retrieval Agent Manager",
    version="1.0.0",
    lifespan=lifespan,
)

# The frontend is same-origin (served from here in production, proxied by Vite in
# dev), so no CORS is needed. Only a frontend hosted on another origin needs it:
# list those origins, comma-separated, in CORS_ORIGINS.
_cors = [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors:
    app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def session_stamp_header(request: Request, call_next):
    """Tell the browser which copy of its session is current.

    The identity provider may issue a new refresh token whenever a session is
    renewed. The browser keeps a copy of the refresh token to survive a
    redeploy (see services.ram.restore_session), so each API response carries
    the session's stamp and the page fetches a fresh copy when it changes."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        stamp = ram_service.session_stamp(request.cookies.get(ram_router.SESSION_COOKIE))
        if stamp is not None:
            response.headers["X-Session-Stamp"] = str(stamp)
    return response


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """Liveness for the platform's health check: answers without calling RAM.
    (/api/health is the RAM connection status the page shows.)"""
    return {"status": "ok", "build": os.getenv("RAILWAY_GIT_COMMIT_SHA", "")[:7] or "local"}


app.include_router(ram_router.router)


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_found(rest: str):
    raise HTTPException(status_code=404, detail=f"No such API route: /api/{rest}")


# ─── Built frontend (production) ─────────────────────────────────────
if FRONTEND_DIST.is_dir():
    if (FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    # index.html and the files from /public are not content-hashed: have browsers
    # revalidate them, so a redeploy shows up on the next load. /assets is hashed.
    _REVALIDATE = {"Cache-Control": "no-cache"}

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path:
            # Only ever a file inside the build: the resolved path must stay under
            # dist, whatever the URL holds ("..", an absolute path, a symlink).
            candidate = (FRONTEND_DIST / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST):
                return FileResponse(candidate, headers=_REVALIDATE)
        return FileResponse(FRONTEND_DIST / "index.html", headers=_REVALIDATE)
else:
    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": "SAS Retrieval Agent Assistant",
            "status": "API only: no frontend build found",
            "ram": ram_service.status(),
            "hint": "Run 'npm run dev' in frontend/ and open http://localhost:5173, "
                    "or 'npm run build' there to have this server serve the UI.",
        }

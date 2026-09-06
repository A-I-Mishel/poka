"""Poka API: FastAPI backend reusing the agent/services stack directly.

Run (from the repo root)::

    uvicorn backend.main:app --port 8000

The React frontend (frontend/) talks to this API; the Streamlit app
(app.py) keeps working untouched during the transition.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from backend.routers import artifacts, briefs, chat, chats, memory, meta, projects, uploads  # noqa: E402

app = FastAPI(title="Poka API", version="0.1.0")

_frontend_origins = [
    origin.strip()
    for origin in (
        os.getenv("POKA_FRONTEND_ORIGIN", "http://localhost:5173").split(",")
    )
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in (
    chat.router,
    chats.router,
    uploads.router,
    artifacts.router,
    projects.router,
    briefs.router,
    memory.router,
    meta.router,
):
    app.include_router(_router)


@app.get("/api")
def root():
    """API index (the UI is served separately in development)."""
    return {"ok": True, "name": "Poka API", "docs": "/docs"}


# Single-server demo mode: when frontend/dist exists, serve it.
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")

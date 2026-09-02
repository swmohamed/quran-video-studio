"""Quran Video Studio — FastAPI backend entrypoint.

Run:  .venv/Scripts/python -m uvicorn app.main:app --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import BACKGROUNDS_DIR, OUTPUT_DIR, RECITERS_DIR, UPLOADS_DIR
from app.core.config import AUDIO_DIR

app = FastAPI(title="Quran Video Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

app.mount("/static/backgrounds", StaticFiles(directory=BACKGROUNDS_DIR), name="backgrounds")
app.mount("/static/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/static/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/static/audio", StaticFiles(directory=RECITERS_DIR), name="audio")
app.mount("/static/surah", StaticFiles(directory=AUDIO_DIR / "surah"), name="surah")


@app.get("/")
def root() -> dict:
    return {"app": "Quran Video Studio", "docs": "/docs", "api": "/api/health"}

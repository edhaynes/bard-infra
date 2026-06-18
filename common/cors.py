"""CORS for the demo console (browser → Registry/Router, plain-HTTP localhost).

Off by default — pass explicit origins to enable. No wildcard, so production
stays headless-safe; the demo passes ``http://localhost:5173``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def apply_cors(app: FastAPI, origins: list[str] | None) -> None:
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

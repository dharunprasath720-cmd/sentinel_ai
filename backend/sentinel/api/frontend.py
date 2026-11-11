"""Serve the built dashboard (frontend/dist) from the API process."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, dist_dir: Path) -> bool:
    """Mount the built SPA at "/" and return True, or mount nothing and return False when there is
    no build. Must be called AFTER every API route is registered so API paths always win; the SPA
    uses hash routing, so no server-side rewrites are needed."""
    dist_dir = Path(dist_dir)
    if not (dist_dir / "index.html").is_file():
        return False
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="dashboard")
    return True

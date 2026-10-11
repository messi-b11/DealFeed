"""Serve the built frontend and persistent API on one origin (container deployment)."""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from backend.app import app as api

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

class NormalizeAPIPath:
    """Accept both API slash forms without redirecting cached static-host URLs."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/api/") and path.endswith("/"):
            scope = dict(scope)
            scope["path"] = path.rstrip("/")
            scope["raw_path"] = scope["path"].encode("utf-8")
        await self.app(scope, receive, send)

app.add_middleware(NormalizeAPIPath)
app.mount("/api", api)
output = Path(__file__).resolve().parents[1] / "out"
if output.is_dir():
    app.mount("/", StaticFiles(directory=output, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

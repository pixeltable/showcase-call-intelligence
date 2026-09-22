import logging
from pathlib import Path

import config
import schema  # noqa: F401 — class-based TableModel apply on first import
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from routers import comments, native, search
from services.health import build_health_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

app = FastAPI(title="Call Center Intelligence", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(native.router)
app.include_router(search.router)
app.include_router(comments.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.get("/api/health")
def health():
    return build_health_response()


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if not FRONTEND_DIR.is_dir():
        return JSONResponse(
            {"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"},
            status_code=404,
        )
    file_path = FRONTEND_DIR / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )

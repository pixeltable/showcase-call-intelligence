import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, calls, comments, search
from app.services.health import build_health_response

upload_dir = settings.upload_dir_path
upload_dir.mkdir(parents=True, exist_ok=True)
if not os.access(upload_dir, os.W_OK):
    raise RuntimeError(f"Upload directory is not writable: {upload_dir}")

app = FastAPI(title="Call Center Intelligence", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(calls.router)
app.include_router(search.router)
app.include_router(comments.router)
if settings.enable_admin_endpoints:
    app.include_router(admin.router)


@app.get("/api/health")
def health():
    return build_health_response()

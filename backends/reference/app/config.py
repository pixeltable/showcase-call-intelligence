from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/callcenter"
    redis_url: str = "redis://localhost:6379/0"
    whisperx_model: str = "base"
    whisperx_diarization_model: str = "pyannote/speaker-diarization-3.1"
    hf_token: str = ""
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_timeout_sec: float = 300.0
    embed_model: str = "all-mpnet-base-v2"
    celery_task_soft_time_limit_sec: int = 3300
    celery_task_time_limit_sec: int = 3600
    upload_dir: str = "./data/reference/uploads"
    max_upload_mb: int = 100
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    enable_admin_endpoints: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_dir_path(self) -> Path:
        p = Path(self.upload_dir)
        if p.is_absolute():
            return p.resolve()
        repo_root = Path(__file__).resolve().parents[3]
        if self.upload_dir.startswith(("./data/", "data/")):
            return (repo_root / p).resolve()
        return (Path.cwd() / p).resolve()


settings = Settings()

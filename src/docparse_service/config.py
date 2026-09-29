from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCPARSE_", env_file=".env", extra="ignore")

    database_url: str = Field(default="sqlite:///./data/docparse.db")
    storage_backend: str = Field(default="local")
    local_storage_dir: str = Field(default="./data/objects")
    minio_endpoint_url: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = Field(default="docparse-mineru34")
    minio_secure: bool = Field(default=False)
    max_file_size_mb: int = Field(default=200)
    run_tasks_inline: bool = Field(default=False)
    mineru_command: str = Field(default="mineru")
    mineru_extra_args: str = Field(default="")
    mineru_device: str = Field(default="auto")
    mineru_cpu_extra_args: str = Field(default="-b pipeline -d cpu --source local")
    mineru_npu_extra_args: str = Field(default="-b pipeline -d npu --source local")
    disable_npu_probe: bool = Field(default=False)

    @property
    def local_storage_path(self) -> Path:
        return Path(self.local_storage_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
